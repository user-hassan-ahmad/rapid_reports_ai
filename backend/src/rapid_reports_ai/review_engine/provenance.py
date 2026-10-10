"""Provenance items (approved by Hassan 2026-10-06): which report text did the radiologist not dictate?

- `ai_generated` (lane accuracy, cls info, detector `provenance`): a report clause in FINDINGS, IMPRESSION or another
  body section that asserts SUBSTANTIVE content no dictated line states: a new finding, inference, diagnosis or
  interpretation. A clause is dictated when it has a confident alignment pair (`lanes.confident`) to a dictated line,
  or when the shared Jev pass's W1n answer (`sup{i}`, "the dictated findings report this finding ... in any wording")
  says so. Connective words, reordering, rephrasing and style changes of a dictated line therefore give no item: a
  reworded restatement is dictated. Partial restatements count as dictated (a confidently paired clause gives no item).
  Clause level only, never sub-clause word spans; adjacent marked clauses of one sentence merge into one span.
  `evidence.form` is "synthesis" (the rail's AI layer: negatives / normals carry "negative" / "normal").
- `recommendation` (lane additions, cls minor, detector `code.recommendation`): a recommendation sentence
  (`jev_pass.recommendation`, minus interpretive "suggests" / "suggestive") that no dictated line states, with a
  code-built whole-sentence removal (`Edit(mode="remove")`) checked with `verifier.apply_edit`; never pre-applied.
  A sentence that also holds other parts ("No X identified; referral recommended.") is anchored and removed on its
  recommendation part only (`_rec_target`), or gets no edit when that part cannot be isolated safely; its other
  parts are judged for `ai_generated` like any clause (paired / W1n-supported / normal / owned give no item).

Never marked: technique / comparison / history sections and signature lines (the alignment's clause splitter skips
them); Jev `not_a_finding` statements; normal / negative statements (the negatives classifier's and the brief's: their
`assumed_normal` / `check` items stay the record, and a mixed clause is judged on its split finding head); any clause
an owned (negatives / brief normals) item already anchors on.

Pure code over the alignment and the existing Jev answers: no model call. These kinds are never adjudicated, probed or
reprepared (`PROVENANCE_KINDS`); the frontend decides how to show them."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .alignment import Alignment, ReportClause
from .checks import hedge_tag
from .claims import content_words
from .items import Edit, ReviewInput, ReviewItem, Span, item_key, text_hash
from .jev_pass import JevPass, noul, recommendation, recommendation_parts, split_tails
from .lanes import confident
from .negatives import is_normal_or_negative
from .verifier import apply_edit

KIND_AI = "ai_generated"
KIND_REC = "recommendation"
PROVENANCE_KINDS = frozenset({KIND_AI, KIND_REC})
DETECTOR_AI = "provenance"
DETECTOR_REC = "code.recommendation"
MAX_AI_ITEMS = 20            # provisional: a report with more undictated clauses than this is a generation problem
SUPPORTED_DICTATED = 0.5     # Jev W1n ≥ this: the dictation states the clause in some wording (accuracy SUPPORTED_FLAG)

# "Features suggest X" / "suggestive of X" interpret, they do not recommend ("MRI is suggested" still does).
_INTERPRETIVE = re.compile(r"\bsuggest(?:s|ive|ing)?\b(?!\s+(?:that\s+)?(?:further|follow|clinical|correlation|"
                           r"repeat|an?\s+(?:mri|ct|ultrasound|biopsy|review)))", re.I)
_REC_WORDS = re.compile(r"recommend\w*|advis\w*|suggest\w*|referr\w*|refer|follow|up|correlat\w*", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(t: str) -> str:
    return re.sub(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+", "", " ".join((t or "").split())).strip().rstrip(".;,").lower()


def _jev_index(jp: Optional[JevPass], text: str) -> Optional[int]:
    """The shared Jev pass's index for an alignment clause: the same text, else containment (the two splitters
    differ on list markers and negative lists)."""
    if jp is None:
        return None
    t = _norm(text)
    if not t:
        return None
    ns = [_norm(c) for c in jp.clauses]
    hit = next((i for i, n in enumerate(ns) if n == t), None)
    if hit is None:
        hit = next((i for i, n in enumerate(ns) if n and (n in t or t in n) and min(len(n), len(t)) >= 0.6 * max(len(n), len(t))), None)
    return hit


def _jev_type(jp: Optional[JevPass], i: Optional[int]) -> Optional[str]:
    return jp.clause_type(i) if jp is not None and i is not None else None


def is_recommendation(text: str, jev_type: Optional[str] = None) -> bool:
    """A recommendation sentence: the shared lexicon, without interpretive "suggests"; a Jev type that says the
    statement is about the patient (abnormal / normal / mixed) overrides the lexicon."""
    if not recommendation(_INTERPRETIVE.sub(" ", text)):
        return False
    return jev_type in (None, "not_a_finding")


def _paired(al: Alignment, c: ReportClause) -> bool:
    return any(p.clause_id == c.id and confident(p) for p in al.pairs)


def _rec_dictated(al: Alignment, c: ReportClause) -> bool:
    """A confident pair, or a dictated recommendation line sharing a content word beyond the recommending words."""
    if _paired(al, c):
        return True
    words = {w for w in content_words(c.text) if not _REC_WORDS.fullmatch(w)}
    return any(recommendation(l.text) and words & {w for w in content_words(l.text) if not _REC_WORDS.fullmatch(w)}
               for l in al.lines)


def _supported(jp: Optional[JevPass], i: Optional[int]) -> Optional[float]:
    return noul(jp.support, f"sup{i}") if jp is not None and i is not None else None


def _overlaps(a: Tuple[int, int], spans: List[Tuple[int, int]]) -> bool:
    return any(a[0] < e and s < a[1] for s, e in spans)


def _head_span(report: str, c: ReportClause) -> Optional[Tuple[int, int, str]]:
    """(start, end, head) of a mixed clause's finding head, located in the clause; None when it is not one."""
    sp = split_tails(c.text)
    if not sp:
        return None
    head = sp[0]
    k = report.find(head, c.start, c.end)
    return (k, k + len(head), head) if k >= 0 else None


