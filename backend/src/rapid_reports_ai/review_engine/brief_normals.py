"""Brief normals → review items (one owner per atom).

The brief's linked normals (`quick_report_brief`, RR_GROUPED_NORMALS) already label every generated normal atom
`default | implicated | contradicted | dictated` before generation. Those labels become review items here, so the
rail does not re-ask the negatives classifier about the same statements:

    atom action (brief)     kind            cls     status  evidence
    keep (default)          assumed_normal  info    open    source "brief" (editor-only, no rail row)
    implicated              assumed_normal  info    open    form "negative" (amber), pointer, included True
    do_not_assert / dictated  (no item: not rendered; the classifier and the lanes still read the final text)

Implicated atoms are rendered by default (Hassan, default-negatives policy) and tinted amber in the AI layer
(`negatives.ai_layer`): the item is the mark, the text stays, no rail card.

With `quality_check.anchors` (brief_anchor, spec 2026-10-09) items come from the anchors instead: every anchored
kept / implicated label the brief owns, conflict cards from `quality_check.brief_conflicts`, and `owned_spans` for
the classifier. The brief owns selection and what it labels reliably (dictated, OMIT, finding-linked negatives,
linked-normal atoms, carded clauses); the classifier owns default-vs-implicated salience for sheet negatives the brief
merely kept (`owned`: no brief item, not owned, so the classifier reads them). Reports without anchors use the legacy
atom anchoring below.

Anchors are on the FINAL report text (the generator may re-merge the brief's sentences), on the atom's structure
term inside the FINDINGS normal statements:
1. the unit's rendered sentence occurs once in FINDINGS → the atom's term span inside it (`atoms[].span`);
2. else the term (or a `linked_normals.TERM_EQUIVALENTS` variant) occurs in exactly one FINDINGS sentence, and that
   sentence is a normal / negative statement → the term span there;
3. else the item is unanchored (anchor None). Never guessed.

`dedupe`: brief labels win over the classifier's own default / implicated verdicts on the same span (the classifier
item is dropped). A classifier finding the brief cannot know about (conflict, number, a code removal) outranks: it
stays, and the brief items on that clause are dropped. Pure code, no model calls.

The engine builds these items BEFORE the classifier starts and passes their anchors as `owned`, so the classifier
does not re-read statements the brief already labelled (it still applies its code number check to them). Every item
carries `evidence.form` ("negative" | "normal") from the atom's statement (`jev_pass.statement_form`)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .. import brief_anchor
from .. import linked_normals as ln
from . import negatives, verifier
from .items import ReviewInput, ReviewItem, Span, item_key, text_hash
from .jev_pass import statement_form

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


NEG_KIND = "brief_negative"
CONFLICT_KIND = "brief_conflict"


def anchors_of(inp: ReviewInput) -> Optional[List[dict]]:
    """quality_check.anchors (brief_anchor), or None for a report generated before anchoring shipped."""
    a = (inp.artifacts.quality_check or {}).get("anchors")
    return a if isinstance(a, list) else None


def _clause_span(report: str, clause: str) -> Optional[Tuple[int, int]]:
    """A carded clause (minus its final ".") on the report: its first whole-sentence occurrence
    (`brief_anchor._clause_spans`), else its only occurrence anywhere; None when absent or ambiguous."""
    c = (clause or "").strip().rstrip(".")
    if not c:
        return None
    whole = brief_anchor._clause_spans(report, c)
    if whole:
        return whole[0]
    return (report.find(c), report.find(c) + len(c)) if report.count(c) == 1 else None


def _conflicts(inp: ReviewInput) -> List[Tuple[dict, Optional[Tuple[int, int]]]]:
    """(brief conflict, its span) — one per clause."""
    report = inp.artifacts.report or ""
    out: List[Tuple[dict, Optional[Tuple[int, int]]]] = []
    taken: List[Tuple[int, int]] = []
    for c in (inp.artifacts.quality_check or {}).get("brief_conflicts") or []:
        if not isinstance(c, dict):
            continue
        span = _clause_span(report, c.get("clause") or "")
        if span and not _free(span, taken):
            continue
        out.append((c, span))
        if span:
            taken.append(span)
    return out


def owned(a: dict) -> bool:
    """Whether the brief owns this anchor. The brief owns selection and what it labels reliably (dictated, contradicted
    / OMIT, finding-linked negatives, linked-normal atoms); the classifier owns default-vs-implicated salience for
    sheet negatives the brief merely kept (lab b204edc: the brief's reasoning-off labeller called 7/58 implicated
    negatives implicated). Those get no brief item and are not in `owned_spans`: the classifier reads them."""
    return not (str(a.get("ref") or "").startswith("neg:") and a.get("source") == "sheet"
                and a.get("action") in ("keep", "default", "implicated"))


def owned_spans(inp: ReviewInput) -> Optional[List[Tuple[int, int]]]:
    """The spans the classifier never re-reads (spec §3.3): every anchored brief label on the final report (dictated,
    and low-score OMIT anchors too: deliberately, the brief owns them), and every clause the post-gen check carded
    (`brief_conflicts`, removal_blocked with refs [] included), so the brief card and its brief_reason stand.
    None without anchors (the engine then uses the legacy brief items' anchors)."""
    anchors = anchors_of(inp)
    if anchors is None:
        return None
    report = inp.artifacts.report or ""
    us = brief_anchor.units(report)
    spans = [sp for a in anchors if isinstance(a, dict) and a.get("how") in ("term", "jev") and owned(a)
             and (sp := brief_anchor.relocate_one(a, report, us))]
    return spans + [sp for _, sp in _conflicts(inp) if sp]


def _conflict_text(c: dict) -> Tuple[str, str]:
    """(label, reason) of a brief conflict card, by `brief_conflicts[].reason` (brief_anchor.rules / the check)."""
    src = str(c.get("source") or "")
    finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
    reason = c.get("reason")
    if reason == "brief_kept":
        what = f"Kept as a pertinent negative for {finding}" if finding else "Stated by the AI as normal"
        return ("Check: may conflict with your dictation",
                f"{what}, but a check found it may contradict your dictation. Remove it, or dismiss to keep it.")
    if reason == "brief_split":
        return ("Check: may conflict with your dictation",
                "The brief kept part of this and advised against part, and a check found it may contradict your "
                "dictation. Remove it, or dismiss to keep it.")
    if reason == "removal_blocked":
        return ("Check: conflicts with your dictation",
                "Contradicts your dictation, but the sentence also states other content, so it was not removed "
                "automatically. Remove it, or dismiss to keep it.")
    p = negatives.pointer_text(c.get("pointer"))
    return ("Check: advised against stating this",
            (f"Your dictation reports “{p}”, so this was not meant to be stated. Remove it, or dismiss to keep it."
             if p else "The brief advised against stating this. Remove it, or dismiss to keep it."))


def _make(inp: ReviewInput, run_id: str, key_text: str, kind: str, cls: str, span: Optional[Tuple[int, int]],
          label: str, reason: str, evidence: dict, edit=None, verified=None, original: str = NEG_KIND) -> ReviewItem:
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h) if span else None
    sec = verifier._section_of(report, span[0], names) if span else None
    return ReviewItem(key=item_key(LANE, original, key_text), report_id=inp.report_id, run_id=run_id, lane=LANE,
                      detectors=[DETECTOR], kind=kind, cls=cls, section=sec.upper() if sec else None,
                      anchor=anchor, label=label, reason=reason, evidence=evidence, edit=edit, verified=verified,
                      status="open", history=[{"at": _now(), "event": "created", "actor": "engine",
                                               "text_hash": h, "detail": {"detectors": [DETECTOR]}}])


