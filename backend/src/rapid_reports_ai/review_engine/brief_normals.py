"""Brief normals → review items (one owner per atom).

The brief's linked normals (`quick_report_brief`, RR_GROUPED_NORMALS) already label every generated normal atom
`default | implicated | contradicted | dictated` before generation. Those labels become review items here, so the
rail does not re-ask the negatives classifier about the same statements:

    atom action (brief)     kind            cls     status  evidence
    keep (default)          assumed_normal  info    open    source "brief" (editor-only, no rail row)
    implicated              check           minor   open    check_reason "uncertain", pointer, included True
    do_not_assert / dictated  (no item: not rendered; the classifier and the lanes still read the final text)

Implicated atoms are rendered by default (Hassan, default-negatives policy) and marked amber by the rail: the item
is the mark, the text stays.

Anchors are on the FINAL report text (the generator may re-merge the brief's sentences), on the atom's structure
term inside the FINDINGS normal statements:
1. the unit's rendered sentence occurs once in FINDINGS → the atom's term span inside it (`atoms[].span`);
2. else the term (or a `linked_normals.TERM_EQUIVALENTS` variant) occurs in exactly one FINDINGS sentence, and that
   sentence is a normal / negative statement → the term span there;
3. else the item is unanchored (anchor None). Never guessed.

`dedupe`: brief labels win over the classifier's own default / implicated verdicts on the same span (the classifier
item is dropped). A classifier finding the brief cannot know about (conflict, number, a code removal) outranks: it
stays, and the brief items on that clause are dropped. Pure code, no model calls."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .. import linked_normals as ln
from . import negatives, verifier
from .items import ReviewInput, ReviewItem, Span, item_key, text_hash

DETECTOR = "brief.linked_normals"
LANE = "accuracy"
ORIGINAL_KIND = "normal_atom"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def linked_atoms(brief: Optional[dict]) -> List[Tuple[dict, dict]]:
    """(unit, atom) for every rendered atom of a linked normal unit (action keep or implicated)."""
    out = []
    for u in ((brief or {}).get("decisions") or {}).get("normals") or []:
        if not isinstance(u, dict) or not u.get("linked"):
            continue
        for a in u.get("atoms") or []:
            if a.get("action") in ("keep", "implicated") and a.get("term"):
                out.append((u, a))
    return out


def _findings_region(report: str, names: List[str]) -> Tuple[int, int]:
    name = next((s for s in names if s.strip().rstrip(":").strip().lower() == "findings"), "FINDINGS")
    return verifier._section_body(report, name, names) or (0, len(report))


def _free(span: Tuple[int, int], taken: List[Tuple[int, int]]) -> bool:
    return not any(a < span[1] and span[0] < b for a, b in taken)


def locate(report: str, unit: dict, atom: dict, names: List[str], taken: List[Tuple[int, int]]
           ) -> Optional[Tuple[int, int]]:
    """The atom's term span in the final report (see the module docstring), or None."""
    a0, a1 = _findings_region(report, names)
    region = report[a0:a1]
    rendered, sp = unit.get("rendered") or "", atom.get("span")
    if rendered and sp and region.count(rendered) == 1:
        s = a0 + region.index(rendered) + sp[0]
        e = a0 + region.index(rendered) + sp[1]
        got = ln.term_span(report[s:e], atom["term"])
        if got == (0, e - s) and _free((s, e), taken):
            return s, e
    hits = []
    for s, e in verifier._sentence_spans(region, names):
        sent = region[s:e]
        pos = 0
        while (m := ln.term_span(sent, atom["term"], pos)) is not None:
            span = (a0 + s + m[0], a0 + s + m[1])
            if _free(span, taken):
                hits.append((span, sent))
            pos = m[1]
    if len(hits) == 1 and negatives.is_normal_or_negative(hits[0][1]):
        return hits[0][0]
    return None


def build_items(inp: ReviewInput, run_id: str) -> List[ReviewItem]:
    """One item per rendered linked-normal atom (module docstring). Empty when the brief has no linked normals."""
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    taken: List[Tuple[int, int]] = []
    items: List[ReviewItem] = []
    for unit, atom in linked_atoms(inp.artifacts.brief):
        span = locate(report, unit, atom, names, taken)
        anchor = None
        if span:
            taken.append(span)
            anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h)
        sec = verifier._section_of(report, span[0], names) if span else None
        base = {"source": "brief", "atom_id": atom.get("id"), "term": atom["term"], "atom_text": atom.get("text"),
                "pid": unit.get("pid"), "label": atom.get("label"), "label_source": atom.get("label_source"),
                "unit_mode": unit.get("mode")}
        if atom["action"] == "implicated":
            pointer = atom.get("pointer") or ""
            label, reason = negatives.check_text("uncertain", pointer)
            kind, cls = "check", negatives.CLS["uncertain"]
            evidence = {**base, "check_reason": "uncertain", "pointer": pointer, "included": True,
                        **({"jev_affected": atom["jev_affected"]} if atom.get("jev_affected") is not None else {})}
        else:
            label, reason, kind, cls = "Assumed normal", "", "assumed_normal", negatives.CLS["assumed_normal"]
            evidence = base
        items.append(ReviewItem(
            key=item_key(LANE, ORIGINAL_KIND, atom.get("text") or atom["term"]), report_id=inp.report_id,
            run_id=run_id, lane=LANE, detectors=[DETECTOR], kind=kind, cls=cls,
            section=sec.upper() if sec else None, anchor=anchor, label=label, reason=reason, evidence=evidence,
            status="open", history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                                     "detail": {"detectors": [DETECTOR]}}]))
    return items


def _overlap(a: Optional[Span], b: Optional[Span]) -> bool:
    return a is not None and b is not None and a.start < b.end and b.start < a.end


def _same_verdict(n: ReviewItem) -> bool:
    """A classifier item that only restates what the brief already decided (default / implicated)."""
    return n.kind == "assumed_normal" or (n.kind == "check" and (n.evidence or {}).get("check_reason") == "uncertain")


def dedupe(neg_items: List[ReviewItem], brief_items: List[ReviewItem]
           ) -> Tuple[List[ReviewItem], List[ReviewItem], List[dict]]:
    """(classifier items kept, brief items kept, log): one item per span (module docstring)."""
    drop_neg, drop_brief, log = set(), set(), []
    for n in neg_items:
        hit = [b for b in brief_items if _overlap(n.anchor, b.anchor)]
        if not hit:
            continue
        if _same_verdict(n):
            drop_neg.add(n.id)
            log.append({"source": "brief_normals", "kept": [b.id for b in hit], "dropped": n.id, "key": n.key,
                        "kind": n.kind, "anchor": n.anchor.model_dump() if n.anchor else None})
        else:
            for b in hit:
                drop_brief.add(b.id)
                log.append({"source": "brief_normals", "kept": [n.id], "dropped": b.id, "key": b.key,
                            "kind": b.kind, "anchor": b.anchor.model_dump() if b.anchor else None})
    return ([n for n in neg_items if n.id not in drop_neg], [b for b in brief_items if b.id not in drop_brief], log)


__all__ = ["DETECTOR", "linked_atoms", "locate", "build_items", "dedupe"]
