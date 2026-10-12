import pytest

from rapid_reports_ai.hybrid_stack.copilot.library.schema import Cases, Entry
from rapid_reports_ai.hybrid_stack.copilot.library.verify import check


def _check(toy, manifest, cases):
    return check(Entry.model_validate(toy), manifest, cases)


def test_toy_passes(toy_entry, manifest, cases):
    assert check(toy_entry, manifest, cases) == []


def test_band_gap_and_overlap(toy, manifest, cases):
    toy["logic"][0]["bands"][1]["min"] = 6.5
    assert any("size_band" in p and "do not meet" in p for p in _check(toy, manifest, cases))
    toy["logic"][0]["bands"][1]["min"] = 6
    toy["logic"][0]["bands"][0]["max_inclusive"] = True
    assert any("in both" in p for p in _check(toy, manifest, cases))


def test_rule_overlap_and_gap_are_found_by_enumeration(toy, manifest, cases):
    toy["logic"][1]["cases"][2]["when"] = {"all": [{"ref": "kind", "eq": "solid"}, {"ref": "size_band", "eq": "6to8"}]}
    assert any("all hold" in p for p in _check(toy, manifest, cases))
    toy = {**toy}
    toy["logic"] = [toy["logic"][0], {**toy["logic"][1], "cases": toy["logic"][1]["cases"][:4]}]
    assert any("no case holds" in p for p in _check(toy, manifest, cases))


def test_a_rule_may_not_compare_a_number(toy, manifest, cases):
    toy["logic"][1]["cases"][0]["when"] = {"all": [{"ref": "kind", "eq": "subsolid"}, {"ref": "size", "eq": 7}]}
    assert any("band it first" in p for p in _check(toy, manifest, cases))


def test_locators(toy, manifest, cases):
    del toy["outcomes"][0]["locator"]
    toy["logic"][1]["cases"][0]["locator"] = {"source": "S2"}
    probs = _check(toy, manifest, cases)
    assert any("outcome subsolid: no locator" in p for p in probs)
    assert any("explanatory" in p for p in probs)


def test_result_values_must_be_outcomes(toy, manifest, cases):
    toy["logic"][1]["cases"][4]["result"] = "biopsy"
    assert any("biopsy" in p and "not an outcome" in p for p in _check(toy, manifest, cases))


def test_golden_cases(toy, manifest, cases):
    cases.cases[3].outcome = "ct12"
    assert any("edge 8 high" in p for p in _check(toy, manifest, cases))
    short = Cases(cases=[c for c in cases.cases if c.name != "subsolid"])
    assert any("outcome subsolid has no golden case" in p for p in _check(toy, manifest, short))
    assert _check(toy, manifest, Cases(cases=[])) == ["no golden cases"]


def test_unfillable_placeholder(toy, manifest, cases):
    toy["outcomes"][0]["classification"] = "subsolid nodule {size}"
    assert any("placeholder" in p for p in _check(toy, manifest, cases))


SCORED = {
    "id": "scored", "version": "1", "topic": "s", "issuer": "T", "system": "s", "display": "S", "edition": "1",
    "tier": 1, "applies_to": {},
    "inputs": [{"id": "x", "label": "X", "type": "number"}],
    "logic": [
        {"step": "score", "id": "s", "kind": "linear", "terms": [{"ref": "x", "coef": 1}],
         "locator": {"source": "S1"}},
        {"step": "band", "id": "s_band", "ref": "s", "locator": {"source": "S1"},
         "bands": [{"id": "lo", "label": "low", "max": 0.5}, {"id": "hi", "label": "high", "min": 0.5}]},
        {"step": "rules", "id": "r", "cases": [
            {"when": {"ref": "s_band", "eq": "lo"}, "result": "a", "locator": {"source": "S1"}},
            {"when": {"ref": "s_band", "eq": "hi"}, "result": "b", "locator": {"source": "S1"}}]}],
    "result": "r",
    "outcomes": [{"id": "a", "classification": "a", "locator": {"source": "S1"}},
                 {"id": "b", "classification": "b", "locator": {"source": "S1"}}],
}


def test_a_banded_score_needs_cases_either_side_of_its_cut_off(manifest):
    e = Entry.model_validate(SCORED)
    one_side = Cases.model_validate({"cases": [
        {"name": "lo", "origin": "ours", "inputs": {"x": 0.2}, "outcome": "a", "steps": {"s": 0.2}}]})
    probs = check(e, manifest, one_side)
    assert any("no golden case reaches band hi" in p for p in probs)
    assert any("s: 1 golden case(s)" in p for p in probs)
    both = Cases.model_validate({"cases": [
        {"name": "lo", "origin": "ours", "inputs": {"x": 0.2}, "outcome": "a", "steps": {"s": 0.2}},
        {"name": "hi", "origin": "ours", "inputs": {"x": 0.5}, "outcome": "b", "steps": {"s": 0.5}}]})
    assert check(e, manifest, both) == []
