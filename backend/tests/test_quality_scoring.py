"""Unit tests for the quality scoring engine (no external DB; judge mocked)."""
from rapid_reports_ai.quality_scoring import (
    compute_edit_burden,
    JudgeScore,
    DIMENSIONS,
)


def test_quality_judge_resolves_to_a_provider():
    from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, _get_model_provider
    model = MODEL_CONFIG["QUALITY_JUDGE"]
    assert _get_model_provider(model) == "anthropic"


def test_dimensions_are_the_three_rubric_columns():
    assert DIMENSIONS == ("sheet_fit", "output_adherence", "input_faithfulness")


def test_judge_score_enforces_1_to_5():
    import pytest
    JudgeScore(score=5, rationale="ok")
    with pytest.raises(Exception):
        JudgeScore(score=6, rationale="too high")


# --- DB-backed tests (SQLite harness; judge injected) ------------------------

import uuid
from rapid_reports_ai.database.models import User, Report, EphemeralSkillSheet, ReportQualityScore
from rapid_reports_ai import quality_scoring as qs


def _mk_user(db):
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x",
             full_name="Org", is_active=True, is_verified=True, is_approved=True)
    db.add(u); db.flush()
    return u


def _mk_quick_report(db, user, report_content="LUNGS: clear.", final=None):
    ess = EphemeralSkillSheet(
        id=uuid.uuid4(), scan_type="CT chest", scan_type_normalized="ct chest",
        clinical_history="cough", skill_sheet_markdown="- check lungs\n- check pleura",
        analyser_model="zai-glm-4.7", user_id=user.id,
    )
    db.add(ess); db.flush()
    r = Report(id=uuid.uuid4(), report_type="auto", generation_mode="quick_ephemeral",
               model_used="zai-glm-4.7", report_content=report_content,
               final_report_content=final, ephemeral_skill_sheet_id=ess.id, user_id=user.id)
    db.add(r); db.flush()
    return r


def test_upsert_score_idempotent_by_rubric(db_session):
    u = _mk_user(db_session)
    r = _mk_quick_report(db_session, u)
    qs.upsert_score(db_session, report_id=r.id, pipeline="quick",
                    scores={"sheet_fit": 4, "output_adherence": 5, "input_faithfulness": 5},
                    edit_burden=0.1, dimensions={}, judge_model="claude-haiku-4-5-20251001")
    qs.upsert_score(db_session, report_id=r.id, pipeline="quick",
                    scores={"sheet_fit": 2, "output_adherence": 2, "input_faithfulness": 2},
                    edit_burden=0.5, dimensions={}, judge_model="claude-haiku-4-5-20251001")
    rows = db_session.query(ReportQualityScore).filter_by(report_id=r.id).all()
    assert len(rows) == 1
    assert rows[0].sheet_fit == 2  # upserted, not duplicated


def test_score_report_quick_path_with_fake_judge(db_session):
    u = _mk_user(db_session)
    r = _mk_quick_report(db_session, u, final="LUNGS: clear. PLEURA: normal.")

    captured = []

    def fake_judge(prompt, case_text):
        captured.append(case_text)
        return qs.JudgeScore(score=4, rationale="adequate", issues=[])

    row = qs.score_report(db_session, r, judge=fake_judge)  # defaults to current rubric
    assert row.pipeline == "quick"
    assert row.rubric_version == qs.RUBRIC_VERSION_CURRENT
    assert (row.output_adherence, row.dictation_fidelity, row.normal_fill_appropriateness) == (4, 4, 4)
    assert row.sheet_fit is None and row.input_faithfulness is None  # retired/split in v2
    assert row.edit_burden is not None and row.edit_burden > 0  # final differs from draft
    # v2.2 adds unwarranted_assertion, which has no DB column and lives here only.
    assert set(row.dimensions_json) == set(qs.DIMENSIONS_V22) | {"_meta"}  # _meta: grouping keys (path), not a dimension
    assert len(captured) == len(qs.DIMENSIONS_V22)   # one judge call per dimension
    assert "check lungs" in captured[0]           # skill sheet shown to the v2 judge


