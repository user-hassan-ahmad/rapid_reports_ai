"""AI draft of the conclusion (spec v2 §5), asked once when dictation stops with no dictated conclusion.
Qwen with low reasoning, plain text in our impression style; the radiologist edits and confirms it."""
from __future__ import annotations

import os
import re
import time

from pydantic import BaseModel

from .http import post_json

URL = "https://api.cerebras.ai/v1/chat/completions"
MODEL = "qwen-3.8-27b"
TIMEOUT_S = 15.0

DRAFT_SYSTEM = """You draft the conclusion of a radiology report from the radiologist's dictated findings. The radiologist will edit and confirm it.

- Brief and synthesised: the diagnosis or overall answer first, then only findings that change management. Usually one to three sentences, never more than four.
- Answer the clinical question when the history asks one.
- Use only what the findings state. Never add a finding, measurement, grade or certainty the findings do not give; keep their hedges.
- Never add a classification, stage, score or category the findings do not name (resectability, a TNM or other stage, a grade, a named scoring system): the radiologist assigns it.
- Do not list absent findings or normal structures. At most one negative, only when it answers the clinical question.
- No recommendation, urgency or management advice ("warranting urgent intervention", "surgical review advised") unless the findings themselves state one: the radiologist adds it.
- British English, report style, no heading, no bullet points, no preamble."""

DRAFT_USER = """Scan type: {scan_type}
Clinical history: {history}

Dictated findings:
{findings}

Write the conclusion."""


class DraftResult(BaseModel):
    text: str = ""
    ms: int = 0
    error: str | None = None


def clean(text: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    s = re.sub(r"^(?:#+\s*)?(?:conclusion|impression)\s*:?\s*\n?", "", s, flags=re.I).strip()
    s = re.sub(r"^\s*[-*•]\s+", "", s, flags=re.M)
    return s.strip().strip('"').strip()


async def draft_conclusion(scan_type: str, history: str, findings: str, transport=None) -> DraftResult:
    t0 = time.perf_counter()
    if not findings.strip():
        return DraftResult(error="no findings")
    body = {"model": MODEL, "temperature": 0.2, "max_tokens": 4000, "reasoning_effort": "low",
            "messages": [{"role": "system", "content": DRAFT_SYSTEM},
                         {"role": "user", "content": DRAFT_USER.format(scan_type=scan_type or "(not specified)",
                                                                       history=history or "(none given)",
                                                                       findings=findings)}]}
    try:
        r = await post_json(URL, os.environ.get("CEREBRAS_API_KEY", ""), body, TIMEOUT_S, transport)
        r.raise_for_status()
        text = clean(r.json()["choices"][0]["message"]["content"])
    except Exception as e:  # fail open: no draft; the radiologist dictates or types one
        return DraftResult(ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
    ms = int((time.perf_counter() - t0) * 1000)
    return DraftResult(text=text, ms=ms, error=None if text else "empty draft")
