"""Check chips (spec v2 §4): the L-45 finding-linked negatives, live per abnormal region. Qwen writes up to
three negatives per finding (report_reconcile's fallback instruction, no prepared finding types); code
drops duplicates and anything the dictation already makes; Jev drops what the dictation already states."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

from pydantic import BaseModel

from ..report_reconcile import _fallback, dictated_negatives, duplicates_negative, split_findings
from .jev_stack import ask_checks, chip_state
from .schemas import scan_key

logger = logging.getLogger(__name__)
MAX_PER_REGION = 3
_CACHE: "OrderedDict[tuple, list[str]]" = OrderedDict()   # Qwen's texts only: states are per dictation
_CACHE_MAX = 256
# Chips are stated by default (spec v2 §4), so each must be one short report sentence. Added to the request
# only: the shared fallback instruction (the brief's) is unchanged.
CHIP_FORM = ("Write each negative as one short report sentence that names one absent finding and nothing else: "
             "no reason or purpose clause, no 'or', no list.")


class Chip(BaseModel):
    text: str
    state: str  # included (in the report unless removed) | optional (opt-in)


class ChipsResult(BaseModel):
    chips: list[Chip]
    cached: bool = False
    ms: int = 0
    error: str | None = None


def clear_cache() -> None:
    _CACHE.clear()


def _key(scan_type: str, region: str, sentences: list[str]) -> tuple:
    return scan_key(scan_type), region.strip().lower(), tuple(" ".join(s.split()).lower() for s in sentences)


async def _texts(scan_type: str, history: str, sentences: list[str], dictation: str) -> list[str]:
    state = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {history or 'none given'}\nDICTATED FINDINGS:\n{dictation}"
             f"\n\n{CHIP_FORM}")
    out = await _fallback(state, [s.strip() for s in sentences if s.strip()], [])
    texts: list[str] = []
    for it in sorted(out.items, key=lambda x: x.index):
        for neg in it.negatives:
            neg = neg.strip()
            if neg and not duplicates_negative(neg, texts):
                texts.append(neg)
    return texts


async def suggest(scan_type: str, history: str, region: str, sentences: list[str], dictation: str,
                  declined: list[str] | None = None) -> ChipsResult:
    """Qwen's texts are cached per (scan, region, sentences); the dictation filter, the removed chips and the
    Jev checks always run against this case's dictation (a cached state could include a contradicted chip)."""
    t0 = time.perf_counter()
    key = _key(scan_type, region, sentences)
    cached = key in _CACHE
    if cached:
        _CACHE.move_to_end(key)
        texts = list(_CACHE[key])
    else:
        try:
            texts = await _texts(scan_type, history, sentences, dictation)
        except Exception as e:  # fail open: no chips
            logger.warning("[stack.chips] %s: %s", type(e).__name__, str(e)[:200])
            return ChipsResult(chips=[], ms=int((time.perf_counter() - t0) * 1000), error=f"{type(e).__name__}: {e}")
        _CACHE[key] = list(texts)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    said = dictated_negatives(split_findings(dictation))
    texts = [t for t in texts if not duplicates_negative(t, said) and not duplicates_negative(t, list(declined or []))]
    try:
        states = [chip_state(st, co) for st, co in await ask_checks(dictation, texts)]
    except Exception as e:  # fail open, but never include unchecked: every chip is opt-in
        logger.warning("[stack.chips.checks] %s: %s", type(e).__name__, str(e)[:200])
        states = ["optional"] * len(texts)
    chips = [Chip(text=t, state=s) for t, s in zip(texts, states) if s != "gone"][:MAX_PER_REGION]
    return ChipsResult(chips=chips, cached=cached, ms=int((time.perf_counter() - t0) * 1000))
