"""Mode → (system prompt, decoding params) selection for the scratchpad polish."""
from __future__ import annotations

from rapid_reports_ai.canvas_routes import (
    _canvas_process_config,
    CANVAS_CLEAN_SYSTEM_PROMPT,
    CANVAS_PROCESS_SYSTEM_PROMPT,
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
