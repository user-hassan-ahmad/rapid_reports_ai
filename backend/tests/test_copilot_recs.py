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


async def test_numbers_and_bullets_are_cleaned(monkeypatch):
    async def call(prompt):
        assert "Never restate the clinical history." in Rc.RECS_SYS
        return Rc.RawRecs(items=["1. Refer to the hepatobiliary MDT.", "- Compare with prior imaging.",
                                 "• MRI liver in six months.", "Repeat in half a year.", "CT in 3 months.",
                                 "Review twenty-four hour urine.", "(b) Correlate with tumour markers."])
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "f", "", [])
    assert out.items == ["Refer to the hepatobiliary MDT.", "Compare with prior imaging.",
                         "Correlate with tumour markers."]


async def test_someone_is_not_a_number(monkeypatch):
    async def call(prompt):
        return Rc.RawRecs(items=["Discuss with someone at the thoracic MDT.", "Bone scan if one is not already planned."])
    monkeypatch.setattr(Rc, "_call", call)
    out = await Rc.suggest("CT", "", "f", "", [])
    assert out.items == ["Discuss with someone at the thoracic MDT."]
