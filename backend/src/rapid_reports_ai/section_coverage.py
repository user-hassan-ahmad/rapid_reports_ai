"""Checklist pill coverage as System 1 decisions: one Noul per section, one call.

The criteria reproduce the rules in canvas_routes.CANVAS_COVERAGE_SYSTEM_PROMPT so
that Jev and the Qwen path answer the same question. Edit COVERAGE_CRITERIA (jev_questions) and that
prompt together; test_section_coverage pins the shared phrases.

Spec: docs/superpowers/specs/2026-09-24-section-coverage-jev-design.md
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel

from .dictation_triage import JEV_MODEL, JEV_TIMEOUT_S, TriageError, _check_unit
from .jev_client import jev_post
from .jev_questions import BINARY_THRESHOLD, COVERAGE_CRITERIA, QSET_VERSION, coverage_questions  # noqa: F401

Candidate = Literal["jev", "qwen"]
@dataclass(frozen=True)
class CoverageDecision:
    candidate: Candidate
    scores: dict[str, float]
    covered: list[str]
    latency_ms: int
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    raw: list[str] = field(default_factory=list)  # qwen only: the model's unnormalised list


def covered_from_scores(
    scores: dict[str, float], sections: list[str], threshold: float = BINARY_THRESHOLD
) -> list[str]:
    return [s for s in sections if scores.get(s, 0.0) >= threshold]


class JevCoverage:
    name: str = "jev"

    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = JEV_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or ""
        if not self._api_key:
            raise TriageError("OPENROUTER_API_KEY is not set")
        self._transport = transport
        self._timeout_s = timeout_s

    async def classify(self, scratchpad: str, sections: list[str], scan_type: str) -> CoverageDecision:
        if not sections:
            return CoverageDecision(candidate="jev", scores={}, covered=[], latency_ms=0)
        body = {
            "model": JEV_MODEL,
            "state": {"scan_type": scan_type or "", "checklist": list(sections), "scratchpad": scratchpad or ""},
            "questions": coverage_questions(sections),
        }
        t0 = time.perf_counter()
        try:
            resp = await jev_post(body, self._api_key, self._timeout_s, self._transport)
        except httpx.HTTPError as e:
            raise TriageError(f"jev coverage transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev coverage http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev coverage returned non-JSON") from e
        answers = data.get("answers") or {}
        scores: dict[str, float] = {}
        for s in sections:
            if s not in answers:
                raise TriageError(f"jev coverage answer missing: {s}")
            scores[s] = _check_unit(answers[s].get("noul"), f"coverage[{s}]")
        usage = data.get("usage") or {}
        return CoverageDecision(
            candidate="jev",
            scores=scores,
            covered=covered_from_scores(scores, sections),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
        )


_JEV: JevCoverage | None = None


def get_jev_coverage() -> JevCoverage:
    global _JEV
    if _JEV is None:
        _JEV = JevCoverage()
    return _JEV


class CoverageCandidateTrace(BaseModel):
    scores: Optional[dict[str, float]] = None
    covered: Optional[list[str]] = None
    raw: Optional[list[str]] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class CoverageTrace(BaseModel):
    selected: Candidate
    qset: str = QSET_VERSION
    jev: Optional[CoverageCandidateTrace] = None
    qwen: Optional[CoverageCandidateTrace] = None


def decision_to_coverage_trace(result: CoverageDecision | BaseException | None) -> CoverageCandidateTrace | None:
    if result is None:
        return None
    if isinstance(result, BaseException):
        return CoverageCandidateTrace(error=type(result).__name__)
    return CoverageCandidateTrace(
        scores=result.scores,
        covered=result.covered,
        raw=result.raw or None,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        cost_usd=result.cost_usd,
    )
