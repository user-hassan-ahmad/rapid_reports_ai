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
    elig = [i.id for i in e.inputs if i.role == "eligibility" and i.id in t.needed]
    assert t.needed == elig + [i.id for i in e.inputs if i.id in t.needed and i.id not in elig]   # eligibility first


def test_over_approximation_keeps_outcomes_behind_a_not_applicable_band():
    """New-I1: a band unknown now but not applicable under some enumerated value must be enumerated over its states
    too, else the rules gated on that state (the 2D arm) drop out of `possible`."""
    given = {"prior_study": True, "resolved": False, "interval_days": 547.5, "benign_features": False, "sex": "female",
             "family_history": False, "emphysema": False, "upper_lobe": True, "spiculation": False}
    t = E.evaluate(_bts(), given)
    assert t.bounded is False and len(t.possible) < len(_bts().outcomes)      # not the over-the-cap fallback
    assert {"growth_workup_2d", "ct_2yr_2d", "volumetry_advised"} <= set(t.possible)


def test_unbounded_decides_between_is_every_possible_outcome():
    """New-I2: on an unbounded trace enumeration cannot tell what one input moves, so each needed input decides between
    every outcome still possible (nodule type: solid can still give ct_3m, brock_low or pet_ct, not only subsolid)."""
    t = E.evaluate(_bts(), {"benign_features": False, "prior_study": False, "age": 65, "sex": "female",
                            "family_history": False, "emphysema": False, "upper_lobe": True, "spiculation": False,
                            "nodule_count": 1})
    assert t.bounded is False and "nodule_type" in t.needed
    assert all(t.decides[k] == t.possible for k in t.needed)
    assert {"subsolid", "ct_3m"} <= set(t.decides["nodule_type"])


def test_a_blocked_formula_state_is_monotone():
    """Only not_applicable (final: a prerequisite is definitively false) outranks unknown; not_assessable and absent
    wait for the unknowns, since a later answer could still change which state wins."""
    U, NA = E.UNKNOWN, E.V(state="not_applicable")
    assert E._blocked(["a", "b"], {"a": NA, "b": U}).state == "not_applicable"
    assert E._blocked(["a", "b"], {"a": E.V(state="not_assessable"), "b": U}).state == "unknown"
    assert E._blocked(["a", "b"], {"a": E.V(state="absent"), "b": U}).state == "unknown"
    assert E._blocked(["a", "b"], {"a": E.V(state="absent"), "b": E.V(state="not_assessable")}).state == "not_assessable"


def _bosniak():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("bosniak-renal-cyst")


def test_an_input_behind_an_unknown_prerequisite_is_not_used_until_the_prerequisite_is_known():
    """Controller ruling: contents enhancement only counts on renal mass protocol CT, so with the technique unknown it
    is not used and the technique is asked; on RMP it settles not_cystic."""
    e = _bosniak()
    t = E.evaluate(e, {"too_small": "no", "contents_enhancement": "present"})
    assert t.outcome is None and "technique" in t.needed
    assert t.inputs["contents_enhancement"].state == "unknown"
    t = E.evaluate(e, {"mimic": False, "too_small": "no", "technique": "renal_mass_protocol",
                       "contents_enhancement": "present"})
    assert t.outcome == "not_cystic"


SOLID7 = {"nodule_type": "solid", "diameter_mm": 7}
ELIGIBLE = {"age": 60, "proven_malignant": False}


def test_clinical_asks_are_worked_out_with_eligibility_held_out():
    """Unknown eligibility inputs are asked first; the clinical asks are those of an eligible patient."""
    e = _bts()
    t, ref = E.evaluate(e, SOLID7), E.evaluate(e, {**SOLID7, **ELIGIBLE})
    assert t.outcome is None and t.needed[:2] == ["age", "proven_malignant"]
    assert t.needed[2:] == ref.needed and t.bounded == ref.bounded
    assert "does_not_apply" in t.possible and set(ref.possible) <= set(t.possible)


def test_a_settled_clinical_path_asks_only_eligibility():
    """Benign features settle the clinical path: with age and proven malignancy unknown, only they are asked, and the
    trace stays bounded (no longer the over-the-cap fallback that asked every reaching input)."""
    e = _bts()
    g = {**SOLID7, "benign_features": True, "prior_study": False}
    ref = E.evaluate(e, {**g, **ELIGIBLE})
    t = E.evaluate(e, g)
    assert ref.outcome == "discharge_benign"
    assert t.outcome is None and t.bounded is True and t.needed == ["age", "proven_malignant"]
    assert sorted(t.possible) == ["discharge_benign", "does_not_apply"]


def test_an_excluding_eligibility_value_still_settles_does_not_apply():
    assert E.evaluate(_bts(), {**SOLID7, "proven_malignant": True}).outcome == "does_not_apply"
    assert E.evaluate(_bts(), {**SOLID7, "age": 16}).outcome == "does_not_apply"


def test_held_out_values_come_from_the_entry():
    """The non-excluding values are worked out from the does_not_apply cases, not hard-coded."""
    e = _bts()
    fill, over = E._non_excluding(e, {}, [e.input("age"), e.input("proven_malignant")])
    assert {k: v.value for k, v in fill.items()} == {"proven_malignant": False}
    assert {k: v.value for k, v in over.items()} == {"age_band": "ge18"}


def test_a_pinned_eligibility_number_is_not_enumerated_in_the_second_pass(monkeypatch):
    """Fleischner age is held out through its age_band override: the clinical pass never enumerates age itself (its
    band is pinned, so its values cannot move anything), and the asks are unchanged."""
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    e = LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("fleischner-pulmonary-nodule")
    g = {"nodule_type": "solid", "count": "single", "diameter_mm": 7}
    seen, real = [], E._once

    def spy(entry, given, over=None):
        seen.append(dict(given))
        return real(entry, given, over)
    monkeypatch.setattr(E, "_once", spy)
    t = E.evaluate(e, g)
    assert not any("age" in x for x in seen)
    assert t.outcome is None and t.needed == ["age", "exclusion", "risk"]
