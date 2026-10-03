"""Build a /dev/negatives-proto bundle (frontend/src/lib/review/negatives-proto/bundle.ts) from a generated report and
its negatives classification. The report IS the document: contradicted negatives, and negatives carrying a number the
dictation lacks, are removed from it (code removal, report_review.remove_negative_clause) and kept as restorable
widgets; default/implicated negatives become green/amber marks; brief options become ghost widgets."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from rapid_reports_ai.report_review import remove_negative_clause

_HEADING = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$", re.M)


def _diff(before: str, after: str) -> Tuple[int, str]:
    """(position, removed text) for a single removal."""
    p = 0
    while p < len(after) and before[p] == after[p]:
        p += 1
    s = 0
    while s < len(after) - p and before[-1 - s] == after[-1 - s]:
        s += 1
    return p, before[p:len(before) - s]


def _locate(report: str, clause: str, taken: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    """Span of a classified clause in the report: the clause itself, or, for an item split out of a negative list
    ("No X" from "No A, X or B"), the item's own words."""
    c = clause.strip().rstrip(".")
    needles = [c]
    m = re.match(r"^(?:No|There is no|There are no|Without)\s+(.+)$", c, re.I)
    if m:
        needles.append(m.group(1))
    for needle in needles:
        start = 0
        while (i := report.find(needle, start)) >= 0:
            span = (i, i + len(needle))
            if not any(a < span[1] and span[0] < b for a, b in taken):
                return span
            start = i + 1
    return None


def _section_end(report: str, section: str) -> int:
    hs = list(_HEADING.finditer(report))
    for k, h in enumerate(hs):
        if h.group(1).strip().upper() == (section or "").strip().upper():
            end = hs[k + 1].start() if k + 1 < len(hs) else len(report)
            return len(report[:end].rstrip())
    return len(report.rstrip())


def build_bundle(case: dict, report: str, cands: List[dict], labels: Dict[str, dict],
                 options: Optional[List[dict]] = None) -> dict:
    """cands: [{clause, number_code}] in classifier order; labels: {"1": {cls, pointer, number}, ...}."""
    removed, doc = [], report
    for i, c in enumerate(cands, 1):
        lab = labels.get(str(i)) or {}
        # A number never auto-removes a sentence the radiologist dictated: that one is marked amber below.
        reason = ("contradicted" if lab.get("cls") == "contradicted"
                  else "number" if c.get("number_code") and lab.get("cls") != "dictated" else None)
        if not reason:
            continue
        new = remove_negative_clause(doc, c["clause"])
        if new == doc:
            continue                                           # not removable by code: left as a mark below
        p, gone = _diff(doc, new)
        for r in removed:                                      # earlier anchors after p shift left
            if r["anchor"] > p:
                r["anchor"] -= len(gone)
        removed.append({"id": f"r{i}", "reason": reason, "anchor": p, "text": gone, "pointer": lab.get("pointer", "")})
        c["_removed"] = True
        doc = new
    marked, taken = [], []
    for i, c in enumerate(cands, 1):
        lab = labels.get(str(i)) or {}
        if c.get("_removed") or (lab.get("cls") == "dictated" and not c.get("number_code")):
            continue
        cls = "implicated" if lab.get("cls") in ("implicated", "contradicted") or c.get("number_code") else "default"
        span = _locate(doc, c["clause"], taken)
        if not span:
            continue
        taken.append(span)
        marked.append({"id": f"m{i}", "cls": cls, "start": span[0], "end": span[1], "text": doc[span[0]:span[1]],
                       "pointer": lab.get("pointer", "")})
    opts = [{"id": o.get("id") or f"o{k}", "anchor": _section_end(doc, o.get("section") or "FINDINGS"),
             "text": o.get("sentence") or o.get("text") or "", "reason": o.get("reason") or o.get("kind") or ""}
            for k, o in enumerate(options or []) if (o.get("sentence") or o.get("text"))]
    return {"version": 1, "id8": case["id8"], "scan": case.get("scan", ""), "history": case.get("history", ""),
            "dictation": case.get("dictation", ""), "report": doc, "marked": sorted(marked, key=lambda m: m["start"]),
            "removed": removed, "options": opts}
