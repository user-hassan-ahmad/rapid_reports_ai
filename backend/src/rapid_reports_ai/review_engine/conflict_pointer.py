"""Grounded reason for conflict cards: the dictated line the flagged statement conflicts with, quoted.

One batched Jev choice question per card (lab: 6/6 clear conflicts at P >= 0.87, `none` on 15/15 control normals,
wrong pointers all 0.49-0.66). Quote only at or above POINTER_MIN; the probabilities are always recorded in
`evidence["conflict_pointer"]`. Never fails a run: any error leaves the items unchanged and is logged."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from .. import report_reconcile as rc
from ..report_review import JEV_TIMEOUT_S, dictated_items
from .items import ReviewInput, ReviewItem

logger = logging.getLogger(__name__)

POINTER_MIN = 0.80      # show the quote at or above this
WEAK_NONE = 0.25        # logged only, no behaviour yet


def q_pointer(clause: str, lines: List[str]) -> dict:
    return {"type": "choice",
            "instructions": f'The report says: "{clause}". Which dictated finding does this statement conflict with?',
            "criteria": {f"d{j}": line for j, line in enumerate(lines)} | {
                "none": "No dictated finding conflicts with it, or the conflict is unclear."}}


def state(inp: ReviewInput) -> str:
    return f"SCAN TYPE: {inp.scan_type}\nDICTATED FINDINGS:\n{inp.artifacts.dictated_findings or ''}"


def _clause(it: ReviewItem) -> str:
    ev = it.evidence or {}
    return (ev.get("clause") or (it.anchor.text if it.anchor else "") or "").strip()


def is_conflict_card(it: ReviewItem) -> bool:
    if it.status not in ("open", "stale"):
        return False
    if it.kind == "check":
        return (it.evidence or {}).get("check_reason") == "conflict" and bool(_clause(it))
    return it.kind == "contradicted" and bool(_clause(it))


def _parse(ans: Optional[dict], n: int):
    """(top line index or None, p_top, p_none) from a choice answer."""
    probs = (ans or {}).get("probabilities") or {}
    p_none = float(probs.get("none") or 0.0)
    best, p_top = None, 0.0
    for j in range(n):
        p = float(probs.get(f"d{j}") or 0.0)
        if p > p_top:
            best, p_top = j, p
    if best is not None and p_none > p_top:      # `none` is the top answer: no line
        return None, p_top, p_none
    return best, p_top, p_none


async def annotate(inp: ReviewInput, items: List[ReviewItem]) -> dict:
    log = {"asked": 0, "quoted": 0, "weak": 0, "error": None}
    try:
        cards = [it for it in items if is_conflict_card(it)]
        lines = dictated_items(inp.artifacts.dictated_findings or "")
        if not cards or not lines:
            return log
        qs = {f"p{k}": q_pointer(_clause(it), lines) for k, it in enumerate(cards)}
        log["asked"] = len(qs)
        res = await asyncio.wait_for(rc._jev(state(inp), qs), JEV_TIMEOUT_S)
        staged = []
        for k, it in enumerate(cards):
            j, p_top, p_none = _parse((res or {}).get(f"p{k}"), len(lines))
            staged.append((it, j, p_top, p_none))
        for it, j, p_top, p_none in staged:
            ev = dict(it.evidence or {})
            ev["conflict_pointer"] = {"line": lines[j] if j is not None else None, "p": p_top, "p_none": p_none}
            if p_none >= WEAK_NONE:
                log["weak"] += 1
            if j is not None and p_top >= POINTER_MIN:
                quote = lines[j]
                ev["dictated_quote"] = quote
                if not ev.get("pointer"):
                    ev["pointer"] = quote
                if quote not in (it.reason or ""):
                    it.reason = f"{it.reason or ''} You dictated: “{quote}”."
                log["quoted"] += 1
            it.evidence = ev
    except Exception as e:  # noqa: BLE001
        log["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        logger.warning("conflict pointer failed (%s)", log["error"])
    return log
