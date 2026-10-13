import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import verify as V
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
    "id": "scored", "version": "1", "topic": "s", "purpose": "Toy test entry.", "issuer": "T", "system": "s", "display": "S", "edition": "1",
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


def _ln_entry(toy, **rng):
    toy["inputs"].append({"id": "v", "label": "Volume", "type": "number", **rng})
    toy["logic"].insert(0, {"step": "derive", "id": "lv", "locator": {"source": "S1", "page": 2},
                            "expr": {"op": "ln", "args": [{"ref": "v"}]}})
    return toy


def test_a_formula_that_fails_inside_its_declared_range_is_a_problem(toy, manifest, cases):
    p = _check(_ln_entry(toy, min_value=0), manifest, cases)                    # v = 0 allowed: ln 0
    assert any("lv: fails inside the declared ranges" in x and "v=0" in x for x in p)


def test_a_formula_safe_across_its_range_passes_and_unranged_inputs_are_skipped(toy, manifest, cases):
    p = _check(_ln_entry(toy, min_value=0, min_inclusive=False), manifest, cases)
    assert not any("lv:" in x and "fails" in x for x in p)
    toy2 = _ln_entry(__import__("copy").deepcopy(toy))
    toy2["inputs"][-1] = {"id": "v", "label": "Volume", "type": "number"}       # no range: not checked
    assert not any("fails inside" in x for x in _check(toy2, manifest, cases))


def test_enumeration_skips_inputs_that_only_feed_a_banded_formula():
    """The gate overrides every band step with each band id, so an input reaching the result only through a band step
    (Brock's sex, family history, emphysema, upper lobe, spiculation) cannot change what the enumeration sees; it is
    left out. An input a rule reads directly (nodule type) or a prerequisite names (prior study) is kept."""
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = Entry.model_validate_json((LB.guidelines_root() / "bts-pulmonary-nodule" / "entry.json").read_text())
    ids = {i.id for i in V._enumerated_inputs(e)}
    assert not ids & {"sex", "family_history", "emphysema", "upper_lobe", "spiculation"}
    assert {"benign_features", "nodule_type", "prior_study"} <= ids


def test_enumeration_keeps_an_input_an_outcome_placeholder_names(toy, manifest, cases):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    e = Entry.model_validate(toy)
    assert "risk" in {i.id for i in V._enumerated_inputs(e)} and "margin" not in {i.id for i in V._enumerated_inputs(e)}


DISCRETE_SCORE = {
    "id": "dscore", "version": "1", "topic": "d", "purpose": "Toy test entry.", "issuer": "T", "system": "d", "display": "D", "edition": "1",
    "tier": 1, "applies_to": {},
    "inputs": [{"id": "k", "label": "K", "type": "enum", "options": ["a", "b"], "locator": {"source": "S1"}}],
    "logic": [
        {"step": "score", "id": "s", "kind": "linear", "terms": [{"ref": "k", "coef": 1, "eq": "b"}],
         "locator": {"source": "S1"}},
        {"step": "derive", "id": "d", "expr": {"op": "div", "args": [{"ref": "s"}, {"ref": "s"}]},
         "locator": {"source": "S1"}},
        {"step": "band", "id": "d_band", "ref": "d", "locator": {"source": "S1"},
         "bands": [{"id": "lo", "label": "low", "max": 0.5}, {"id": "hi", "label": "high", "min": 0.5}]},
        {"step": "rules", "id": "r", "cases": [
            {"when": {"ref": "d_band", "eq": "lo"}, "result": "x", "locator": {"source": "S1"}},
            {"when": {"ref": "d_band", "eq": "hi"}, "result": "y", "locator": {"source": "S1"}}]}],
    "result": "r",
    "outcomes": [{"id": "x", "classification": "x", "locator": {"source": "S1"}},
                 {"id": "y", "classification": "y", "locator": {"source": "S1"}}],
}


def test_gate_2_runs_a_discrete_only_chain_above_a_band(manifest):
    """A band whose upstream has no number is not a cut point for the enumeration: its discrete inputs are enumerated
    and the chain is executed, so a defect only some combination hits (0/0 when k = a) fails the gate."""
    e = Entry.model_validate(DISCRETE_SCORE)
    assert [i.id for i in V._enumerated_inputs(e)] == ["k"]
    assert any("0/0" in p for p in check(e, manifest, None))


