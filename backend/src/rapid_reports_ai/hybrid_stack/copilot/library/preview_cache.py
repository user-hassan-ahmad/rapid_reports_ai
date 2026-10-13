"""Pack settlements computed before the card is opened (library spec §12 next slice, item 3). /match starts the
settlement of every pack card it returns; /open and /preview await the same task, so opening a card is a cache hit
and the settle latency is hidden. The key holds no answer: the dictation is read once per (pack, finding, dictation,
history), and each answer re-runs only the engine over the cached settlement (pack_preview.finish), never the model
or Jev, so settled values cannot change between answers. Process-local, bounded (LRU, MAX_ENTRIES), never persisted;
the key holds clinical text and is never logged. Fail open: a failed settlement (an error or a timeout included,
through the caller's fallback) is cached too, so answers re-run only the engine over whatever settled; a fresh /open
may retry it once, and that result is kept."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Coroutine


logger = logging.getLogger(__name__)

MAX_ENTRIES = 256
TASK_TIMEOUT_S = 25.0                      # a hung preview ends here and leaves _RUNNING (as the route's own bound)
PREWARM_MAX = 8                            # concurrent prewarm tasks; over it /match skips and /open computes on demand
_C: "OrderedDict[tuple, tuple[asyncio.Task, bool]]" = OrderedDict()   # key -> (task, already retried)
_RUNNING: set[asyncio.Task] = set()        # strong refs, so an evicted task still finishes
_PREWARMING: set[asyncio.Task] = set()     # the running tasks /match started


def _t(s: str) -> str:
    return " ".join((s or "").split())


def key(pack_key: str, finding: str, findings: str, history: str) -> tuple:
    """Everything the settlement reads; never an answer. An empty finding stays empty: every lesion input is asked."""
    return (pack_key, _t(finding), _t(findings), _t(history))


def _usable(t: asyncio.Task, loop: asyncio.AbstractEventLoop) -> bool:
    """Running, or done with a result (a failed settlement included): never a task that raised or was cancelled."""
    if t.get_loop() is not loop or t.cancelled():
        return False
    return not t.done() or t.exception() is None


def _failed(t: asyncio.Task) -> bool:
    return t.done() and bool(getattr(t.result(), "failed", False))


def _done(t: asyncio.Task) -> None:
    _RUNNING.discard(t)
    _PREWARMING.discard(t)
    if not t.cancelled() and t.exception() is not None:   # the type only: a message may quote the dictation
        logger.warning("[library.cache] preview %s", type(t.exception()).__name__)


async def _run(make: Callable[[], Coroutine[Any, Any, Any]], fallback: Callable[[], Any] | None) -> Any:
    """The settlement, bounded by TASK_TIMEOUT_S; an error or a timeout gives fallback() (a failed settlement, which is
    cached like any other) when there is one, else raises."""
    try:
        return await asyncio.wait_for(make(), TASK_TIMEOUT_S)
    except Exception as ex:
        if fallback is None:
            raise
        logger.warning("[library.cache] preview %s", type(ex).__name__)   # the type only
        return fallback()


def start(k: tuple, make: Callable[[], Coroutine[Any, Any, Any]], prewarm: bool = False, retry: bool = False,
          fallback: Callable[[], Any] | None = None) -> asyncio.Task | None:
    """The cached task for this key while it is usable (running, or done with a result), else a new one. A failed
    settlement is served like any other, so an answer never settles again (review I3); only a caller passing
    `retry` (a fresh /open) may start it once more, and that second result is kept whatever it is. A prewarm over
    PREWARM_MAX running prewarms starts nothing (None): /open computes it."""
    loop = asyncio.get_running_loop()
    hit = _C.get(k)
    if hit is not None and _usable(hit[0], loop):
        t, retried = hit
        if not (retry and not retried and _failed(t)):
            _C.move_to_end(k)
            return t
        retried = True
    else:
        retried = False
    if prewarm and len(_PREWARMING) >= PREWARM_MAX:
        return None
    t = loop.create_task(_run(make, fallback))
    _RUNNING.add(t)
    if prewarm:
        _PREWARMING.add(t)
    t.add_done_callback(_done)
    _C[k] = (t, retried)
    _C.move_to_end(k)
    while len(_C) > MAX_ENTRIES:
        _C.popitem(last=False)
    return t


def peek(k: tuple) -> asyncio.Task | None:
    """The cached task for this key while it is usable, never a new one: Calculate (spec §7.7) starts no settle."""
    hit = _C.get(k)
    if hit is None or not _usable(hit[0], asyncio.get_running_loop()):
        return None
    _C.move_to_end(k)
    return hit[0]


def clear() -> None:
    """Forget every entry and running task (tests; the tasks themselves are left to finish or be collected)."""
    _C.clear()
    _RUNNING.clear()
    _PREWARMING.clear()
