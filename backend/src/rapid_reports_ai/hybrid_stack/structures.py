"""Sub-pills of a template session (Hassan 2026-10-14, option A): a findings paragraph that COVERS two or more
structures shows one assumed-normal pill per structure. Paragraph regions stay as they are for grouping, the assumed
check and Generate; this only says which structure each offered sentence belongs to. A NORMAL line's own tag decides
(code); an untagged NEGATIVE is bound to one structure by a Jev choice, once per sheet (cached by its hash). Fail
closed: a sentence Jev cannot bind (an error, low confidence, "none") belongs to no structure and stays with its
paragraph, never dropped and never in two places."""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
from collections import OrderedDict
from typing import Any

from ..jev_client import JEV_MODEL, jev_post
from ..template_sheet_structure import SheetStructure
from .template import label_case, template_region_normals, template_structure_split

logger = logging.getLogger(__name__)

BIND_MIN = 0.6   # the choice bar used for the conclusion boundary (gate.MIN_CONF); no lab of its own yet
TIMEOUT_S = 10.0
BIND_BUDGET_S = 2.5   # the whole binding, every paragraph: /slim-sheet waits on it, so a slow Jev leaves negatives unbound
NONE = "none"

_CACHE: "OrderedDict[str, dict[str, dict[str, list[str]]]]" = OrderedDict()
_CACHE_MAX = 128
SLOW_TTL_S = 60.0
_INFLIGHT: "dict[str, asyncio.Task]" = {}   # sheet key -> the binding still running for it
_SLOW: dict[str, float] = {}               # sheet key -> monotonic time until which a call does not wait for it


def clear_cache() -> None:
    _CACHE.clear()
    _SLOW.clear()
    for t in _INFLIGHT.values():
        if not t.done() and not t.get_loop().is_closed():
            t.cancel()
    _INFLIGHT.clear()


def bind_question(sentence: str, structures: list[str]) -> dict[str, Any]:
    crit = {f"s_{i}": s for i, s in enumerate(structures)}
    crit[NONE] = "It describes none of these structures alone, or several of them equally."
    return {"type": "choice",
            "instructions": f"Which structure of the PARAGRAPH does this normal report sentence describe: {sentence}",
            "criteria": crit}


async def _bind(region: str, structures: list[str], sentences: list[str], transport=None) -> tuple[dict[str, str], bool]:
    """(sentence -> structure for the sentences Jev binds at or above BIND_MIN, whether every question was
    answered), one call per paragraph."""
    qs = {f"q_{i}": bind_question(s, structures) for i, s in enumerate(sentences)}
    state = f"PARAGRAPH: {region}\nSTRUCTURES IT REPORTS: " + "; ".join(structures)
    r = await jev_post({"model": JEV_MODEL, "state": state, "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), TIMEOUT_S, transport)
    r.raise_for_status()
    ans = r.json().get("answers") or {}
    out: dict[str, str] = {}
    complete = all(isinstance(ans.get(f"q_{i}"), dict) for i in range(len(sentences)))
    for i, s in enumerate(sentences):
        a = ans.get(f"q_{i}") or {}
        c = a.get("choice")
        if not (isinstance(c, str) and c.startswith("s_") and c[2:].isdigit()) or int(c[2:]) >= len(structures):
            continue
        if float(a.get("confidence") or 0.0) >= BIND_MIN:
            out[s] = structures[int(c[2:])]
    return out, complete


async def _bind_all(asks: list, transport=None) -> tuple[dict[str, dict[str, str]], bool]:
    """(region -> sentence -> structure, whether any paragraph failed or was answered in part)."""
    got = await asyncio.gather(*(_bind(r, structs, ask, transport) for r, structs, ask in asks), return_exceptions=True)
    bound: dict[str, dict[str, str]] = {}
    failed = False
    for (region, _, _), g in zip(asks, got):
        if isinstance(g, BaseException):
            failed = True
            logger.warning("[stack.structures] %s: %s", type(g).__name__, str(g)[:200])
            continue
        bound[region], complete = g
        failed = failed or not complete
    return bound, failed


def _assemble(st: SheetStructure, split: dict, bound: dict[str, dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    offered = template_region_normals(st)
    out: dict[str, dict[str, list[str]]] = {}
    for region, (structs, fixed, _) in split.items():
        owner = {**bound.get(region, {}), **fixed}
        order = offered.get(region, [])
        groups: dict[str, list[str]] = {}
        for c in structs:
            mine = [t for t in order if owner.get(t) == c]
            if mine:
                groups.setdefault(label_case(c), []).extend(mine)
        if groups:
            out[region] = groups
    return out


def _finish(key: str, st: SheetStructure, split: dict, task: "asyncio.Task") -> None:
    """A binding ended (in time or after its caller stopped waiting): cache it when every question was answered."""
    if _INFLIGHT.get(key) is task:
        del _INFLIGHT[key]
    if task.cancelled():
        return
    if task.exception() is not None:
        logger.warning("[stack.structures] binding failed: %s", str(task.exception())[:200])
        return
    bound, failed = task.result()
    if failed:
        return
    _SLOW.pop(key, None)
    _CACHE[key] = _assemble(st, split, bound)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def structure_normals(st: SheetStructure, transport=None) -> dict[str, dict[str, list[str]]]:
    """Region -> {structure label -> its offered sentences}, for multi-structure findings paragraphs only, in COVERS
    order; a structure with no sentence is left out, and so is every sentence bound to none (the paragraph keeps
    it). Cached by sheet hash only when every Jev question was answered. A binding over BIND_BUDGET_S is not cut
    off: the caller gets the unbound split, the binding finishes in the background and caches itself, a call for
    the same sheet meanwhile joins it rather than asking again, and for SLOW_TTL_S after it ran over, a call does
    not wait for it at all (a slow Jev costs one wait per sheet, not one per /slim-sheet)."""
    key = f"{JEV_MODEL}:{st.sheet_hash}"
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return copy.deepcopy(_CACHE[key])
    split = template_structure_split(st)
    asks = [(region, structs, ask) for region, (structs, _, ask) in split.items() if ask]
    loop = asyncio.get_running_loop()
    task = _INFLIGHT.get(key)
    if task is None or task.get_loop() is not loop:
        task = loop.create_task(_bind_all(asks, transport))
        _INFLIGHT[key] = task
        task.add_done_callback(lambda t: _finish(key, st, split, t))
    now = time.monotonic()
    for k in [k for k, until in _SLOW.items() if until <= now]:
        del _SLOW[k]
    budget = 0.0 if key in _SLOW else BIND_BUDGET_S
    try:
        bound, _ = await asyncio.wait_for(asyncio.shield(task), budget)
    except asyncio.TimeoutError:
        if budget:
            _SLOW[key] = time.monotonic() + SLOW_TTL_S
            logger.warning("[stack.structures] binding over %.1fs: negatives stay with their paragraphs for now",
                           BIND_BUDGET_S)
        bound = {}
    return _assemble(st, split, bound)
