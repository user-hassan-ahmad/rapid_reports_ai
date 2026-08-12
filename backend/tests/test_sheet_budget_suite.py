"""Tests for the Qwen sheet-budget experiment harness.

Spec: docs/superpowers/specs/2026-08-12-qwen-sheet-budget-experiment-design.md
Plan: docs/superpowers/plans/2026-08-12-qwen-sheet-budget-harness.md
"""
from __future__ import annotations

from rapid_reports_ai import quick_report_analyser as qra


def test_production_prompts_are_byte_identical_without_a_budget():
    """Regression guard: the two production analysers must not change at all."""
    assert qra.get_analyser_prompt("zai-glm-4.7") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )


def test_empty_budget_leaves_no_override_block():
    """T1 is a true control - identical to what the bake-off ran."""
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "   ") == qra.ANALYSER_SYSTEM_PROMPT_GLM


def test_budget_directive_is_appended_and_placeholder_is_consumed():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    assert "Cover exactly 3 findings." in prompt
    assert "{{BUDGET_DIRECTIVE}}" not in prompt
    assert prompt.startswith(qra.ANALYSER_SYSTEM_PROMPT_GLM)


def test_budget_block_declares_itself_an_override():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    tail = prompt[len(qra.ANALYSER_SYSTEM_PROMPT_GLM):]
    assert "OVERRIDE" in tail.upper()


def test_anthropic_ignores_the_budget():
    """Sonnet path is out of scope for this experiment and must not change."""
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001", "Cover exactly 3 findings.")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )


# ── Task 2: tier config ──────────────────────────────────────────────────────

from rapid_reports_ai.scripts.sheet_budget import tiers as T


def test_tiers_load_all_five():
    loaded = T.load_tiers()
    assert [t["id"] for t in loaded] == ["T1", "T2", "T3", "T4", "T5"]


def test_t1_is_the_unbudgeted_control():
    t1 = T.load_tiers()[0]
    assert t1["findings"] is None
    assert t1["variants_per_finding"] is None
    assert T.render_directive(t1) == ""


def test_budgets_are_non_increasing_down_the_ladder():
    T.validate_tiers(T.load_tiers())  # raises if not


def test_validate_rejects_an_increasing_ladder():
    bad = [
        {"id": "A", "findings": 2, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
        {"id": "B", "findings": 4, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
    ]
    try:
        T.validate_tiers(bad)
    except ValueError as exc:
        assert "findings" in str(exc)
    else:
        raise AssertionError("expected ValueError on an increasing ladder")
