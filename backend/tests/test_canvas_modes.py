"""Mode → (system prompt, decoding params) selection for the scratchpad polish."""
from __future__ import annotations

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import (
    _canvas_process_config,
    CANVAS_CLEAN_SYSTEM_PROMPT,
    CANVAS_PROCESS_SYSTEM_PROMPT,
    process_transcript,
    CanvasProcessRequest,
    CanvasProcessResponse,
)


def test_clean_mode_uses_clean_prompt_and_low_temp():
    prompt, settings = _canvas_process_config("clean")
    assert prompt is CANVAS_CLEAN_SYSTEM_PROMPT
    assert settings["temperature"] == 0.15


def test_structured_mode_uses_structured_prompt_and_retuned_temp():
    prompt, settings = _canvas_process_config("structured")
    assert prompt is CANVAS_PROCESS_SYSTEM_PROMPT
    assert settings["temperature"] == 0.3  # down from the current 0.7


def test_unknown_or_missing_mode_defaults_to_clean():
    assert _canvas_process_config("")[0] is CANVAS_CLEAN_SYSTEM_PROMPT
    assert _canvas_process_config("wobble")[0] is CANVAS_CLEAN_SYSTEM_PROMPT


def test_clean_prompt_forbids_bullets_and_regrouping():
    # Guard the load-bearing Clean-mode instructions against accidental edits.
    p = CANVAS_CLEAN_SYSTEM_PROMPT
    assert "do NOT reduce to bullet fragments" in p
    assert "Revisions" in p
    assert "authoritative" in p  # dictated line/paragraph breaks


async def _capture_process(mode, monkeypatch):
    """Call process_transcript with _run_canvas_with_fallback stubbed to record args."""
    captured = {}

    async def _stub(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings, use_thinking=False, label=""):
        captured["system_prompt"] = system_prompt
        captured["model_settings"] = model_settings
        return CanvasProcessResponse(scratchpad="- ok", covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", _stub)
    req = CanvasProcessRequest(session_transcript="the liver is normal", scratchpad_content="", mode=mode)
    await process_transcript(req, current_user=None)
    return captured


async def test_process_clean_mode_selects_clean_prompt(monkeypatch):
    captured = await _capture_process("clean", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_CLEAN_SYSTEM_PROMPT
    assert captured["model_settings"]["temperature"] == 0.15


async def test_process_structured_mode_selects_structured_prompt(monkeypatch):
    captured = await _capture_process("structured", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_PROCESS_SYSTEM_PROMPT
    assert captured["model_settings"]["temperature"] == 0.3


async def test_process_defaults_to_clean(monkeypatch):
    captured = await _capture_process("", monkeypatch)
    assert captured["system_prompt"] is cr.CANVAS_CLEAN_SYSTEM_PROMPT
