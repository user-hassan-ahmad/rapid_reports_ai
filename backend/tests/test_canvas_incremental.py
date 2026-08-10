from __future__ import annotations

from rapid_reports_ai.canvas_routes import (
    CanvasProcessRequest,
    CommittedEdit,
    CanvasIncrementalResponse,
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
