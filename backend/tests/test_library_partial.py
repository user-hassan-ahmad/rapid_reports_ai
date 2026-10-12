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
    assert t.bounded is False and t.needed == ["size", "risk"]    # cannot tell: every unknown that reaches the result
    assert t.possible == sorted(o.id for o in toy_entry.outcomes)


def test_a_single_possible_outcome_is_settled_even_when_a_table_key_is_unknown():
    L = {"source": "S1", "page": 2}
    e = Entry.model_validate({
        "id": "t", "version": "1", "topic": "t", "issuer": "T", "system": "T", "display": "T", "edition": "1", "tier": 1,
        "applies_to": {"region": ["chest"], "modality": ["CT"], "finding_type": ["nodule"], "context": ["incidental"]},
        "aliases": [],
        "inputs": [{"id": "a", "label": "A", "type": "enum", "options": ["x", "y"]},
                   {"id": "b", "label": "B", "type": "enum", "options": ["p", "q"]}],
        "logic": [{"step": "table", "id": "res", "keys": ["a", "b"], "rows": [
            {"match": ["x", "p"], "result": "o1"}, {"match": ["x", "q"], "result": "o1"},
            {"match": ["y", "p"], "result": "o2"}, {"match": ["y", "q"], "result": "o3"}]}],
        "result": "res",
        "outcomes": [{"id": o, "classification": f"class {o}", "recommendation": f"rec {o}", "locator": L}
                     for o in ("o1", "o2", "o3")],
        "reference": {"summary": [{"id": "sum.1", "text": "t", "locator": {"source": "S2"}}]},
    })
    t = E.evaluate(e, {"a": "x"})
    assert t.outcome == "o1" and t.needed == [] and t.possible == ["o1"] and t.bounded
    t = E.evaluate(e, {"a": "y"})
    assert t.outcome is None and t.needed == ["b"] and t.possible == ["o2", "o3"]


def test_partial_evaluation_samples_only_inside_a_declared_range(toy):
    toy["inputs"][1].update(min_value=0, min_inclusive=False, max_value=7)      # size in (0, 7]
    e = Entry.model_validate(toy)
    xs = [v.value for v in E.domain(e, e.input("size"))]
    assert xs and all(0 < x <= 7 for x in xs)
    assert {E.evaluate(e, {"kind": "solid", "size": x, "risk": "low"}).outcome for x in xs} == {"none", "ct12"}
    t = E.evaluate(e, {"kind": "solid", "risk": "low"})                         # never feeds 0 or 8+ to the engine
    assert t.possible == ["ct12", "none"] and t.needed == ["size"]


def _bts():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("bts-pulmonary-nodule")


BTS_10MM = {"diameter_mm": 10, "nodule_type": "solid", "benign_features": False, "prior_study": False}
BTS_BROCK = {"age", "sex", "family_history", "emphysema", "upper_lobe", "spiculation", "nodule_count"}


def test_unbounded_asks_every_applicable_input_that_reaches_the_result():
    """I4: a 10 mm solid nodule with no prior goes to Brock, whose inputs feed a formula. The card must ask every one
    of them, not only those the enumerable part shows to matter; inputs made not applicable are never asked."""
    e = _bts()
    t = E.evaluate(e, BTS_10MM)
    assert t.outcome is None and t.bounded is False
    assert BTS_BROCK <= set(t.needed)
    assert not {"prior_volume_mm3", "current_volume_mm3", "interval_days", "diameter_mm"} & set(t.needed)
    assert t.needed == [i.id for i in e.inputs if i.id in t.needed]          # in the entry's input order
