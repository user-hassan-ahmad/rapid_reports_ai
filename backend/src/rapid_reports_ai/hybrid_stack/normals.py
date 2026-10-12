"""Assumed normals (checklist spec §5): the slim sheet's region normals that reach the report unless the
radiologist removes them. Untouched regions keep all their sentences; a dictated-normal region keeps the
radiologist's words instead; an abnormal region keeps only the sentences the dictation neither covers, hedges nor
contradicts (Jev). Sentences the radiologist removed never return."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel

from .jev_stack import (CONDITION_MIN, CONTRA_MIN, GLOBAL_NORMAL_MIN, HEDGED_MIN, REMOVED_MIN, STATED_MIN,
                        ask_conditions, ask_global_normal, ask_rows, normal_assumed)
from .template import jev_text, norm_key

logger = logging.getLogger(__name__)


class AssumedResult(BaseModel):
    assumed: dict[str, list[str]]
    dropped: dict[str, list[dict]] = {}   # region -> [{sentence, reason: covered|hedged|contradicted|removed|rule}]
    ms: int = 0
    error: str | None = None


BATCH = 15   # sentences per Jev call; batches run in parallel (one call over every sentence timed out)


async def _ask(dictation: str, sentences: list[str], gone: list[str]):
    chunks = [sentences[i:i + BATCH] for i in range(0, len(sentences), BATCH)]
    parts = await asyncio.gather(*(ask_rows(dictation, c, gone) for c in chunks))
    return [c for part in parts for c in part]


def _reason(c) -> str:
    """Why a checked normal was not assumed (the order of jev_stack.row_fate)."""
    if c.removed >= REMOVED_MIN:
        return "removed"
    if c.stated >= STATED_MIN:
        return "covered"
    if c.contra >= CONTRA_MIN:
        return "contradicted"
    return "hedged"


def _covered_only(c) -> bool:
    """A bare global "normal" covers every normal; it neither contradicts nor removes one (Task A3)."""
    return c.contra < HEDGED_MIN and c.removed < REMOVED_MIN


async def _no_conditions():
    return []


async def assumed(dictation: str, region_normals: dict[str, list[str]], abnormal: list[str],
                  dictated_normal: list[str], removed: list[str], owned: list[str] | None = None,
                  touched: list[str] | None = None, suppressions: list[tuple[str, str]] | None = None,
                  clinical_history: str = "", labels: dict[str, str] | None = None) -> AssumedResult:
    """Every region of the sheet is answered (an empty list: nothing assumed), so the caller never falls back to
    the raw sheet. Every sentence is checked against the dictation, untouched regions included: a finding the
    grouper filed under another region leaves its own region looking untouched (side review 2026-10-12: "The spleen
    is normal" beside a misplaced splenic finding). A sentence is assumed only when the dictation neither covers,
    hedges nor contradicts it and it does not say the same as a removed sentence or a row's (owned). A template's
    context rule (`suppressions`: condition, sentence) whose condition is met for the case (clinical history and
    dictation) hides its sentence. Every sentence not assumed is in `dropped` with its reason. `labels` (sentence ->
    structure label, template_normal_labels) names a subject-less sentence for the Jev check only; what is returned
    is always the template's own sentence. Labels are keyed by sentence: one sentence in two regions takes the first
    label (acceptable: the same words under two labels is rare and both labels name the sentence's structure). On a
    Jev failure nothing is assumed. `touched` is accepted for compatibility; every sentence is asked now."""
    t0 = time.perf_counter()
    gone = list(dict.fromkeys(r for r in [*removed, *(owned or [])] if r.strip()))
    said = set(dictated_normal)
    labels = labels or {}
    asked = [(region, s) for region, sentences in region_normals.items() if region not in said for s in sentences]
    out: dict[str, list[str]] = {r: [] for r in region_normals}
    dropped: dict[str, list[dict]] = {r: [] for r in region_normals}
    error = None
    if asked:
        try:
            conds = list(dict.fromkeys(c for c, _ in suppressions or []))
            ctx = f"CLINICAL HISTORY:\n{clinical_history or '(not given)'}\nDICTATED FINDINGS:\n{dictation}"
            checks, met, global_normal = await asyncio.gather(
                _ask(dictation, [jev_text(s, labels[s]) if s in labels else s for _, s in asked], gone),
                ask_conditions(ctx, conds) if conds else _no_conditions(),
                ask_global_normal(dictation))
            hidden = {norm_key(s) for c, s in suppressions or [] if met[conds.index(c)] >= CONDITION_MIN}
            for (region, s), c in zip(asked, checks):
                if norm_key(s) in hidden:
                    dropped[region].append({"sentence": s, "reason": "rule"})
                elif normal_assumed(c) or (global_normal >= GLOBAL_NORMAL_MIN and _covered_only(c)):
                    out[region].append(s)
                else:
                    dropped[region].append({"sentence": s, "reason": _reason(c)})
        except Exception as e:
            logger.warning("[stack.normals] %s: %s", type(e).__name__, str(e)[:200])
            error = f"{type(e).__name__}: {e}"
            out = {r: [] for r in region_normals}
            dropped = {r: [] for r in region_normals}
    return AssumedResult(assumed=out, dropped=dropped, ms=int((time.perf_counter() - t0) * 1000), error=error)
