from __future__ import annotations

import pytest

from rapid_reports_ai.dictation_triage import TriageDecision, TriageState
from rapid_reports_ai.dictation_triage_router import (
    DETERMINISTIC_ACTIONS,
    apply_deterministic,
    map_formatting,
    route,
)

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


def test_formatting_command_appends_mapped_text():
    assert apply_deterministic("formatting_command", _state("new paragraph")) == ACTIVE + "\n\n"


def test_formatting_command_with_nothing_to_map_leaves_active_unchanged():
    assert apply_deterministic("formatting_command", _state("er")) == ACTIVE


@pytest.mark.parametrize("action", ["ignore_noise", "restate_existing_finding"])
def test_noop_actions_return_active_unchanged(action):
    assert apply_deterministic(action, _state("um so")) == ACTIVE


def test_delete_removes_last_non_blank_line():
    assert (
        apply_deterministic("delete_previous_utterance", _state("scratch that", ACTIVE + "\n"))
        == "- 6 mm nodule right upper lobe"
    )


def test_delete_on_empty_active_falls_through():
    assert apply_deterministic("delete_previous_utterance", _state("scratch that", "")) is None
    assert apply_deterministic("delete_previous_utterance", _state("scratch that", "\n\n")) is None


@pytest.mark.parametrize("action", ["append_new_finding", "correct_previous_finding"])
def test_model_actions_fall_through(action):
    assert apply_deterministic(action, _state("anything")) is None


def test_route_deterministic_above_threshold():
    kind, text = route(_decision("ignore_noise", 0.95), 0.9, _state("um"))
    assert kind == "deterministic" and text == ACTIVE


def test_route_falls_to_model_below_threshold():
    kind, text = route(_decision("ignore_noise", 0.5), 0.9, _state("um"))
    assert kind == "model" and text is None


def test_route_no_confidence_counts_as_certain():
    kind, _ = route(_decision("formatting_command", None, candidate="qwen"), 0.99, _state("new line"))
    assert kind == "deterministic"


def test_route_model_action_never_deterministic():
    kind, _ = route(_decision("correct_previous_finding", 1.0), 0.5, _state("actually left"))
    assert kind == "model"


def test_deterministic_set():
    assert DETERMINISTIC_ACTIONS == {
        "formatting_command", "delete_previous_utterance", "ignore_noise", "restate_existing_finding",
    }
