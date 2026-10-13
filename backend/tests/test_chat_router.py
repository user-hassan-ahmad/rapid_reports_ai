"""The chat-edit router end to end with fake Jev and fake targeted calls (spec "Testing", unit)."""
import pytest

from rapid_reports_ai import chat_router as R
from rapid_reports_ai import chat_router_calls as C
from rapid_reports_ai import chat_router_changes as CH
from rapid_reports_ai import chat_router_jev as J
from rapid_reports_ai import chat_router_ledger as L
from tests.template_sheet_fixtures import ROUTER_SHEET


@pytest.fixture(autouse=True)
def no_unit_checks(monkeypatch):
    from rapid_reports_ai import template_sheet_save as S

    async def none(structure, sheet):
        return []
    monkeypatch.setattr(S, "check_units", none)


def tags(**scores):
    return {k: scores.get(k, 0.0) for k in J.KINDS}


@pytest.fixture
def fake(monkeypatch):
    state = {"tags": tags(), "calls": {}, "requires": {}, "seen": []}

    async def tag(instruction, scan_type="", context="", transport=None):
        if isinstance(state["tags"], Exception):
            raise state["tags"]
        return state["tags"]

    async def call_kind(kind, instruction, view, context="", rejection=None):
        state["seen"].append((kind, instruction))
        r = state["calls"].get(kind)
        if isinstance(r, Exception):
            raise r
        return r if r is not None else CH.OUTPUTS[kind]()

    async def requires(lines, transport=None):
        if isinstance(state["requires"], Exception):
            raise state["requires"]
        return [state["requires"].get(l, 0.0) for l in lines]

    monkeypatch.setattr(J, "tag", tag)
    monkeypatch.setattr(C, "call_kind", call_kind)
    monkeypatch.setattr(J, "requires", requires)
    return state


async def test_a_failed_tag_call_falls_back(fake):
    fake["tags"] = TimeoutError()
    with pytest.raises(R.Fallback):
        await R.route_turn(ROUTER_SHEET, [], "drop width")


async def test_misfit_or_no_kind_asks_and_changes_nothing(fake):
    fake["tags"] = tags(misfit=0.9, value=0.8)
    t = await R.route_turn(ROUTER_SHEET, [], "add the weather")
    assert not t.applied and t.sheet == ROUTER_SHEET and "Router test" in t.reply and fake["seen"] == []
    fake["tags"] = tags(value=0.2)
    t = await R.route_turn(ROUTER_SHEET, [], "hmm")
    assert not t.applied and "What should they do differently?" in t.reply
    assert t.evidence["route"] == "ask"


async def test_a_value_change_is_applied_through_the_ledger(fake):
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.reply == "Width is no longer required."
    assert t.claim == "Width is no longer required." and t.records[0]["type"] == "ledger"
    width = L.entry(t.ledger, "value", "Width")
    assert width["choice"] == {"need": "not_needed"} and width["source"] == "chat"
    assert [k for k, _ in fake["seen"]] == ["value"]


