"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Untouched regions keep all their sentences; a dictated-normal region keeps the
radiologist's words instead; an abnormal region keeps only the sentences the dictation neither covers, hedges nor
contradicts (Jev). Sentences the radiologist removed never return."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from .jev_stack import ask_rows, normal_assumed

logger = logging.getLogger(__name__)


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    ms: int = 0
    error: str | None = None


def _norm(s: str) -> str:
    return " ".join(s.lower().strip().rstrip(".").split())


BATCH = 15   # sentences per Jev call; batches run in parallel (one call over every sentence timed out)


async def _ask(dictation: str, sentences: list[str], gone: list[str]):
    chunks = [sentences[i:i + BATCH] for i in range(0, len(sentences), BATCH)]
    parts = await asyncio.gather(*(ask_rows(dictation, c, gone) for c in chunks))
    return [c for part in parts for c in part]


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None,
                  touched: list[str] | None = None) -> AssumedResult:
    """Every region of the sheet is answered (an empty list: nothing assumed), so the caller never falls back to
    the raw sheet. Every sentence is checked against the dictation, untouched regions included: a finding the
    grouper filed under another region leaves its own region looking untouched (side review 2026-10-12: "The spleen
    is normal" beside a misplaced splenic finding). A sentence is assumed only when the dictation neither covers,
    hedges nor contradicts it and it does not say the same as a removed sentence or a row's (owned). On a Jev failure
    nothing is assumed. `touched` is accepted for compatibility; every sentence is asked now."""
    t0 = time.perf_counter()
    gone = list(dict.fromkeys(r for r in [*removed, *(owned or [])] if r.strip()))
    said = set(dictated_normal)
    asked = [(region, s) for region, sentences in region_normals.items() if region not in said for s in sentences]
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    error = None
    if asked:
        try:
            checks = await _ask(dictation, [s for _, s in asked], gone)
            for (region, s), c in zip(asked, checks):
                if normal_assumed(c):
                    out[region].append(s)
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            out = {r: [] for r in region_normals}
    return AssumedResult(assumed=out, ms=int((time.perf_counter() - t0) * 1000), error=error)
