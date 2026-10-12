from rapid_reports_ai.hybrid_stack.copilot import recs as Rc


async def test_suggestions_capped_and_deduped_against_applied(monkeypatch):
    async def call(prompt):
        assert "APPLIED" in prompt
        return Rc.RawRecs(items=["Refer to the urology MDT.", "CT chest at 6-12 months.", "a", "b", "c", "d"])
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "findings", "conclusion", ["CT chest at 6-12 months"])
    assert out.items[0] == "Refer to the urology MDT." and "CT chest at 6-12 months." not in out.items
    assert len(out.items) <= Rc.MAX_ITEMS


async def test_failure_returns_empty(monkeypatch):
    async def call(prompt):
        raise RuntimeError("x")
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "f", "", [])
    assert out.items == [] and out.error
