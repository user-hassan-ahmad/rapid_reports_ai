from rapid_reports_ai.hybrid_stack import chips as C
from rapid_reports_ai.report_reconcile import FallbackItem, FallbackNegatives


def _fb(*lists):
    async def fake(state, items, keys):
        assert keys == []
        return FallbackNegatives(items=[FallbackItem(index=i, covered=False, negatives=n) for i, n in enumerate(lists)])
    return fake


async def _stated_none(dictation, chips):
    return [0.0] * len(chips)


async def test_flattens_dedupes_and_caps_at_three(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No free gas.", "No abscess."], ["no free gas", "No fistula.", "No obstruction."]))
    monkeypatch.setattr(C, "ask_stated", _stated_none)
    out = await C.suggest("CT AP", "", "Bowel", ["Sigmoid diverticulitis.", "Wall thickening."], "Sigmoid diverticulitis.")
    assert out.chips == ["No free gas.", "No abscess.", "No fistula."]
    assert out.cached is False and out.error is None


async def test_drops_what_the_dictation_says_and_what_jev_calls_stated(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No free gas.", "No abscess.", "No fistula."]))

    async def stated(dictation, chips):
        return [0.9 if c == "No fistula." else 0.1 for c in chips]
    monkeypatch.setattr(C, "ask_stated", stated)
    out = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis. No free gas.")
    assert out.chips == ["No abscess."]


async def test_cache_and_fail_open(monkeypatch):
    C.clear_cache()
    calls = []

    async def fb(state, items, keys):
        calls.append(1)
        return FallbackNegatives(items=[FallbackItem(index=0, covered=False, negatives=["No abscess."])])
    monkeypatch.setattr(C, "_fallback", fb)
    monkeypatch.setattr(C, "ask_stated", _stated_none)
    a = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis.")
    b = await C.suggest("ct  ap", "", "Bowel", [" Diverticulitis. "], "Diverticulitis.")
    assert a.chips == b.chips == ["No abscess."] and b.cached and len(calls) == 1

    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(C, "_fallback", boom)
    out = await C.suggest("CT AP", "", "Liver", ["Cyst."], "Cyst.")
    assert out.chips == [] and "RuntimeError" in out.error


async def test_stated_check_failure_keeps_chips(monkeypatch):
    C.clear_cache()
    monkeypatch.setattr(C, "_fallback", _fb(["No abscess."]))

    async def boom(*a, **k):
        raise RuntimeError("jev down")
    monkeypatch.setattr(C, "ask_stated", boom)
    out = await C.suggest("CT AP", "", "Bowel", ["Diverticulitis."], "Diverticulitis.")
    assert out.chips == ["No abscess."]