def test_score_report_skips_existing_unless_rescore(db_session):
    u = _mk_user(db_session)
    r = _mk_quick_report(db_session, u)
    calls = {"n": 0}

    def fake_judge(p, c):
        calls["n"] += 1
        return qs.JudgeScore(score=3, rationale="ok")

    qs.score_report(db_session, r, judge=fake_judge)
    first = calls["n"]
    qs.score_report(db_session, r, judge=fake_judge)            # exists -> skip
    assert calls["n"] == first
    qs.score_report(db_session, r, judge=fake_judge, rescore=True)  # forced re-run
    assert calls["n"] == first + len(qs.DIMENSIONS_V22)  # one call per dimension


def test_edit_burden_zero_when_identical():
    assert compute_edit_burden("LUNGS: clear.", "LUNGS: clear.") == 0.0


def test_edit_burden_one_when_no_overlap():
    assert compute_edit_burden("aaaa", "bbbb") == 1.0


def test_edit_burden_none_when_no_final():
    assert compute_edit_burden("anything", None) is None
    assert compute_edit_burden("anything", "") is None


def test_edit_burden_partial_between_0_and_1():
    v = compute_edit_burden("the quick brown fox", "the slow brown fox")
    assert v is not None
    assert 0.0 < v < 1.0


# --- Template final from report versions (D6, 2026-10-13) ---

def _mk_template_report(db, user, template, content="edited text", stamp=None):
    from rapid_reports_ai.database.models import Report
    rep = Report(user_id=user.id, report_type="templated", report_content=content, model_used="m",
                 template_id=template.id, input_data={}, generation_stamp=stamp)
    db.add(rep); db.flush()
    return rep


def test_template_final_is_the_latest_edited_version(db_session, test_user, guided_template):
    from rapid_reports_ai.database.models import ReportVersion
    rep = _mk_template_report(db_session, test_user, guided_template)
    db_session.add_all([ReportVersion(report_id=rep.id, version_number=1, report_content="ai text", is_current=False),
                        ReportVersion(report_id=rep.id, version_number=2, report_content="edited text", is_current=True)])
    db_session.commit()
    db_session.refresh(rep)
    case = qs._assemble_case(db_session, rep)
    assert case["ai_output"] == "ai text" and case["final_output"] == "edited text"


def test_template_single_version_has_no_final(db_session, test_user, guided_template):
    from rapid_reports_ai.database.models import ReportVersion
    rep = _mk_template_report(db_session, test_user, guided_template, content="ai text")
    db_session.add(ReportVersion(report_id=rep.id, version_number=1, report_content="ai text", is_current=True))
    db_session.commit()
    db_session.refresh(rep)
    case = qs._assemble_case(db_session, rep)
    assert case["ai_output"] == "ai text" and case["final_output"] is None


def test_score_template_report_without_final_scores_with_null_edit_burden(db_session, test_user, guided_template):
    rep = _mk_template_report(db_session, test_user, guided_template, content="ai text")
    db_session.commit()
    row = qs.score_report(db_session, rep, judge=lambda p, c: qs.JudgeScore(score=3, rationale="ok", issues=[]))
    assert row.pipeline == "template" and row.edit_burden is None and row.output_adherence == 3


# --- Judge against the stamped sheet (D7, 2026-10-13) ---

_OLD_SHEET = "## FINDINGS\nOld sheet wording."


def _with_old_version(db, template):
    from rapid_reports_ai.database.models import TemplateVersion
    db.add(TemplateVersion(template_id=template.id, name=template.name, version_number=1,
                           template_config={**template.template_config, "skill_sheet": _OLD_SHEET}))
    db.commit()


def test_template_judged_against_the_stamped_sheet(db_session, test_user, guided_template):
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    _with_old_version(db_session, guided_template)
    rep = _mk_template_report(db_session, test_user, guided_template,
                              stamp={"sheet_hash": sheet_hash(_OLD_SHEET), "path": "scratchpad"})
    case = qs._assemble_case(db_session, rep)
    assert case["skill_sheet"] == _OLD_SHEET and case["path"] == "scratchpad"


