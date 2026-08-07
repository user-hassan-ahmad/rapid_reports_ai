"""Tests for rubric v2.2 — splitting normal-fill into two questions.

v2.1's `normal_fill_appropriateness` conflated two things and consequently sat
at a near-ceiling 4.92/5.0 while human review found real defects:

  "is this a plausible normal for this scan type?"   <- genuinely near-perfect
  "did we put words in the radiologist's mouth?"     <- not measured at all

v2.2 keeps the first as normal_fill_appropriateness and adds
`unwarranted_assertion` for the second: out-of-volume claims, normals that
contradict a dictated positive, and negatives the radiologist never indicated
they reviewed.
"""
from __future__ import annotations

import uuid

from rapid_reports_ai import quality_scoring as qs
from rapid_reports_ai.database.models import EphemeralSkillSheet, Report, User


def test_v22_adds_unwarranted_assertion_to_the_v21_dimensions():
    assert "unwarranted_assertion" in qs.DIMENSIONS_V22
    # the three v2.1 dimensions survive unchanged
    for d in qs.DIMENSIONS_V2:
        assert d in qs.DIMENSIONS_V22
    assert len(qs.DIMENSIONS_V22) == len(qs.DIMENSIONS_V2) + 1


def test_v22_is_the_current_rubric():
    assert qs.RUBRIC_VERSION_CURRENT == "v2.2"


def test_every_v22_dimension_has_a_prompt():
    _, prompts, _ = qs._rubric(qs.RUBRIC_VERSION_CURRENT)
    for d in qs.DIMENSIONS_V22:
        assert prompts.get(d), f"no prompt for {d}"


def test_unwarranted_assertion_prompt_covers_all_three_failure_modes():
    p = qs.UNWARRANTED_ASSERTION_PROMPT.lower()
    assert "imaged volume" in p          # out-of-volume claims
    assert "contradict" in p             # normals contradicting a dictated positive
    assert "did not indicate" in p       # unsolicited certification


def test_unwarranted_assertion_requires_evidence_for_a_deduction():
    """Calibration guard from the first live run: the judge scored a clean
    CTPA 4/5 with an empty issues list and a rationale saying nothing was
    wrong. Deducting without naming a span is the same unevidenced-assertion
    behaviour this dimension exists to detect."""
    p = qs.UNWARRANTED_ASSERTION_PROMPT
    assert "SCORE AND EVIDENCE MUST AGREE" in p
    assert "If you list no offending spans, the score is 5" in p


def test_normal_fill_prompt_narrowed_to_conventionality():
    """Out-of-scope moves to the new dimension; keeping it in both would
    double-penalise the same defect and defeat the point of splitting."""
    assert "outside" not in qs.NORMAL_FILL_PROMPT_V22.lower()
    assert "conventional" in qs.NORMAL_FILL_PROMPT_V22.lower()


# --- DB-backed: scores land where the analytics view can read them ----------


def _mk_report(db):
    u = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x",
             full_name="T", is_active=True, is_verified=True, is_approved=True)
    db.add(u); db.flush()
    sheet = EphemeralSkillSheet(id=uuid.uuid4(), scan_type="CT head",
                                scan_type_normalized="ct head", clinical_history="fall",
                                skill_sheet_markdown="# sheet", analyser_model="zai-glm-4.7",
                                user_id=u.id)
    db.add(sheet); db.flush()
    r = Report(id=uuid.uuid4(), report_type="auto", user_id=u.id,
               model_used="zai-glm-4.7",
               generation_mode="quick_ephemeral", ephemeral_skill_sheet_id=sheet.id,
               input_data={"variables": {"FINDINGS": "8mm subdural", "SCAN_TYPE": "CT head"}},
               report_content="The basal cisterns are clear.")
    db.add(r); db.commit()
    return r


def _fake_judge(prompt, case_text):
    return qs.JudgeScore(score=3, rationale="ok", issues=[])


def test_v22_scores_all_four_dimensions_into_dimensions_json(db_session):
    r = _mk_report(db_session)
    row = qs.score_report(db_session, r, judge=_fake_judge,
                          version=qs.RUBRIC_VERSION_CURRENT)
    assert row.rubric_version == "v2.2"
    for d in qs.DIMENSIONS_V22:
        assert d in row.dimensions_json, f"{d} missing from dimensions_json"
        assert row.dimensions_json[d]["score"] == 3


def test_v22_still_populates_the_existing_columns(db_session):
    """The three v2.1 dimensions have real DB columns; unwarranted_assertion
    lives in dimensions_json only, so no migration is required."""
    r = _mk_report(db_session)
    row = qs.score_report(db_session, r, judge=_fake_judge,
                          version=qs.RUBRIC_VERSION_CURRENT)
    assert row.output_adherence == 3
    assert row.dictation_fidelity == 3
    assert row.normal_fill_appropriateness == 3
    assert not hasattr(row, "unwarranted_assertion")


def test_v21_scoring_is_unaffected(db_session):
    """Adding v2.2 must not change what v2.1 produces — the existing cohort
    stays comparable."""
    r = _mk_report(db_session)
    row = qs.score_report(db_session, r, judge=_fake_judge, version="v2.1")
    assert row.rubric_version == "v2.1"
    assert set(row.dimensions_json) == set(qs.DIMENSIONS_V2)
