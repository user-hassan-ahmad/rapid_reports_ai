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
    # gemma-4-31b -> no like-for-like replacement identified, but each now
    # fails over to gpt-oss-120b on OpenRouter rather than to another
    # Cerebras model, so a tier outage degrades instead of stopping.
    "CANVAS_PROCESS", "CANVAS_COVERAGE", "CANVAS_INTELLIPROMPTS",
}


def test_every_cerebras_role_fails_over_off_cerebras():
    """Whether the Developer Tier sunset removes gpt-oss and gemma is not
    confirmed - the notice was tier-wide, not per-model. So rather than
    switching primaries on an assumption, every Cerebras role must have a
    fallback on a different provider. If Cerebras survives, nothing changes;
    if it does not, each role degrades to a working path."""
    off = []
    for role, model in MODEL_CONFIG.items():
        if role.endswith("_FALLBACK") or MODEL_PROVIDERS.get(model) != "cerebras":
            continue
        fb = MODEL_CONFIG.get(f"{role}_FALLBACK")
        if fb is None or MODEL_PROVIDERS.get(fb) == "cerebras":
            off.append(f"{role} -> {fb}")
    assert not off, f"Cerebras roles with no off-provider fallback: {off}"


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


# Groq decommissions Llama 3.3 70B Versatile on 2026-08-16 - one day before the
# Cerebras Developer Tier sunset, so it lands first.
DECOMMISSIONED = {"llama-3.3-70b-versatile"}


def test_nothing_points_at_a_decommissioned_groq_model():
    stranded = {k: v for k, v in MODEL_CONFIG.items() if v in DECOMMISSIONED}
    assert not stranded, f"still on decommissioned Groq models: {stranded}"


def test_no_hardcoded_decommissioned_model_outside_the_config():
    """A config edit does not move hardcoded call sites - knowledge_reify.py
    held one, and main.py's allow-list held another."""
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai"
    offenders = []
    for f in src.rglob("*.py"):
        text = f.read_text(errors="replace")
        for dead in DECOMMISSIONED:
            if f'"{dead}"' in text and "MODEL_PROVIDERS" not in text.split(f'"{dead}"')[0][-400:]:
                offenders.append(f"{f.name}: {dead}")
    assert not offenders, f"hardcoded decommissioned model: {offenders}"


def test_linguistic_validator_is_not_the_model_it_validates():
    """It checks generator output; sharing a family makes it self-review."""
    validator = MODEL_CONFIG["LINGUISTIC_VALIDATOR"]
    assert validator != MODEL_CONFIG["PRIMARY_REPORT_GENERATOR"]
    assert not validator.startswith("qwen"), "validator must differ from the generator family"


def test_no_stale_per_model_prompt_stub_can_be_selected():
    """qwen.json was a 4,404-byte November 2025 stub from the old monolithic
    system, sitting next to the 25,501-byte tuned template. `load_prompt` has a
    legacy `model` arg that loads `{model}.json` directly, so a stub in this
    directory is one plausible call away from silently replacing the real
    prompt. llama.json is the same vintage and its model is decommissioned."""
    import pathlib
    d = (pathlib.Path(__file__).resolve().parents[1]
         / "src/rapid_reports_ai/prompts/radiology_report")
    tuned = (d / "zai-glm-4.7.json").stat().st_size
    stubs = {f.name: f.stat().st_size for f in d.glob("*.json")
             if f.name not in {"metadata.json"} and f.stat().st_size < tuned * 0.35}
    assert "qwen.json" not in stubs, "the stale Qwen stub is back"
    # llama.json is the same vintage and its model is decommissioned 2026-08-16.
    # Left in place pending a decision; listed here so it cannot be forgotten.
    assert set(stubs) <= {"llama.json", "gptoss.json", "unified.json", "claude.json",
                          "gptoss_old_v2.json"}, f"unexpected prompt stub: {stubs}"
