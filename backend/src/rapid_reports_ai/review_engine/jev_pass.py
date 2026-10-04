"""The one shared Jev pass (spec §6.2–§6.3): today's check() questions, two batched requests in parallel, raw answers
kept so the lanes can route unsure answers (§6.5) instead of dropping them. A third request in parallel asks the
Accuracy lane's W1n (supported) and C1n (certainty) questions of every positive report clause, in the
dictation-plus-history state the wording lab measured (binding correction 11; ledger L-53, L-55).

Statement type (type_tier lab, wording TB): the report-only request also asks `typ{i}` of every checked clause. The
requests run in parallel, so W1n / C1n are asked of every clause the loose code pre-filter keeps (`asked`), on the
split head of a finding with a negative / normal tail (`split_tails`); `JevPass.keeps` then counts the answers only
for abnormal / mixed clauses. Normal clauses and mixed clauses' tails are the negatives classifier's
(`negatives.candidates(report, types)`); not_a_finding gives nothing. Without a type answer (request failure or an
unparseable answer) the clause falls back to today's lexicon (`positive`)."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .. import report_reconcile as rc
from ..report_review import (JEV_TIMEOUT_S, Q_CONTRA, checked_clauses_in_context, dictated_items, q_dictated,
                             q_omission, q_restated, q_select_choice, q_select_noul, restate, without)
from .alignment import section_models
from .checks import hedge_tag
from .items import ReviewInput

logger = logging.getLogger(__name__)

# Lab wordings verbatim (scripts/review_labs/gate_b.py W1n, certainty_lab.py C1n).
Q_SUPPORTED = 'The dictated findings report this finding, including as a possibility, in any wording. Report statement: "{c}"'
Q_CERTAINTY = ('Read only this one report statement: "{c}". It states a finding as more certain or more severe than the '
               'dictated findings do, for example a possibility stated as a fact, or a milder grade stated as a worse one.')
_NORMAL = re.compile(r"\b(?:normal|unremarkable|within normal limits|wnl)\b", re.I)
_DIGIT = re.compile(r"\d")
# Normal statements worded without "normal" (structural form, any anatomy): a normal predicate that ends the clause
# ("The ligament is intact.", "Disc heights are preserved.", "The liver surface is smooth.", "Cruciate ligaments
# intact.") or a "maintains continuity"-style verb phrase. The predicate must close the clause (a short qualifier or a
# trailing "with no ..." / "without ..." aside), so "is smooth and thickened" or "with preserved fat plane" mid-clause
# stay positive. Also a subject that "shows no ..." or "is not <predicate>" with no positive turn after it.
_PRED = r"(?:intact|preserved|maintained|smooth|patent|clear)"
_QUAL = r"(?:\s+(?:throughout|bilaterally|in (?:size|calibre|caliber|configuration|appearance|position|morphology)" \
        r"(?: and (?:size|calibre|caliber|configuration|appearance|position|morphology))?))?"
_TAIL = _QUAL + r"(?:\s*,?\s*(?:(?:and|with)\s+(?:no|without)|without)\b[^0-9]*)?\s*[.;]?\s*$"
_NOT = r"[^,;:]*?\b(?:is|are|was|were)\s+not\s+\w+"
# one character of a clause with no positive turn ("but", "which", "and is ...")
_PLAIN = r"(?:(?!\b(?:but|however|although|though|while|whereas|which|except|and\s+(?:is|are|was|were|has|have|" \
         r"shows?))\b)[^;:])"
_NORMAL_STATEMENT = re.compile(
    r"\b(?:(?:is|are|was|were|appears?|remains?|seems?)\s+(?:(?:otherwise|grossly|entirely|completely|well|also|"
    r"again|still|both)\s+)?)?" + _PRED + r"(?![-\w])" + _TAIL +
    r"|\bmaintains?\s+(?:(?:its|their|normal)\s+)?(?:continuity|integrity|alignment|calibre|caliber|configuration)"
    r"(?![-\w])" + _TAIL +
    r"|\bno\s+(?:\w+\s+){0,2}abnormalit(?:y|ies)\b"
    # a subject that "shows no ..." / "is not dilated" (and a second such part), nothing positive after it
    r"|^" + _PLAIN + r"*?\b(?:shows?|demonstrates?|has|have|contains?)\s+no\b" + _PLAIN + r"*$"
    r"|^" + _NOT + r"(?:\s*(?:,|;|\band\b)\s*" + _NOT + r")*\s*[.;]?\s*$", re.I)


# Recommendation sentences ("MRI is recommended", "CT spine without contrast"): never a finding to check. Shared by the
# negatives classifier's candidates and the W1n / C1n positives (undictated recommendations are a feature).
_RECOMMENDATION = re.compile(r"\b(recommend\w*|advis\w*|suggest\w*|referr\w*|refer|follow-?up|"
                             r"for (?:surgical|further|treatment)|correlat\w*)\b", re.I)


def recommendation(clause: str) -> bool:
    return bool(_RECOMMENDATION.search(clause))


def normal_statement(clause: str) -> bool:
    """A plain normal statement with no number: generated normals are owned by the negatives classifier (default-
    negatives policy), so the Accuracy lane never asks W1n / C1n of them."""
    if _DIGIT.search(clause):
        return False
    return bool(_NORMAL.search(clause) or _NORMAL_STATEMENT.search(clause.strip()))


def q_supported(clause: str) -> dict:
    return {"type": "noul", "instructions": Q_SUPPORTED.format(c=clause),
            "criteria": {"true": "stated", "false": "not stated"}}


def q_certainty(clause: str) -> dict:
    return {"type": "noul", "instructions": Q_CERTAINTY.format(c=clause),
            "criteria": {"true": "more certain or more severe than dictated", "false": "same or less"}}


def positive(clause: str) -> bool:
    """A clause that asserts a finding: not a negative, not a plain normal statement (undictated normals are stated
    by design, so asking whether the dictation reports them would flag every one), and not a recommendation."""
    if recommendation(clause) or restate(clause) is not None or hedge_tag(clause) == "negated":
        return False
    return not normal_statement(clause)


# ── statement type (type_tier lab, wording TB: 4-class 99.4%, positive gate 100%, 0 drift over 2 runs) ──────────
TYPES = ("abnormal", "normal", "mixed", "not_a_finding")
Q_TYPE = 'Read only this one report statement: "{c}". Classify what it says about the patient.'
TYPE_CRITERIA = {
    "abnormal": "It reports at least one abnormality or finding (a possible or likely one counts), and nothing in it "
                "is stated as normal or absent.",
    "normal": "It only says that structures are normal, intact, preserved or patent, or that findings are absent "
              "(no ..., free of ..., without ...).",
    "mixed": "It reports an abnormality or finding AND, in the same statement, says something is normal or absent.",
    "not_a_finding": "It is not about the patient's anatomy: the scan technique, a comparison, a recommendation or "
                     "follow-up, or a communication.",
}


def q_type(clause: str) -> dict:
    return {"type": "choice", "instructions": Q_TYPE.format(c=clause), "criteria": dict(TYPE_CRITERIA)}


def clause_type_of(ans: Any) -> Optional[str]:
    """The argmax type of a Jev choice answer; None when the answer is missing or not a type choice."""
    if not isinstance(ans, dict):
        return None
    probs = {k: v for k, v in (ans.get("probabilities") or {}).items() if k in TYPES}
    if probs:
        try:
            return max(probs, key=lambda k: float(probs[k]))
        except (TypeError, ValueError):
            return None
    return ans.get("choice") if ans.get("choice") in TYPES else None


# ── certainty tiers (type_tier lab + hybrid_lab validation on real wording, 2026-10-04) ──────────────────────────
# The overstated trigger compares tiers: the report statement's tier from code (`report_tier`, checks.hedge_tag) and
# the dictation's tier for the same finding from Jev (`dt{i}`, wording D2 with a not_stated option, D2n).
TIERS = ("excluded", "possible", "probable", "fact")          # ascending certainty of presence
TIER_RANK = {t: i for i, t in enumerate(TIERS)}
DICT_TIERS = TIERS + ("not_stated",)
Q_DICT_TIER = ('This report statement describes a finding: "{c}". How certain do the dictated findings state that same '
               'finding?')
DICT_TIER_CRITERIA = {
    "fact": 'definite: stated as a fact with no hedge (for example "represents", "diagnostic of", or stated plainly)',
    "probable": "probable: likely, probable, consistent with, in keeping with, compatible with, or suggestive of",
    "possible": "possible: possible, may represent, cannot be excluded, query, or a question mark",
    "excluded": "excluded: stated as absent, negated or ruled out",
    "not_stated": "not stated: the dictated findings do not mention this finding",
}
CODE_TIER = {"definite": "fact", "probable": "probable", "possible": "possible", "negated": "excluded"}


def q_dictation_tier(clause: str) -> dict:
    return {"type": "choice", "instructions": Q_DICT_TIER.format(c=clause), "criteria": dict(DICT_TIER_CRITERIA)}


def dictation_tier_of(ans: Any) -> Optional[str]:
    """The argmax dictation tier (or not_stated) of a Jev choice answer; None when missing or unparseable."""
    if not isinstance(ans, dict):
        return None
    probs = {k: v for k, v in (ans.get("probabilities") or {}).items() if k in DICT_TIERS}
    if probs:
        try:
            return max(probs, key=lambda k: float(probs[k]))
        except (TypeError, ValueError):
            return None
    return ans.get("choice") if ans.get("choice") in DICT_TIERS else None


def report_tier(clause: str) -> str:
    return CODE_TIER[hedge_tag(clause)]


def asked(clause: str) -> bool:
    """The loose code pre-filter for W1n / C1n: everything but a recommendation or a plain negative. The type
    answer (same round, report request) decides afterwards which answers count (`JevPass.keeps`)."""
    return not recommendation(clause) and restate(clause) is None and hedge_tag(clause) != "negated"


# A mixed clause's tail: "<finding>[,] [with|and] no|without <negated>" or "; <negative or normal statement>". The
# negated part must not turn positive again ("no enhancement but invades ..."), and the head must itself be a
# finding (not a normal statement), so "The liver is normal, with no focal lesion" is not split.
_NEG_TAIL = re.compile(r"^(?P<head>.+?)(?:\s*,\s*|\s+)(?:(?:and|with)\s+)?(?:no|without)\b\s*(?P<rest>.+)$", re.I)
_TURN = re.compile(r"\b(?:but|however|although|though|while|whereas|which|except|and\s+(?:is|are|was|were|has|have|"
                   r"shows?))\b", re.I)
_LEAD_NEG = re.compile(r"^(?:no|without)\b\s*(?P<rest>.+)$", re.I)


def _neg_text(rest: str) -> Optional[str]:
    rest = rest.strip().rstrip(".").strip()
    return f"No {rest}" if rest and not _TURN.search(rest) else None


def split_tails(clause: str) -> Optional[Tuple[str, List[str]]]:
    """(head, tails) for a finding followed by negative / normal tails, else None. Tails are negatives-classifier
    clauses: "No <negated>" (located by its own words) or the normal part verbatim."""
    text = (clause or "").strip().rstrip(".").strip()
    if not text or restate(text) is not None or hedge_tag(text) == "negated":
        return None
    parts = [p.strip() for p in text.split(";")]
    head, tails = parts[0], []
    m = _NEG_TAIL.match(head)
    if m:
        neg = _neg_text(m.group("rest"))
        if neg is None:
            return None
        head = m.group("head").strip().rstrip(",").strip()
        tails.append(neg)
    for p in parts[1:]:
        lead = _LEAD_NEG.match(p)
        if lead:
            neg = _neg_text(lead.group("rest"))
            if neg is None:
                return None
            tails.append(neg)
        elif p and normal_statement(p):
            tails.append(p.rstrip("."))
        else:
            return None                         # a second finding, not a normal tail
    if not tails or not head or normal_statement(head) or _NORMAL.search(head):
        return None
    return head, tails


class JevPass(BaseModel):
    clauses: List[str] = []
    before: Dict[str, str] = {}
    items: List[str] = []
    contra: Dict[str, Any] = {}
    omit: Dict[str, Any] = {}              # i{i} (omission) and typ{i} (statement type), i indexes `clauses`
    support: Dict[str, Any] = {}           # sup{i} (W1n), cer{i} (C1n), dt{i} (dictation tier), i indexes `clauses`
    types: Dict[str, str] = {}             # clause text → Jev statement type (parsed answers only)
    heads: Dict[int, str] = {}             # clause index → the split head W1n / C1n were asked of
    contra_error: Optional[str] = None
    omit_error: Optional[str] = None
    support_error: Optional[str] = None

    def clause_type(self, i: int) -> Optional[str]:
        return self.types.get(self.clauses[i])

    def keeps(self, i: int) -> bool:
        """Do this clause's W1n / C1n answers count? Jev type abnormal or mixed; today's lexicon without a type."""
        t = self.clause_type(i)
        return positive(self.clauses[i]) if t is None else t in ("abnormal", "mixed")

    def head(self, i: int) -> str:
        return self.heads.get(i, self.clauses[i])


def sections_for(inp: ReviewInput):
    return section_models(inp.artifacts.sections) if inp.pathway == "templated" else None


def support_state(inp: ReviewInput) -> str:
    return (f"SCAN TYPE: {inp.scan_type}\nCLINICAL HISTORY: {inp.clinical_history or '(none)'}\n"
            f"DICTATED FINDINGS:\n{inp.artifacts.dictated_findings}")


async def run(inp: ReviewInput, report: str) -> JevPass:
    sections = sections_for(inp)
    findings = inp.artifacts.dictated_findings
    before = checked_clauses_in_context(report, sections)
    cls = list(before)
    items = dictated_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    restated = {i: restate(t) for i, t in enumerate(cls)}
    contra_qs.update({f"r{i}": q_restated(r) for i, r in restated.items() if r})
    contra_qs.update({f"d{i}": q_dictated(cls[i], before[cls[i]]) for i, r in restated.items() if r})
    contra_qs.update({f"sel{i}": q_select_choice(t) for i, t in enumerate(items)})
    contra_qs.update({f"lt{i}": q_select_noul(t) for i, t in enumerate(items)})
    omit_qs = {f"i{i}": q_omission(t) for i, t in enumerate(items)}
    omit_qs.update({f"typ{i}": q_type(t) for i, t in enumerate(cls)})      # same report-only request
    pos = [i for i, t in enumerate(cls) if asked(t)]
    heads = {i: sp[0] for i in pos if (sp := split_tails(cls[i]))}
    support_qs = {f"sup{i}": q_supported(heads.get(i, cls[i])) for i in pos}
    support_qs.update({f"cer{i}": q_certainty(heads.get(i, cls[i])) for i in pos})
    support_qs.update({f"dt{i}": q_dictation_tier(heads.get(i, cls[i])) for i in pos})
    hidden = ([inp.clinical_history] if inp.clinical_history else []) if sections is not None else []

    async def ask(state: str, qs: dict):
        return await asyncio.wait_for(rc._jev(state, qs), JEV_TIMEOUT_S) if qs else {}

    contra, omit, support = await asyncio.gather(
        ask(f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        ask(f"REPORT:\n{without(report, hidden, sections)}", omit_qs),
        ask(support_state(inp), support_qs), return_exceptions=True)
    out = JevPass(clauses=cls, before=before, items=items, heads=heads)
    for name, res in (("contra", contra), ("omit", omit), ("support", support)):
        if isinstance(res, BaseException):
            setattr(out, f"{name}_error", f"{type(res).__name__}: {str(res)[:200]}")
            logger.warning("review engine: Jev %s request failed (%s)", name, type(res).__name__)
        else:
            setattr(out, name, res or {})
    for i, t in enumerate(cls):
        ct = clause_type_of(out.omit.get(f"typ{i}"))
        if ct is not None:
            out.types[t] = ct
    return out


def noul(answers: Dict[str, Any], key: str) -> Optional[float]:
    try:
        return float(answers[key]["noul"])
    except Exception:
        return None