def _rec_target(report: str, c: ReportClause, sentence: str, names: List[str]
                ) -> Tuple[int, int, Optional[Edit]]:
    """(start, end, remove edit or None) of a recommendation item. A whole recommendation sentence is removed whole.
    A sentence that also holds other parts at ';' (`jev_pass.recommendation_parts`) is anchored on its recommendation
    part(s) only; the removal is offered only when they end the sentence and what stays is the other part(s) closed
    by a '.' ("No X identified; referral recommended." → "No X identified."). Else no edit (never guessed)."""
    parts = recommendation_parts(sentence, is_recommendation)
    if parts is None:
        edit = Edit(mode="remove", find=sentence, section=c.section)
        ok = report.count(sentence) == 1 and apply_edit(report, edit, names) is not None
        return c.sentence_start, c.sentence_end, edit if ok else None
    k = next(i for i, p in enumerate(parts) if p[2])
    j = k
    while j + 1 < len(parts) and parts[j + 1][2]:
        j += 1                                              # the contiguous run of recommendation parts
    start, end = c.sentence_start + parts[k][0], c.sentence_start + parts[j][1]
    find = report[start:end]
    if j != len(parts) - 1 or k == 0 or report.count(find) != 1:
        return start, end, None
    edit = Edit(mode="remove", find=find, section=c.section)
    out = apply_edit(report, edit, names)
    keep = sentence[:parts[k][0]].rstrip().rstrip(";").rstrip() + "."
    if out is None or out[c.sentence_start:c.sentence_start + len(keep)] != keep:
        return start, end, None
    return start, end, edit


