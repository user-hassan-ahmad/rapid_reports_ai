from __future__ import annotations

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import (
    CanvasProcessRequest,
    CommittedEdit,
    CanvasIncrementalResponse,
    process_transcript,
    CanvasProcessResponse,
    _canvas_process_config,
    CANVAS_CLEAN_SYSTEM_PROMPT,
    CANVAS_PROCESS_SYSTEM_PROMPT,
    CANVAS_INCREMENTAL_SUFFIX,
)


def test_committed_context_defaults_none_full_mode():
    req = CanvasProcessRequest(session_transcript="x", scratchpad_content="")
    assert req.committed_context is None  # absent => full regeneration


def test_incremental_response_shape():
    r = CanvasIncrementalResponse(
        active_scratchpad="- liver normal",
        committed_edits=[CommittedEdit(original="5 mm nodule", corrected="10 mm nodule")],
    )
    assert r.active_scratchpad == "- liver normal"
    assert r.committed_edits[0].corrected == "10 mm nodule"


def test_incremental_response_defaults_no_edits():
    assert CanvasIncrementalResponse(active_scratchpad="x").committed_edits == []


def test_full_config_unchanged():
    prompt, _ = _canvas_process_config("clean")  # incremental defaults False
    assert prompt is CANVAS_CLEAN_SYSTEM_PROMPT
    assert CANVAS_INCREMENTAL_SUFFIX not in prompt


def test_incremental_clean_appends_suffix():
    prompt, settings = _canvas_process_config("clean", incremental=True)
    assert prompt.startswith(CANVAS_CLEAN_SYSTEM_PROMPT)
    assert CANVAS_INCREMENTAL_SUFFIX in prompt
    assert settings["temperature"] == 0.15


def test_incremental_structured_appends_suffix():
    prompt, settings = _canvas_process_config("structured", incremental=True)
    assert prompt.startswith(CANVAS_PROCESS_SYSTEM_PROMPT)
    assert CANVAS_INCREMENTAL_SUFFIX in prompt
    assert settings["temperature"] == 0.3


async def test_full_path_when_no_committed_context(monkeypatch):
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["output_type"] = output_type
        return CanvasProcessResponse(scratchpad="- full", covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    out = await process_transcript(
        CanvasProcessRequest(session_transcript="t", scratchpad_content="- full"), current_user=None
    )
    assert captured["output_type"] is CanvasProcessResponse
    assert out.scratchpad == "- full"


async def test_incremental_path_when_committed_context_present(monkeypatch):
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["output_type"] = output_type
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return CanvasIncrementalResponse(active_scratchpad="- active updated", committed_edits=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    out = await process_transcript(
        CanvasProcessRequest(
            session_transcript="new words",
            scratchpad_content="- active",       # the ACTIVE tail
            committed_context="- committed line", # frozen prefix
        ),
        current_user=None,
    )
    assert captured["output_type"] is CanvasIncrementalResponse
    assert cr.CANVAS_INCREMENTAL_SUFFIX in captured["system_prompt"]
    assert "- committed line" in captured["user_prompt"]   # committed sent as context
    assert out.active_scratchpad == "- active updated"


async def test_incremental_error_guard_returns_active_unchanged(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("all models failed")

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _boom)
    out = await process_transcript(
        CanvasProcessRequest(session_transcript="t", scratchpad_content="- active", committed_context="- c"),
        current_user=None,
    )
    assert isinstance(out, CanvasIncrementalResponse)
    assert out.active_scratchpad == "- active"  # unchanged; committed untouched
    assert out.committed_edits == []
