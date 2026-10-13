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


def has_cue(span: str, new: str) -> bool:
    """A correction cue in the new words, or ending the span: the model may change things."""
    last = (_statements(span) or [""])[-1]
    return bool(CORRECTION_CUE.search(new or "") or CORRECTION_CUE.search(last))


def _ordered(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def moved_into_earlier(span: str, new: str, out: str) -> bool:
    """Whether the output may have moved words onto another finding: a trigger for the Jev
    question (polish_attachment), never a verdict. Any of:
    (A) new words placed before text already dictated: an output statement after the first one
        holding new words is span text only (live 2026-10-12: "of the right kidney" went onto
        the stranding sentence instead of the calculus it followed);
    (B) new words out of the order they were said (a new sentence's tail moved back onto the
        previous sentence: "...lower lobe with air bronchograms" -> "effusion with air bronchograms");
    (C) a side or number shifting between statements already dictated (counts unchanged, so the
        count check passes a swap);
    (D) a new sentence after a finished one, merged into another ("The liver is normal.
        The mass encases the SMA." -> "The liver is normal and encases the SMA"). Joins of related
        findings also trigger it; Jev clears those."""
    span_words = set(_ordered(span))
    new_order = [w for w in _ordered(new) if w not in span_words]
    fresh = set(new_order)
    stmts = _statements(out)
    words = [set(_ordered(s)) for s in stmts]
    if fresh:
        first = next((i for i, w in enumerate(words) if w & fresh), None)
        if first is not None and any(not (w & fresh) and (w & span_words) for w in words[first + 1:]):
            return True                                                            # (A)
        out_words = _ordered(out)
        kept = set(out_words)
        if [w for w in new_order if w in kept] != [w for w in out_words if w in fresh]:
            return True                                                            # (B)
        opens = (span or "").rstrip()[-1:] in ".?!" and (new or "").lstrip()[:1].isupper()
        if opens and len(stmts) < len(_statements(span)) + len(_statements(new)):
            return True                                                            # (D)
    for st in _statements(span):                                                   # (C)
        sw = set(_ordered(st))
        if not sw:
            continue
        k = max(range(len(words)), key=lambda i: len(sw & words[i]) / len(sw), default=None)
        if k is None:
            return False
        if _lost(_count(_SIDE, st), _count(_SIDE, stmts[k])) or _lost(_count(_NUMBER, st), _count(_NUMBER, stmts[k])):
            return True
    return False


def fidelity_violation(span: str, new: str, out: str, committed_edits: list) -> str | None:
    """The reason the output must not be used, or None. With a correction cue in the new
    words, or ending the span, the model may change things (that is what the cue asks for)."""
    if has_cue(span, new):
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
