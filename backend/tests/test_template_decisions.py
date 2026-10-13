"""The decision ledger's data and validation (Rules-step spec, "Decision ledger")."""
import pytest

from rapid_reports_ai import template_decisions as td
from rapid_reports_ai import template_sheet_grammar as tsg


def test_concepts_are_the_four_standard_ones_with_parseable_conditions():
    assert list(td.CONCEPTS) == ["comparison", "contrast", "sequences", "limitation"]
    assert td.CONCEPTS["comparison"].conditions == ("the dictation names a previous imaging study for comparison",)
    # contrast has a condition for both states: its default is whatever is usual in the template's examples
    assert td.CONCEPTS["contrast"].conditions == ("the dictation states a contrast agent was given",
                                                  "the dictation states no contrast agent was given")
    for c in td.CONCEPTS.values():
        for cond in c.conditions:
            assert len(tsg._content_words(cond)) >= 2, c.name   # the grammar's subject rule
            assert td.concept_of_condition(cond.upper()) == c.name


def test_normal_and_negative_keys_round_trip():
    assert td.split_normal_key(td.normal_key("Liver", "liver")) == ("Liver", "liver", False)
    assert td.split_normal_key(td.negative_key("Liver", "No focal lesion.")) == ("Liver", "No focal lesion.", True)
    with pytest.raises(td.DecisionError):
        td.split_normal_key("no separator")


def test_match_key_ignores_case_spacing_and_final_full_stop():
    assert td.match_key("value", " LVEF ") == td.match_key("value", "lvef")
    assert td.match_key("fixed", "Axial images.") == td.match_key("fixed", "axial  images")
    assert td.match_key("normal", "Liver :: Liver") == td.match_key("normal", "liver ::  liver")
    assert td.match_key("normal", 'Liver :: "No lesion."') == td.match_key("normal", 'liver :: "no lesion"')


@pytest.mark.parametrize("kind,key,choice", [
    ("value", "LVEF", {"need": "sometimes"}),
    ("value", 'a "quoted" name', {"need": "every"}),
    ("value", "one two three four five six seven eight nine", {"need": "every"}),
    ("concept", "laterality", {"use": True, "default": "x", "when_met": ""}),
    ("concept", "comparison", {"use": "yes", "default": "x", "when_met": ""}),
    ("concept", "comparison", {"use": True, "default": "", "when_met": ""}),
    ("concept", "comparison", {"use": True, "default": "Same.", "when_met": "same"}),
    ("concept", "contrast", {"use": True, "default": "With an agent.", "when_met": ""}),           # which condition?
    ("concept", "comparison", {"use": True, "default": "x", "when_met": "", "condition": "some other text"}),
    ("fixed", "Line.", {"keep": "maybe"}),
    ("normal", "Liver :: liver", {"text": "The liver measures {size}."}),
    ("normal", "Liver :: liver", {"text": 'Has a "quote".'}),
    ("other", "k", {}),
])
def test_invalid_changes_are_refused(kind, key, choice):
    with pytest.raises(td.DecisionError):
        td.validate(kind, key, choice)


def test_validate_canonicalises():
    assert td.validate("value", "  LV  EF ", {"need": "every", "extra": 1}) == ("LV EF", {"need": "every"})
    assert td.validate("concept", "comparison", {"use": False, "default": "x", "when_met": "y"}) == (
        "comparison", {"use": False, "default": "", "when_met": "", "condition": "", "dictated": False})
    assert td.validate("concept", "contrast", {"use": False, "dictated": True})[1]["dictated"] is True
    assert td.validate("concept", "comparison", {"use": True, "default": "None.", "when_met": ""}) == (
        "comparison", {"use": True, "default": "None.", "when_met": "",
                       "condition": "the dictation names a previous imaging study for comparison", "dictated": False})
    assert td.validate("concept", "contrast", {"use": True, "default": "No agent.", "when_met": "",
                                               "condition": "The dictation states a contrast agent was given"}
                       )[1]["condition"] == "the dictation states a contrast agent was given"
    assert td.validate("normal", "Liver :: liver", {"text": " The liver  is normal. "}) == (
        "Liver :: liver", {"text": "The liver is normal."})


def test_set_decision_adds_then_changes_and_reports_the_change():
    led, ch = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t0")
    assert led == [{"kind": "value", "key": "LVEF", "choice": {"need": "every"}, "by": "radiologist", "at": "t0",
                    "source": "creation"}]
    assert ch == {"kind": "value", "key": "LVEF", "old": None, "new": {"need": "every"}, "source": "creation",
                  "confirmed": False}
    led2, ch2 = td.set_decision(led, "value", "lvef", {"need": "not_needed"}, source="chat", at="t1")
    assert len(led2) == 1 and led2[0]["key"] == "LVEF" and led2[0]["source"] == "chat"
    assert ch2["old"] == led[0] and ch2["confirmed"] is True             # the old entry whole
    assert led[0]["choice"] == {"need": "every"}          # never mutates the input


def test_same_choice_is_no_change_but_a_reconfirmation_updates_the_source():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="default", by="code")
    led2, ch = td.set_decision(led, "value", "LVEF", {"need": "every"}, source="creation")
    assert ch is None and led2[0]["source"] == "creation" and led2[0]["by"] == "radiologist"


def test_a_change_to_a_default_is_not_a_confirmed_change():
    led, _ = td.set_decision([], "fixed", "Line.", {"keep": "always"}, source="default", by="code")
    _, ch = td.set_decision(led, "fixed", "Line.", {"keep": "remove"}, source="chat")
    assert ch["confirmed"] is False and td.describe_change(ch) == ""


