"""Accuracy lane (spec §6.3): is everything in the report supported and consistent?
- Jev contradiction per clause (today's wording). A contradicted negative gets code's removal (never an LLM rewrite,
  L-47), built by the verifier's `_negative_fix` so it can qualify for pre-apply (binding correction 12); a positive
  one goes to the adjudicator.
- Jev W1n (supported) on every positive clause (binding correction 11; L-53).
- Overstated (hybrid rule, hybrid_lab 2026-10-04, replacing C1n ≥ 0.5): the report tier (code, `hedge_tag`) above the
  Jev dictation tier `dt{i}`, or both fact and C1n ≥ FACT_C1N_FLAG. On a Jev failure or no usable tier: the report
  tier above the aligned dictated line's `hedge_tag` tier, code only (`code.certainty_tier`); never C1n alone.
- The code checks (numbers, dates, priors, modality, size words).
W1n answers in an unsure band go to the adjudicator with `evidence.jev_unsure` naming the question (§6.5)."""
from __future__ import annotations

from typing import List, Optional

from ...report_review import CONTRA_FLAG, DICTATED_KEEP, RESTATED_FLAG, checked_clauses_in_context, restate
from ..alignment import ReportClause, section_models
from ..checks import hedge_tag
from ..claims import content_words
from ..items import Candidate, ReviewInput, Span
from ..jev_pass import CODE_TIER, TIER_RANK, JevPass, dictation_tier_of, noul, positive, report_tier
from ..verifier import _negative_fix, guard_failures
from . import LaneContext, confident

CONTRA_UNSURE_LO = 0.4   # provisional: the unsure band below CONTRA_FLAG (§6.5), set in a wording read
SUPPORTED_FLAG = 0.5     # provisional: Gate F (W1n < this → unsupported; L-53)
FACT_C1N_FLAG = 0.5      # provisional: Gate F (hybrid rule's fact/fact arm; 0.75 gave 0 false alarms in hybrid_lab
                         # but lost 2/14 real upgrades). Decided 2026-10-04: stays 0.5 until Gate F re-reads it.
CODE_TIER_OVERLAP = 0.8  # provisional: share of a dictated line's content words the clause must carry (code fallback)
JEV_UNSURE_LO = 0.4      # provisional: Gate F (W1n unsure band, binding correction 11)
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


def overstated_rule(report_tier: str, dictation_tier: Optional[str], c1n: Optional[float]) -> Optional[str]:
    """The hybrid certainty rule (hybrid_lab, 2026-10-04): "tier" when the report states the finding more certainly
    than the dictation; "fact_c1n" when both state it as fact and C1n ≥ FACT_C1N_FLAG (a meaning upgrade with no hedge
    word); None otherwise, and always when the dictation does not state the finding (W1n's territory). C1n alone never
    triggers: it flags 40% of equal-tier synonym swaps ("likely" → "consistent with")."""
    if dictation_tier not in TIER_RANK:
        return None
    if TIER_RANK[report_tier] > TIER_RANK[dictation_tier]:
        return "tier"
    if report_tier == dictation_tier == "fact" and c1n is not None and c1n >= FACT_C1N_FLAG:
        return "fact_c1n"
    return None


def code_dictation_tier(ctx: LaneContext, report: str, text: str) -> Optional[str]:
    """The fallback dictation tier: hedge_tag of the confidently aligned dictated line(s) whose content words the report
    clause carries (≥ CODE_TIER_OVERLAP of them, so the hedged finding itself is restated: "Renal cyst." does not
    restate "renal cyst, likely simple"), the most certain one; a negated line is a contradiction's business."""
    c = _clause(ctx, report, text)
    if c is None:
        return None
    ids = {p.line_id for p in ctx.alignment.pairs if p.clause_id == c.id and confident(p)}
    words = content_words(text)

    def restated(line: str) -> bool:
        lw = content_words(line)
        return bool(lw) and len(lw & words) >= CODE_TIER_OVERLAP * len(lw)
    tiers = [CODE_TIER[hedge_tag(l.text)] for l in ctx.alignment.lines if l.id in ids and restated(l.text)]
    tiers = [t for t in tiers if t != "excluded"]
    return max(tiers, key=TIER_RANK.get) if tiers else None


def _certainty(jp: Optional[JevPass], ctx: LaneContext, report: str, i: int, t: str, h: str) -> Optional[Candidate]:
    rt = report_tier(h)
    dt = None if jp is None or jp.support_error else dictation_tier_of(jp.support.get(f"dt{i}"))
    if dt is not None:
        k = noul(jp.support, f"cer{i}")
        rule = overstated_rule(rt, dt, k)
        detector = "jev.certainty"
    else:                                    # Jev failed or gave no usable tier: code tiers only, never C1n
        k = None
        dt = code_dictation_tier(ctx, report, t)
        rule = "code_tier" if overstated_rule(rt, dt, None) == "tier" else None
        detector = "code.certainty_tier"
    if rule is None:
        return None
    ev = {"rule": rule, "report_tier": rt, "dictation_tier": dt, "clause": h, **({"score": k} if k is not None else {})}
    return Candidate(evidence=ev, **_headed(_common(ctx, report, t, "overstated", detector), report, h))


def _support(jp: JevPass, ctx: LaneContext, report: str) -> List[Candidate]:
    out: List[Candidate] = []
    for i, t in enumerate(jp.clauses):
        if not jp.keeps(i):                  # Jev type normal / not_a_finding (or, untyped, today's lexicon)
            continue
        h = jp.head(i)                       # the questions were asked of the split head, if any
        w = None if jp.support_error else noul(jp.support, f"sup{i}")
        if w is not None and (w < SUPPORTED_FLAG or _band(w)):
            ev = {"jev_unsure": {"question": "supported"}} if _band(w) else {"score": w, "clause": h}
            out.append(Candidate(evidence=ev, **_headed(_common(ctx, report, t, "unsupported", "jev.supported"),
                                                        report, h)))
        if jp.support_error or f"cer{i}" in jp.support or f"dt{i}" in jp.support:
            c = _certainty(jp, ctx, report, i, t, h)
            if c is not None:
                out.append(c)
    return out


def _code_only(ctx: LaneContext, inp: ReviewInput, report: str) -> List[Candidate]:
    """No Jev pass at all: the certainty fallback over today's positive clauses."""
    sections = section_models(inp.artifacts.sections) if inp.pathway == "templated" else None
    out = []
    for t in checked_clauses_in_context(report, sections):
        if positive(t):
            c = _certainty(None, ctx, report, -1, t, t)
            if c is not None:
                out.append(c)
    return out


def _headed(common: dict, report: str, head: str) -> dict:
    """Trim the anchor to the split head when the clause's report text starts with it."""
    an = common.get("anchor")
    if an is not None and head and head != an.text and report.startswith(head, an.start):
        common = {**common, "anchor": Span(start=an.start, end=an.start + len(head), text=head)}
    return common


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
        out += _support(jp, ctx, report) if jp is not None else _code_only(ctx, inp, report)
        out += [c for c in ctx.checks if c.lane == "accuracy"]
        return out
