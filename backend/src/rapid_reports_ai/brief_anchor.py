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
