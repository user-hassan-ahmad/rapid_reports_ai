"""Conclusion check (confirm gate): what type of recommendation the report's CONCLUSION gives for a card's FINDING,
by one Jev choice per card. Categories only (none / surveillance / workup / refer); the card's own verdict is compared
client-side. Failures, timeouts, an unoffered choice or low confidence are None (not checked), never a guess.
The cache holds normalised clinical text in its keys, is bounded by matcher._CACHE_MAX, process-local, never
persisted and never logged; successes only."""
from __future__ import annotations

import asyncio
import os
from collections import OrderedDict

from ...jev_client import JEV_MODEL, jev_post
from . import jev as J
from . import matcher as M
from . import registry as R

CHOICE_MIN = 0.6
JEV_TIMEOUT_S = 4.0
CONCURRENCY = 4

OPTIONS = {
    "c0": ("No follow-up or management is recommended for the FINDING.", "none"),
    "c1": ("Follow-up imaging of the FINDING.", "surveillance"),
    "c2": ("Further tests or investigation of the FINDING, such as another imaging test or tissue sampling.", "workup"),
    "c3": ("Referral to a specialist team or multidisciplinary meeting for the FINDING.", "refer"),
}
_QUESTION = {"type": "choice", "instructions": "What does the CONCLUSION recommend for the FINDING?",
             "criteria": {k: t for k, (t, _) in OPTIONS.items()}}

_CACHE: "OrderedDict[tuple, str]" = OrderedDict()   # (conclusion, key, finding) -> category (successes only)


def clear_cache() -> None:
    _CACHE.clear()


async def _one(conclusion: str, key: str, finding: str, sem: asyncio.Semaphore) -> str | None:
    k = (R.norm(conclusion), key, R.norm(finding))
    hit, v = M._get(_CACHE, k)
    if hit:
        return v
    try:
        async with sem:
            r = await jev_post({"model": JEV_MODEL, "state": f"CONCLUSION:\n{conclusion}\n\nFINDING:\n{finding}",
                                "questions": {"rec": _QUESTION}},
                               os.environ.get("OPENROUTER_API_KEY", ""), JEV_TIMEOUT_S)
            r.raise_for_status()
            c, conf = J.choice(r.json(), "rec")
    except Exception:   # a failed check is no verdict: the gate never blocks on it
        return None
    if c not in OPTIONS:
        return None
    if conf < CHOICE_MIN:
        return None
    v = OPTIONS[c][1]
    M._put(_CACHE, k, v)
    return v


async def check(conclusion: str, cards: list[tuple[str, str]]) -> dict[str, str | None]:
    if not conclusion.strip():
        return {k: None for k, _ in cards}
    sem = asyncio.Semaphore(CONCURRENCY)
    got = await asyncio.gather(*(_one(conclusion, k, f, sem) for k, f in cards))
    return {k: v for (k, _), v in zip(cards, got)}
