"""Accuracy lane (spec §6.3): is everything in the report supported and consistent?
- Jev contradiction per clause (today's wording). A contradicted negative gets code's removal (never an LLM rewrite,
  L-47), built by the verifier's `_negative_fix` so it can qualify for pre-apply (binding correction 12); a positive
  one goes to the adjudicator.
- Jev W1n (supported) and C1n (certainty) on every positive clause (binding correction 11; L-53, L-55).
- The code checks (numbers, dates, priors, modality, size words).
Answers in an unsure band go to the adjudicator with `evidence.jev_unsure` naming the question (§6.5)."""
from __future__ import annotations

from typing import List, Optional

from ...report_review import CONTRA_FLAG, DICTATED_KEEP, RESTATED_FLAG, restate
from ..alignment import ReportClause
from ..items import Candidate, ReviewInput, Span
from ..jev_pass import JevPass, noul
from ..verifier import _negative_fix, guard_failures
from . import LaneContext

CONTRA_UNSURE_LO = 0.4   # provisional: the unsure band below CONTRA_FLAG (§6.5), set in a wording read
SUPPORTED_FLAG = 0.5     # provisional: Gate F (W1n < this → unsupported; L-53)
CERTAINTY_FLAG = 0.5     # provisional: Gate F (C1n ≥ this → overstated; L-55)
JEV_UNSURE_LO = 0.4      # provisional: Gate F (W1n / C1n unsure band, binding correction 11)
JEV_UNSURE_HI = 0.6      # provisional: Gate F


def _clause(ctx: LaneContext, report: str, text: str) -> Optional[ReportClause]:
    """The alignment clause for a checked clause: the same text, else (a negative-list item the two splitters
    phrase differently) the first clause whose text is contained in it or contains it."""
    cs = ctx.alignment.clauses
    hit = next((c for c in cs if c.text == text), None)
    if hit is not None:
        return hit
    t = text.strip().rstrip(".").lower()
    return next((c for c in cs if c.text.strip().rstrip(".").lower() in t or t in c.text.lower()), None)


def _common(ctx: LaneContext, report: str, text: str, kind: str, detector: str) -> dict:
    c = _clause(ctx, report, text)
    anchor = Span(start=c.start, end=c.end, text=report[c.start:c.end]) if c else None
    return dict(lane="accuracy", kind=kind, section=c.section if c else None, anchor=anchor, detector=detector)


def _band(score: float) -> bool:
    return JEV_UNSURE_LO <= score < JEV_UNSURE_HI


def _support(jp: JevPass, ctx: LaneContext, report: str) -> List[Candidate]:
    out: List[Candidate] = []
    if jp.support_error is not None:
        return out
    for i, t in enumerate(jp.clauses):
        w = noul(jp.support, f"sup{i}")
        if w is not None and (w < SUPPORTED_FLAG or _band(w)):
            ev = {"jev_unsure": {"question": "supported"}} if _band(w) else {"score": w, "clause": t}
            out.append(Candidate(evidence=ev, **_common(ctx, report, t, "unsupported", "jev.supported")))
        k = noul(jp.support, f"cer{i}")
        if k is not None and (k >= CERTAINTY_FLAG or _band(k)):
            ev = {"jev_unsure": {"question": "certainty"}} if _band(k) else {"score": k, "clause": t}
            out.append(Candidate(evidence=ev, **_common(ctx, report, t, "overstated", "jev.certainty")))
    return out


class AccuracyLane:
    name = "accuracy"

    async def candidates(self, inp: ReviewInput, ctx: LaneContext) -> List[Candidate]:
        out: List[Candidate] = []
        jp, report = ctx.jev, inp.artifacts.report
        names = inp.artifacts.sections
        if jp is not None and jp.contra_error is None:
            for i, t in enumerate(jp.clauses):
                c = noul(jp.contra, f"c{i}")
                if c is None or c < CONTRA_UNSURE_LO:
                    continue
                common = _common(ctx, report, t, "contradicted", "jev.contradiction")
                if c < CONTRA_FLAG:
                    out.append(Candidate(evidence={"jev_unsure": {"question": "contradiction"}}, **common))
                    continue
                if restate(t):
                    if (noul(jp.contra, f"r{i}") or 0.0) < RESTATED_FLAG:
                        continue
                    d = noul(jp.contra, f"d{i}")
                    if d is None or d >= DICTATED_KEEP:
                        continue                  # the dictation itself states this negative (L-49)
                    an = common["anchor"]
                    fix = _negative_fix(report, an.start, an.end, t, names) if an else None
                    if fix is not None and guard_failures(report, fix, "contradicted", inp.artifacts.dictated_findings,
                                                          inp.clinical_history, sections=names, target=t):
                        fix = None                # the adjudicator handles a negative code cannot remove cleanly
                    out.append(Candidate(evidence={"negative": True, "score": c, "clause": t}, proposed=fix,
                                         code_fix=fix is not None, pre_apply=fix is not None, **common))
                else:
                    out.append(Candidate(evidence={"negative": False, "score": c}, **common))
        if jp is not None:
            out += _support(jp, ctx, report)
        out += [c for c in ctx.checks if c.lane == "accuracy"]
        return out
