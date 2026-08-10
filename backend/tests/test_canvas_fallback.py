"""_run_canvas_with_fallback: Gemma primary, gpt-oss-120b fallback on ANY failure."""
from __future__ import annotations

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import _run_canvas_with_fallback, CanvasProcessResponse


def _stub_providers(monkeypatch):
    monkeypatch.setattr(cr, "_get_model_provider", lambda m: "cerebras")
    monkeypatch.setattr(cr, "_get_api_key_for_provider", lambda p: "k")


class _R:
    def __init__(self, scratchpad):
        self.output = CanvasProcessResponse(scratchpad=scratchpad, covered_sections=[])


async def _call():
    return await _run_canvas_with_fallback(
        "gemma-4-31b",
        "gpt-oss-120b",
        output_type=CanvasProcessResponse,
        system_prompt="s",
        user_prompt="u",
        model_settings={},
        label="test",
    )


async def test_primary_success_serves_primary(monkeypatch):
    _stub_providers(monkeypatch)

    async def _run(**kw):
        return _R(f"from:{kw['model_name']}")

    monkeypatch.setattr(cr, "_run_agent_with_model", _run)
    out = await _call()
    assert out.scratchpad == "from:gemma-4-31b"


async def test_falls_back_when_primary_raises(monkeypatch):
    _stub_providers(monkeypatch)

    async def _run(**kw):
        if kw["model_name"] == "gemma-4-31b":
            raise RuntimeError("status_code: 404, model_not_found")
        return _R(f"from:{kw['model_name']}")

    monkeypatch.setattr(cr, "_run_agent_with_model", _run)
    out = await _call()
    assert out.scratchpad == "from:gpt-oss-120b"


async def test_raises_when_all_candidates_fail(monkeypatch):
    _stub_providers(monkeypatch)

    async def _run(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(cr, "_run_agent_with_model", _run)
    with pytest.raises(RuntimeError):
        await _call()
