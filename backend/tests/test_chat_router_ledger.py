"""The router's adapter over the Rules step's ledger (chat-edit router spec, Flow 2 and 5)."""
import pytest

from rapid_reports_ai import chat_router_ledger as L
from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg
from tests.template_sheet_fixtures import ROUTER_SHEET, ROUTER_SHEET_CONCEPT

COMPARED = "Compared with the {study} of {date}."
NO_PRIOR = "No previous imaging available."


@pytest.fixture(autouse=True)
def no_unit_checks(monkeypatch):
    """The save function's unit checks call a model; these tests check the ledger only."""
    from rapid_reports_ai import template_sheet_save as S

    async def none(structure, sheet):
        return []
    monkeypatch.setattr(S, "check_units", none)


def test_the_fixtures_are_lint_clean():
    assert not tsg.parse_sheet(ROUTER_SHEET, mode="template").errors
    assert not tsg.parse_sheet(ROUTER_SHEET_CONCEPT, mode="template").errors


def test_seed_values_records_the_listed_values_as_defaults_once():
    led = L.seed_values([], ROUTER_SHEET)
    assert [(e["key"], e["choice"], e["source"], e["by"]) for e in led] == [
        ("Width", {"need": "every"}, "default", "code"), ("Depth", {"need": "every"}, "default", "code")]
    assert L.seed_values(led, ROUTER_SHEET) == led
    assert L.values(ROUTER_SHEET, []) == [("Width", "every"), ("Depth", "every")]


def test_set_choice_writes_a_chat_entry_and_returns_the_change():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    assert led[0]["source"] == "chat" and led[0]["by"] == "radiologist" and "route" not in led[0]
    assert change["kind"] == "value" and change["key"] == "Width" and change["old"] is None
    with pytest.raises(L.Rejected):
        L.set_choice([], "value", 'a "quoted" name', {"need": "every"})
    with pytest.raises(L.Rejected):
        L.set_choice([], "concept", "no-such-concept", {"use": False})


def test_a_route_marks_the_entry_and_survives_clean():
    led, _ = L.set_choice([], "value", "Width", {"need": "relevant"}, route="llm_unsure")
    assert led[0]["route"] == "llm_unsure" and L.clean(led)[0]["route"] == "llm_unsure"
    assert "route" not in td.clean_ledger([{**led[0], "route": "made-up"}])[0]
    with pytest.raises(L.Rejected):
        L.set_choice([], "value", "Width", {"need": "every"}, route="made-up")


def test_undo_wraps_undo_change_and_restores_the_old_entry_whole():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    assert L.undo(led, change) == []
    seeded = L.seed_values([], ROUTER_SHEET)
    led2, change2 = L.set_choice(seeded, "value", "Width", {"need": "relevant"})
    width = L.entry(L.undo(led2, change2), "value", "Width")
    assert width["choice"] == {"need": "every"} and width["source"] == "default" and width["by"] == "code"


def test_undo_leaves_an_entry_a_later_turn_changed():
    led, change = L.set_choice([], "value", "Width", {"need": "not_needed"})
    led, _ = L.set_choice(led, "value", "Width", {"need": "relevant"})
    assert L.entry(L.undo(led, change), "value", "Width")["choice"] == {"need": "relevant"}


def test_concept_choice_round_trips_every_state_through_the_real_validate():
    cond = L.condition_for("comparison", "compared")
    assert cond == "the dictation names a previous imaging study for comparison"
    _, used = L.check("concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED, cond))
    assert L.concept_state(used) == ("used", NO_PRIOR, COMPARED, cond)
    _, auto = L.check("concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED))
    assert auto["condition"] == cond      # one standard condition: filled by the ledger
    _, dictated = L.check("concept", "comparison", L.concept_choice("dictated", NO_PRIOR, COMPARED))
    assert dictated["use"] is False and dictated["dictated"] is True
    assert L.concept_state(dictated) == ("dictated", "", "", "")
    _, off = L.check("concept", "comparison", L.concept_choice("not_used", NO_PRIOR, COMPARED))
    assert L.concept_state(off) == ("not_used", "", "", "")


def test_contrast_needs_one_of_its_two_conditions():
    with pytest.raises(L.Rejected):
        L.check("concept", "contrast", L.concept_choice("used", "Contrast was given.", "No contrast was given."))
    cond = L.condition_for("contrast", "not_given")
    assert cond == "the dictation states no contrast agent was given" and L.condition_for("contrast", cond) == cond
    _, choice = L.check("concept", "contrast",
                        L.concept_choice("used", "Contrast was given.", "No contrast was given.", cond))
    assert choice["condition"] == cond
    assert L.concept_states("contrast") == {"given": "the dictation states a contrast agent was given",
                                            "not_given": cond}
    assert L.condition_for("contrast", "sometimes") == ""
    assert L.usual_question("contrast") == "Is contrast usually given for this scan?"   # the Rules step's own words


def test_concept_owner_finds_a_line_by_the_ledger_or_the_sheet():
    led, _ = L.set_choice([], "concept", "comparison", L.concept_choice("used", NO_PRIOR, COMPARED))
    assert L.concept_owner(ROUTER_SHEET, led, "no previous imaging available") == "comparison"
    assert L.concept_owner(ROUTER_SHEET_CONCEPT, [], NO_PRIOR) == "comparison"
    assert L.concept_owner(ROUTER_SHEET_CONCEPT, [], COMPARED) == "comparison"
    assert L.concept_owner(ROUTER_SHEET, [], NO_PRIOR) is None
    with pytest.raises(L.Rejected):     # the ledger refuses a FIXED decision on a concept's line
        L.set_choice(led, "fixed", NO_PRIOR, {"keep": "remove"})


def test_current_reads_the_sheet():
    assert L.current(ROUTER_SHEET, "fixed", "Axial images were acquired.") == {"keep": "always"}
    assert L.current(ROUTER_SHEET, "normal", L.normal_key("Upper", "alpha")) == {"text": "Alpha is normal."}
    assert L.current(ROUTER_SHEET, "normal", L.normal_key("Nowhere", "alpha")) is None
    assert L.concept_state(L.current(ROUTER_SHEET_CONCEPT, "concept", "comparison"))[:3] == ("used", NO_PRIOR, COMPARED)


def test_card_is_the_rules_step_card_or_none():
    card = L.card("value", "Width", {"need": "not_needed"})
    assert card["ledger_kind"] == "value" and card["key"] == "Width" and card["selected"] is None
    assert L.card("normal", "no separator", {"text": "x"}) is None


def test_rekeys_follow_a_paragraph_rename_and_a_fixed_reword():
    led, _ = L.set_choice([], "normal", L.normal_key("Upper", "alpha"), {"text": "Alpha is fine."})
    led, _ = L.set_choice(led, "fixed", "Axial images were acquired.", {"keep": "always"})
    led = L.rekey_paragraph(led, "upper", "Top")
    assert L.entry(led, "normal", L.normal_key("Top", "alpha"))["choice"] == {"text": "Alpha is fine."}
    led, change = L.rekey_fixed(led, "Axial images were acquired.", "Axial and coronal images were acquired.")
    assert L.entry(led, "fixed", "Axial and coronal images were acquired.") is not None
    assert change["old"]["key"] == "Axial images were acquired."
    assert L.entry(L.undo(led, change), "fixed", "Axial images were acquired.") is not None
    assert L.rekey_fixed(led, "Not decided.", "Other.") == (led, None)
    assert [e["key"] for e in L.paragraph_entries(led, "TOP")] == [L.normal_key("Top", "alpha")]
    assert L.normal_label(L.negative_key("Upper", "No beta abnormality.")) == ("Upper", "No beta abnormality.")


def test_restore_validates_a_client_sent_entry():
    good = {"kind": "normal", "key": L.normal_key("Lower", "gamma"), "choice": {"text": "Gamma is fine."},
            "by": "radiologist", "at": "t", "source": "chat"}
    assert L.entry(L.restore([], good), "normal", good["key"])["choice"] == {"text": "Gamma is fine."}
    assert L.restore([good], good) == [good]
    with pytest.raises(L.Rejected):
        L.restore([], {"kind": "value", "key": 'a "b"', "choice": {"need": "every"}})


async def test_save_applies_the_ledger_and_reports_unmatched_and_cards():
    led, _ = L.set_choice(L.seed_values([], ROUTER_SHEET), "value", "Width", {"need": "not_needed"})
    saved = await L.save(ROUTER_SHEET, ROUTER_SHEET, led)
    assert saved.status == "saved" and 'LIST_MISSING ["Depth"]' in saved.sheet
    assert L.entry(saved.ledger, "value", "Width")["choice"] == {"need": "not_needed"}
    assert saved.cards == [] and saved.unmatched == []


def test_forget_removes_an_entry_and_undo_restores_it_whole():
    led, _ = L.set_choice([], "value", "Width", {"need": "relevant"}, route="llm_unsure")
    out, change = L.forget(led, "value", "width")
    assert out == [] and change["new"] is None and change["old"]["route"] == "llm_unsure"
    assert L.undo(out, change) == led
    assert L.forget([], "value", "Width") == ([], None)
    assert L.FORGET == {"forget": True}
