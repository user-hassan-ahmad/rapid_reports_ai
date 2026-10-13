import math

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry

CALC = {
    "id": "calc", "version": "1", "topic": "calc", "purpose": "Toy test entry.", "issuer": "T", "system": "calc", "display": "Calc", "edition": "1",
    "tier": 1, "applies_to": {},
    "inputs": [{"id": "a", "label": "A", "type": "number"}, {"id": "b", "label": "B", "type": "number"},
               {"id": "flag", "label": "Flag", "type": "boolean"},
               {"id": "grade", "label": "Grade", "type": "enum", "options": ["g1", "g2", "g3"]}],
    "logic": [
        {"step": "derive", "id": "r", "expr": {"op": "ln", "args": [{"op": "div", "args": [{"ref": "b"}, {"ref": "a"}]}]}},
        {"step": "derive", "id": "q", "expr": {"op": "div", "args": [{"ref": "a"}, {"ref": "b"}]}},
        {"step": "score", "id": "s", "kind": "linear", "intercept": 1,
         "terms": [{"ref": "a", "coef": 2}, {"ref": "flag", "coef": 3}, {"ref": "grade", "coef": 5, "eq": "g2"}]},
        {"step": "score", "id": "p", "kind": "logistic", "intercept": 0, "terms": [{"ref": "a", "coef": 1}]},
        {"step": "band", "id": "a_band", "ref": "a", "bands": [{"id": "small", "label": "small", "max": 10},
                                                              {"id": "big", "label": "big", "min": 10}]},
        {"step": "table", "id": "t", "keys": ["grade"], "rows": [{"match": ["g1"], "result": "low"},
                                                                 {"match": ["g2"], "result": "mid"},
                                                                 {"match": ["g3"], "result": "high"}]},
        {"step": "rules", "id": "u", "cases": [
            {"when": {"count_gte": 2, "of": [{"ref": "flag", "eq": True}, {"ref": "grade", "in": ["g2", "g3"]},
                                             {"ref": "a_band", "eq": "big"}]}, "result": "high"},
            {"when": {"none": [{"count_gte": 2, "of": [{"ref": "flag", "eq": True},
                                                        {"ref": "grade", "in": ["g2", "g3"]},
                                                        {"ref": "a_band", "eq": "big"}]}]}, "result": "low"}]},
        {"step": "adjust", "id": "final", "of": ["t", "u"], "order": ["low", "mid", "high"], "ceiling": "mid"}],
    "result": "final",
    "outcomes": [{"id": "low", "classification": "low"}, {"id": "mid", "classification": "mid"},
                 {"id": "high", "classification": "high"}],
}


@pytest.fixture
def calc():
    return Entry.model_validate(CALC)


def _step(t, sid):
    return next(s for s in t.steps if s.id == sid)


def test_known_inputs_give_the_outcome_and_a_trace(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7, "risk": "high"})
    assert t.outcome == "ct6" and t.possible == ["ct6"] and t.needed == []
    band, plan = _step(t, "size_band"), _step(t, "plan")
    assert (band.value, band.fired) == ("6to8", "6to8")
    assert (plan.value, plan.fired, plan.uses) == ("ct6", "3", ["kind", "risk", "size_band"])
    assert plan.locator.page == 3


@pytest.mark.parametrize("size,band", [(5.99, "lt6"), (6, "6to8"), (8, "6to8"), (8.01, "gt8"), (-1, "lt6")])
def test_band_edges_follow_inclusivity(toy_entry, size, band):
    assert _step(E.evaluate(toy_entry, {"kind": "solid", "size": size}), "size_band").value == band


def test_prerequisite_false_makes_an_input_not_applicable(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "subsolid", "risk": "high"})
    assert t.outcome == "subsolid" and t.inputs["risk"].state == "not_applicable"


def test_a_number_answered_as_a_band(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": {"band": "6to8"}, "risk": "low"})
    assert t.outcome == "ct12" and _step(t, "size_band").value == "6to8"


def test_states_and_values_are_validated(toy_entry):
    assert E.evaluate(toy_entry, {"kind": "subsolid", "margin": {"state": "not_assessable"}}).outcome == "subsolid"
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "subsolid", "margin": {"state": "absent"}})
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "cystic"})


def test_unknown_blocks_the_outcome(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7})
    assert t.outcome is None and _step(t, "plan").state == "unknown"


