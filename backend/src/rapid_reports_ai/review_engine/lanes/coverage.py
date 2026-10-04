"""Coverage lane (spec §6.2): is everything dictated carried, as dictated? Classify-first per selected line
(L-49); dictated negatives never checked; unsure answers routed to the adjudicator (§6.5)."""
from __future__ import annotations

import re
from typing import List, Optional

from ...report_review import missing_detail, omission_class, selected
from ..alignment import Alignment, ReportClause
from ..items import Candidate, ReviewInput, Span
from . import LaneContext, confident

OMIT_CONFIDENT = 0.6   # provisional: Gate A wording read sets the unsure band (§6.5)
_KIND = {"absent": "absent", "partial": "partial", "different": "differs"}
_DICT_NEG = re.compile(r"^\s*(no|nil|without)\b", re.I)


def _anchor_clause(al: Alignment, line_id: str) -> Optional[ReportClause]:
    """The line's best confidently paired clause (L-56: weak pairs never place an anchor)."""
    ps = sorted((p for p in al.pairs if p.line_id == line_id and confident(p)), key=lambda p: -p.score)
    return al.clause(ps[0].clause_id) if ps else None


class CoverageLane:
    name = "coverage"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        out: List[Candidate] = []
        jp, report = ctx.jev, inp.artifacts.report
        if jp is not None and jp.omit_error is None:
            sel = jp.contra if jp.contra_error is None else {}
            for i, t in enumerate(jp.items):
                if _DICT_NEG.match(t) or not selected(t, sel.get(f"sel{i}"), sel.get(f"lt{i}")):
                    continue
                kind, p = omission_class(jp.omit.get(f"i{i}"))
                if kind is None or kind == "unclear" or (kind == "stated" and p >= OMIT_CONFIDENT):
                    continue
                line_id = f"d{i}"
                c = _anchor_clause(ctx.alignment, line_id)
                anchor = Span(start=c.start, end=c.end, text=report[c.start:c.end]) if c else None
                common = dict(lane="coverage", section=c.section if c else None, anchor=anchor, line_id=line_id,
                              line_text=t, detector="jev.classify_first")
                if p < OMIT_CONFIDENT:
                    out.append(Candidate(kind="coverage_check", evidence={"jev_unsure": {"question": "classify_first"}},
                                         **common))
                    continue
                ev = {}
                if kind == "partial":
                    md = missing_detail(t, report)
                    if md:
                        ev["missing_detail"] = md
                out.append(Candidate(kind=_KIND[kind], evidence=ev, **common))
        out += [c for c in ctx.checks if c.lane == "coverage"]
        return out
