from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry

from tests.test_library_engine import CALC


def test_only_inputs_that_change_the_outcome_are_needed(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7})
    assert t.outcome is None and t.needed == ["risk"] and t.possible == ["ct12", "ct6"] and t.bounded


def test_numbers_are_enumerated_through_their_band_edges(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.needed == ["size", "risk"] and t.possible == ["ct12", "ct6", "none", "pet"]


def test_nothing_known(toy_entry):
    t = E.evaluate(toy_entry, {})
    assert t.needed == ["kind", "size", "risk"]          # margin never changes the outcome: never asked
    assert t.possible == ["ct12", "ct6", "none", "pet", "subsolid"]


def test_number_domain_covers_edges_and_regions(toy_entry):
    xs = [v.value for v in E.domain(toy_entry, toy_entry.input("size"))]
    assert xs == [5, 6, 7, 8, 9]
    assert [v.state for v in E.domain(toy_entry, toy_entry.input("margin"))][-1] == "not_assessable"


def test_a_number_feeding_a_formula_is_unbounded():
    calc = Entry.model_validate(CALC)
    t = E.evaluate(calc, {"b": 3, "flag": True, "grade": "g1"})
    assert E.domain(calc, calc.input("a")) is None
    assert t.outcome is None and "a" in t.needed and t.bounded is False


def test_too_many_combinations_falls_back_to_everything(toy_entry, monkeypatch):
    monkeypatch.setattr(E, "MAX_COMBOS", 1)
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.bounded is False and t.needed == ["size", "risk", "margin"]    # cannot tell: every unknown is asked
    assert t.possible == sorted(o.id for o in toy_entry.outcomes)
