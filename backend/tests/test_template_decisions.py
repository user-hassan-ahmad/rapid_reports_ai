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