def test_template_sheet_falls_back_to_current(db_session, test_user, guided_template):
    current = guided_template.template_config["skill_sheet"]
    _with_old_version(db_session, guided_template)
    for stamp in (None, {"sheet_hash": None, "path": "lean"}, {"sheet_hash": "f" * 64}, "not-a-dict"):
        rep = _mk_template_report(db_session, test_user, guided_template, stamp=stamp)
        case = qs._assemble_case(db_session, rep)
        assert case["skill_sheet"] == current, stamp
    assert qs._assemble_case(db_session, _mk_template_report(db_session, test_user, guided_template))["path"] == ""


def test_score_row_carries_path(db_session, test_user, guided_template):
    rep = _mk_template_report(db_session, test_user, guided_template, stamp={"sheet_hash": None, "path": "scratchpad"})
    db_session.commit()
    row = qs.score_report(db_session, rep, judge=lambda p, c: qs.JudgeScore(score=3, rationale="ok", issues=[]))
    assert row.dimensions_json["_meta"] == {"path": "scratchpad"}


def test_quick_report_path_is_empty_and_ignores_stamps(db_session):
    u = _mk_user(db_session)
    r = _mk_quick_report(db_session, u)
    r.generation_stamp = {"sheet_hash": "f" * 64, "path": "scratchpad"}
    db_session.flush()
    case = qs._assemble_case(db_session, r)
    assert case["path"] == "" and case["skill_sheet"] == "- check lungs\n- check pleura"


def test_template_versions_out_of_order(db_session, test_user, guided_template):
    from rapid_reports_ai.database.models import ReportVersion
    rep = _mk_template_report(db_session, test_user, guided_template, content="v3")
    db_session.add_all([ReportVersion(report_id=rep.id, version_number=n, report_content=f"v{n}", is_current=n == 3)
                        for n in (3, 1, 2)])
    db_session.commit()
    rep.versions = sorted(rep.versions, key=lambda v: -v.version_number)  # relationship order not relied on
    case = qs._assemble_case(db_session, rep)
    assert case["ai_output"] == "v1" and case["final_output"] == "v3"


def test_template_empty_first_version_has_no_final(db_session, test_user, guided_template):
    from rapid_reports_ai.database.models import ReportVersion
    rep = _mk_template_report(db_session, test_user, guided_template, content="edited")
    db_session.add_all([ReportVersion(report_id=rep.id, version_number=1, report_content="", is_current=False),
                        ReportVersion(report_id=rep.id, version_number=2, report_content="edited", is_current=True)])
    db_session.commit()
    db_session.refresh(rep)
    case = qs._assemble_case(db_session, rep)
    assert case["final_output"] is None and case["ai_output"] == "edited"


def test_stamp_matching_current_sheet_skips_version_lookup(db_session, test_user, guided_template, monkeypatch):
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    current = guided_template.template_config["skill_sheet"]
    _with_old_version(db_session, guided_template)
    rep = _mk_template_report(db_session, test_user, guided_template, stamp={"sheet_hash": sheet_hash(current)})
    real_query = db_session.query

    def no_version_query(*a, **k):
        from rapid_reports_ai.database.models import TemplateVersion
        assert TemplateVersion not in a, "version history queried although the stamp matches the current sheet"
        return real_query(*a, **k)

    monkeypatch.setattr(db_session, "query", no_version_query)
    assert qs._assemble_case(db_session, rep)["skill_sheet"] == current


def test_non_string_current_sheet_does_not_crash(db_session, test_user, guided_template):
    from rapid_reports_ai.template_sheet_structure import sheet_hash
    rep = _mk_template_report(db_session, test_user, guided_template, stamp={"sheet_hash": sheet_hash("x")})
    assert qs._sheet_for(db_session, rep, {"not": "a string"}) == ""
