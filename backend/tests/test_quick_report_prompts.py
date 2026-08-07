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
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE

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


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_secondary_regions_must_lie_inside_imaged_volume(prompt: str):
    """A region outside the declared imaged volume cannot carry a normal line."""
    assert "must lie within the declared Imaged volume" in prompt


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_co_acquisition_is_not_visibility(prompt: str):
    """Guards the exact failure seen: trauma co-ordering made the analyser
    emit a cervical-spine normal on a vertex-to-skull-base head CT."""
    assert "Co-acquisition convention" in prompt


# ── Generator-side override licence (Principle 12) ──────────────────────────
# The analyser-side rules above only shape sheets generated from now on.
# Principle 12 is what reaches the sheets already cached in
# ephemeral_skill_sheets, because it licenses the generator to override them.


def test_preamble_has_evidence_override_principle():
    assert "**12. A canonical line from the skill sheet is a proposal" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )


def test_principle_12_names_both_override_conditions():
    """Out-of-volume and companion-contradiction are the two triggers."""
    assert "outside the declared imaged volume" in QUICK_REPORT_HARDENING_PREAMBLE
    assert "companion of a dictated positive" in QUICK_REPORT_HARDENING_PREAMBLE


def test_principle_12_preserves_coverage():
    assert "Dropping an assertion is not dropping the structure" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )


def test_principle_12_exempts_mandatory_negatives():
    """Regression guard for a real over-fire found in behavioural testing.

    The first version of Principle 12 keyed the override on "the Companion
    Matrix names this region". The Companion Matrix holds BOTH in-scope
    companions AND mandatory negatives, so the rule accidentally licensed
    dropping mandatory negatives — and both analyser variants promptly did,
    losing the four-compartment haemorrhage negative on a query-haemorrhage
    head CT. Mandatory negatives answer the clinical question; they are never
    silent-case filler.
    """
    assert "Mandatory negatives are outside this principle" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )
    assert "Never drop a mandatory negative under this principle" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_analyser_defeasibility_exempts_mandatory_negatives(prompt: str):
    """The sheet must not author the over-suppression either."""
    assert "mandatory negatives are never" in prompt


def test_principle_11_gender_rule_not_clobbered():
    """Regression guard — Principle 12 is appended, not substituted."""
    assert "**11. Gender-specific structures require an explicit gender " in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )
