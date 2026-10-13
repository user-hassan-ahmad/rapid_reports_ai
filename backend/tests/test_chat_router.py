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
        if state.get("requires_fn"):
            return await state["requires_fn"](lines)
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


async def test_misfit_asks_and_changes_nothing(fake):
    fake["tags"] = tags(misfit=0.9, value=0.8)
    t = await R.route_turn(ROUTER_SHEET, [], "add the weather")
    assert not t.applied and t.sheet == ROUTER_SHEET and "Router test" in t.reply and fake["seen"] == []
    assert t.evidence["route"] == "ask"


async def test_no_kind_at_the_threshold_takes_todays_refine(fake):
    """Hassan 2026-10-13 (supersedes D-R2): only tags >= 0.5 route; the 0.35-0.5 band is not routed at all."""
    fake["tags"] = tags(value=0.45, normal=0.49)
    with pytest.raises(R.Fallback) as e:
        await R.route_turn(ROUTER_SHEET, [], "width maybe")
    assert str(e.value) == "no_tag" and fake["seen"] == []


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


async def test_a_kind_below_the_threshold_is_not_called_when_another_routes(fake):
    fake["tags"] = tags(value=0.9, normal=0.45)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    t = await R.route_turn(ROUTER_SHEET, [], "drop width")
    assert [k for k, _ in fake["seen"]] == ["value"] and "route" not in L.entry(t.ledger, "value", "Width")
    assert "route" not in t.records[0] and "unsure" not in t.evidence


async def test_a_call_that_decides_nothing_changes_nothing(fake):
    fake["tags"] = tags(value=0.9)
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


NEW_IC = "Lead with the main finding in one sentence."


async def test_a_style_edit_touches_prose_only(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)],
                                         summary="The impression will be one sentence.")
    t = await R.route_turn(ROUTER_SHEET, [], "make the impression more concise")
    assert t.applied and NEW_IC in t.sheet and "Keep it brief." not in t.sheet
    assert t.records[0] == {"type": "style", "claim": "The impression will be one sentence.",
                            "blocks": [{"before": "Lead with the most important finding.\nKeep it brief.",
                                        "after": NEW_IC}]}
    assert t.reply == "The impression will be one sentence." and t.evidence["style"] == "applied"


async def test_a_style_edit_that_changes_a_unit_line_is_rejected(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text='NORMAL [alpha] "Alpha is fine."')])
    t = await R.route_turn(ROUTER_SHEET, [], "tone it down")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == R.STYLE_TOUCHED_RULES


async def test_a_rule_in_disguise_is_left_out_and_rerouted_to_a_card(fake):
    hidden = "Always state the alpha size."
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=f"{NEW_IC}\n{hidden}")],
                                         summary="The impression will be one sentence.")
    fake["requires"] = {hidden: 0.9, NEW_IC: 0.1}
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", structure="alpha", to="reword",
                                                                    text="Alpha is normal in size.")])
    t = await R.route_turn(ROUTER_SHEET, [], "shorter impression, and always mention the alpha size")
    assert t.applied and NEW_IC in t.sheet and hidden not in t.sheet
    assert t.cards and t.cards[0]["ledger_kind"] == "normal"
    assert ("normal", f'Every report should state: "{hidden}"') in fake["seen"]
    assert t.evidence["disguise"] == [{"line": NEW_IC, "score": 0.1}, {"line": hidden, "score": 0.9}]


async def test_a_disguised_line_with_no_rule_kind_asks(fake):
    hidden = "Always state the alpha size."
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text=hidden)], summary="x")
    fake["requires"] = {hidden: 0.9}
    t = await R.route_turn(ROUTER_SHEET, [], "always mention the alpha size")
    assert not t.applied and "Which part of the report should state it?" in t.reply


async def test_a_failed_requires_check_leaves_the_style_out(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="x")
    fake["requires"] = TimeoutError()
    t = await R.route_turn(ROUTER_SHEET, [], "shorter")
    assert not t.applied and t.reply == R.REQUIRES_FAILED


async def test_a_style_tag_below_the_threshold_alone_takes_todays_refine(fake):
    fake["tags"] = tags(style=0.4)
    with pytest.raises(R.Fallback):
        await R.route_turn(ROUTER_SHEET, [], "maybe shorter")


async def test_a_style_edit_with_a_miscased_unit_line_is_rejected_by_the_grammar_guard(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text='Normal [alpha] "Alpha is fine."')])
    t = await R.route_turn(ROUTER_SHEET, [], "tone it down")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == R.STYLE_TOUCHED_RULES


async def _turn(fake, kind, out, instruction, ledger=None):
    fake["tags"] = tags(**{kind: 0.9})
    fake["calls"][kind] = out
    return await R.route_turn(ROUTER_SHEET, ledger or [], instruction)


async def test_undo_reverses_a_ledger_turn(fake):
    t = await _turn(fake, "value", CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")]), "drop width")
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert u.applied and 'LIST_MISSING ["Width" | "Depth"]' in u.sheet
    assert L.entry(u.ledger, "value", "Width")["choice"] == {"need": "every"}
    assert u.reply == "Undone: Width is no longer required." and u.evidence["route"] == "undo"


async def test_undo_reverses_a_layout_edit_and_its_rekey(fake):
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is normal."})
    t = await _turn(fake, "layout", CH.LayoutOut(changes=[CH.LayoutChange(op="rename_paragraph", target="Upper",
                                                                           name="Top")]), "call it Top", led)
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert "## Paragraph: Upper (FINDINGS)" in u.sheet and L.entry(u.ledger, "normal", L.normal_key("Upper", "alpha"))


async def test_undo_reverses_a_fixed_reword_and_its_decided_entry(fake):
    led, _ = L.set_choice([], "fixed", "Axial images were acquired.", {"keep": "always"})
    t = await _turn(fake, "fixed", CH.FixedOut(changes=[CH.FixedChange(
        to="reword", line="Axial images were acquired.", text="Axial and coronal images were acquired.")]),
        "say Axial and coronal images were acquired.", led)
    assert L.entry(t.ledger, "fixed", "Axial and coronal images were acquired.") is not None
    assert [r["type"] for r in t.records] == ["edit", "ledger"]
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert 'FIXED "Axial images were acquired."' in u.sheet
    assert L.entry(u.ledger, "fixed", "Axial images were acquired.")["choice"] == {"keep": "always"}
    assert L.entry(u.ledger, "fixed", "Axial and coronal images were acquired.") is None


async def test_undo_puts_back_validated_dropped_entries_only(fake):
    # a decision confirmed at creation (not by chat): undo must bring it back as it was
    led = L.clean([{"kind": "normal", "key": L.normal_key("Lower", "gamma"), "choice": {"text": "Gamma is fine."},
                    "by": "radiologist", "at": "2026-10-01T09:00:00+00:00", "source": "creation"}])
    original = L.entry(led, "normal", L.normal_key("Lower", "gamma"))
    t = await _turn(fake, "layout", CH.LayoutOut(changes=[CH.LayoutChange(op="remove_paragraph", target="Lower")]),
                    "remove the lower paragraph", led)
    assert L.entry(t.ledger, "normal", L.normal_key("Lower", "gamma")) is None
    tampered = [{**t.records[0], "dropped": [*t.records[0]["dropped"],
                                             {"kind": "value", "key": 'a "b"', "choice": {"need": "every"}}]}]
    u = await R.undo_turn(t.sheet, t.ledger, tampered)
    assert "## Paragraph: Lower (FINDINGS)" in u.sheet
    restored = L.entry(u.ledger, "normal", L.normal_key("Lower", "gamma"))
    assert restored["choice"] == {"text": "Gamma is fine."}
    assert restored == original and restored["source"] == "creation"   # the original entry whole
    assert not any(e["kind"] == "value" for e in u.ledger)


async def test_undo_restores_the_previous_prose(fake):
    fake["requires"] = {}
    t = await _turn(fake, "style", CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="Shorter."),
                    "shorter")
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert "Keep it brief." in u.sheet and NEW_IC not in u.sheet


async def test_undo_leaves_what_a_later_turn_changed(fake):
    t = await _turn(fake, "value", CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")]), "drop width")
    led, _ = L.set_choice(t.ledger, "value", "Width", {"need": "relevant"})
    u = await R.undo_turn(t.sheet, led, t.records)
    assert not u.applied and u.reply.startswith("Nothing to undo") and u.evidence["skipped"] == 1


async def test_answer_card_writes_the_ledger_as_chat():
    t = await R.answer_card(ROUTER_SHEET, [], {"kind": "value", "key": "Width", "choice": {"need": "not_needed"}})
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and t.reply == "Width is no longer required."
    assert L.entry(t.ledger, "value", "Width")["source"] == "chat" and t.evidence["route"] == "card"


async def test_answer_card_applies_a_proposal():
    apply = {"kind": "fixed", "key": "Axial images were obtained.", "choice": None,
             "op": {"op": "fixed_reword", "line": "Axial images were acquired.", "text": "Axial images were obtained."},
             "claim": '"Axial images were acquired." now reads "Axial images were obtained."'}
    t = await R.answer_card(ROUTER_SHEET, [], {"proposal": apply})
    assert t.applied and 'FIXED "Axial images were obtained."' in t.sheet and t.records[0]["type"] == "edit"


async def test_answer_card_refuses_what_code_cannot_apply_without_internal_text():
    t = await R.answer_card(ROUTER_SHEET, [], {"kind": "value", "key": 'a "bad" name', "choice": {"need": "every"}})
    assert not t.applied and t.sheet == ROUTER_SHEET and t.reply == R.CARD_REJECTED
    assert "short plain name" in t.evidence["detail"]


def test_response_and_the_kill_switch_defaults_off(monkeypatch):
    t = R.Turn("S", [{"kind": "value"}], True, "Done.", claim="c", records=[{"type": "ledger"}], cards=[{"id": "x"}])
    assert R.response(t) == {"success": True, "skill_sheet": "S", "response": "Done.", "behavioral_claim": "c",
                             "applied": True, "route": "router", "changes": [{"type": "ledger"}],
                             "cards": [{"id": "x"}], "decisions": [{"kind": "value"}], "unmatched": []}
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_CHAT_ROUTER", raising=False)
    assert not R.enabled()                                  # D-R3: off unless switched on
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    assert R.enabled()
    monkeypatch.setenv("RR_CHAT_ROUTER", "0")
    assert not R.enabled()
    monkeypatch.setenv("RR_CHAT_ROUTER", "1")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert not R.enabled()


async def test_a_forget_card_removes_the_entry_and_undo_puts_it_back():
    led, _ = L.set_choice([], "normal", L.normal_key("Gone", "x"), {"text": "X is normal."})
    t = await R.answer_card(ROUTER_SHEET, led, {"kind": "normal", "key": L.normal_key("Gone", "x"), "choice": L.FORGET})
    assert t.applied and L.entry(t.ledger, "normal", L.normal_key("Gone", "x")) is None
    assert t.reply == f"Forgot this decision: {L.normal_key('Gone', 'x')}."
    u = await R.undo_turn(t.sheet, t.ledger, t.records)
    assert L.entry(u.ledger, "normal", L.normal_key("Gone", "x"))["choice"] == {"text": "X is normal."}
    none = await R.answer_card(ROUTER_SHEET, [], {"kind": "value", "key": "Width", "choice": L.FORGET})
    assert not none.applied and none.reply == "No change was needed."


async def test_answer_card_checks_a_client_sent_proposal():
    t = await R.answer_card(ROUTER_SHEET, [], {"proposal": {
        "kind": "fixed", "key": "x", "choice": None, "claim": "x",
        "op": {"op": "unit_drop", "keyword": "FIXED", "text": "Axial images were acquired."}}})
    assert not t.applied and t.sheet == ROUTER_SHEET and "unit_drop" not in t.reply


# ── review fixes (Tasks 6-11): cost caps and the style-undo guard ─────────────────────────────────────────────────
import asyncio


async def test_at_most_eight_new_prose_lines_are_checked_and_the_rest_left_out(fake):
    lines = [f"Line number {i} is short." for i in range(10)]
    asked = []

    async def requires(ls, transport=None):
        asked.extend(ls)
        return [0.0 for _ in ls]
    fake["tags"] = tags(style=0.9)
    keep = "Lead with the most important finding.\nKeep it brief."   # nothing deleted: only the cap is under test
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=keep + "\n" + "\n".join(lines))],
                                         summary="Longer.")
    fake["requires_fn"] = requires
    t = await R.route_turn(ROUTER_SHEET, [], "add guidance")
    assert len(asked) == R.MAX_REQUIRES_LINES == 8
    assert "Line number 7 is short." in t.sheet and "Line number 8 is short." not in t.sheet
    assert R.CAPPED_LINE in t.reply and t.evidence["truncated"]["requires"] == 2


async def test_at_most_three_flagged_lines_are_rerouted(fake):
    lines = [f"Always state item {i}." for i in range(5)]
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text="\n".join(lines))], summary="x")
    fake["requires"] = {l: 0.9 for l in lines}
    t = await R.route_turn(ROUTER_SHEET, [], "always state items")
    rerouted = {i for k, i in fake["seen"] if k == "normal"}
    assert len(rerouted) == R.MAX_REROUTES == 3
    assert t.evidence["truncated"]["reroutes"] == 2 and t.reply.count("Which part of the report should state it?") == 5


async def test_at_most_ten_changes_per_call_are_used(fake):
    fake["tags"] = tags(value=0.9)
    names = [f"Size {i}" for i in range(12)]
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name=n, to="every") for n in names])
    t = await R.route_turn(ROUTER_SHEET, [], "always give " + ", ".join(names))
    assert len(t.evidence["changes"]) == R.MAX_CHANGES_PER_CALL == 10
    assert t.evidence["truncated"]["changes"] == {"value": 2}


async def test_a_turn_past_its_deadline_applies_what_is_done(fake, monkeypatch):
    monkeypatch.setattr(R, "TURN_TIMEOUT_S", 0.2)
    fast = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])

    async def call_kind(kind, instruction, view, context="", rejection=None):
        if kind == "normal":
            await asyncio.sleep(5)
        return fast if kind == "value" else CH.OUTPUTS[kind]()
    monkeypatch.setattr(C, "call_kind", call_kind)
    fake["tags"] = tags(value=0.9, normal=0.9)
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and reword the alpha normal")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet
    assert "I couldn't change the normal findings just now; please try that part again." in t.reply
    assert t.evidence["timed_out"] == ["normal"]


async def test_a_style_undo_that_would_change_a_unit_line_is_refused():
    rec = {"type": "style", "claim": "x",
           "blocks": [{"before": 'NORMAL [gamma] "Gamma is fine."', "after": "Keep it brief."}]}
    u = await R.undo_turn(ROUTER_SHEET, [], [rec])
    assert not u.applied and u.sheet == ROUTER_SHEET and u.evidence["skipped"] == 1


async def test_the_deadline_starts_before_the_tag_call(fake, monkeypatch):
    monkeypatch.setattr(R, "TURN_TIMEOUT_S", 0.3)
    fast = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])

    async def slow_tag(instruction, scan_type="", context="", transport=None):
        await asyncio.sleep(0.2)
        return tags(value=0.9, normal=0.9)

    async def call_kind(kind, instruction, view, context="", rejection=None):
        if kind == "normal":
            await asyncio.sleep(0.2)    # fits 0.3 s alone, not after the tag's 0.2 s
        return fast if kind == "value" else CH.OUTPUTS[kind]()
    monkeypatch.setattr(J, "tag", slow_tag)
    monkeypatch.setattr(C, "call_kind", call_kind)
    t = await R.route_turn(ROUTER_SHEET, [], "drop width and reword the alpha normal")
    assert t.applied and t.evidence["timed_out"] == ["normal"]


async def test_a_tag_call_past_the_deadline_falls_back(fake, monkeypatch):
    monkeypatch.setattr(R, "TURN_TIMEOUT_S", 0.05)

    async def stuck(instruction, scan_type="", context="", transport=None):
        await asyncio.sleep(5)
    monkeypatch.setattr(J, "tag", stuck)
    with pytest.raises(R.Fallback):
        await R.route_turn(ROUTER_SHEET, [], "drop width")


async def test_a_plausible_always_mention_request_passes_the_misfit_check(fake):
    """misfit_B: a request to add, require or mention something the scan could assess is not unrelated."""
    assert "A request to add, require or mention something this scan could plausibly assess is not unrelated." in (
        J.QUESTIONS["misfit"]["instructions"])
    fake["tags"] = tags(misfit=0.1, normal=0.9)
    t = await R.route_turn(ROUTER_SHEET, [], "always mention the ECV")
    assert t.evidence["route"] == "router" and [k for k, _ in fake["seen"]] == ["normal"]
    fake["tags"], fake["seen"] = tags(misfit=0.5, normal=0.9), []
    blocked = await R.route_turn(ROUTER_SHEET, [], "always mention the ECV")
    assert blocked.evidence["route"] == "ask" and fake["seen"] == [] and not blocked.applied