import copy as _copy

ELIG = {"id": "known_cancer", "label": "Known primary cancer", "type": "boolean", "scope": "patient",
        "role": "eligibility", "fact": "known_primary_cancer", "locator": {"source": "S1", "page": 1, "section": "Scope"}}


def _eligible_toy(toy, elig=ELIG):
    t = _copy.deepcopy(toy)
    t["inputs"].insert(0, _copy.deepcopy(elig))
    rules = t["logic"][1]
    for c in rules["cases"]:
        c["when"] = {"all": [{"ref": elig["id"], "eq": False}, c["when"]]}
    rules["cases"].insert(0, {"when": {"ref": elig["id"], "eq": True}, "result": "does_not_apply",
                              "locator": {"source": "S1", "page": 1}})
    t["outcomes"].append({"id": "does_not_apply", "classification": "the toy guideline does not apply",
                          "recommendation": "Manage per the clinical context.",
                          "locator": {"source": "S1", "page": 1, "section": "Scope"}})
    return t


def test_an_eligible_pack_passes_the_eligibility_gate(toy):
    assert V._eligibility(Entry.model_validate(_eligible_toy(toy))) == []


def test_the_eligibility_gate(toy):
    t = _eligible_toy(toy)
    for n in range(3):            # four eligibility inputs in all
        t["inputs"].insert(1, {**ELIG, "id": f"other{n}", "fact": None})
    assert any("at most 3" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _eligible_toy(toy, {**ELIG, "locator": None})
    assert any("no locator" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _eligible_toy(toy)
    t["outcomes"] = [o for o in t["outcomes"] if o["id"] != "does_not_apply"]
    t["logic"][1]["cases"][0]["result"] = "none"
    assert any("does_not_apply outcome" in p for p in V._eligibility(Entry.model_validate(t)))
    t = _copy.deepcopy(toy)
    t["inputs"].insert(0, _copy.deepcopy(ELIG))       # declared, but no rule reads it
    t["outcomes"].append({"id": "does_not_apply", "classification": "x", "locator": {"source": "S1", "page": 1}})
    assert any("never reaches the result" in p for p in V._eligibility(Entry.model_validate(t)))


def test_every_does_not_apply_combination_has_an_eligibility_input_settled(toy):
    """(a) A combination that reaches does_not_apply with no eligibility input settled excludes for no stated reason."""
    t = _copy.deepcopy(toy)
    t["inputs"].insert(0, _copy.deepcopy(ELIG))                         # declared, never read
    t["outcomes"].append({"id": "does_not_apply", "classification": "x", "locator": {"source": "S1", "page": 1}})
    sub = next(c for c in t["logic"][1]["cases"] if c["result"] == "subsolid")
    sub["result"] = "does_not_apply"
    p = V._enumerate(Entry.model_validate(t))
    assert any("does_not_apply with no eligibility input settled" in x for x in p)


def test_each_eligibility_input_must_lead_to_does_not_apply(toy):
    """(b) An eligibility input that never decides a does_not_apply combination is not eligibility."""
    t = _eligible_toy(toy)
    t["inputs"].insert(1, {**ELIG, "id": "other", "fact": None})        # declared, never read
    p = V._enumerate(Entry.model_validate(t))
    assert any("other never leads to does_not_apply" in x for x in p)
    assert not any("known_cancer never leads" in x for x in p)


def test_a_does_not_apply_outcome_needs_an_eligibility_input(toy):
    """(c)"""
    t = _copy.deepcopy(toy)
    t["outcomes"].append({"id": "does_not_apply", "classification": "x", "locator": {"source": "S1", "page": 1}})
    assert any("no eligibility input" in x for x in V._eligibility(Entry.model_validate(t)))


def test_the_does_not_apply_text_has_no_placeholder(toy):
    """(d) The exclusion always reads in full: no input can be left unknown in its text."""
    t = _eligible_toy(toy)
    next(o for o in t["outcomes"] if o["id"] == "does_not_apply")["classification"] = "excluded at {risk} risk"
    assert any("placeholder" in x for x in V._eligibility(Entry.model_validate(t)))


def test_an_eligible_toy_passes_the_enumeration_eligibility_checks(toy):
    assert V._enumerate(Entry.model_validate(_eligible_toy(toy))) == []
