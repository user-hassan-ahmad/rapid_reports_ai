"""Pack settlements computed before the card is opened (library spec §12 next slice, item 3). /match starts the
settlement of every pack card it returns; /open and /preview await the same task, so opening a card is a cache hit
and the settle latency is hidden. The key holds no answer: the dictation is read once per (pack, finding, dictation,
history), and each answer re-runs only the engine over the cached settlement (pack_preview.finish), never the model
or Jev, so settled values cannot change between answers. Process-local, bounded (LRU, MAX_ENTRIES), never persisted;
the key holds clinical text and is never logged. Fail open: a failed settlement (or an error) reaches the caller once
and is never served again; one with no finding unit is deterministic and is."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Coroutine


logger = logging.getLogger(__name__)

MAX_ENTRIES = 256
TASK_TIMEOUT_S = 25.0                      # a hung preview ends here and leaves _RUNNING (as the route's own bound)
PREWARM_MAX = 8                            # concurrent prewarm tasks; over it /match skips and /open computes on demand
_C: "OrderedDict[tuple, asyncio.Task]" = OrderedDict()
_RUNNING: set[asyncio.Task] = set()        # strong refs, so an evicted task still finishes
_PREWARMING: set[asyncio.Task] = set()     # the running tasks /match started


def _t(s: str) -> str:
    return " ".join((s or "").split())


def key(pack_key: str, finding: str, findings: str, history: str) -> tuple:
    """Everything the settlement reads; never an answer. An empty finding stays empty: every lesion input is asked."""
    return (pack_key, _t(finding), _t(findings), _t(history))


def _good(t: asyncio.Task, loop: asyncio.AbstractEventLoop) -> bool:
    if t.get_loop() is not loop or t.cancelled():
        return False
    if not t.done():
        return True
    if t.exception() is not None:
        return False
    return getattr(t.result(), "failed", None) is False


def _done(t: asyncio.Task) -> None:
    _RUNNING.discard(t)
    _PREWARMING.discard(t)
    if not t.cancelled() and t.exception() is not None:   # the type only: a message may quote the dictation
        logger.warning("[library.cache] preview %s", type(t.exception()).__name__)


def start(k: tuple, make: Callable[[], Coroutine[Any, Any, Any]], prewarm: bool = False) -> asyncio.Task | None:
    """The cached task for this key while it is good (running, or done and not failed), else a new one, bounded
    by TASK_TIMEOUT_S. A prewarm over PREWARM_MAX running prewarms starts nothing (None): /open computes it."""
    loop = asyncio.get_running_loop()
    t = _C.get(k)
    if t is not None and _good(t, loop):
        _C.move_to_end(k)
        return t
    if prewarm and len(_PREWARMING) >= PREWARM_MAX:
        return None
    t = loop.create_task(asyncio.wait_for(make(), TASK_TIMEOUT_S))
    _RUNNING.add(t)
    if prewarm:
        _PREWARMING.add(t)
    t.add_done_callback(_done)
    _C[k] = t
    _C.move_to_end(k)
    while len(_C) > MAX_ENTRIES:
        _C.popitem(last=False)
    return t


def clear() -> None:
    """Forget every entry and running task (tests; the tasks themselves are left to finish or be collected)."""
    _C.clear()
    _RUNNING.clear()
    _PREWARMING.clear()
