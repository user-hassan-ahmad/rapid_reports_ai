"""Pre-applied items from the post-generation check (spec §10.4; decision: automatic edits happen ONLY before render).

The background engine never rewrites the report. The only automatic edits are the post-gen check's
(`report_review.run_quality_check`): code removal of a contradicted negative and insertion of an absent dictated
finding. The check records the report before its edits (`quality_check.pre_edit_report`) and what it applied
(`quality_check.applied_edits`: {"type": "removal", "clause"} / {"type": "insertion", "sentence"}). `bridge_items`
turns each applied edit into one `pre_applied` item on the FINAL text the user is shown (the reviewed report):
- removal → kind `removed`, lane accuracy, detector `post_check.removal`, a zero-width anchor at the removal point,
  `evidence.removed_text` (the flagged clause);
- insertion → kind `absent`, lane coverage, detector `post_check.insert`, anchor = the inserted text;
- both carry `evidence.undo = {"final_span": [j1, j2], "original_text", "final_text", "left", "right"}`: replacing
  that span of the final text (`final_text`) with `original_text` restores the pre-edit text of that edit; `left` /
  `right` are up to UNDO_CONTEXT characters of final text either side, so a client can re-find the edit by context
  once the report has changed.
Spans come from a character diff of the pre-edit and final texts (the only differences are the check's own edits);
an edit that cannot be located exactly, or whose diff region is not a clean removal / insertion, is skipped (logged),
never guessed. `dedupe` drops the engine's own items on a bridged span (the bridge item wins). Pure code."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from .items import Edit, ReviewInput, ReviewItem, Span, item_key, text_hash

Op = Tuple[str, int, int, int, int]
Region = Tuple[int, int, int, int]
UNDO_CONTEXT = 16
REMOVAL, INSERT = "post_check.removal", "post_check.insert"
_NEG_HEAD = re.compile(r"^(?:No|There is no|There are no|Without)\s+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def opcodes(original: str, final: str) -> List[Op]:
    return SequenceMatcher(None, original, final, autojunk=False).get_opcodes()


def _changed(ops: List[Op], lo: int, hi: int, side: str) -> Optional[Region]:
    """The merged changed region(s) touching [lo, hi) on the original (side "i") or the final text ("j")."""
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


def undo(original: str, final: str, region: Region) -> dict:
    i1, i2, j1, j2 = region
    return {"final_span": [j1, j2], "original_text": original[i1:i2], "final_text": final[j1:j2],
            "left": final[max(0, j1 - UNDO_CONTEXT):j1], "right": final[j2:j2 + UNDO_CONTEXT]}


def _occurrences(text: str, needle: str) -> List[int]:
    out, k = [], text.find(needle) if needle else -1
    while k >= 0:
        out.append(k)
        k = text.find(needle, k + 1)
    return out


def _slide(longer: str, a: int, b: int, ok) -> Optional[Tuple[int, int]]:
    """A pure insertion / deletion of `longer[a:b]` can sit anywhere along a run of repeated text (the diff may draw
    '. Small effusion' for an inserted ' Small effusion.'). The nearest equivalent placement (same resulting text)
    that satisfies `ok(x, y)`, else None."""
    base, n = longer[:a] + longer[b:], b - a
    for d in sorted(range(-n, n + 1), key=abs):
        x, y = a + d, b + d
        if 0 <= x and y <= len(longer) and ok(x, y) and longer[:x] + longer[y:] == base:
            return x, y
    return None


def _locate_removal(pre: str, final: str, ops: List[Op], clause: str) -> Optional[Region]:
    """The diff region that removed `clause`: a whole sentence (the clause itself) or one item of a negative list
    (the item's text). Clean only when the final side is shorter, keeps none of the needle, and the region covers
    the needle's middle."""
    target = clause.strip().rstrip(".")
    item = _NEG_HEAD.sub("", target)
    for needle in dict.fromkeys(n for n in (target, item) if n):
        for k in _occurrences(pre, needle):
            r = _changed(ops, k, k + len(needle), "i")
            if r is None:
                continue
            i1, i2, j1, j2 = r
            if j1 == j2:                    # a pure deletion: place it on the clause (or the list item) itself
                def ok(x, y):
                    return pre[x:y].strip().rstrip(".") == needle or pre[x:y].strip(" ,.;") == needle
                m = _slide(pre, i1, i2, ok)
                if m is not None:
                    i1, i2, j1, j2 = m[0], m[1], j1 + m[0] - r[0], j1 + m[0] - r[0]
            if j2 - j1 < i2 - i1 and needle not in final[j1:j2] and i1 <= k + len(needle) // 2 < i2:
                return i1, i2, j1, j2
    return None


def _locate_insert(pre: str, final: str, ops: List[Op], sentence: str) -> Optional[Tuple[int, Region]]:
    """(start of the inserted sentence in the final text, its diff region): the sentence occurs once in the final
    text and its region added only it (plus whitespace)."""
    s = sentence.strip()
    if not s or final.count(s) != 1:
        return None
    k = final.find(s)
    r = _changed(ops, k, k + len(s), "j")
    if r is None:
        return None
    i1, i2, j1, j2 = r
    if i1 == i2 and final[j1:j2].strip() != s:     # a pure insertion drawn off the sentence: slide it on
        m = _slide(final, j1, j2, lambda x, y: final[x:y].strip() == s)
        if m is not None:
            i1 = i2 = i1 + m[0] - j1
            j1, j2 = m
    if pre[i1:i2].strip() or final[j1:j2].strip() != s:
        return None
    return k, (i1, i2, j1, j2)


_SENT_END = re.compile(r"[.!?:](?=\s)|\n")


def _sentence_before(final: str, j: int) -> Optional[str]:
    """The sentence (or heading line) ending at `j` in the final text, when it occurs there exactly once: the anchor
    an insert edit re-applies after."""
    tail = final[:j].rstrip()
    if not tail:
        return None
    start = 0
    for m in _SENT_END.finditer(tail, 0, len(tail) - 1):
        start = m.end()
    s = tail[start:].strip()
    return s if s and final.count(s) == 1 else None


def _item(inp: ReviewInput, run_id: str, h: str, lane: str, kind: str, det: str, text: str, anchor: Span,
          section: Optional[str], label: str, reason: str, edit: Edit, evidence: dict) -> ReviewItem:
    return ReviewItem(
        key=item_key(lane, kind, text), report_id=inp.report_id, run_id=run_id, lane=lane, detectors=[det],
        kind=kind, cls="action", section=section.upper() if section else None, anchor=anchor, label=label[:80],
        reason=reason, edit=edit, evidence=evidence, source_line=text if kind == "absent" else None,
        status="pre_applied",
        history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h, "detail": {"detectors": [det]}},
                 {"at": _now(), "event": "pre_applied", "actor": "post_check", "text_hash": h,
                  "detail": {"kind": kind}}])


