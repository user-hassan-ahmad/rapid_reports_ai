"""Documents the real wire contract. Skipped unless RR_LIVE_TESTS=1 and a key exists.
Asserts shape only — answers are the bake-off's job."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS, JevTriager, TriageState

pytestmark = pytest.mark.skipif(
    os.environ.get("RR_LIVE_TESTS") != "1" or not os.environ.get("OPENROUTER_API_KEY"),
    reason="live test: set RR_LIVE_TESTS=1 and OPENROUTER_API_KEY",
)

FIXTURES = Path(__file__).parent / "fixtures" / "triage_utterances.jsonl"


async def test_jev_live_shape_on_first_five_fixtures():
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()][:5]
    triager = JevTriager()
    for c in cases:
        d = await triager.classify(TriageState(c["committed"], c["active"], c["utterance"], c["scan_type"]))
        assert d.action in TRIAGE_ACTIONS
        assert 0.0 <= d.confidence <= 1.0
        assert abs(sum(d.probabilities.values()) - 1.0) < 0.02
        assert 0.0 <= d.is_correction <= 1.0 and 0.0 <= d.needs_committed_edit <= 1.0
        assert d.latency_ms < 3000
