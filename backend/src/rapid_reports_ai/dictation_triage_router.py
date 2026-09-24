"""Lab-only routing: act on a triage decision without calling the live model.

Only the four classes with an obvious deterministic effect are handled here.
Appends and corrections always go to the live model (homophone correction and
consolidation live there). The formatting lexicon mirrors
main.process_dictation_transcript plus the spoken forms the lab feeder types.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from .dictation_triage import TriageDecision, TriageState

DETERMINISTIC_ACTIONS: frozenset[str] = frozenset(
    {"formatting_command", "delete_previous_utterance", "ignore_noise", "restate_existing_finding"}
)

_FORMATTING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\\n\\n>"), "\n\n"),
    (re.compile(r"<\\n>"), "\n"),
    (re.compile(r"\bnew\s+paragraph\b", re.IGNORECASE), "\n\n"),
    (re.compile(r"\bnew\s+line\b", re.IGNORECASE), "\n"),
    (re.compile(r"\bfull\s*stop\b", re.IGNORECASE), "."),
)


def map_formatting(utterance: str) -> str:
    """Return only the characters a formatting utterance stands for ('' if none)."""
    out: list[str] = []
    for pattern, replacement in _FORMATTING_RULES:
        for _ in pattern.findall(utterance or ""):
            out.append(replacement)
    return "".join(out)


def apply_deterministic(action: str, state: TriageState) -> Optional[str]:
    """New active text, or None to fall through to the live model."""
    active = state.active or ""
    if action == "formatting_command":
        mapped = map_formatting(state.latest_utterance)
        return active + mapped if mapped else active
    if action in ("ignore_noise", "restate_existing_finding"):
        return active
    if action == "delete_previous_utterance":
        lines = active.split("\n")
        idx = max((i for i, line in enumerate(lines) if line.strip()), default=None)
        if idx is None:
            return None
        return "\n".join(lines[:idx]).rstrip("\n")
    return None


def route(
    decision: TriageDecision, threshold: float, state: TriageState
) -> tuple[Literal["deterministic", "model"], Optional[str]]:
    if decision.action not in DETERMINISTIC_ACTIONS:
        return "model", None
    confidence = 1.0 if decision.confidence is None else decision.confidence
    if confidence < threshold:
        return "model", None
    new_active = apply_deterministic(decision.action, state)
    if new_active is None:
        return "model", None
    return "deterministic", new_active
