"""Guards for model routing (Qwen 3.8 / gpt-oss-120b / Sonnet 5.5, 2026-09-28).

The risk is never the config edit. It is the paths that do not move with it: prompt
selection keyed on a model string (zai-glm-4.7.json is 25,501 bytes and carries the
report-integrity hardening, unified.json is 6,846 bytes and eight months older), hardcoded
model ids outside MODEL_CONFIG, and provider keys that stay behind when a model moves
(the 2026-08-14 and 2026-09-28 prod 401s).
"""
from __future__ import annotations

import pathlib

from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, MODEL_PROVIDERS
from rapid_reports_ai.prompt_manager import PromptManager

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai"

# Retired by their providers, or removed from the registry on 2026-09-28.
RETIRED = {
    "zai-glm-4.7", "gemma-4-31b", "qwen/qwen3.6-27b", "llama-3.3-70b-versatile",
    "claude-sonnet-4-20250514", "claude-sonnet-4-6", "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001", "accounts/fireworks/models/glm-5p1",
    "deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash",
}


def test_qwen_selects_the_tuned_report_prompt_not_the_unified_fallback():
    pm = PromptManager()
    tuned = pm.load_prompt("radiology_report", primary_model="zai-glm-4.7")
    for qwen in ("qwen-3.8-27b", "qwen/qwen3.8-27b"):
        prompt = pm.load_prompt("radiology_report", primary_model=qwen)
        assert prompt["template"] == tuned["template"], f"{qwen} fell through to unified.json"
    assert len(tuned["template"]) > 15000, "tuned template is ~25KB; got a stub"


def test_claude_fallback_selects_the_claude_prompt():
    pm = PromptManager()
    claude = pm.load_prompt("radiology_report", primary_model=MODEL_CONFIG["FALLBACK_REPORT_GENERATOR"])
    unified = pm.load_prompt("radiology_report", primary_model="no-such-model")
    assert claude["template"] != unified["template"], "Sonnet fell through to unified.json"


def test_no_role_points_at_a_retired_model():
    stranded = {k: v for k, v in MODEL_CONFIG.items() if v in RETIRED}
    assert not stranded, f"roles on retired models: {stranded}"
    assert not RETIRED & set(MODEL_PROVIDERS), "a retired model is back in MODEL_PROVIDERS"


def test_no_hardcoded_retired_model_in_production_code():
    """A config edit does not move hardcoded call sites. zai-glm-4.7 survives only as the
    tuned prompt's file name, which agentic_routes renders by name."""
    offenders = []
    for f in SRC.rglob("*.py"):
        if "scripts" in f.parts:
            continue
        text = f.read_text(errors="replace")
        for dead in RETIRED - {"zai-glm-4.7"}:
            if f'"{dead}"' in text:
                offenders.append(f"{f.name}: {dead}")
    assert not offenders, f"hardcoded retired model: {offenders}"


def test_every_fallback_is_on_a_different_provider():
    """A fallback on the primary's provider does not survive that provider's outage."""
    same = []
    for role, fb in MODEL_CONFIG.items():
        if not role.endswith("_FALLBACK"):
            continue
        primary = MODEL_CONFIG.get(role[: -len("_FALLBACK")])
        if primary and MODEL_PROVIDERS[primary] == MODEL_PROVIDERS[fb]:
            same.append(f"{role}: {primary} -> {fb}")
    assert not same, f"fallback shares its primary's provider: {same}"


def test_no_role_has_itself_as_fallback():
    degenerate = {
        k: v for k, v in MODEL_CONFIG.items()
        if k.endswith("_FALLBACK") and MODEL_CONFIG.get(k[: -len("_FALLBACK")]) == v
    }
    assert not degenerate, f"primary == fallback: {degenerate}"


def test_every_configured_model_resolves_to_a_provider():
    unknown = {k: v for k, v in MODEL_CONFIG.items() if v not in MODEL_PROVIDERS}
    assert not unknown, f"models with no provider mapping: {unknown}"


def test_anthropic_is_sonnet_5_5_only():
    anthropic = {m for m, p in MODEL_PROVIDERS.items() if p == "anthropic"}
    assert anthropic == {"claude-sonnet-5-5"}


def test_linguistic_validator_is_not_the_model_it_validates():
    """It checks generator output; sharing a family makes it self-review."""
    validator = MODEL_CONFIG["LINGUISTIC_VALIDATOR"]
    assert validator != MODEL_CONFIG["PRIMARY_REPORT_GENERATOR"]
    assert not validator.startswith("qwen"), "validator must differ from the generator family"


def test_quick_report_generator_follows_the_config():
    from rapid_reports_ai import quick_report_api
    assert quick_report_api.GENERATOR_MODEL == MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"]


def test_prefetch_model_follows_the_config():
    from rapid_reports_ai import guideline_prefetch as gp
    import inspect
    assert gp.PREFETCH_MODEL == MODEL_CONFIG["GUIDELINE_PREFETCH"]
    src = inspect.getsource(gp)
    assert 'os.environ.get("CEREBRAS_API_KEY"' not in src, "prefetch reads a provider key directly again"
    assert src.count("model_name=PREFETCH_MODEL") >= 6, "a call site bypasses PREFETCH_MODEL"


def test_canvas_runs_with_reasoning_off_on_both_providers():
    """Reasoning on broke IntelliPrompts' structured output on both providers."""
    from rapid_reports_ai.canvas_routes import _adapt_canvas_settings, _canvas_process_config
    from rapid_reports_ai.enhancement_utils import normalise_model_settings
    for mode in ("structured", "clean"):
        _, settings = _canvas_process_config(mode)
        for model in (MODEL_CONFIG["CANVAS_PROCESS"], MODEL_CONFIG["CANVAS_PROCESS_FALLBACK"]):
            sent = normalise_model_settings(model, _adapt_canvas_settings(model, settings))
            assert sent["extra_body"]["reasoning_effort"] == "none"
            assert sent["max_tokens"] == 8000


def test_no_stale_per_model_prompt_stub_can_be_selected():
    """qwen.json was a 4,404-byte November 2025 stub next to the 25,501-byte tuned
    template; `load_prompt`'s legacy `model` arg loads `{model}.json` directly."""
    d = SRC / "prompts/radiology_report"
    tuned = (d / "zai-glm-4.7.json").stat().st_size
    stubs = {f.name: f.stat().st_size for f in d.glob("*.json")
             if f.name not in {"metadata.json"} and f.stat().st_size < tuned * 0.35}
    assert "qwen.json" not in stubs, "the stale Qwen stub is back"
    assert set(stubs) <= {"llama.json", "gptoss.json", "unified.json", "claude.json",
                          "gptoss_old_v2.json"}, f"unexpected prompt stub: {stubs}"
