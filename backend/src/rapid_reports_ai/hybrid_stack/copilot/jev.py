"""Jev gates of the targeted fetch (spec §2.20, §5.3, §5.5): judgements about meaning over source text. Code does
only the exact-quote first pass. Thresholds are provisional until the seed lab (plan Task 13) sets them where false
yes answers reach zero."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from ...jev_client import JEV_MODEL, jev_post

logger = logging.getLogger(__name__)

TIMEOUT_S = 6.0
STATE_MAX = 12000          # chars of source text per Jev call; the lab (Task 13) may raise this
WINDOW_CAP = 6             # a source past this many windows is capped, not sent whole (latency, cost)
SOURCE_MAX = STATE_MAX * WINDOW_CAP   # the structure step (Task 5) should cap a guideline's stored source to this

COVER_MIN = 0.7            # provisional: SOURCE states the criteria or management for a branch
EVIDENCE_MIN = 0.8         # provisional: SOURCE states a claim whose quote is not an exact match
ANSWERS_MIN = 0.7          # provisional: the stored material answers a radiologist's question

_DASH = str.maketrans({"–": "-", "—": "-", "‐": "-", "−": "-"})
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _flat(s: str) -> str:
    s = s.lower().translate(_DASH).replace("≥", ">=").replace("≤", "<=")
    s = re.sub(r"[^\w<>=.%/+-]+|_", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"(\d)\s*(mm|cm|%)\b", r"\1 \2", s)
    s = re.sub(r"([<>]=?)\s+", r"\1", s)
    return " ".join(s.split())


def quote_in(source: str, quote: str) -> bool:
    """The exact-match first pass: the quote appears in the source as whole tokens once whitespace, case,
    dashes and punctuation runs are flattened (tables lose their layout in extraction; meaning-level matches go to
    Jev). A quote under 4 tokens is too easy to false-match on a bare number or unit, so it never passes here."""
    q = _flat(quote)
    return len(q.split()) >= 4 and f" {q} " in f" {_flat(source)} "


def _numbers_covered(claim: str, quote: str) -> bool:
    """An exact quote only counts as evidence for a claim when every number the claim states also appears in the
    quote — otherwise "CT at 3 months" would pass evidence from a quote that actually says 6 months."""
    return set(_NUM.findall(claim)) <= set(_NUM.findall(quote))


def _windows(source: str) -> list[str]:
    """Split the source into windows that each fit STATE_MAX, breaking on chunk boundaries ("\\n\\n[", how fetch
    joins "[url]\\ntext" chunks) so a window never cuts mid-chunk; falls back to a plain paragraph split when the
    source carries no such markers. Capped at WINDOW_CAP windows (logged) rather than sent whole."""
    pieces = re.split(r"\n\n(?=\[)", source) if "\n\n[" in source else source.split("\n\n")
    windows: list[str] = []
    cur = ""
    for piece in pieces:
        nxt = f"{cur}\n\n{piece}" if cur else piece
        if cur and len(nxt) > STATE_MAX:
            windows.append(cur)
            cur = piece
        else:
            cur = nxt
    if cur:
        windows.append(cur)
    out: list[str] = []
    for w in windows:
        while len(w) > STATE_MAX:
            out.append(w[:STATE_MAX])
            w = w[STATE_MAX:]
        out.append(w)
    out = out or [""]
    if len(out) > WINDOW_CAP:
        logger.warning("[copilot.jev] %d windows, dropping %d beyond the cap of %d", len(out), len(out) - WINDOW_CAP, WINDOW_CAP)
        out = out[:WINDOW_CAP]
    return out


def _state(window: str) -> str:
    return "SOURCE:\n" + window


async def _ask(state: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": questions},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    return {k: float((ans.get(k) or {}).get("noul") or 0.0) for k in questions}


async def _ask_windowed(source: str, questions: dict[str, dict[str, Any]], transport=None) -> dict[str, float]:
    """One call per window, in parallel; the max score per question (an existence question is true if any window
    shows it, never diluted by the windows that don't)."""
    results = await asyncio.gather(*(_ask(_state(w), questions, transport) for w in _windows(source)))
    out: dict[str, float] = {k: 0.0 for k in questions}
    for r in results:
        for k, v in r.items():
            out[k] = max(out[k], v)
    return out


async def coverage(source: str, branches: list[str], transport=None) -> dict[str, float]:
    """P(the SOURCE sets out the criteria or management for each branch), one call per window."""
    if not branches:
        return {}
    qs = {f"b_{i}": {"type": "noul", "instructions": (
        "The SOURCE states the classification criteria or the management recommendations for this case of the "
        f"guideline (not only mentions it): {b}")} for i, b in enumerate(branches)}
    got = await _ask_windowed(source, qs, transport)
    return {b: got[f"b_{i}"] for i, b in enumerate(branches)}


async def evidence(source: str, claims: list[tuple[str, str]], transport=None) -> list[float]:
    """Per (quote, claim): 1.0 when the quote is an exact match whose numbers also match the claim; otherwise
    P(the SOURCE states the claim), from whichever window shows it."""
    out: list[float] = [1.0 if quote_in(source, q) and _numbers_covered(c, q) else -1.0 for q, c in claims]
    need = {f"c_{i}": {"type": "noul", "instructions": f"The SOURCE states this, with the same values: {c}"}
            for i, (_, c) in enumerate(claims) if out[i] < 0}
    if need:
        got = await _ask_windowed(source, need, transport)
        for k, v in got.items():
            out[int(k[2:])] = v
    return out


async def answers(material: str, question: str, transport=None) -> float:
    """P(the stored guideline material answers the radiologist's question)."""
    got = await _ask_windowed(material, {"q": {"type": "noul", "instructions": (
        f"The SOURCE contains the answer to this question: {question}")}}, transport)
    return got["q"]
