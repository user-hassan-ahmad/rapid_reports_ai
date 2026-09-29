"""Quick-report failover: primary Cerebras Qwen 3.8 raises -> one hop to Groq Qwen 3.8.

Stubs the shared agent runner so no network is touched; asserts which model each
stage called, what the provider would receive, and what the result records.
"""
from types import SimpleNamespace

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG, normalise_model_settings
from rapid_reports_ai.quick_report_analyser import generate_ephemeral_skill_sheet
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE

PRIMARY = "qwen-3.8-27b"
FALLBACK = "qwen/qwen3.8-27b"


def test_quick_report_roles_declare_the_groq_fallback():
    for role in ("QUICK_REPORT_ANALYZER_FAST", "QUICK_REPORT_ANALYZER_BEST", "QUICK_REPORT_GENERATOR", "TEMPLATE_REPORT_GENERATOR"):
        assert MODEL_CONFIG[role] == PRIMARY
        assert MODEL_CONFIG[f"{role}_FALLBACK"] == FALLBACK


def _stub_runner(calls, fail_models):
    async def fake(**kw):
        model = kw["model_name"]
        calls.append({"model": model, "settings": kw.get("model_settings"), "output_type": kw.get("output_type")})
        if model in fail_models:
            raise RuntimeError(f"{model} down")
        if kw.get("output_type") is str:
            return SimpleNamespace(output="COMPARISON:\nNone.\n\nTECHNIQUE:\nCT.\n\nFINDINGS:\nx.\n\nIMPRESSION:\ny.", all_messages=lambda: [])
        return SimpleNamespace(output=SimpleNamespace(description="stub description"), all_messages=lambda: [])
    return fake


def _sent(call):
    """What the provider receives for this call."""
    return normalise_model_settings(call["model"], call["settings"])


@pytest.mark.asyncio
async def test_analyser_falls_back_to_groq_when_cerebras_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_runner(calls, {PRIMARY}))
    out = await generate_ephemeral_skill_sheet(scan_type="CT head", clinical_history="fall", api_key="")
    assert [c["model"] for c in calls] == [PRIMARY, FALLBACK]
    assert out["model_used"] == FALLBACK and out["fallback_from"] == PRIMARY
    groq, cerebras = _sent(calls[1]), _sent(calls[0])
    assert groq["max_tokens"] == 16384 and groq["extra_body"] == {"reasoning_effort": "low"}
    assert cerebras["max_tokens"] == 65536 and cerebras["extra_body"] == {"reasoning_effort": "medium"}


@pytest.mark.asyncio
async def test_analyser_uses_primary_when_it_succeeds(monkeypatch):
    calls = []
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_runner(calls, set()))
    out = await generate_ephemeral_skill_sheet(scan_type="CT head", clinical_history="fall", api_key="")
    assert [c["model"] for c in calls] == [PRIMARY]
    assert out["model_used"] == PRIMARY and out["fallback_from"] is None


@pytest.mark.asyncio
async def test_analyser_raises_when_fallback_also_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_runner(calls, {PRIMARY, FALLBACK}))
    with pytest.raises(RuntimeError):
        await generate_ephemeral_skill_sheet(scan_type="CT head", clinical_history="fall", api_key="")
    assert [c["model"] for c in calls] == [PRIMARY, FALLBACK]


@pytest.mark.asyncio
async def test_direct_groq_call_does_not_chain_to_another_roles_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_runner(calls, {FALLBACK}))
    with pytest.raises(RuntimeError):
        await generate_ephemeral_skill_sheet(scan_type="CT head", clinical_history="fall", api_key="", model_override=FALLBACK)
    assert [c["model"] for c in calls] == [FALLBACK]


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [None, PRIMARY])
async def test_quick_report_generator_falls_back_to_groq_when_cerebras_raises(monkeypatch, override):
    """Production passes model_override=GENERATOR_MODEL (the primary). Before the split the
    shared generator skipped its fallback whenever any override was set, so production
    quick reports had none."""
    from rapid_reports_ai import quick_report_generator as qrg
    calls = []
    monkeypatch.setattr(qrg, "_run_agent_with_model", _stub_runner(calls, {PRIMARY}))
    monkeypatch.setattr(qrg, "_get_api_key_for_provider", lambda provider, fallback_api_key=None: "k")
    out = await qrg.generate_quick_report(skill_sheet="# Skill Sheet: CT head\n", scan_type="CT head",
                                          findings="No acute abnormality.", clinical_history="fall",
                                          model_override=override)
    report_calls = [c for c in calls if c["output_type"] is str]
    assert [c["model"] for c in report_calls] == [PRIMARY, FALLBACK]
    assert out["model_used"] == FALLBACK and out["fallback_from"] == PRIMARY
    assert _sent(report_calls[1])["extra_body"] == {"reasoning_effort": "low"}
    assert "IMPRESSION:" in out["report_content"]


@pytest.mark.asyncio
async def test_an_override_naming_another_model_does_not_fall_back(monkeypatch):
    from rapid_reports_ai import quick_report_generator as qrg
    calls = []
    monkeypatch.setattr(qrg, "_run_agent_with_model", _stub_runner(calls, {FALLBACK}))
    monkeypatch.setattr(qrg, "_get_api_key_for_provider", lambda provider, fallback_api_key=None: "k")
    with pytest.raises(RuntimeError):
        await qrg.generate_quick_report(skill_sheet="x", scan_type="CT head", findings="f", clinical_history="h",
                                        model_override=FALLBACK)
    assert [c["model"] for c in calls if c["output_type"] is str] == [FALLBACK]
