"""Tier-2 scratchpad audit with Jev (lab): code proposes candidates, Jev judges them in one call.

Every flag uses its candidate's own offsets, so it is verbatim by construction; a conflict
also carries the other statement. Advisory (medium) like the model tier, and any Jev failure
returns no flags (never blocks). Compared with the model tier by scripts/audit_eval.py.

Plan: docs/superpowers/plans/2026-09-27-jev-scratchpad-audit.md
"""
from __future__ import annotations

import logging
import os
import time

import httpx

from .audit_candidates import candidates
from .dictation_integrity import IntegrityFlag
from .dictation_triage import JEV_MODEL, JEV_TIMEOUT_S, _check_unit
from .jev_client import jev_post
from .jev_questions import AUDIT_BANDS, audit_questions

logger = logging.getLogger(__name__)

_KIND = {"pair": "internal_contradiction", "negation": "internal_contradiction",
         "side": "laterality_conflict", "measure": "measurement_mismatch"}
_MESSAGE = {
    "pair": "These two statements appear to contradict each other.",
    "negation": "This negative statement seems to be contradicted elsewhere in the dictation.",
    "side": "The side here may not match the rest of the dictation or the clinical history.",
    "measure": "This measurement may not fit what it describes.",
}


class JevAudit:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = JEV_TIMEOUT_S) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        self._transport = transport
        self._timeout_s = timeout_s
        self.last_latency_ms: int | None = None

    async def check(self, scan_type: str, clinical_history: str, findings: str) -> list[IntegrityFlag]:
        cands = candidates(findings or "", clinical_history or "")
        if not cands or not self._api_key:
            return []
        body = {"model": JEV_MODEL,
                "state": {"scan_type": scan_type or "", "clinical_history": clinical_history or "", "scratchpad": findings},
                "questions": audit_questions(cands)}
        t0 = time.perf_counter()
        try:
            resp = await jev_post(body, self._api_key, self._timeout_s, self._transport)
            self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code != 200:
                raise ValueError(f"http {resp.status_code}")
            answers = resp.json().get("answers") or {}
            scores = [_check_unit((answers.get(f"audit_{i}") or {}).get("noul"), f"audit_{i}") for i in range(len(cands))]
        except Exception as e:  # fail open: an audit must never block or error mid-dictation
            logger.warning("[jev.audit] ❌ %s: %s", type(e).__name__, e)
            return []
        flags, seen = [], set()
        for c, score in zip(cands, scores):
            if score > AUDIT_BANDS["flag_max_noul"]:
                continue
            target = c.statements[1] if c.kind == "pair" else c.statements[0]
            other = c.statements[0] if c.kind == "pair" else (c.statements[1] if len(c.statements) > 1 else None)
            kind = _KIND[c.kind]
            if (target.start, kind) in seen:
                continue
            seen.add((target.start, kind))
            flags.append(IntegrityFlag(kind=kind, severity="medium", excerpt=target.text[:60], message=_MESSAGE[c.kind],
                                       start=target.start, end=target.end,
                                       related_start=other.start if other else None,
                                       related_end=other.end if other else None))
        return flags


async def jev_semantic(scan_type: str, clinical_history: str, findings: str) -> list[IntegrityFlag]:
    return await JevAudit().check(scan_type, clinical_history, findings)