def bridge_items(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], List[dict]]:
    """(items, log): one `pre_applied` item per edit the post-gen check applied, on the reviewed (final) text."""
    from .verifier import _section_of
    qc = inp.artifacts.quality_check or {}
    pre, final = inp.pre_edit_report, inp.artifacts.report
    edits = qc.get("applied_edits") or []
    if not pre or not edits or pre == final:
        return [], []
    names = list(inp.artifacts.sections or [])
    ops = opcodes(pre, final)
    h = text_hash(final)
    items: List[ReviewItem] = []
    log: List[dict] = []
    for e in edits:
        typ = e.get("type")
        entry = {"type": typ, "located": False}
        log.append(entry)
        if typ == "removal":
            clause = (e.get("clause") or "").strip()
            entry["clause"] = clause
            r = _locate_removal(pre, final, ops, clause) if clause else None
            if r is None:
                continue
            u = undo(pre, final, r)
            sec = (_section_of(final, r[2], names) or "").upper() or None
            items.append(_item(inp, run_id, h, "accuracy", "removed", REMOVAL, clause,
                               Span(start=r[2], end=r[2], text="", text_hash=h), sec,
                               f"Removed: {clause}",
                               "Contradicted by the dictation; removed before the report was shown.",
                               Edit(mode="remove", find=clause, section=sec),
                               {"source": "post_check", "removed_text": clause, "negative": True, "undo": u}))
        elif typ == "insertion":
            sent = (e.get("sentence") or "").strip()
            entry["sentence"] = sent
            loc = _locate_insert(pre, final, ops, sent)
            if loc is None:
                continue
            k, r = loc
            u = undo(pre, final, r)
            sec = (_section_of(final, k, names) or "").upper() or None
            items.append(_item(inp, run_id, h, "coverage", "absent", INSERT, sent,
                               Span(start=k, end=k + len(sent), text=sent, text_hash=h), sec,
                               f"Added: {sent}",
                               "A dictated finding was missing from the report; added before the report was shown.",
                               Edit(mode="insert", replace=sent, after=_sentence_before(final, r[2]), section=sec),
                               {"source": "post_check", "inserted_text": sent, "undo": u}))
        else:
            continue
        entry.update(located=True, final_span=u["final_span"])
    return items, log


def is_bridge(it: ReviewItem) -> bool:
    return bool(it.detectors) and all(d in (REMOVAL, INSERT) for d in it.detectors)


def dedupe(items: List[ReviewItem], bridge: List[ReviewItem]) -> Tuple[List[ReviewItem], List[ReviewItem]]:
    """(kept, dropped): the engine's own items whose anchor overlaps a bridge item's non-empty span (the inserted
    text). The bridge item wins: the edit really was applied."""
    spans = [(b.anchor.start, b.anchor.end) for b in bridge if b.anchor is not None and b.anchor.end > b.anchor.start]
    kept, dropped = [], []
    for it in items:
        a = it.anchor
        dup = a is not None and any(a.start < e and s < a.end for s, e in spans)
        (dropped if dup else kept).append(it)
    return kept, dropped


__all__ = ["UNDO_CONTEXT", "REMOVAL", "INSERT", "opcodes", "undo", "bridge_items", "is_bridge", "dedupe"]
