"""Guards for the Cerebras -> Qwen migration.

The risk is not the config edit. It is the paths keyed on the literal string
"zai-glm-4.7" that do not move with it, most dangerously prompt selection:
zai-glm-4.7.json is 25,501 bytes and carries the report-integrity hardening,
while the unified.json fallback is 6,846 bytes and eight months older. A rename
without a selector update swaps one for the other in silence.
"""
from __future__ import annotations

from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, MODEL_PROVIDERS
from rapid_reports_ai.prompt_manager import PromptManager

QWEN = "qwen/qwen3.6-27b"


def test_qwen_selects_the_tuned_report_prompt_not_the_unified_fallback():
    pm = PromptManager()
    glm = pm.load_prompt("radiology_report", primary_model="zai-glm-4.7")
    qwen = pm.load_prompt("radiology_report", primary_model=QWEN)
    assert qwen["template"] == glm["template"], (
        "Qwen fell through to unified.json; it must select the tuned template"
    )
    assert len(qwen["template"]) > 15000, "tuned template is ~25KB; got a stub"


def test_glm_is_fully_migrated_off_cerebras():
    stranded = {k: v for k, v in MODEL_CONFIG.items() if v == "zai-glm-4.7"}
    assert not stranded, f"still on zai-glm-4.7: {stranded}"


# Roles still on Cerebras, with their escape route. Cerebras Developer Tier
# retires 2026-08-17, so every one of these is outstanding migration work.
# The allowlist exists so the test fails the moment something NEW lands on
# Cerebras, rather than going quiet about a known gap.
KNOWN_CEREBRAS_DEBT = {
    # gpt-oss-120b -> openai/gpt-oss-120b on OpenRouter. Same weights, 16
    # providers with tools + structured outputs, verified working. Mechanical.
    "STRUCTURE_VALIDATOR", "FINDING_EXTRACTION", "QUERY_GENERATION",
    "GUIDELINE_VALIDATOR", "COMPATIBILITY_FILTER", "GUIDELINE_SEARCH",
    "COMPARISON_ANALYZER", "ACTION_APPLIER", "CANVAS_SECTIONS",
    "CANVAS_SECTIONS_FROM_TEMPLATE", "KNOWLEDGE_MAINTENANCE",
    "CANVAS_PROCESS_FALLBACK", "CANVAS_COVERAGE_FALLBACK",
    "CANVAS_INTELLIPROMPTS_FALLBACK",
    # gemma-4-31b -> no escape route identified yet.
    "CANVAS_PROCESS", "CANVAS_COVERAGE", "CANVAS_INTELLIPROMPTS",
}


def test_no_new_role_lands_on_cerebras():
    on_cerebras = {
        k for k, v in MODEL_CONFIG.items() if MODEL_PROVIDERS.get(v) == "cerebras"
    }
    unexpected = on_cerebras - KNOWN_CEREBRAS_DEBT
    assert not unexpected, f"new Cerebras dependency introduced: {unexpected}"
    resolved = KNOWN_CEREBRAS_DEBT - on_cerebras
    assert not resolved, (
        f"these migrated - remove from KNOWN_CEREBRAS_DEBT: {resolved}"
    )


def test_no_role_has_itself_as_fallback():
    """A fallback identical to its primary is not a fallback."""
    degenerate = {
        k: v for k, v in MODEL_CONFIG.items()
        if k.endswith("_FALLBACK") and MODEL_CONFIG.get(k[: -len("_FALLBACK")]) == v
    }
    assert not degenerate, f"primary == fallback: {degenerate}"


def test_every_configured_model_resolves_to_a_provider():
    unknown = {k: v for k, v in MODEL_CONFIG.items() if v not in MODEL_PROVIDERS}
    assert not unknown, f"models with no provider mapping: {unknown}"


def test_quick_report_generator_is_not_hardcoded_to_a_retiring_model():
    from rapid_reports_ai import quick_report_api
    assert quick_report_api.GENERATOR_MODEL != "zai-glm-4.7"
