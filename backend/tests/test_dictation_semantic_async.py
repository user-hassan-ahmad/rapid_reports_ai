"""Regression test for the tier-2 semantic check running-loop bug.

The default analyser must run on the caller's event loop. Previously it used
asyncio.run() inside the async /api/dictation/check handler, which raised
RuntimeError, was swallowed, and made tier-2 silently return no flags in prod.
"""
from __future__ import annotations

import rapid_reports_ai.enhancement_utils as eu
from rapid_reports_ai.dictation_semantic import (
    SemanticIssue,
    SemanticFindings,
    check_semantic,
)

FINDINGS = (
    "- MRI of the right ankle demonstrates a joint effusion.\n"
    "- There is oedema within the left ankle mortise."
)


async def test_default_analyser_runs_on_the_request_loop(monkeypatch):
    """check_semantic, called from a running loop with NO injected analyser,
    must reach the model and return a located flag — not swallow a RuntimeError."""

    class _Result:
        output = SemanticFindings(
            issues=[
                SemanticIssue(
                    kind="laterality_conflict",
                    quote="left ankle mortise",
                    message="Findings mention both a right and a left ankle.",
                )
            ]
        )

    async def _stub_run(**kwargs):
        return _Result()

    # _default_analyse imports these from enhancement_utils at call time, so we
    # patch them at the source module.
    monkeypatch.setattr(eu, "_run_agent_with_model", _stub_run)
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda provider: "test-key")
    monkeypatch.setattr(eu, "_get_model_provider", lambda model: "cerebras")

    flags = await check_semantic("MRI ankle", "right ankle pain", FINDINGS)

    assert len(flags) == 1
    assert FINDINGS[flags[0].start:flags[0].end] == "left ankle mortise"
    assert flags[0].kind == "laterality_conflict"
