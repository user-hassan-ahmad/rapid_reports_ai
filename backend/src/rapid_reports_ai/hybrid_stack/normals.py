"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Untouched regions keep all their sentences; a dictated-normal region keeps the
radiologist's words instead; an abnormal region keeps only the sentences the dictation neither covers, hedges nor
contradicts (Jev). Sentences the radiologist removed never return."""
from __future__ import annotations

import logging
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


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None) -> AssumedResult:
    """owned: the checklist rows' sentences. A row owns its check, so a region normal saying the same is never
    assumed (hand read 2026-10-12: the sheet's "The appendix is normal" answered a ?appendicitis referral
    silently)."""
    t0 = time.perf_counter()
    removed = [r for r in [*removed, *(owned or [])] if r.strip()]
    ab, said = set(abnormal), set(dictated_normal)
    asked: list[tuple[str, str]] = []           # (region, sentence) sent to Jev
    out: dict[str, list[str]] = {}
    for region, sentences in region_normals.items():
        if region in said:
            continue
        for s in sentences:
            if region in ab or removed:          # untouched regions are asked only about removed sentences
                asked.append((region, s))
            else:
                out.setdefault(region, []).append(s)
    error = None
    if asked:
        try:
            checks = await ask_rows(dictation, [s for _, s in asked], removed)
            for (region, s), c in zip(asked, checks):
                keep = normal_assumed(c) if region in ab else c.removed < REMOVED_MIN
                if keep:
                    out.setdefault(region, []).append(s)
        except Exception as e:  # never assume in an abnormal region unchecked; removed by exact match
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            gone = {_norm(r) for r in removed}
            for region, s in asked:
                if region not in ab and _norm(s) not in gone:
                    out.setdefault(region, []).append(s)
    ordered = {r: out[r] for r in region_normals if out.get(r)}
    return AssumedResult(assumed=ordered, ms=int((time.perf_counter() - t0) * 1000), error=error)
