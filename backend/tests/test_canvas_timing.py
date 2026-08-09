"""process_transcript must emit a per-request latency log for the live path."""
from __future__ import annotations

import logging

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.canvas_routes import (
    process_transcript,
    CanvasProcessRequest,
    CanvasProcessResponse,
)


async def test_process_transcript_logs_latency(monkeypatch, caplog):
    async def _stub_run(**kwargs):
        class _R:
            output = CanvasProcessResponse(scratchpad="- liver is normal", covered_sections=[])
        return _R()

    monkeypatch.setattr(cr, "_run_agent_with_model", _stub_run)
    monkeypatch.setattr(cr, "_get_model_provider", lambda model: "groq")
    monkeypatch.setattr(cr, "_get_api_key_for_provider", lambda provider: "test-key")

    req = CanvasProcessRequest(
        session_transcript="the liver is normal",
        scratchpad_content="",
        scan_type="CT abdomen",
        clinical_history="",
        preferred_section_names=[],
    )

    with caplog.at_level(logging.INFO, logger="rapid_reports_ai.canvas_routes"):
        out = await process_transcript(req, current_user=None)

    assert out.scratchpad == "- liver is normal"
    assert any("[canvas.process]" in r.message for r in caplog.records)
