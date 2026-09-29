"""Narrow fidelity check on the lab lean polish: without a correction cue in the new words,
nothing already dictated may be lost.

Measured (2026-09-27): on 167 replayed lean polishes, one per model lost a dictated fact with
no cue anywhere (27 mm overwritten by the next fragment's 42 mm), and live, "No disc
extrusion." replaced "The extrusion measures 7 mm.". About 1 in 170 polishes, silent, and
the worst kind of error in a report. The check is code (no model), and it fails safe: on a
violation the span is kept as it was and the new words are appended as said, so the worst
case is untidy text, which the audit flags if it contradicts.

Only numbers, left/right, negations and whole statements are checked; wording repairs pass.
"""
from __future__ import annotations

import re

CORRECTION_CUE = re.compile(
    r"\b(actually|sorry|correction|correct that|make that|scratch that|delete that|strike that|"
    r"i mean|rather|instead|no wait)\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SIDE = re.compile(r"\b(left|right)\b", re.IGNORECASE)
# Words that make a statement negative: losing one flips its meaning ("no effusion" → "effusion").
_NEGATION = re.compile(r"\b(?:no|not|without|absent|negative)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z]{4,}")
_SPLIT = re.compile(r"(?<=[.?!:])\s+|\n+")
KEPT_OVERLAP = 0.5  # share of a statement's content words found in one output statement


def _count(pattern: re.Pattern, text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in pattern.finditer(text):
        k = m.group(0).lower()
        out[k] = out.get(k, 0) + 1
    return out


def _lost(before: dict[str, int], after: dict[str, int]) -> bool:
    return any(after.get(k, 0) < n for k, n in before.items())


def _statements(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text or "") if s.strip()]


def _kept(statement: str, out_statements: list[set[str]]) -> bool:
    words = set(_WORD.findall(statement.lower()))
    if not words:
        return True
    return max((len(words & o) / len(words) for o in out_statements), default=0.0) >= KEPT_OVERLAP


def _edit_texts(edit) -> tuple[str, str]:
    if isinstance(edit, dict):
        return edit.get("original", "") or "", edit.get("corrected", "") or ""
    return getattr(edit, "original", "") or "", getattr(edit, "corrected", "") or ""


def fidelity_violation(span: str, new: str, out: str, committed_edits: list) -> str | None:
    """The reason the output must not be used, or None. With a correction cue in the new
    words, or ending the span, the model may change things (that is what the cue asks for)."""
    last = (_statements(span) or [""])[-1]
    if CORRECTION_CUE.search(new or "") or CORRECTION_CUE.search(last):
        return None  # a bare "Correction." can arrive as its own final, just before the words
    for e in committed_edits:  # edits to earlier lines: repairs pass, fact changes do not
        original, corrected = _edit_texts(e)
        if (_lost(_count(_NUMBER, original), _count(_NUMBER, corrected))
                or _lost(_count(_SIDE, original), _count(_SIDE, corrected))
                or not _kept(original, [set(_WORD.findall(corrected.lower()))])):
            return "edited_committed"
    before = f"{span}\n{new}"
    if _lost(_count(_NUMBER, before), _count(_NUMBER, out)):
        return "lost_number"
    if _lost(_count(_SIDE, before), _count(_SIDE, out)):
        return "lost_side"
    if _lost(_count(_NEGATION, before), _count(_NEGATION, out)):
        return "lost_negation"
    out_statements = [set(_WORD.findall(s.lower())) for s in _statements(out)]
    if not all(_kept(s, out_statements) for s in _statements(span)):
        return "lost_statement"
    return None


def verbatim_append(span: str, new: str) -> str:
    """The safe text: the span unchanged, the new words appended as said."""
    if not span:
        return new
    if not new or new.startswith("\n") or span.endswith(("\n", " ")):
        return span + new
    return f"{span} {new}"
