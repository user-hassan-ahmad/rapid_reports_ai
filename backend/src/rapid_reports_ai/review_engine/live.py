"""Live mode: after the engine writes its pre-applied edits to the report, every persisted anchor moves onto the
written text (the text the user now sees; I5 "one text" holds on the new text) and each pre-applied item carries
the information to undo it.

`rebase_items(items, original, final)` maps positions through a character diff of the two texts (the only
differences are the engine's own pre-applied edits, so the diff is exact in practice; whatever it maps is
re-checked against the text, so a wrong alignment can only unanchor, never mis-anchor):
- an anchor whose text is unchanged moves to its new position (`text_hash` = hash of the written text);
- an anchor that cannot be mapped verbatim is dropped (the original kept in `evidence.original_anchor`);
- a pre-applied removal's anchor becomes zero-width at its removal point (as the shadow log's post-removal anchors);
- a pre-applied insert's anchor is the inserted text when it occurs once in the written text;
- every pre-applied item gets `evidence.undo = {"final_span": [j1, j2], "original_text", "final_text", "left",
  "right"}`: replacing that span of the written text (`final_text`) with `original_text` restores the pre-edit text
  of that edit; `left` / `right` are up to UNDO_CONTEXT characters of written text either side of the span.
Pure code."""
from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from .items import ReviewItem, Span, text_hash

Op = Tuple[str, int, int, int, int]
# Characters of written text kept each side of an undo span, so a client can re-find the edit by context once the
# report has changed (it never trusts stored offsets on a text it has not hashed as the written one).
UNDO_CONTEXT = 16


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opcodes(original: str, final: str) -> List[Op]:
    return SequenceMatcher(None, original, final, autojunk=False).get_opcodes()


def map_pos(p: int, ops: List[Op], end: bool = False) -> Optional[int]:
    """`p` on the original → the written text, through unchanged characters only; None inside a changed run."""
    for tag, i1, i2, j1, j2 in ops:
        if tag != "equal":
            continue
        if (i1 < p <= i2) if end else (i1 <= p < i2):
            return j1 + p - i1
    return None


def rebase_span(span: Span, ops: List[Op], final: str, h: str) -> Optional[Span]:
    if span.end <= span.start:
        return None
    s, e = map_pos(span.start, ops), map_pos(span.end, ops, end=True)
    if s is None or e is None or final[s:e] != span.text:
        return None
    return Span(start=s, end=e, text=span.text, text_hash=h)


def _changed(ops: List[Op], lo: int, hi: int, side: str) -> Optional[Tuple[int, int, int, int]]:
    """The merged changed region(s) touching [lo, hi) on the original (side "i") or the written text ("j")."""
    hit = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        a, b = (i1, i2) if side == "i" else (j1, j2)
        if (a < hi and lo < b) or (a == b and lo <= a <= hi) or (lo == hi and a <= lo <= b):
            hit.append((i1, i2, j1, j2))
    if not hit:
        return None
    return min(x[0] for x in hit), max(x[1] for x in hit), min(x[2] for x in hit), max(x[3] for x in hit)


def rebase_items(items: List[ReviewItem], original: str, final: str) -> None:
    ops = opcodes(original, final)
    h = text_hash(final)
    for it in items:
        ev = dict(it.evidence or {})
        old = it.anchor
        if it.status == "pre_applied" and it.edit is not None:
            region = None
            if it.edit.mode == "remove" and old is not None:
                region = _changed(ops, old.start, old.end, "i")
                it.anchor = Span(start=region[2], end=region[2], text="", text_hash=h) if region else None
            else:
                new = (it.edit.replace or "").strip()
                k = final.find(new) if new and final.count(new) == 1 else -1
                it.anchor = Span(start=k, end=k + len(new), text=new, text_hash=h) if k >= 0 else None
                if k >= 0:
                    region = _changed(ops, k, k + len(new), "j")
            if region:
                i1, i2, j1, j2 = region
                ev["undo"] = {"final_span": [j1, j2], "original_text": original[i1:i2], "final_text": final[j1:j2],
                              "left": final[max(0, j1 - UNDO_CONTEXT):j1], "right": final[j2:j2 + UNDO_CONTEXT]}
        elif old is not None:
            it.anchor = rebase_span(old, ops, final, h)
        if old is not None and (it.anchor is None or it.anchor.start != old.start or it.anchor.end != old.end):
            ev["original_anchor"] = old.model_dump()
        if ev.get("also_anchors"):
            moved = [rebase_span(Span(**a), ops, final, h) for a in ev["also_anchors"]]
            ev["also_anchors"] = [m.model_dump() for m in moved if m is not None]
        it.evidence = ev or None
        it.history.append({"at": _now(), "event": "rebased", "actor": "engine", "text_hash": h,
                           "detail": {"from": text_hash(original)}})


__all__ = ["opcodes", "map_pos", "rebase_span", "rebase_items"]
