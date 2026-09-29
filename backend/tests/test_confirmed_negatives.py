"""Policy 1 for confirmed branches (spec 2026-09-29-policy1-confirmed-branch-negatives-design)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import quick_report_analyser as qa


def test_confirmed_negatives_is_an_opt_in_directive():
    model = "qwen-3.8-27b"
    prod = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES)
    arm_b = qa.get_analyser_prompt(model, directives=qa.PRODUCTION_DIRECTIVES + ("confirmed_negatives",))
    assert "**If confirmed:**" not in prod
    assert "**If confirmed:**" in arm_b
    assert "(core | contextual)" in arm_b
    assert "confirmed_negatives" not in qa.PRODUCTION_DIRECTIVES
