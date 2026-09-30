"""Negatives stay out of the quick-report impression by default (2026-09-30, quick reports only).

Before/after review: impressions read as lists of absent findings, in production as well as with
finding-linked negatives (7/11 recent prod impressions carried a negative sentence). The rule is
countable (L-44: countable checklist lines beat prose) and the sites that taught the lists are
edited where they stand.
"""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa
from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_hardening as qh
from rapid_reports_ai import quick_report_prompts as qp

RULE = ("The impression contains at most one negative: the answer to the clinical question when no positive "
        "finding answers it, or one clause that changes the next step. It never lists absent findings")


def test_checklist_carries_the_countable_rule():
    assert RULE in qp.QR_VERIFICATION_CHECKLIST_BRIEF


def test_hardening_no_longer_makes_negatives_an_impression_obligation():
    assert "mandatory negatives that bear on it" not in qh.QUICK_REPORT_HARDENING_PREAMBLE
    assert "negatives about extent, staging or complications stay in FINDINGS" in qh.QUICK_REPORT_HARDENING_PREAMBLE


@pytest.mark.parametrize("prompt", [qa.ANALYSER_SYSTEM_PROMPT_ANTHROPIC, qa.ANALYSER_SYSTEM_PROMPT_OPEN_WEIGHTS])
def test_analyser_stops_teaching_impression_negative_lists(prompt):
    assert "the negative answers to the remaining questions follow it" not in prompt
    assert "with mandatory negatives that bear on the question" not in prompt
    assert "carry it into the IMPRESSION as a direct negative answer" not in prompt
    assert "negatives about the remaining questions stay in FINDINGS unless one changes the next step" in prompt
    assert "no list of absent findings" in prompt
    assert "only when no positive finding answers the clinical question" in prompt


def test_plan_carries_at_most_one_negative_and_never_finding_negatives():
    assert "negatives that answer the clinical question." not in qb.PLAN_SYS
    assert "Never carry more than one negative." in qb.PLAN_SYS
    assert not hasattr(qb, "PLAN_NEGATIVES_RULE")
    assert "carry_negatives" not in qb.ImpressionPlan.model_fields
