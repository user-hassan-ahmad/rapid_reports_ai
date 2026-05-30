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

    row = qs.score_report(db_session, r, judge=fake_judge)  # defaults to rubric v2
    assert row.pipeline == "quick"
    assert row.rubric_version == "v2"
    assert (row.output_adherence, row.dictation_fidelity, row.normal_fill_appropriateness) == (4, 4, 4)
    assert row.sheet_fit is None and row.input_faithfulness is None  # retired/split in v2
    assert row.edit_burden is not None and row.edit_burden > 0  # final differs from draft
    assert set(row.dimensions_json) == {"output_adherence", "dictation_fidelity", "normal_fill_appropriateness"}
    assert len(captured) == 3                     # one judge call per dimension
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
    assert calls["n"] == first + 3


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