def conflict_cards(inp: ReviewInput, run_id: str) -> Tuple[List[ReviewItem], List[Tuple[int, int]]]:
    """(check cards, their spans) from `quality_check.brief_conflicts`: one card per clause, code's one-click
    removal when its guards pass (never pre-applied)."""
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    out: List[ReviewItem] = []
    taken: List[Tuple[int, int]] = []
    for c, span in _conflicts(inp):
        clause = report[span[0]:span[1]] if span else (c.get("clause") or "").strip().rstrip(".")
        anchor = Span(start=span[0], end=span[1], text=clause, text_hash=h) if span else None
        fix, verified = negatives._conflict_fix(inp, report, anchor, c.get("clause") or "", names)
        label, reason = _conflict_text(c)
        out.append(_make(inp, run_id, clause, "check", negatives.CLS["conflict"], span, label, reason,
                         {"source": "brief", "check_reason": "conflict", "brief_reason": c.get("reason"),
                          "refs": c.get("refs") or [], "score": c.get("score"),
                          "pointer": negatives.pointer_text(c.get("pointer")),
                          **({"why": c["why"]} if c.get("why") else {})},
                         edit=fix, verified=verified, original=CONFLICT_KIND))
        if span:
            taken.append(span)
    return out, taken


def _from_anchors(inp: ReviewInput, run_id: str, anchors: List[dict]) -> List[ReviewItem]:
    report = inp.artifacts.report or ""
    out, taken = conflict_cards(inp, run_id)
    us = brief_anchor.units(report)
    for a in anchors:
        if not isinstance(a, dict) or a.get("how") not in ("term", "jev") \
                or a.get("action") not in ("keep", "default", "implicated") or not owned(a):
            continue      # dictated: your own words; OMIT: removed, or a conflict card above; a kept sheet
            #               negative: the classifier's default-vs-implicated call (`owned`)
        span = brief_anchor.relocate_one(a, report, us)
        if span and not _free(span, taken):
            continue      # one card per clause: the conflict card stands
        src = str(a.get("source") or "")
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        cls = "implicated" if a.get("action") == "implicated" else "default"
        label, reason, form = negatives.ai_layer(cls, a.get("pointer") or "", finding,
                                                 report[span[0]:span[1]] if span else "")
        ev = {"source": "brief", "ref": a.get("ref"), "label": cls, "how": a.get("how"), "form": form,
              **({"pointer": negatives.pointer_text(a.get("pointer")) or finding}
                 if (cls == "implicated" or finding) else {})}
        out.append(_make(inp, run_id, a.get("ref") or a.get("span_text") or "", "assumed_normal",
                         negatives.CLS["assumed_normal"], span, label, reason, ev))
    return out


