"""One Jev call per utterance: triage + standalone + section coverage.

Rev 2 component 1. The question texts are the separate components' own, imported
rather than copied, so a bundle-vs-separate difference measures bundling, not
wording. The shared state forces two subject edits: 'standalone' names the open line
plus the latest utterance (was: buffered words plus the chunk), and coverage names
COMMITTED plus ACTIVE (was: the scratchpad). Coverage is of the scratchpad before
this utterance, as /review asks it today; per-utterance section nouls are component 3.

Spec: docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md §4, §7.1
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .dictation_triage import (
    JEV_MODEL,
    JEV_TIMEOUT_S,
    JEV_URL,
    TRIAGE_QUESTIONS,
    JevTriager,
    TriageDecision,
    TriageError,
    _check_unit,
)
from .section_coverage import coverage_questions
from .utterance_boundary import BOUNDARY_QUESTIONS

STANDALONE_QUESTION: dict[str, Any] = {
    **BOUNDARY_QUESTIONS["standalone"],
    "instructions": BOUNDARY_QUESTIONS["standalone"]["instructions"].replace(
        "the buffered words plus the chunk", "the open line plus the latest utterance"
    ),
}


def section_key(i: int) -> str:
    return f"section_{i}"


def bundle_questions(checklist: list[str]) -> dict[str, dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {**TRIAGE_QUESTIONS, "standalone": STANDALONE_QUESTION}
    for i, (_, q) in enumerate(coverage_questions(checklist).items()):
        questions[section_key(i)] = {
            **q,
            "instructions": q["instructions"].replace("The scratchpad", "The scratchpad (COMMITTED plus ACTIVE)", 1),
        }
    return questions


@dataclass(frozen=True)
class BundleState:
    scan_type: str
    committed: str
    active: str
    open_line: str
    latest_utterance: str
    checklist: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, Any]:
        return {
            "scan_type": self.scan_type or "",
            "committed": self.committed or "",
            "active": self.active or "",
            "open_line": self.open_line or "",
            "latest_utterance": self.latest_utterance or "",
            "checklist": list(self.checklist),
        }


@dataclass(frozen=True)
class BundleDecision:
    triage: TriageDecision
    standalone: float
    coverage: dict[str, float]
    latency_ms: int
    n_questions: int
    input_tokens: Optional[int]
    cost_usd: Optional[float]


class JevBundle:
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

    async def classify(self, state: BundleState) -> BundleDecision:
        questions = bundle_questions(state.checklist)
        body = {"model": JEV_MODEL, "state": state.as_payload(), "questions": questions}
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout_s) as client:
                resp = await client.post(JEV_URL, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise TriageError(f"jev bundle transport failure: {type(e).__name__}") from e
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            raise TriageError(f"jev bundle http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise TriageError("jev bundle returned non-JSON") from e
        triage = JevTriager.parse(data, latency_ms)  # validates the three triage answers
        answers = data.get("answers") or {}
        if "standalone" not in answers:
            raise TriageError("jev bundle answer missing: standalone")
        coverage: dict[str, float] = {}
        for i, s in enumerate(state.checklist):
            key = section_key(i)
            if key not in answers:
                raise TriageError(f"jev bundle answer missing: {key}")
            coverage[s] = _check_unit(answers[key].get("noul"), f"coverage[{s}]")
        usage = data.get("usage") or {}
        return BundleDecision(
            triage=triage,
            standalone=_check_unit(answers["standalone"].get("noul"), "standalone"),
            coverage=coverage,
            latency_ms=latency_ms,
            n_questions=len(questions),
            input_tokens=usage.get("input_tokens"),
            cost_usd=usage.get("cost"),
        )


_JEV: JevBundle | None = None


def get_jev_bundle() -> JevBundle:
    global _JEV
    if _JEV is None:
        _JEV = JevBundle()
    return _JEV
