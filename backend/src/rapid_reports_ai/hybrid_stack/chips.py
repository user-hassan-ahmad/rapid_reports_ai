"""Check chips (spec v2 §4): the L-45 finding-linked negatives, live per abnormal region. Qwen writes up to
three negatives per finding (report_reconcile's fallback instruction, no prepared finding types); code
drops duplicates and anything the dictation already makes; Jev drops what the dictation already states."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

from pydantic import BaseModel

from ..report_reconcile import _fallback, dictated_negatives, duplicates_negative, split_findings
from .jev_stack import STATED_MIN, ask_stated
from .schemas import scan_key

logger = logging.getLogger(__name__)
MAX_PER_REGION = 3
_CACHE: "OrderedDict[tuple, list[str]]" = OrderedDict()
_CACHE_MAX = 256


class ChipsResult(BaseModel):
    chips: list[str]
    cached: bool = False
    ms: int = 0
    error: str | None = None


def clear_cache() -> None:
    _CACHE.clear()


def _key(scan_type: str, region: str, sentences: list[str]) -> tuple:
    return scan_key(scan_type), region.strip().lower(), tuple(" ".join(s.split()).lower() for s in sentences)


async def suggest(scan_type: str, history: str, region: str, sentences: list[str], dictation: str) -> ChipsResult:
    t0 = time.perf_counter()
    key = _key(scan_type, region, sentences)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return ChipsResult(chips=list(_CACHE[key]), cached=True)
    state = f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\nDICTATED FINDINGS:\n{dictation}"
    try:
        out = await _fallback(state, [s.strip() for s in sentences if s.strip()], [])
    except Exception as e:  # fail open: no chips
        logger.warning("[stack.chips] %s: %s", type(e).__name__, str(e)[:200])
        return ChipsResult(chips=[], ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
    said = dictated_negatives(split_findings(dictation))
    chips: list[str] = []
    for it in sorted(out.items, key=lambda x: x.index):
        for neg in it.negatives:
            neg = neg.strip()
            if neg and not duplicates_negative(neg, said + chips):
                chips.append(neg)
    try:
        scores = await ask_stated(dictation, chips)
        chips = [c for c, p in zip(chips, scores) if p < STATED_MIN]
    except Exception as e:  # fail open: keep the chips; dictation re-asks later
        logger.warning("[stack.chips.stated] %s: %s", type(e).__name__, str(e)[:200])
    chips = chips[:MAX_PER_REGION]
    _CACHE[key] = chips
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return ChipsResult(chips=list(chips), ms=int((time.perf_counter() - t0) * 1000))