async def test_a_mixed_instruction_applies_each_tagged_kind(fake):
    fake["tags"] = tags(value=0.9, fixed=0.8)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["fixed"] = CH.FixedOut(changes=[CH.FixedChange(to="remove", line="No previous imaging available.")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and stop printing no previous imaging")
    assert t.applied and "No previous imaging available." not in t.sheet and 'LIST_MISSING ["Depth"]' in t.sheet
    assert sorted(k for k, _ in fake["seen"]) == ["fixed", "value"]
    assert t.reply.splitlines() == ["Width is no longer required.", '"No previous imaging available." is no longer printed.']


async def test_an_unsure_tag_lets_the_call_decide_and_marks_the_route(fake):
    fake["tags"] = tags(value=0.4)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "width maybe")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and not t.cards
    assert L.entry(t.ledger, "value", "Width")["route"] == "llm_unsure"
    assert t.records[0]["route"] == "llm_unsure" and t.evidence["changes"][0]["route"] == "llm_unsure"
    assert t.evidence["unsure"] == ["value"]


async def test_an_unsure_call_that_decides_nothing_changes_nothing(fake):
    fake["tags"] = tags(value=0.4)
    t = await R.route_turn(ROUTER_SHEET, [], "width maybe")
    assert not t.applied and t.records == [] and t.reply == "No change was needed."


async def test_applied_only_when_the_sheet_or_ledger_changed(fake, monkeypatch):
    async def same(sheet, previous, ledger):
        return L.Saved("unchanged", previous, [], "")
    monkeypatch.setattr(L, "save", same)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert not t.applied and t.records == [] and t.claim == ""


async def test_unmatched_decisions_are_surfaced(fake, monkeypatch):
    real = L.save

    async def with_unmatched(sheet, previous, ledger):
        out = await real(sheet, previous, ledger)
        out.unmatched = [{"kind": "normal", "key": "Gone :: x"}]
        return out
    monkeypatch.setattr(L, "save", with_unmatched)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert t.applied and t.unmatched == [{"kind": "normal", "key": "Gone :: x"}] and R.UNMATCHED_LINE in t.reply


async def test_an_explicit_removal_of_a_confirmed_concept_is_applied_and_named(fake):
    led, _ = L.set_choice([], "concept", "comparison",
                          L.concept_choice("used", "No previous imaging available.", "Compared with the {study} of {date}."))
    fake["tags"] = tags(concept=0.9)
    fake["calls"]["concept"] = CH.ConceptOut(changes=[CH.ConceptChange(concept="comparison", state="not_used")])
    t = await R.route_turn(ROUTER_SHEET, led, "never mention comparison")
    assert t.applied and "This changes something you confirmed" in t.reply and t.records
    assert L.concept_state(L.entry(t.ledger, "concept", "comparison")["choice"])[0] == "not_used"


async def test_a_failed_targeted_call_leaves_the_other_parts_applied(fake):
    fake["tags"] = tags(value=0.9, normal=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["normal"] = TimeoutError()
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and reword the alpha normal")
    assert t.applied and "Width is no longer required." in t.reply
    assert "I couldn't change the normal findings just now" in t.reply and t.evidence["failed"] == ["normal"]
    assert "TimeoutError" not in t.reply


async def test_invented_wording_cards_that_part_and_applies_the_rest(fake):
    fake["tags"] = tags(value=0.9, normal=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", structure="alpha",
                                                                    to="reword", text="Alpha looks fine.")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and make the alpha normal friendlier")
    assert t.applied and "Alpha is normal." in t.sheet and t.cards[0]["ledger_kind"] == "normal"
    assert t.evidence["changes"][1]["invented"] is True


async def test_a_paragraph_rename_rekeys_the_ledger(fake):
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is normal."})
    fake["tags"] = tags(layout=0.9)
    fake["calls"]["layout"] = CH.LayoutOut(changes=[CH.LayoutChange(op="rename_paragraph", target="Upper", name="Top")])
    t = await R.route_turn(ROUTER_SHEET, led, "call the upper paragraph Top")
    assert "## Paragraph: Top (FINDINGS)" in t.sheet and L.entry(t.ledger, "normal", L.normal_key("Top", "alpha"))
    assert t.records[0]["inverse"] == [{"op": "rename_paragraph", "paragraph": "Top", "to": "Upper"}]


async def test_a_change_to_a_confirmed_item_says_so(fake):
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Width", {"need": "every"})  # re-confirmed
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, led, "drop width")
    assert "This changes something you confirmed" in t.reply


async def test_a_refused_save_keeps_the_previous_sheet_and_ledger(fake, monkeypatch):
    async def refuse(sheet, previous, ledger):
        return L.Saved("refused", previous, ledger, "Couldn't apply: it would break the template.")
    monkeypatch.setattr(L, "save", refuse)
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert not t.applied and t.refused and t.sheet == ROUTER_SHEET and t.ledger == [] and t.reply.startswith("Couldn't")


async def test_a_clarification_after_a_rejection_may_use_the_original_wording(fake):
    fake["tags"] = tags(value=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Height", to="every")])
    t = await R.route_turn(ROUTER_SHEET, [], "no, in every report",
                           rejection={"original_instruction": "always give the height", "rejected_claim": "x"})
    assert t.applied and L.entry(t.ledger, "value", "Height")["choice"] == {"need": "every"}
