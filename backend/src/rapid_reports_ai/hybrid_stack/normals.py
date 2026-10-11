"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Untouched regions keep all their sentences; a dictated-normal region keeps the
radiologist's words instead; an abnormal region keeps only the sentences the dictation neither covers, hedges nor
contradicts (Jev). Sentences the radiologist removed never return."""
from __future__ import annotations

import logging
import re
import time

from pydantic import BaseModel

from .jev_stack import REMOVED_MIN, ask_rows, normal_assumed

logger = logging.getLogger(__name__)


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    ms: int = 0
    error: str | None = None


def _norm(s: str) -> str:
    return " ".join(s.lower().strip().rstrip(".").split())


# A cheap candidate filter only: an untouched region's sentence is sent to Jev when it shares a content word with an
# owned or removed sentence; Jev decides. Everything else needs no question (review 2026-10-12: one Jev call over
# every sentence of every region timed out and fell back to exact matching).
_STOP = {"normal", "normally", "there", "with", "without", "seen", "identified", "evidence", "noted", "appears",
         "appearance", "calibre", "caliber", "size", "visualised", "visualized", "unremarkable", "within", "limits",
         "demonstrated", "present", "no", "the", "and", "are", "is"}


def _content(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower()) if w not in _STOP}


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None) -> AssumedResult:
    """Every region of the sheet is answered (an empty list: nothing assumed), so the caller never falls back to
    the raw sheet. owned: the checklist rows' sentences. A row owns its check, so a region normal saying the same
    is never assumed (hand read 2026-10-12). On a Jev failure nothing that might be owned, removed or affected is
    assumed: abnormal regions and candidate sentences are hidden."""
    t0 = time.perf_counter()
    gone = [r for r in [*removed, *(owned or [])] if r.strip()]
    gone_words = [_content(g) for g in gone]
    candidate = lambda s: bool(_content(s)) and any(_content(s) & g for g in gone_words)
    ab, said = set(abnormal), set(dictated_normal)
    asked: list[tuple[str, str]] = []           # (region, sentence) sent to Jev
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    for region, sentences in region_normals.items():
        if region in said:
            continue
        for s in sentences:
            if region in ab or candidate(s):
                asked.append((region, s))
            else:
                out[region].append(s)
    error = None
    if asked:
        try:
            checks = await ask_rows(dictation, [s for _, s in asked], gone)
            kept = {(region, s) for (region, s), c in zip(asked, checks)
                    if (normal_assumed(c) if region in ab else c.removed < REMOVED_MIN)}
            for region, sentences in region_normals.items():
                out[region] = [s for s in sentences if (region, s) in kept or s in out[region]]
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
    return AssumedResult(assumed=out, ms=int((time.perf_counter() - t0) * 1000), error=error)