def test_remove_decision_undoes_an_entry():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="chat")
    assert td.remove_decision(led, "value", "lvef") == []


def test_unknown_source_or_by_is_refused():
    with pytest.raises(td.DecisionError):
        td.set_decision([], "value", "LVEF", {"need": "every"}, source="writer")
    with pytest.raises(td.DecisionError):
        td.set_decision([], "value", "LVEF", {"need": "every"}, source="chat", by="someone")


def test_ledger_from_changes_records_valid_changes_and_lists_invalid_ones():
    led, errors = td.ledger_from_changes([
        {"kind": "value", "key": "LVEF", "choice": {"need": "every"}},
        {"kind": "value", "key": "ECV", "choice": {"need": "relevant"}, "source": "default"},
        {"kind": "concept", "key": "nonsense", "choice": {"use": False}},
    ], source="creation")
    assert [(e["key"], e["source"], e["by"]) for e in led] == [("LVEF", "creation", "radiologist"),
                                                               ("ECV", "default", "code")]
    assert len(errors) == 1 and "nonsense" in errors[0]


def test_describe_change_words_a_confirmed_change():
    led, _ = td.set_decision([], "concept", "comparison",
                             {"use": True, "default": "No previous imaging.", "when_met": "Compared with {date}."},
                             source="creation")
    _, ch = td.set_decision(led, "concept", "comparison", {"use": False}, source="chat")
    assert td.describe_change(ch) == ('This changes something you confirmed: Comparison with previous imaging '
                                      '"No previous imaging." → not used.')
    _, ch = td.set_decision(led, "concept", "comparison", {"use": False, "dictated": True}, source="chat")
    assert td.describe_change(ch).endswith("→ whichever is dictated.")


def test_undo_change_restores_the_old_entry_whole():
    led, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t0")
    led2, ch = td.set_decision(led, "value", "LVEF", {"need": "not_needed"}, source="chat", at="t1")
    assert td.undo_change(led2, ch) == led                               # source, by and at come back too
    led3, ch_new = td.set_decision(led, "value", "ECV", {"need": "every"}, source="chat")
    assert td.undo_change(led3, ch_new) == led


def test_a_fixed_entry_on_a_concepts_wording_is_refused():
    led, _ = td.set_decision([], "concept", "comparison", {"use": True, "default": "No previous imaging.",
                                                           "when_met": ""}, source="creation")
    with pytest.raises(td.DecisionError):
        td.set_decision(led, "fixed", "No previous imaging", {"keep": "remove"}, source="creation")


def test_clean_ledger_drops_what_code_cannot_apply():
    good, _ = td.set_decision([], "value", "LVEF", {"need": "every"}, source="creation", at="t")
    dirty = [*good, {"kind": "value", "key": "X", "choice": {"need": "bogus"}}, "junk",
             {"kind": "fixed", "key": "Line.", "choice": {"keep": "remove"}, "source": "weird", "by": "x"}]
    out = td.clean_ledger(dirty)
    assert out[0] == good[0]
    assert out[1] == {"kind": "fixed", "key": "Line.", "choice": {"keep": "remove"}, "by": "code", "at": "",
                      "source": "default"}
    assert len(out) == 2


def test_a_quoted_structure_label_is_not_a_negative_key():
    assert td.normal_key("Shoulder", '"ROTATOR CUFF"') == "Shoulder :: ROTATOR CUFF"
    assert td.split_normal_key(td.normal_key("Shoulder", '"ROTATOR CUFF"')) == ("Shoulder", "ROTATOR CUFF", False)


def test_a_forget_change_removes_the_entry():
    led, _ = td.ledger_from_changes([{"kind": "fixed", "key": "A line.", "choice": {"keep": "always"}},
                                     {"kind": "value", "key": "LVEF", "choice": {"need": "every"}}])
    out, errors = td.ledger_from_changes([{"kind": "fixed", "key": "A line.", "choice": dict(td.FORGET)}], base=led)
    assert errors == [] and [e["key"] for e in out] == ["LVEF"]


def test_a_replacement_or_use_wording_must_be_a_full_sentence():
    import pytest
    from rapid_reports_ai import template_decisions as td
    for frag in ("assessment is limited by {limitation}", "Assessment is limited by {limitation}",
                 "compared with the {study}."):
        with pytest.raises(td.DecisionError, match="full sentence"):
            td.validate("concept", "limitation", {"use": True, "default": "", "when_met": frag})
        with pytest.raises(td.DecisionError, match="full sentence"):
            td.validate("concept", "limitation", {"use": True, "default": "Image quality is adequate.",
                                                  "when_met": frag})
    for ok in ("Assessment is limited by {limitation}.", "{Limitation} limits assessment.", "Limitations:"):
        td.validate("concept", "limitation", {"use": True, "default": "", "when_met": ok})
    assert td.is_sentence("No previous imaging.") and not td.is_sentence("no previous imaging.")
    # a stored fragment is dropped, so it never becomes a rule
    stored = [{"kind": "concept", "key": "limitation", "by": "radiologist", "at": "t", "source": "creation",
               "choice": {"use": True, "default": "", "when_met": "assessment is limited by {limitation}"}}]
    assert td.clean_ledger(stored) == []
    from rapid_reports_ai import template_sheet_lab_prompts as P
    assert "assessment is limited" not in P.decided_block(stored)
