"""Brief labels → the words the generator wrote (spec docs/superpowers/specs/2026-10-09-negatives-one-owner-design.md
§3.1). One owner per judgement: the brief selected and labelled every negative and linked normal before the report was
written; this finds where each one landed so the post-gen check and the review engine defer to that label instead of
re-judging it.

    brief_labels(decisions)          every brief label (mandatory / finding-linked negatives, linked-normal atoms,
                                     dictated negatives) with a stable ref and a key term
    units(report)                    the normal / negative statements of FINDINGS + IMPRESSION, with positions
    match_terms(report, labels, us)  pass 1, code: a label's key term in exactly one unit, longest term first
    link(labels, us)                 pass 2, Jev: "does this sentence say X?" for the labels pass 1 left
    anchor(report, decisions)        both passes; never raises
    relocate(anchors, report)        anchors re-found on the report after the check's own edits
    brief_rules(...)                 spec Q2 / Q3: protect brief-kept clauses, remove OMIT clauses on two signals
    anchor_log(anchors, rules)       counts, unanchored labels, brief errors (logged, never surfaced: spec Q4)

An unanchored label is not an error: the generator dropped or merged it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple

from . import linked_normals as ln
from . import report_reconcile as rc

logger = logging.getLogger(__name__)

KEEP = frozenset({"keep", "default", "implicated", "dictated"})
OMIT = frozenset({"contradicted", "expected", "do_not_assert"})

_LEAD = re.compile(r"^\s*(?:no|nil|without|there\s+(?:is|are|was|were)\s+no)\s+", re.I)
_INNER = re.compile(r"\b(?:no|without)\s+(?=\S)", re.I)
_HEDGE = re.compile(r"^(?:definite|definitive|evidence\s+of|any|significant|obvious)\s+", re.I)
_VERB_TAIL = re.compile(r"\s+(?:(?:is|are|was|were)\s+)?(?:identified|seen|present|demonstrated|noted|detected)\b.*$",
                        re.I)
_PLACE_TAIL = re.compile(r"\s+(?:by|on|in|at|within|from|involving)\s+(?:the\s+)?\S.*$", re.I)
# A trailing place phrase is boilerplate ("in the visualised thoracic skeleton") unless it carries a side or a level
# ("at T7", "in the left kidney"): then it is part of the claim and stays in the term. "by ..." names the cause
# ("invasion by the right upper lobe mass"), never part of the claim, so it always goes.
_QUALIFIER = re.compile(r"\b(?:left|right|bilateral|contralateral|ipsilateral|[CTLS]\d{1,2}(?:/\d)?|segment\s+\w+)\b",
                        re.I)


@dataclass
class Label:
    ref: str
    text: str
    term: str
    action: str
    source: str            # "sheet" | "finding:<key>" | "atom" | "dictated"
    pointer: str = ""


def enabled() -> bool:
    """Kill switch: RR_BRIEF_ANCHOR=0 skips anchoring end to end (today's behaviour)."""
    return os.environ.get("RR_BRIEF_ANCHOR", "1").strip().lower() not in ("0", "false", "off")


def key_term(text: str) -> str:
    """The denied phrase without its boilerplate: "No osseous lesion identified in the visualised thoracic skeleton"
    → "osseous lesion"; "... with no definite chest wall involvement" → "chest wall involvement"."""
    t = (text or "").strip().rstrip(".")
    if _LEAD.match(t):
        t = _LEAD.sub("", t)
    else:
        found = list(_INNER.finditer(t))
        if not found:
            return ""
        t = t[found[-1].end():]
    t = _HEDGE.sub("", t)
    t = _VERB_TAIL.sub("", t)
    m = _PLACE_TAIL.search(t)
    if m and (m.group(0).split()[0].lower() == "by" or not _QUALIFIER.search(m.group(0))):
        t = t[:m.start()]
    return t.strip(" ,;")


def _pointer(p) -> str:
    p = str(p or "").strip()
    return "" if p in ("-", "->", "—", "none") else p


def brief_labels(decisions: Optional[dict]) -> List[Label]:
    d = decisions or {}
    out: List[Label] = []
    for i, n in enumerate(d.get("negatives") or []):
        term = key_term(n.get("text") or "")
        if not term:
            continue
        src = n.get("source") or "sheet"
        finding = src.split(":", 1)[1] if src.startswith("finding:") else ""
        out.append(Label(f"neg:{i}", n["text"], term, n.get("action") or "keep", src,
                         _pointer(n.get("dictated_finding")) or finding))
    for u in d.get("normals") or []:
        if not isinstance(u, dict) or not u.get("linked"):
            continue
        for a in u.get("atoms") or []:
            if a.get("term"):
                out.append(Label(f"atom:{u.get('pid')}:{a.get('id')}", a.get("text") or a["term"], a["term"],
                                 a.get("action") or "keep", "atom", _pointer(a.get("pointer"))))
    for i, t in enumerate(d.get("dictated_negatives") or []):
        term = key_term(t)
        if term:
            out.append(Label(f"dict:{i}", t, term, "dictated", "dictated"))
    return out


_NORMAL = re.compile(r"\b(?:no|not|nil|without|normal(?:ly)?|unremarkable|patent|intact|clear|preserved|"
                     r"maintained|non-?dilated|undilated)\b", re.I)


@dataclass
class Unit:
    text: str
    start: int
    end: int


@dataclass
class Anchor:
    ref: str
    action: str
    source: str
    pointer: str = ""
    how: str = "none"                 # "term" | "jev" | "none" | "removed" (its clause was edited out)
    span: Optional[List[int]] = None  # the label's words (term) or the whole unit (jev)
    span_text: str = ""
    unit: str = ""                    # the statement the span sits in
    offset: int = 0                   # span start minus unit start (relocation)
    p: Optional[float] = None         # pass 2 probability
    shadowed_by: Optional[str] = None # its only hit is held by this (longer or dictated) label


def units(report: str) -> List[Unit]:
    """Normal / negative statements of FINDINGS + IMPRESSION: a whole normal sentence, or the negative / normal tails
    of a finding sentence ("The nodes measure 14 mm; no contralateral lymphadenopathy" → the tail). Positive heads are
    never units."""
    from .report_review import _sentence_positions, report_sections
    from .review_engine.jev_pass import split_tails   # lazy: review_engine imports report_review
    out: List[Unit] = []
    for sec in report_sections(report):
        a = report.find(sec) if sec else -1
        if a < 0:
            continue
        for s, i, j in _sentence_positions(report, a, a + len(sec)):
            sp = split_tails(s)
            if sp:
                for tail in sp[1]:
                    words = _LEAD.sub("", tail).rstrip(".")
                    k = s.find(words)
                    if words and k >= 0:
                        out.append(Unit(words, i + k, i + k + len(words)))
            elif _NORMAL.search(s):
                out.append(Unit(s, i, j))
    return out


def _rank(lab: Label) -> Tuple[int, int]:
    """Longest term first; among equal terms a dictated label, then a kept one, then an OMIT one."""
    return (-len(lab.term), 0 if lab.action == "dictated" else (1 if lab.action in KEEP else 2))


def _anchor(lab: Label, **kw) -> Anchor:
    return Anchor(lab.ref, lab.action, lab.source, lab.pointer, **kw)


def match_terms(report: str, labels: List[Label], us: List[Unit]) -> Tuple[Dict[str, Anchor], List[Label]]:
    """Pass 1 → ({ref: Anchor}, labels for pass 2). A label anchors when its term occurs in exactly one unit at a
    position no earlier-ranked label holds. A label whose every hit is held is shadowed (merged into the holder);
    no hit, or several free hits, goes to pass 2."""
    taken: List[Tuple[int, int, str]] = []
    got: Dict[str, Anchor] = {}
    left: List[Label] = []
    for lab in sorted(labels, key=_rank):
        free: List[Tuple[int, int, Unit]] = []
        held: Optional[str] = None
        for u in us:
            pos = 0
            while (m := ln.term_span(u.text, lab.term, pos)) is not None:
                s, e = u.start + m[0], u.start + m[1]
                owner = next((r for a, b, r in taken if a < e and s < b), None)
                if owner is None:
                    free.append((s, e, u))
                elif held is None:
                    held = owner
                pos = m[1]
        if len(free) == 1:
            s, e, u = free[0]
            taken.append((s, e, lab.ref))
            got[lab.ref] = _anchor(lab, how="term", span=[s, e], span_text=report[s:e], unit=u.text,
                                   offset=s - u.start)
        elif not free and held is not None:
            got[lab.ref] = _anchor(lab, how="none", shadowed_by=held)
        else:
            left.append(lab)
    return got, left


LINK_MIN = 0.80        # pass 2 acceptance; Task 4's wording lab confirms or moves it
LINK_TIMEOUT_S = 4.0
LINK_WORDING = 'Read only this sentence. It says, in any wording: "{t}".'


def q_says(lab: Label) -> dict:
    return {"type": "noul", "instructions": LINK_WORDING.format(t=lab.text.strip().rstrip(".")),
            "criteria": {"true": "the sentence says it", "false": "the sentence does not say it"}}


def _words(s: str) -> set:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


async def link(labels: List[Label], us: List[Unit], jev=None) -> Dict[str, Anchor]:
    """Pass 2 → {ref: Anchor}: one Jev request per unit (the state is the sentence alone), asking each label that
    shares a content word with it. A label anchors to the unit Jev scores at P >= LINK_MIN when no other unit does."""
    jev = jev or rc._jev
    asks: Dict[int, Dict[str, dict]] = {}
    for k, lab in enumerate(labels):
        w = _words(lab.term)
        for n, u in enumerate(us):
            if w & _words(u.text):
                asks.setdefault(n, {})[f"l{k}"] = q_says(lab)
    if not asks:
        return {}

    async def one(n: int):
        return n, await asyncio.wait_for(jev(us[n].text, asks[n]), LINK_TIMEOUT_S)
    results = await asyncio.gather(*(one(n) for n in asks), return_exceptions=True)
    scores: Dict[int, List[Tuple[float, int]]] = {}
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("brief anchor: Jev link failed (%s: %s)", type(r).__name__, str(r)[:200])
            continue
        n, ans = r
        for qk in asks[n]:
            try:
                p = float(ans[qk]["noul"])
            except (KeyError, TypeError, ValueError):
                continue
            scores.setdefault(int(qk[1:]), []).append((p, n))
    out: Dict[str, Anchor] = {}
    for k, ps in scores.items():
        ps.sort(reverse=True)
        if ps[0][0] >= LINK_MIN and (len(ps) == 1 or ps[1][0] < LINK_MIN):
            lab, u = labels[k], us[ps[0][1]]
            out[lab.ref] = _anchor(lab, how="jev", span=[u.start, u.end], span_text=u.text, unit=u.text, offset=0,
                                   p=round(ps[0][0], 3))
    return out


async def anchor(report: str, decisions: Optional[dict], jev=None) -> List[Anchor]:
    """Both passes, one Anchor per brief label in label order. Never raises."""
    try:
        labels = brief_labels(decisions)
        if not labels:
            return []
        us = units(report)
        got, left = match_terms(report, labels, us)
        if left:
            got.update(await link(left, us, jev))
        return [got.get(l.ref) or _anchor(l) for l in labels]
    except Exception as e:  # noqa: BLE001 - anchoring never blocks the report
        logger.warning("brief anchor failed (%s: %s)", type(e).__name__, str(e)[:200])
        return []


def relocate(anchors: List[Anchor], report: str) -> List[Anchor]:
    """The anchors re-found on `report` (the check's edits shift positions): the unit text, then the span inside it.
    A unit no longer in the report is "removed"."""
    out: List[Anchor] = []
    for a in anchors:
        if a.how not in ("term", "jev"):
            out.append(a)
            continue
        i = report.find(a.unit)
        k = i + a.offset
        if i < 0 or report[k:k + len(a.span_text)] != a.span_text:
            out.append(Anchor(**{**asdict(a), "how": "removed", "span": None}))
        else:
            out.append(Anchor(**{**asdict(a), "span": [k, k + len(a.span_text)]}))
    return out
