"""Derive what the live scratchpad model actually did from its before/after text.

This is the ground-truth label for shadow mode. It is line-based (one finding per
line), deterministic, and deliberately lenient in AGREEMENT_MAP because a rewrite
by the live model is not a clean signal. Precise labels live in the fixture file.
"""
from __future__ import annotations

import re
from typing import Literal

DerivedAction = Literal["append", "correct", "delete", "noop", "committed_edit"]

_WS = re.compile(r"\s+")


def _lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = _WS.sub(" ", raw).strip().casefold()
        if line:
            out.append(line)
    return out


def derive_action(before_active: str, after_active: str, committed_edits: list[tuple[str, str]]) -> DerivedAction:
    if committed_edits:
        return "committed_edit"
    before = _lines(before_active)
    after = _lines(after_active)
    if sorted(before) == sorted(after):
        return "noop"
    if len(after) > len(before) and set(before) <= set(after):
        return "append"
    if len(after) < len(before):
        return "delete"
    return "correct"


AGREEMENT_MAP: dict[str, frozenset[str]] = {
    "append_new_finding": frozenset({"append"}),
    "correct_previous_finding": frozenset({"correct", "committed_edit"}),
    "restate_existing_finding": frozenset({"noop", "correct"}),
    "delete_previous_utterance": frozenset({"delete"}),
    "formatting_command": frozenset({"noop", "append"}),
    "ignore_noise": frozenset({"noop"}),
}


def agrees(action: str, derived: str) -> bool:
    return derived in AGREEMENT_MAP.get(action, frozenset())
