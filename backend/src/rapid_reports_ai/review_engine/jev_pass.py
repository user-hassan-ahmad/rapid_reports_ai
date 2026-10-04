"""The one shared Jev pass (spec §6.2–§6.3): today's check() questions, two batched requests in parallel, raw answers
kept so the lanes can route unsure answers (§6.5) instead of dropping them. A third request in parallel asks the
Accuracy lane's W1n (supported) and C1n (certainty) questions of every positive report clause, in the
dictation-plus-history state the wording lab measured (binding correction 11; ledger L-53, L-55)."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

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


def q_supported(clause: str) -> dict:
    return {"type": "noul", "instructions": Q_SUPPORTED.format(c=clause),
            "criteria": {"true": "stated", "false": "not stated"}}


def q_certainty(clause: str) -> dict:
    return {"type": "noul", "instructions": Q_CERTAINTY.format(c=clause),
            "criteria": {"true": "more certain or more severe than dictated", "false": "same or less"}}


def positive(clause: str) -> bool:
    """A clause that asserts a finding: not a negative, and not a plain normal statement (undictated normals are
    stated by design, so asking whether the dictation reports them would flag every one)."""
    if restate(clause) is not None or hedge_tag(clause) == "negated":
        return False
    return not (_NORMAL.search(clause) and not _DIGIT.search(clause))


class JevPass(BaseModel):
    clauses: List[str] = []
    before: Dict[str, str] = {}
    items: List[str] = []
    contra: Dict[str, Any] = {}
    omit: Dict[str, Any] = {}
    support: Dict[str, Any] = {}           # sup{i} (W1n) and cer{i} (C1n), i indexes `clauses`
    contra_error: Optional[str] = None
    omit_error: Optional[str] = None
    support_error: Optional[str] = None


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
    pos = [i for i, t in enumerate(cls) if positive(t)]
    support_qs = {f"sup{i}": q_supported(cls[i]) for i in pos}
    support_qs.update({f"cer{i}": q_certainty(cls[i]) for i in pos})
    hidden = ([inp.clinical_history] if inp.clinical_history else []) if sections is not None else []

    async def ask(state: str, qs: dict):
        return await asyncio.wait_for(rc._jev(state, qs), JEV_TIMEOUT_S) if qs else {}

    contra, omit, support = await asyncio.gather(
        ask(f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
        ask(f"REPORT:\n{without(report, hidden, sections)}", omit_qs),
        ask(support_state(inp), support_qs), return_exceptions=True)
    out = JevPass(clauses=cls, before=before, items=items)
    for name, res in (("contra", contra), ("omit", omit), ("support", support)):
        if isinstance(res, BaseException):
            setattr(out, f"{name}_error", f"{type(res).__name__}: {str(res)[:200]}")
            logger.warning("review engine: Jev %s request failed (%s)", name, type(res).__name__)
        else:
            setattr(out, name, res or {})
    return out


def noul(answers: Dict[str, Any], key: str) -> Optional[float]:
    try:
        return float(answers[key]["noul"])
    except Exception:
        return None
