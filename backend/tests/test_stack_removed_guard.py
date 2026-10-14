import pytest

from rapid_reports_ai.hybrid_stack import removed_guard as RG
from rapid_reports_ai.hybrid_stack.jev_stack import RowCheck


def _rows(scores):
    async def fake(dictation, sentences, removed, transport=None, *, stated=True, contra=True):
        return [RowCheck(*scores.get(s, (0.0, 0.0, 0.0))) for s in sentences]
    return fake


@pytest.mark.asyncio
async def test_reconcile_keeps_a_removed_sentence_the_units_state(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"No effusion.": (0.95, 0.0, 0.0)}))
    still, dropped = await RG.reconcile(["No effusion.", "No ascites."], "There is no effusion.")
    assert still == ["No ascites."] and dropped == ["No effusion."]


@pytest.mark.asyncio
async def test_reconcile_keeps_every_removal_when_jev_fails(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("jev down")
    monkeypatch.setattr(RG, "ask_rows", boom)
    assert await RG.reconcile(["No ascites."], "x") == (["No ascites."], [])


@pytest.mark.asyncio
async def test_guard_removes_the_exact_removed_sentence(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"No ascites.": (0.0, 0.0, 0.9)}))
    report, edits, items = await RG.guard("FINDINGS\nLiver normal. No ascites.\n", ["No ascites."], "Liver normal.")
    assert report == "FINDINGS\nLiver normal.\n"
    assert edits == [{"type": "removal", "clause": "No ascites."}] and items == []


@pytest.mark.asyncio
async def test_guard_flags_a_reworded_assertion(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"There is no free fluid.": (0.0, 0.0, 0.9)}))
    report, edits, items = await RG.guard("Liver normal. There is no free fluid.", ["No ascites."], "Liver normal.")
    assert "There is no free fluid." in report and edits == []
    assert items[0]["kind"] == "removed_asserted" and items[0]["severity"] == "high"


@pytest.mark.asyncio
async def test_guard_keeps_an_exact_sentence_the_statements_support(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"No ascites.": (0.9, 0.0, 0.9)}))
    report, edits, items = await RG.guard("No ascites.", ["No ascites."], "No ascites.")
    assert report == "No ascites." and edits == [] and items[0]["kind"] == "removed_asserted"


@pytest.mark.asyncio
async def test_guard_jev_failure_flags_and_keeps_report(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("jev down")
    monkeypatch.setattr(RG, "ask_rows", boom)
    report, edits, items = await RG.guard("Liver normal. No ascites.", ["No ascites."], "Liver normal.")
    assert report == "Liver normal. No ascites." and edits == []
    assert items == [{"kind": "removed_unverified", "severity": "medium",
                      "message": "Couldn't verify removed sentences"}]


@pytest.mark.asyncio
async def test_reconcile_exact_redictation_wins_without_jev(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("jev down")
    monkeypatch.setattr(RG, "ask_rows", boom)
    still, dropped = await RG.reconcile(["No ascites."], "Liver normal. No ascites.")
    assert still == [] and dropped == ["No ascites."]


@pytest.mark.asyncio
async def test_guard_cuts_a_list_item_and_its_line(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"- No ascites.": (0.0, 0.0, 0.9)}))
    report, edits, items = await RG.guard("FINDINGS\n- Liver normal.\n- No ascites.\nIMPRESSION\nNormal.",
                                          ["No ascites."], "Liver normal.")
    assert report == "FINDINGS\n- Liver normal.\nIMPRESSION\nNormal." and items == []


@pytest.mark.asyncio
async def test_guard_cut_at_line_start_leaves_no_leading_space(monkeypatch):
    monkeypatch.setattr(RG, "ask_rows", _rows({"No ascites.": (0.0, 0.0, 0.9)}))
    report, _, _ = await RG.guard("No ascites. Liver normal.", ["No ascites."], "Liver normal.")
    assert report == "Liver normal."


@pytest.mark.asyncio
async def test_guard_short_jev_reply_is_a_failure(monkeypatch):
    async def short(dictation, sentences, removed, transport=None, *, stated=True, contra=True):
        return [RowCheck(0.0, 0.0, 0.9)]
    monkeypatch.setattr(RG, "ask_rows", short)
    report, edits, items = await RG.guard("Liver normal. No ascites.", ["No ascites."], "Liver normal.")
    assert edits == [] and items[0]["kind"] == "removed_unverified"
