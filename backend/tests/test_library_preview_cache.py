import asyncio

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import preview_cache as PC
from rapid_reports_ai.hybrid_stack.copilot.types import Preview

K = PC.key("p@1", "7 mm nodule.", "7 mm nodule. Liver normal.", "", {}, {})


def _maker(calls, out):
    async def make():
        calls.append(1)
        await asyncio.sleep(0)
        if isinstance(out, Exception):
            raise out
        return out
    return make


async def test_the_same_key_shares_one_preview():
    calls = []
    make = _maker(calls, Preview(missing=["x"]))
    a, b = PC.start(K, make), PC.start(K, make)
    assert a is b and (await a).missing == ["x"]
    assert (await PC.start(K, make)).missing == ["x"] and len(calls) == 1


def test_the_key_reads_every_input():
    base = ["p@1", "f", "d", "h", {"a": "1"}, {"age_years": "60"}]
    variants = [base, ["p@2", *base[1:]], ["p@1", "g", *base[2:]], [*base[:2], "e", *base[3:]],
                [*base[:3], "i", *base[4:]], [*base[:4], {"a": "2"}, base[5]], [*base[:5], {"age_years": "61"}]]
    assert len({PC.key(*v) for v in variants}) == len(variants)
    assert PC.key("p@1", "", "d", "h", {}, {}) != PC.key("p@1", "d", "d", "h", {}, {})   # no unit asks lesion inputs
    assert PC.key("p@1", "f  x\n", "d", "h", {}, {}) == PC.key("p@1", "f x", "d", "h", {}, {})


@pytest.mark.parametrize("first", [Preview(degraded=True), RuntimeError("boom")])
async def test_a_degraded_or_failed_preview_is_never_served_again(first):
    calls = []
    t = PC.start(K, _maker(calls, first))
    try:
        await t
    except RuntimeError:
        pass
    again = await PC.start(K, _maker(calls, Preview(missing=["fresh"])))
    assert again.missing == ["fresh"] and len(calls) == 2


async def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(PC, "MAX_ENTRIES", 2)
    calls = []
    for n in range(3):
        await PC.start(("k", n), _maker(calls, Preview()))
    await PC.start(("k", 0), _maker(calls, Preview()))          # evicted: computed again
    assert len(calls) == 4


async def test_a_hung_preview_times_out_and_leaves_the_running_set(monkeypatch):
    monkeypatch.setattr(PC, "TASK_TIMEOUT_S", 0.01)

    async def hang():
        await asyncio.sleep(60)
    t = PC.start(("hang",), hang)
    with pytest.raises(asyncio.TimeoutError):
        await t
    await asyncio.sleep(0)
    assert t not in PC._RUNNING


async def test_prewarm_is_capped_and_open_still_computes(monkeypatch):
    monkeypatch.setattr(PC, "PREWARM_MAX", 2)
    gate = asyncio.Event()
    calls = []

    def make(n):
        async def go():
            calls.append(n)
            await gate.wait()
            return Preview(missing=[str(n)])
        return go
    a, b = PC.start(("w", 1), make(1), prewarm=True), PC.start(("w", 2), make(2), prewarm=True)
    assert a is not None and b is not None and PC.start(("w", 3), make(3), prewarm=True) is None   # over the cap
    c = PC.start(("w", 3), make(3))                              # /open: never capped
    gate.set()
    assert (await c).missing == ["3"] and sorted(calls) == [1, 2, 3]
    await asyncio.gather(a, b)
    await asyncio.sleep(0)
    assert PC.start(("w", 4), make(4), prewarm=True) is not None    # done prewarms free their slots


async def test_a_failed_preview_logs_its_type_never_its_text(caplog):
    async def make():
        raise RuntimeError("7 mm nodule in Mrs Smith")
    t = PC.start(("x",), make)
    with pytest.raises(RuntimeError):
        await t
    await asyncio.sleep(0)
    assert "RuntimeError" in caplog.text and "Smith" not in caplog.text


async def test_clear_forgets_every_entry_and_running_task():
    gate = asyncio.Event()

    async def make():
        await gate.wait()
        return Preview()
    PC.start(("c",), make, prewarm=True)
    PC.clear()
    assert not PC._C and not PC._RUNNING and not PC._PREWARMING
    gate.set()