def build_items(inp: ReviewInput, run_id: str, al: Alignment, jp: Optional[JevPass],
                owned: List[ReviewItem]) -> Tuple[List[ReviewItem], dict]:
    """(items, log). `owned` = the negatives classifier's and the brief normals' items (their anchors are theirs)."""
    report = inp.artifacts.report or ""
    names = list(inp.artifacts.sections or [])
    h = text_hash(report)
    owned_spans = [(it.anchor.start, it.anchor.end) for it in owned if it.anchor is not None]
    marked: List[Tuple[ReportClause, int, int, dict]] = []      # (clause, start, end, evidence)
    recs: List[Tuple[ReportClause, str]] = []
    rec_seen = set()
    skipped = {"paired": 0, "supported": 0, "normal": 0, "not_a_finding": 0, "owned": 0, "rec_dictated": 0}
    for c in sorted(al.clauses, key=lambda x: x.start):
        i = _jev_index(jp, c.text)
        t = _jev_type(jp, i)
        if is_recommendation(c.text, t):
            if c.sentence_start in rec_seen:
                continue
            rec_seen.add(c.sentence_start)
            sentence = report[c.sentence_start:c.sentence_end]
            if _rec_dictated(al, c):
                skipped["rec_dictated"] += 1
            else:
                recs.append((c, sentence))
            # its other parts ("Findings suspicious for X; MDT recommended.") are judged like any clause
            for ps, pe, rec in recommendation_parts(sentence, is_recommendation) or []:
                a, b = c.sentence_start + ps, c.sentence_start + pe
                if rec or not (c.start <= a and b <= c.end):
                    continue
                part = report[a:b]
                pi = _jev_index(jp, part)
                pt = _jev_type(jp, pi)
                if pt in ("normal", "not_a_finding") or hedge_tag(part) == "negated" or (
                        pt is None and is_normal_or_negative(part)):
                    skipped["normal"] += 1
                    continue
                if _paired(al, c):
                    skipped["paired"] += 1
                    continue
                sup = _supported(jp, pi)
                if sup is not None and sup >= SUPPORTED_DICTATED:
                    skipped["supported"] += 1
                    continue
                if _overlaps((a, b), owned_spans):
                    skipped["owned"] += 1
                    continue
                marked.append((c, a, b, {"clauses": [c.id], "jev_type": pt, "supported": sup, "form": "synthesis"}))
            continue
        if t == "not_a_finding":
            skipped["not_a_finding"] += 1
            continue
        start, end = c.start, c.end
        if t == "normal" or hedge_tag(c.text) == "negated":
            skipped["normal"] += 1
            continue
        hs = _head_span(report, c) if t in (None, "mixed") else None
        if hs:
            start, end = hs[0], hs[1]
        elif t is None and is_normal_or_negative(c.text):
            skipped["normal"] += 1
            continue
        if _paired(al, c):
            skipped["paired"] += 1
            continue
        sup = _supported(jp, i)
        if sup is not None and sup >= SUPPORTED_DICTATED:
            skipped["supported"] += 1
            continue
        if _overlaps((start, end), owned_spans):
            skipped["owned"] += 1
            continue
        marked.append((c, start, end, {"clauses": [c.id], "jev_type": t, "supported": sup, "form": "synthesis"}))

    merged: List[Tuple[ReportClause, int, int, dict]] = []      # adjacent marked clauses of one sentence → one span
    for c, s, e, ev in marked:
        if merged and merged[-1][0].sentence_start == c.sentence_start:
            pc, ps, pe, pev = merged[-1]
            merged[-1] = (pc, min(ps, s), max(pe, e), {**pev, "clauses": pev["clauses"] + ev["clauses"]})
        else:
            merged.append((c, s, e, ev))
    capped = max(0, len(merged) - MAX_AI_ITEMS)
    merged = merged[:MAX_AI_ITEMS]

    def item(lane: str, kind: str, cls: str, detector: str, c: ReportClause, s: int, e: int, label: str,
             reason: str, evidence: dict, edit: Optional[Edit] = None, verified: Optional[dict] = None) -> ReviewItem:
        text = report[s:e]
        return ReviewItem(key=item_key(lane, kind, text), report_id=inp.report_id, run_id=run_id, lane=lane,
                          detectors=[detector], kind=kind, cls=cls, section=c.section,
                          anchor=Span(start=s, end=e, text=text, text_hash=h), label=label, reason=reason,
                          edit=edit, verified=verified, evidence=evidence, status="open",
                          history=[{"at": _now(), "event": "created", "actor": "engine", "text_hash": h,
                                    "detail": {"detectors": [detector]}}])

    items = [item("accuracy", KIND_AI, "info", DETECTOR_AI, c, s, e, "AI-generated", "Not in your dictation.", ev)
             for c, s, e, ev in merged]
    unplaced = 0
    for c, sentence in recs:
        s, e, edit = _rec_target(report, c, sentence, names)
        ok = edit is not None
        if not ok:
            unplaced += 1
        items.append(item("additions", KIND_REC, "minor", DETECTOR_REC, c, s, e,
                          "Recommendation not dictated", "Added by the report writer; remove it if not wanted.",
                          {"sentence": sentence}, edit,
                          {"code": ok, "failed": [] if ok else ["not_placeable"], "addressed": None, "contra": None,
                           "unconfirmed": True}))
    log = {"ai_generated": len(merged), "recommendation": len(recs), "capped": capped, "unplaced": unplaced,
           "skipped": skipped}
    return items, log


__all__ = ["KIND_AI", "KIND_REC", "PROVENANCE_KINDS", "DETECTOR_AI", "DETECTOR_REC", "is_recommendation",
           "build_items"]
