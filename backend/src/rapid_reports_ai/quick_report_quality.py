"""Post-generation check: Jev flags contradictions and omissions, one focal Qwen call repairs them.

Spec docs/superpowers/specs/2026-09-30-post-generation-check-design.md; probe ledger L-46.

    units   -> report clauses, option sentences, positive dictated items (code)
    check   -> two Jev calls in parallel: contradiction (dictation state), omission (report state)
    repair  -> one Qwen call returns verbatim find/replace edits; code applies each only when its
               find occurs exactly once
Flagged options are dropped, never repaired. Nothing here raises: on any failure the report and
options ship as generated, with the reason in the telemetry.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import List, Optional, Tuple

from pydantic import BaseModel, field_validator

from . import quick_report_brief as qb
from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)

Q_CONTRA = "The dictated findings state something that this report statement denies or contradicts. Statement: "
Q_OMIT = "The report states this dictated finding, in any wording: "
CONTRA_FLAG = 0.6   # L-46: 31/31 genuine contradictions >= 0.5, 29/31 >= 0.7
OMIT_FLAG = 0.5     # L-46: 24/24 deleted findings < 0.5
JEV_TIMEOUT_S = 6.0
REPAIR_TIMEOUT_S = 8.0
REPAIR_MODEL = qb.QWEN

# ── units ────────────────────────────────────────────────────────────────────

_HEADER = re.compile(r"^([A-Z][A-Z /&()-]{2,}):\s*$", re.M)


def report_sections(report: str) -> Tuple[str, str]:
    """FINDINGS and IMPRESSION text; the impression stops at the signature's blank line."""
    parts, marks = {}, list(_HEADER.finditer(report))
    for m, nxt in zip(marks, marks[1:] + [None]):
        parts[m.group(1)] = report[m.end():nxt.start() if nxt else len(report)].strip()
    imp = re.split(r"\n\s*\n", parts.get("IMPRESSION", ""), maxsplit=1)[0].strip()
    return parts.get("FINDINGS", ""), imp


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def clauses(text: str) -> List[str]:
    """Sentences, with a negative list split at its commas into one clause per finding. A bare
    'or' never splits: 'No pericolic or paracolic fluid collection' is one finding (L-46)."""
    out: List[str] = []
    for s in _sentences(text):
        m = re.match(r"^(No|There is no|There are no|Without)\s+(.*?)\.?$", s, re.I)
        parts = [p.strip() for p in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)) if p.strip()] if m else []
        out.extend(f"No {p}" for p in parts) if len(parts) > 1 else out.append(s)
    return out


_BACKGROUND = re.compile(r"^\s*(no|nil)\b|\b(unremarkable|normal|intact|clear)\b", re.I)


def positive_items(findings: str) -> List[str]:
    """Dictated positive findings; negatives and background lines are not checked for omission (L-46)."""
    return [t for t in qb.split_findings(findings) if not _BACKGROUND.search(t)]


# ── check ────────────────────────────────────────────────────────────────────

class Flag(BaseModel):
    kind: str          # "contradiction" | "omission"
    text: str          # the report clause, or the dictated item missing from the report
    score: float


class CheckResult(BaseModel):
    flags: List[Flag] = []
    bad_option_ids: List[str] = []
    n_clauses: int = 0
    n_items: int = 0
    error: Optional[str] = None


async def check(report: str, findings: str, scan_type: str, options: List[dict]) -> CheckResult:
    """Two Jev calls in parallel: every report clause and option against the dictation, every
    positive dictated item against the report."""
    fnd, imp = report_sections(report)
    cls = list(dict.fromkeys(clauses(fnd) + clauses(imp)))
    opts = [(o["id"], o["sentence"]) for o in options if o.get("sentence")]
    items = positive_items(findings)
    contra_qs = {f"c{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, t in enumerate(cls)}
    contra_qs.update({f"o{i}": {"type": "noul", "instructions": Q_CONTRA + t} for i, (_, t) in enumerate(opts)})
    omit_qs = {f"i{i}": {"type": "noul", "instructions": Q_OMIT + t} for i, t in enumerate(items)}

    async def ask(state, qs):
        return await qb._jev(state, qs) if qs else {}
    try:
        contra, omit = await asyncio.wait_for(asyncio.gather(
            ask(f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}", contra_qs),
            ask(f"REPORT:\n{report}", omit_qs)), JEV_TIMEOUT_S)
    except Exception as e:  # never blocks the report
        logger.warning("quality check: Jev failed (%s: %s)", type(e).__name__, str(e)[:200])
        return CheckResult(n_clauses=len(cls), n_items=len(items), error=f"{type(e).__name__}: {str(e)[:200]}")

    score = lambda ans, k: float(ans[k]["noul"])
    flags = [Flag(kind="contradiction", text=t, score=score(contra, f"c{i}"))
             for i, t in enumerate(cls) if score(contra, f"c{i}") >= CONTRA_FLAG]
    flags += [Flag(kind="omission", text=t, score=score(omit, f"i{i}"))
              for i, t in enumerate(items) if score(omit, f"i{i}") < OMIT_FLAG]
    bad = [oid for i, (oid, _) in enumerate(opts) if score(contra, f"o{i}") >= CONTRA_FLAG]
    return CheckResult(flags=flags, bad_option_ids=bad, n_clauses=len(cls), n_items=len(items))
