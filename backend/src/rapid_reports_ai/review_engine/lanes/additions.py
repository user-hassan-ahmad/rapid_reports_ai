"""Additions lane (spec §6.4): producers, then one Jev gate (Task 7). Brief options arrive pre-classed `minor`
with their sentence (not judged again, Principle 2); a finding_negative on a structure the report already calls
normal goes to the adjudicator for an `upgrade`. S4 synthesis cards map in code; the clinical pass joins after Gate C."""
from __future__ import annotations

import re
from typing import List, Optional

from ... import report_reconcile as rc
from ..alignment import ANATOMY, Alignment, ReportClause, words
from ..items import Candidate, Edit, ReviewInput, Span
from . import LaneContext

_NORMAL = re.compile(r"\b(normal|unremarkable)\b", re.I)


def _normal_clause_for(sentence: str, al: Alignment) -> Optional[ReportClause]:
    anat = words(sentence) & ANATOMY
    for c in al.clauses:
        if anat and _NORMAL.search(c.text) and not c.negative and anat & words(c.text):
            return c
    return None


def brief_candidates(inp: ReviewInput, al: Alignment) -> List[Candidate]:
    out = []
    for o in inp.artifacts.options:
        s = (o.get("sentence") or "").strip()
        if not s:
            continue
        sub = o.get("kind") or "impression"
        section = o.get("section") or "IMPRESSION"
        ev = {"sub_kind": sub, "option_id": o.get("id"), "sentence": s, "reason": o.get("reason") or ""}
        target = _normal_clause_for(s, al) if sub == "finding_negative" else None
        if target is not None:
            out.append(Candidate(lane="additions", kind="option", section=target.section,
                                 anchor=Span(start=target.start, end=target.end,
                                             text=inp.artifacts.report[target.start:target.end]),
                                 evidence={**ev, "upgrade_target": target.text}, probe=rc.Q_CONVEYS + s,
                                 detector="brief.option"))
        else:
            out.append(Candidate(lane="additions", kind="option", section=section, evidence=ev,
                                 proposed=Edit(mode="insert", replace=s, after=None, section=section),
                                 preclassed="minor", probe=rc.Q_CONVEYS + s, detector="brief.option"))
    return out


def _s4(card: dict, kind: str, detector: str, evidence: dict) -> Candidate:
    src = (card.get("sources") or [{}])[0]
    return Candidate(lane="additions", kind=kind, line_text=card.get("finding_short_label") or card.get("finding"),
                     evidence={"finding": card.get("finding"), **{k: v for k, v in evidence.items() if v}},
                     citation={"card": card.get("finding_number"), "source": src.get("url"), "label": src.get("title")},
                     detector=detector)


def s4_candidates(synthesis: Optional[dict], with_criteria: bool = False) -> List[Candidate]:
    """S4 cards → candidates (same mapping as the Gate C lab, scripts/review_labs/additions_map.py)."""
    out: List[Candidate] = []
    for card in (synthesis or {}).get("guidelines") or []:
        for c in card.get("classifications") or []:
            ev = {"system": c.get("system"), "grade": c.get("grade")}
            if with_criteria:
                ev["criteria"] = c.get("criteria")
            out.append(_s4(card, "grade", "s4.classification", ev))
        for t in card.get("thresholds") or []:
            out.append(_s4(card, "threshold", "s4.threshold", {"parameter": t.get("parameter"),
                                                              "threshold": t.get("threshold"),
                                                              "significance": t.get("significance")}))
        for i, f in enumerate(card.get("follow_up_actions") or []):
            out.append(_s4(card, "follow_up" if i == 0 else "option", "s4.follow_up",
                           {"modality": f.get("modality"), "timing": f.get("timing"), "indication": f.get("indication")}))
        for d in card.get("differentials") or []:
            out.append(_s4(card, "option", "s4.differential", {"text": d.get("diagnosis")}))
        for fl in card.get("imaging_flags") or []:
            out.append(_s4(card, "option", "s4.imaging_flag", {"text": fl if isinstance(fl, str) else str(fl)}))
    return out


class AdditionsLane:
    name = "additions"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        return brief_candidates(inp, ctx.alignment) + s4_candidates(inp.synthesis)
