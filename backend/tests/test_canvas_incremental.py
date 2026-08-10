from __future__ import annotations

from rapid_reports_ai.canvas_routes import (
    CanvasProcessRequest,
    CommittedEdit,
    CanvasIncrementalResponse,
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
