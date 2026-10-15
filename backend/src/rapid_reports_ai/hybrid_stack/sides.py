"""Paired normals (side brief 2026-10-14): the library states a paired organ once per side, so a left cyst drops only
the left sentence. A right and a left sentence of one region that read the same once the side word is swapped are a
pair. This is a text match on the sheet, never a judgement about meaning: whether the dictation states a finding's
side is Jev's question (jev_stack.ask_sides)."""
from __future__ import annotations

import re

_SIDE = re.compile(r"\b(right|left)\b", re.IGNORECASE)


def _key(s: str) -> str:
    return " ".join(s.lower().split()).rstrip(".")


def _one_side(s: str) -> str | None:
    """'right' or 'left' when every side word in the sentence is that one side, else None."""
    words = {w.lower() for w in _SIDE.findall(s)}
    return words.pop() if len(words) == 1 else None


def _swapped(s: str) -> str:
    return _SIDE.sub(lambda m: "left" if m.group(1).lower() == "right" else "right", s)


def side_pairs(sentences: list[str]) -> list[tuple[int, int]]:
    """(right index, left index) of each pair, in the order of the right sentences. A sentence naming both sides is
    never paired."""
    lefts = {_key(s): i for i, s in enumerate(sentences) if _one_side(s) == "left"}
    out: list[tuple[int, int]] = []
    for i, s in enumerate(sentences):
        if _one_side(s) == "right" and (j := lefts.get(_key(_swapped(s)))) is not None:
            out.append((i, j))
    return out


def side_label(s: str) -> str:
    """The pair as one line for the "Which side?" ask: its side word written as both sides."""
    return _SIDE.sub(lambda m: "right/left" if m.group(1).islower() else "Right/left", s)