def test_two_cases_holding_is_an_entry_error(toy):
    toy["logic"][1]["cases"][2]["when"] = {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"}]}
    with pytest.raises(E.EvaluationError, match="all hold"):
        E.evaluate(Entry.model_validate(toy), {"kind": "solid", "size": 7, "risk": "high"})


def test_render_fills_inputs_and_band_labels(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid", "size": 7, "risk": "high"})
    assert E.render(toy_entry, t, "solid nodule {size_band}, {risk} risk, {size} mm") == \
        "solid nodule 6-8 mm, high risk, 7 mm"
    t2 = E.evaluate(toy_entry, {"kind": "subsolid"})
    assert E.render(toy_entry, t2, "x {size_band}") == "x {size_band}"     # nothing to fill: left as written


def test_derive_score_table_rules_adjust(calc):
    t = E.evaluate(calc, {"a": 2, "b": 2 * math.e, "flag": True, "grade": "g3"})
    assert math.isclose(_step(t, "r").value, 1.0)
    assert _step(t, "s").value == 1 + 2 * 2 + 3 * 1 + 0          # g3 is not g2
    assert math.isclose(_step(t, "p").value, 1 / (1 + math.exp(-2)))
    assert _step(t, "t").value == "high" and _step(t, "u").value == "high"
    assert t.outcome == "mid"                                       # highest is high, ceiling mid
    t2 = E.evaluate(calc, {"a": 2, "b": 3, "flag": False, "grade": "g1"})
    assert _step(t2, "u").value == "low" and t2.outcome == "low"


def test_formula_edges(calc):
    assert _step(E.evaluate(calc, {"a": 0, "b": 3, "flag": False, "grade": "g1"}), "r").value == math.inf   # ln(3/0)
    with pytest.raises(E.EvaluationError, match="ln"):
        E.evaluate(calc, {"a": 2, "b": -1, "flag": False, "grade": "g1"})


def test_a_band_only_number_cannot_feed_a_formula(calc):
    t = E.evaluate(calc, {"a": {"band": "big"}, "b": 3, "flag": True, "grade": "g2"})
    assert _step(t, "r").state == "unknown" and _step(t, "a_band").value == "big"


# --- declared input ranges ---------------------------------------------------------------------------------------

def _ranged():
    d = {**CALC, "inputs": [dict(i) for i in CALC["inputs"]]}
    d["inputs"][0].update(min_value=0, min_inclusive=False)            # a > 0
    d["inputs"][1].update(min_value=0, max_value=100)                  # 0 <= b <= 100
    return Entry.model_validate(d)


def test_a_number_outside_its_range_is_refused():
    e = _ranged()
    with pytest.raises(ValueError, match="outside its valid range"):
        E.evaluate(e, {"a": 0, "b": 1})                                # exclusive minimum
    with pytest.raises(ValueError, match="outside its valid range"):
        E.evaluate(e, {"a": 1, "b": 100.5})
    E._coerce(e.input("a"), E.as_value(1e-9)); E._coerce(e.input("b"), E.as_value(0))   # just inside, inclusive edge
    E.evaluate(e, {"a": 1, "b": 100})


def test_range_needs_a_number_and_a_non_empty_interval():
    with pytest.raises(ValueError, match="only a number"):
        Entry.model_validate({**CALC, "inputs": [{"id": "f", "label": "F", "type": "boolean", "min_value": 0}]})
    bad = {**CALC, "inputs": [{"id": "a", "label": "A", "type": "number", "min_value": 5, "max_value": 5,
                               "max_inclusive": False}]}
    with pytest.raises(ValueError, match="empty range"):
        Entry.model_validate(bad)


def test_pow_of_zero_and_huge_logistic_do_not_escape_as_python_errors():
    pw = {**CALC, "inputs": [{"id": "a", "label": "A", "type": "number"}],
          "logic": [{"step": "derive", "id": "r", "expr": {"op": "pow", "args": [{"ref": "a"}, {"const": -0.5}]}},
                    {"step": "score", "id": "p", "kind": "logistic", "terms": [{"ref": "a", "coef": -1}]},
                    {"step": "rules", "id": "out", "cases": [{"when": {"ref": "a", "state": "present"}, "result": "o"}]}],
          "result": "out", "outcomes": [{"id": "o", "classification": "o"}]}
    e = Entry.model_validate(pw)
    with pytest.raises(E.EvaluationError, match="pow"):
        E.evaluate(e, {"a": 0})
    t = E.evaluate(e, {"a": 1e6})                                      # exp(1e6) would overflow a naive logistic
    assert next(s for s in t.steps if s.id == "p").value == 0.0


def test_a_bad_value_behind_an_unknown_or_false_prerequisite_is_refused(toy_entry):
    """A given value is validated even when its prerequisite is unknown (kind not given) or false (subsolid)."""
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"size": 7, "risk": "medium"})
    with pytest.raises(ValueError):
        E.evaluate(toy_entry, {"kind": "subsolid", "size": 7, "risk": "medium"})
    assert E.evaluate(toy_entry, {"size": 7, "risk": "low"}).needed == ["kind"]