# ── habit guard (until item 5: findings-triggered rows) ──────────────────────────────────────────────────────────
async def test_a_finding_triggered_habit_is_parked_and_nothing_is_written(fake):
    led, _ = L.set_choice([], "value", "Width", {"need": "every"})
    fake["tags"] = {**tags(normal=0.9, value=0.8, fixed=0.7), "habit": 0.9}
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", negative="No collection.",
                                                                    to="add", text="No collection.")])
    t = await R.route_turn(ROUTER_SHEET, led, "with diverticulitis always comment on collection")
    assert not t.applied and t.sheet == ROUTER_SHEET and t.ledger == L.clean(led) and t.records == []
    assert fake["seen"] == []                                   # no normal, negative, value or fixed call at all
    (card,) = t.cards
    assert card["kind"] == "habit" and card["title"] == (
        "Saved as a habit to set up: when diverticulitis, always comment on collection")
    assert t.evidence["habit"] == {"score": 0.9, "condition": "diverticulitis",
                                   "parked": "with diverticulitis always comment on collection"}
    assert R.HABIT_LINE in t.reply


async def test_a_habit_turn_still_applies_its_style_part(fake):
    fake["tags"] = {**tags(normal=0.9, style=0.9), "habit": 0.8}
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text=NEW_IC)], summary="Shorter.")
    t = await R.route_turn(ROUTER_SHEET, [], "when there is a mass say so, and keep the impression shorter")
    assert t.applied and NEW_IC in t.sheet and [k for k, _ in fake["seen"]] == ["style"]
    assert t.cards[0]["kind"] == "habit" and "when there is a mass" in t.cards[0]["title"]


async def test_a_habit_with_no_clear_condition_gets_an_ask_line(fake):
    fake["tags"] = {**tags(normal=0.9), "habit": 0.6}
    t = await R.route_turn(ROUTER_SHEET, [], "comment on collections in the right cases")
    assert not t.applied and t.cards[0]["title"] == (
        "Saved as a habit to set up: comment on collections in the right cases")
    assert R.HABIT_ASK in t.reply


async def test_no_habit_below_the_threshold(fake):
    fake["tags"] = {**tags(normal=0.9), "habit": 0.49}
    fake["calls"]["normal"] = CH.NormalOut(changes=[CH.NormalChange(paragraph="Upper", structure="alpha",
                                                                    to="reword", text="Alpha is fine.")])
    t = await R.route_turn(ROUTER_SHEET, [], "say Alpha is fine.")
    assert t.applied and "habit" not in t.evidence


# ── prose deletion check (a structural backstop) ──────────────────────────────────────────────────────────────────
async def test_a_value_instruction_cannot_strip_unrelated_prose(fake):
    fake["tags"] = tags(value=0.9, style=0.9)
    fake["calls"]["value"] = CH.ValueOut(changes=[CH.ValueChange(name="Width", to="not_needed")])
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b4", text="Lead with the most important finding.")],
                                         summary="Shorter.")
    t = await R.route_turn(ROUTER_SHEET, [], "drop Width")
    assert t.applied and 'LIST_MISSING ["Depth"]' in t.sheet and "Keep it brief." in t.sheet
    assert R.PROSE_KEPT in t.reply and t.evidence["prose_kept"] == ["b4"]
    assert not any(r["type"] == "style" for r in t.records)


async def test_prose_the_instruction_names_may_be_removed(fake):
    fake["tags"] = tags(style=0.9)
    fake["calls"]["style"] = CH.StyleOut(blocks=[CH.StyleBlock(id="b1", text="Sentences are declarative.")],
                                         summary="No length rule.")
    t = await R.route_turn(ROUTER_SHEET, [], "stop asking for short sentences")
    assert t.applied and "Sentences are declarative." in t.sheet and "prose_kept" not in t.evidence


def test_content_words_are_a_simple_overlap():
    assert R.content_words("Keep it brief, please.") == {"keep", "brief", "please"}
    assert R.mentioned("Lead with the most important findings.", "the impression should lead with findings", "")
    assert not R.mentioned("Keep it brief.", "drop Width", "Impression Construction")
    assert R.mentioned("Keep it brief.", "make it more concise", "Impression Construction") is False
    assert R.mentioned("Keep it brief.", "shorter impression", "Impression Construction")