def build_items(inp: ReviewInput, run_id: str) -> List[ReviewItem]:
    """With anchors: `_from_anchors`. Else one item per rendered linked-normal atom (module docstring), plus any
    brief conflict cards. Empty when the brief has no linked normals and the check left no cards."""
    anchors = anchors_of(inp)
    if anchors is not None:
        return _from_anchors(inp, run_id, anchors)
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    items, card_spans = conflict_cards(inp, run_id)
    taken: List[Tuple[int, int]] = []
    for unit, atom in linked_atoms(inp.artifacts.brief):
        span = locate(report, unit, atom, names, taken)
        if span and not _free(span, card_spans):
            continue                                  # one card per clause: the conflict card stands
        anchor = None
        if span:
            taken.append(span)
            anchor = Span(start=span[0], end=span[1], text=report[span[0]:span[1]], text_hash=h)
        sec = verifier._section_of(report, span[0], names) if span else None
        base = {"source": "brief", "atom_id": atom.get("id"), "term": atom["term"], "atom_text": atom.get("text"),
                "pid": unit.get("pid"), "label": atom.get("label"), "label_source": atom.get("label_source"),
                "unit_mode": unit.get("mode"),
                "form": statement_form(atom.get("text") or (report[span[0]:span[1]] if span else atom["term"]))}
        if atom["action"] == "implicated":
            pointer = negatives.pointer_text(atom.get("pointer"))   # a stored "->" is the labeller's "none"
            label, reason, form = negatives.ai_layer("implicated", pointer)
            kind, cls = "assumed_normal", negatives.CLS["assumed_normal"]
            evidence = {**base, "form": form, "pointer": pointer, "included": True,
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


__all__ = ["DETECTOR", "linked_atoms", "locate", "build_items", "dedupe", "owned_spans", "owned", "anchors_of",
           "conflict_cards"]
