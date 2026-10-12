"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Untouched regions keep all their sentences; a dictated-normal region keeps the
radiologist's words instead; an abnormal region keeps only the sentences the dictation neither covers, hedges nor
contradicts (Jev). Sentences the radiologist removed never return."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from .jev_stack import (CONDITION_MIN, CONTRA_MIN, REMOVED_MIN, STATED_MIN, RowCheck, ask_conditions, ask_rows,
                        normal_assumed)
from .template import jev_text, norm_key

logger = logging.getLogger(__name__)


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    dropped: dict[str, list[dict]] = {}   # region -> [{sentence, reason: covered|hedged|contradicted|removed|rule}]
    ms: int = 0
    error: str | None = None


BATCH = 15   # sentences per Jev call; batches run in parallel (one call over every sentence timed out)


async def _ask(dictation: str, sentences: list[str], gone: list[str], **parts):
    chunks = [sentences[i:i + BATCH] for i in range(0, len(sentences), BATCH)]
    got = await asyncio.gather(*(ask_rows(dictation, c, gone, **parts) for c in chunks))
    return [c for part in got for c in part]


def _batches(n: int) -> int:
    return -(-n // BATCH)


def _text_regions(asked: list[tuple[str, str]], region_text: dict[str, str]) -> list[str]:
    # region_text keys must match the region names exactly: a mismatch finds no text, so it fails toward offering
    # more normals (nothing covers them), never toward dropping them.
    return list(dict.fromkeys(r for r, _ in asked if (region_text.get(r) or "").strip()))


def _jev_calls(asked: list[tuple[str, str]], region_text: dict[str, str] | None, conds: list[str]) -> int:
    """The Jev calls one refresh makes (logged, so fan-out can be watched live)."""
    n = _batches(len(asked)) + (1 if conds else 0)
    if region_text is not None:
        n += sum(_batches(sum(1 for r, _ in asked if r == t)) for t in _text_regions(asked, region_text))
    return n


async def _ask_by_region(dictation: str, asked: list[tuple[str, str]], texts: list[str], gone: list[str],
                         region_text: dict[str, str]) -> list[RowCheck]:
    """Task A3b: a normal is covered or hedged only by the sentences grouped in its own region (one stated call per
    region with text, in parallel; a region with none is covered by nothing); contradicted (and the same as a
    removed sentence) by the whole dictation, conclusion included."""
    regions = _text_regions(asked, region_text)
    idx = {r: [i for i, (ar, _) in enumerate(asked) if ar == r] for r in regions}
    whole, *per_region = await asyncio.gather(
        _ask(dictation, texts, gone, stated=False),
        *(_ask(region_text[r], [texts[i] for i in idx[r]], [], contra=False) for r in regions))
    stated = [0.0] * len(asked)
    for r, checks in zip(regions, per_region):
        for i, c in zip(idx[r], checks):
            stated[i] = c.stated
    return [RowCheck(s, c.contra, c.removed) for s, c in zip(stated, whole)]


def _reason(c) -> str:
    """Why a checked normal was not assumed (the order of jev_stack.row_fate)."""
    if c.removed >= REMOVED_MIN:
        return "removed"
    if c.stated >= STATED_MIN:
        return "covered"
    if c.contra >= CONTRA_MIN:
        return "contradicted"
    return "hedged"


async def _no_conditions():
    return []


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None,
                  touched: list[str] | None = None, suppressions: list[tuple[str, str]] | None = None,
                  clinical_history: str = "", labels: dict[str, str] | None = None,
                  region_text: dict[str, str] | None = None) -> AssumedResult:
    """Every region of the sheet is answered (an empty list: nothing assumed), so the caller never falls back to
    the raw sheet. Every sentence is checked for contradiction against the whole dictation, untouched regions
    included: a finding the grouper filed under another region leaves its own region looking untouched (side review
    2026-10-12: "The spleen is normal" beside a misplaced splenic finding). A sentence is assumed only when the dictation neither covers,
    hedges nor contradicts it and it does not say the same as a removed sentence or a row's (owned). A template's
    context rule (`suppressions`: condition, sentence) whose condition is met for the case (clinical history and
    dictation) hides its sentence. Every sentence not assumed is in `dropped` with its reason. `labels` (sentence ->
    structure label, template_normal_labels) names a subject-less sentence for the Jev check only; what is returned
    is always the template's own sentence. Labels are keyed by sentence: one sentence in two regions takes the first
    label (acceptable: the same words under two labels is rare and both labels name the sentence's structure).
    `region_text` (region -> its grouped sentences; Technique, General, Conclusion and unplaced excluded): a normal
    is covered or hedged only by its own region's sentences, so a conclusion or a bare "normal" covers nothing;
    contradiction is still asked on the whole dictation. None: the whole dictation answers both (older callers). On
    a Jev failure nothing is assumed. `touched` is accepted for compatibility; every sentence is asked now."""
    t0 = time.perf_counter()
    gone = list(dict.fromkeys(r for r in [*removed, *(owned or [])] if r.strip()))
    said = set(dictated_normal)
    labels = labels or {}
    asked = [(region, s) for region, sentences in region_normals.items() if region not in said for s in sentences]
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    dropped: dict[str, list[dict]] = {r: [] for r in region_normals}
    error = None
    conds = list(dict.fromkeys(c for c, _ in suppressions or []))
    if asked:
        try:
            ctx = f"CLINICAL HISTORY:\n{clinical_history or '(not given)'}\nDICTATED FINDINGS:\n{dictation}"
            texts = [jev_text(s, labels[s]) if s in labels else s for _, s in asked]
            checks, met = await asyncio.gather(
                _ask(dictation, texts, gone) if region_text is None
                else _ask_by_region(dictation, asked, texts, gone, region_text),
                ask_conditions(ctx, conds) if conds else _no_conditions())
            hidden = {norm_key(s) for c, s in suppressions or [] if met[conds.index(c)] >= CONDITION_MIN}
            for (region, s), c in zip(asked, checks):
                if norm_key(s) in hidden:
                    dropped[region].append({"sentence": s, "reason": "rule"})
                elif normal_assumed(c):
                    out[region].append(s)
                else:
                    dropped[region].append({"sentence": s, "reason": _reason(c)})
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            out = {r: [] for r in region_normals}
            dropped = {r: [] for r in region_normals}
        logger.log(logging.WARNING if error else logging.INFO, "[stack.normals] jev_calls=%d failed=%s mode=%s",
                   _jev_calls(asked, region_text, conds), error is not None,
                   "whole" if region_text is None else "region")
    return AssumedResult(assumed=out, dropped=dropped, ms=int((time.perf_counter() - t0) * 1000), error=error)
