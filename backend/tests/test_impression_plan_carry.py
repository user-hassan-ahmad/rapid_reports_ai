"""PLAN2 (L-50): the impression plan carries, it never lists Findings only.

Dictated conclusion lines are a code floor of the Carry forward list, verbatim; each carried item
names its dictated hedge so the impression keeps the certainty the radiologist dictated.
"""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_hardening as qh
from rapid_reports_ai import quick_report_prompts as qp
from tests.test_quick_report_brief import JEV, QWEN, SHEET, _stub


def test_conclusion_floor_is_verbatim_lines_after_the_marker_with_bullets_stripped():
    f = ("Mass in the left lobe.\n\nConclusion: \n\n-Left lobe mass, suspicious for malignancy.\n"
         "* Small effusion\nOK\n")
    assert qb.dictated_conclusion(f) == ["Left lobe mass, suspicious for malignancy", "Small effusion"]


@pytest.mark.parametrize("f, expected", [
    ("A. Impression: 1. stable nodule.", ["1. stable nodule"]),                 # the rest of the marker line is an item
    ("Findings text.\nIMPRESSION\n- Acute appendicitis\n", ["Acute appendicitis"]),
    ("Findings text. Opinion - nil acute\n", ["nil acute"]),
    ("Nothing dictated as a conclusion.\n", []),
    ("Summary:\n- One\n- Two words\n", ["Two words"]),                         # fewer than two words dropped
    ("Conclusion:\nRA erosion across the ankle\n+ others\n", ["RA erosion across the ankle"]),
])
def test_conclusion_floor_markers(f, expected):
    assert qb.dictated_conclusion(f) == expected


def test_hedge_tag_names_the_dictated_word():
    assert qb.hedge_tag("suspicious for a vertebral artery dissection") == ' (dictated hedge: "suspicious for")'
    assert qb.hedge_tag("likely in keeping with infection") == ' (dictated hedge: "likely", "in keeping with")'
    assert qb.hedge_tag("?early appendicitis") == ' (dictated hedge: "?")'
    assert qb.hedge_tag("Acute appendicitis") == ""


def test_impression_plan_schema_has_no_findings_only():
    assert "findings_only" not in qb.ImpressionPlan.model_fields
    p = qb.ImpressionPlan.model_validate({"recommendations": "[]", "impression": "[0]", "optional_impression": "[]"})
    assert p.impression == [0]
    assert "findings_only" not in qb.PLAN_SYS
    assert "A finding in neither list is placed as the writer judges. Never place a number in both lists." in qb.PLAN_SYS


@pytest.mark.asyncio
async def test_carry_forward_is_conclusion_lines_then_deduplicated_picks(monkeypatch):
    findings = ("8 mm right subdural. 3 mm midline shift. Age-related involutional change.\n"
                "Conclusion:\n- 8 mm right subdural, likely acute.\n")
    plan = qb.ImpressionPlan(recommendations=[], impression=[0, 1, 3])
    _stub(monkeypatch, JEV, QWEN, plan)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", findings, "fall")
    block = b.text.split("## Impression Plan")[1]
    assert ('- **Carry forward (the impression addresses each, at the certainty dictated):** '
            '"8 mm right subdural, likely acute" (dictated hedge: "likely") "3 mm midline shift"') in block
    # pick 0 sits inside the conclusion line; pick 3 is the bare "Conclusion:" heading
    assert block.count("8 mm right subdural") == 1 and '"Conclusion' not in block
    assert "Findings only" not in b.text
    assert b.decisions["impression_plan"] == {
        "conclusion": ["8 mm right subdural, likely acute"],
        "carry": ["8 mm right subdural, likely acute", "3 mm midline shift"], "optional": []}


@pytest.mark.asyncio
async def test_conclusion_floor_holds_when_the_plan_fails(monkeypatch):
    _stub(monkeypatch, JEV, QWEN, None)
    b = await qb.compile_brief(SHEET, "CT head non-contrast", "Subdural.\nImpression: \nPossible small subdural\n")
    assert '"Possible small subdural" (dictated hedge: "Possible")' in b.text.split("## Impression Plan")[1]


def test_checklist_and_hardening_never_mention_findings_only():
    new = "- Every Carry forward finding is addressed in the impression, with its dictated hedge unchanged\n"
    assert new in qp.QR_VERIFICATION_CHECKLIST_BRIEF
    for text in (qp.QR_VERIFICATION_CHECKLIST_BRIEF, qh.QUICK_REPORT_HARDENING_PREAMBLE_BRIEF):
        assert "Findings only" not in text
