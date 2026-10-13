"""The chat-edit router's Jev questions (spec Flow 1 and 3): one call tags a whole instruction with a yes/no per
kind of change (no splitting: a mixed instruction is several yeses); one call per new prose line asks whether a
style edit hid a rule. Thresholds are lab-set constants (scripts/chat_router_lab.py; Hassan sets them)."""
from __future__ import annotations

import asyncio
import os
from typing import Dict, List

from .jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 4.0
TAG_MIN = 0.5        # a kind at or above is worked (spec: threshold 0.5 as elsewhere)
TAG_UNSURE = 0.35    # [TAG_UNSURE, TAG_MIN): decided by the targeted call, marked llm_unsure (decision D-R2)
REQUIRES_MIN = 0.5   # a new prose line at or above is a rule in disguise

KINDS = ("value", "concept", "fixed", "normal", "layout", "style", "misfit")
QUESTIONS: Dict[str, str] = {
    "value": "Does the INSTRUCTION ask to change which values every report must state?",
    "concept": "Does the INSTRUCTION ask to change how comparison / prior imaging, contrast, sequences not acquired "
               "or a technical limitation is worded?",
    "fixed": "Does the INSTRUCTION ask to change a sentence printed in every report?",
    "normal": "Does the INSTRUCTION ask to change how a normal finding for a region is worded, or whether it is "
              "stated?",
    "layout": "Does the INSTRUCTION ask to add, remove, rename or reorder a section or paragraph?",
    "style": "Does the INSTRUCTION ask to change style, tone, length or phrasing?",
    "misfit": "Does the INSTRUCTION ask for something that does not belong in a report of this scan type?",
}
REQUIRES = "Does this LINE require the report to state something?"


def _score(answers: dict, key: str) -> float:
    v = (answers.get(key) or {}).get("noul")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("jev: incomplete answers")
    return float(v)


async def tag(instruction: str, scan_type: str = "", context: str = "", transport=None) -> Dict[str, float]:
    """P(yes) per kind in KINDS, one Jev call. Raises on any failure (the caller falls back)."""
    state = f"SCAN TYPE: {scan_type or 'not given'}\n\nINSTRUCTION:\n{(instruction or '').strip()}"
    if (context or "").strip():
        state += f"\n\nPREVIOUS REPLY (context only):\n{context.strip()}"
    r = await jev_post({"model": JEV_MODEL, "state": state,
                        "questions": {k: {"type": "noul", "instructions": QUESTIONS[k]} for k in KINDS}},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    answers = r.json().get("answers") or {}
    return {k: _score(answers, k) for k in KINDS}


async def requires(lines: List[str], transport=None) -> List[float]:
    """P(the line requires the report to state something), one Jev call per line, in order. Raises on failure."""
    async def one(line: str) -> float:
        r = await jev_post({"model": JEV_MODEL, "state": f"LINE:\n{line}",
                            "questions": {"q": {"type": "noul", "instructions": REQUIRES}}},
                           os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
        r.raise_for_status()
        return _score(r.json().get("answers") or {}, "q")
    if not lines:
        return []
    return list(await asyncio.gather(*(one(l) for l in lines)))
