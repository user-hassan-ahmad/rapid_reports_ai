"""Pack previews computed before the card is opened (library spec §12 next slice, item 3). /match starts the preview
of every pack card it returns; /open and /preview await the same task, so opening a card is a cache hit and the
settle latency is hidden. Process-local, bounded (LRU, MAX_ENTRIES), never persisted; the key holds clinical text
(finding, dictation, history) and is never logged. Fail open: a failed or degraded preview reaches the caller once
and is never served again."""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any, Callable, Coroutine

from ..types import Preview

logger = logging.getLogger(__name__)

MAX_ENTRIES = 256
_C: "OrderedDict[tuple, asyncio.Task]" = OrderedDict()
_RUNNING: set[asyncio.Task] = set()        # strong refs, so an evicted task still finishes


def _t(s: str) -> str:
    return " ".join((s or "").split())


def key(pack_key: str, finding: str, findings: str, history: str, answered: dict[str, str],
        patient: dict[str, str]) -> tuple:
    """Everything the preview reads. An empty finding is the whole dictation, as in preview_pack."""
    return (pack_key, _t(finding) or _t(findings), _t(findings), _t(history), tuple(sorted(answered.items())),
            tuple(sorted(patient.items())))


def _good(t: asyncio.Task, loop: asyncio.AbstractEventLoop) -> bool:
    if t.get_loop() is not loop or t.cancelled():
        return False
    if not t.done():
        return True
    if t.exception() is not None:
        return False
    r = t.result()
    return isinstance(r, Preview) and not r.degraded


def _done(t: asyncio.Task) -> None:
    _RUNNING.discard(t)
    if not t.cancelled() and t.exception() is not None:
        ex = t.exception()
        logger.warning("[library.cache] preview %s: %s", type(ex).__name__, str(ex)[:200])


def start(k: tuple, make: Callable[[], Coroutine[Any, Any, Preview]]) -> asyncio.Task:
    """The cached task for this key while it is good (running, or done with a full preview), else a new one."""
    loop = asyncio.get_running_loop()
    t = _C.get(k)
    if t is not None and _good(t, loop):
        _C.move_to_end(k)
        return t
    t = loop.create_task(make())
    _RUNNING.add(t)
    t.add_done_callback(_done)
    _C[k] = t
    _C.move_to_end(k)
    while len(_C) > MAX_ENTRIES:
        _C.popitem(last=False)
    return t


def clear() -> None:
    _C.clear()
