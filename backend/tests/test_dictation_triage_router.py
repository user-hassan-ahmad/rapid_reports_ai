from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TriageDecision, TriageState
from rapid_reports_ai.dictation_triage_router import map_formatting

ACTIVE = "- 6 mm nodule right upper lobe\n- no pleural effusion"


def _state(utterance: str, active: str = ACTIVE) -> TriageState:
    return TriageState(committed="", active=active, latest_utterance=utterance)


def _decision(action: str, confidence: float | None, candidate="jev") -> TriageDecision:
    return TriageDecision(
        candidate=candidate, action=action, confidence=confidence, probabilities=None,
        is_correction=None, needs_committed_edit=None, latency_ms=1, input_tokens=None, cost_usd=None,
    )


@pytest.mark.parametrize(
    "utterance, expected",
    [
        ("new paragraph", "\n\n"),
        ("New Line", "\n"),
        ("full stop", "."),
        ("fullstop", "."),
        ("<\\n\\n>", "\n\n"),
        ("<\\n>", "\n"),
        ("um", ""),
    ],
)
def test_map_formatting(utterance, expected):
    assert map_formatting(utterance) == expected


