"""Prompt-content tests for the quick-report analyser prompts and the
generator hardening preamble.

These are pure string constants — no fixtures, no DB, no LLM call. We assert
that the doctrine we depend on is actually present in BOTH analyser variants.
The GLM variant serves ~95% of production sheets; a rule present only in the
Sonnet variant is effectively absent from production.

See docs/superpowers/plans/2026-08-04-report-integrity-defeasible-fills.md
"""
from __future__ import annotations

import pytest

from rapid_reports_ai.quick_report_analyser import (
    ANALYSER_SYSTEM_PROMPT_GLM,
    ANALYSER_SYSTEM_PROMPT_SONNET,
)

BOTH_ANALYSER_PROMPTS = [
    pytest.param(ANALYSER_SYSTEM_PROMPT_SONNET, id="sonnet"),
    pytest.param(ANALYSER_SYSTEM_PROMPT_GLM, id="glm"),
]


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_default_normal_lines_are_declared_defeasible(prompt: str):
    """A canonical default-normal is a proposal, not a mandate."""
    assert "defeasible" in prompt.lower()


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_defeasibility_is_scoped_to_companion_contradiction(prompt: str):
    """The override trigger must name the Companion Matrix, not be vague."""
    assert "Companion Matrix" in prompt


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_coverage_obligation_survives_defeasibility(prompt: str):
    """Dropping an assertion must not license dropping the structure.

    Regression guard: the fix must not swing the pendulum into under-coverage.
    """
    assert "Coverage of the structure remains obligatory" in prompt
