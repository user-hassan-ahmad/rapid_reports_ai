"""Jev gates of the targeted fetch (spec §2.20, §5.3, §5.5): judgements about meaning over source text. Code does
only the exact-quote first pass. Thresholds are provisional until the seed lab (plan Task 13) sets them where false
yes answers reach zero."""
from __future__ import annotations

import os
import re
from typing import Any

from ...jev_client import JEV_MODEL, jev_post

TIMEOUT_S = 6.0
STATE_MAX = 12000          # chars of source text per Jev call

COVER_MIN = 0.7            # provisional: SOURCE states the criteria or management for a branch
EVIDENCE_MIN = 0.8         # provisional: SOURCE states a claim whose quote is not an exact match
ANSWERS_MIN = 0.7          # provisional: the stored material answers a radiologist's question


def _state(source: str) -> str:
    return "SOURCE:\n" + source[:STATE_MAX]


def _flat(s: str) -> str:
    return " ".join(re.sub(r"[^\w<>≤≥=.%/+-]+", " ", s.lower()).split())


def quote_in(source: str, quote: str) -> bool:
    """The exact-match first pass: the quote appears in the source once whitespace, case and punctuation runs are
    flattened (tables lose their layout in extraction; meaning-level matches go to Jev)."""
    q = _flat(quote)
    return bool(q) and q in _flat(source)


async def _ask(state: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return {k: float((ans.get(k) or {}).get("noul") or 0.0) for k in questions}


async def coverage(source: str, branches: list[str], transport=None) -> dict[str, float]:
    """P(the SOURCE sets out the criteria or management for each branch), one call."""
    if not branches:
        return {}
    qs = {f"b_{i}": {"type": "noul", "instructions": (
        "The SOURCE states the classification criteria or the management recommendations for this case of the "
        f"guideline (not only mentions it): {b}")} for i, b in enumerate(branches)}
    got = await _ask(_state(source), qs, transport)
    return {b: got[f"b_{i}"] for i, b in enumerate(branches)}


async def evidence(source: str, claims: list[tuple[str, str]], transport=None) -> list[float]:
    """Per (quote, claim): 1.0 when the quote is an exact match; otherwise P(the SOURCE states the claim)."""
    out: list[float] = [1.0 if quote_in(source, q) else -1.0 for q, _ in claims]
    need = {f"c_{i}": {"type": "noul", "instructions": f"The SOURCE states this, with the same values: {c}"}
            for i, (_, c) in enumerate(claims) if out[i] < 0}
    if need:
        got = await _ask(_state(source), need, transport)
        for k, v in got.items():
            out[int(k[2:])] = v
    return out


async def answers(material: str, question: str, transport=None) -> float:
    """P(the stored guideline material answers the radiologist's question)."""
    got = await _ask(_state(material), {"q": {"type": "noul", "instructions": (
        f"The SOURCE contains the answer to this question: {question}")}}, transport)
    return got["q"]
