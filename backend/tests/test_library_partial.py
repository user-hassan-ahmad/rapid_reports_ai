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
    assert t.needed == ["kind", "size"] and t.waiting == ["risk"]   # margin never changes the outcome: never asked
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
        "id": "t", "version": "1", "topic": "t", "purpose": "Toy test entry.", "issuer": "T", "system": "T", "display": "T", "edition": "1", "tier": 1,
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


def _bts():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup("bts-pulmonary-nodule")


def test_a_child_behind_an_unknown_parent_waits_and_the_parent_is_asked(toy_entry):
    t = E.evaluate(toy_entry, {})
    assert t.needed == ["kind", "size"] and t.waiting == ["risk"]      # kind is risk's parent: asked, first


def test_a_known_parent_releases_its_child(toy_entry):
    t = E.evaluate(toy_entry, {"kind": "solid"})
    assert t.needed == ["size", "risk"] and t.waiting == []


def test_bts_follow_up_inputs_wait_for_prior_study():
    e = _bts()
    t = E.evaluate(e, {})
    follow_up = {"resolved", "growth", "prior_volume_mm3", "current_volume_mm3", "interval_days"}
    assert not follow_up & set(t.needed) and follow_up <= set(t.waiting)
    assert t.needed[:3] == ["age", "proven_malignant", "prior_study"]   # eligibility, then the parent
    t = E.evaluate(e, {"age": 60, "proven_malignant": False, "prior_study": True})
    assert "resolved" in t.needed and "resolved" not in t.waiting


def _packs():
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    raw = json.loads(LB.BUNDLE.read_text())
    lib = LB.Library(raw)
    current = [lib.lookup(k.split("@")[0]) for k in sorted(raw["entries"])]
    return [e for e in {e.key: e for e in current}.values() if e.result]     # tier 1 (computed) packs only


def _golden(e):
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "guidelines" / e.id / "cases.json"
    return [c["inputs"] for c in json.loads(p.read_text())["cases"]] if p.exists() else []


def test_parents_first_never_leaves_an_open_bounded_card_with_nothing_to_ask(toy_entry):
    for given in ({}, {"size": 7}, {"kind": "solid"}):
        t = E.evaluate(toy_entry, given)
        assert t.outcome is not None or t.needed
    for e in _packs():                                  # every pack, empty and on each golden case's inputs
        for given in [{}] + _golden(e):
            t = E.evaluate(e, given)
            assert t.outcome is not None or not t.bounded or t.needed, (e.key, given)
            assert not set(t.needed) & set(t.waiting), (e.key, given)


def test_an_input_with_a_value_never_waits_but_its_unknown_parent_is_asked():
    t = E.evaluate(_bts(), {"age": 60, "proven_malignant": False, "resolved": False})
    assert "resolved" not in t.waiting and "prior_study" in t.needed
    bosniak = next(e for e in _packs() if e.id == "bosniak-renal-cyst")
    t = E.evaluate(bosniak, {"technique": "renal_mass_protocol"})     # the CT exam preset
    assert "technique" not in t.waiting and "too_small" in t.needed


def test_a_gate_that_can_settle_the_exam_is_asked_straight_after_eligibility():
    pirads = next(e for e in _packs() if e.id == "pi-rads-2-1")
    assert E.gates(pirads) == {"finding_above_1"}      # no finding above 1 settles the exam at PI-RADS 1
    t = E.evaluate(pirads, {})
    assert t.needed[:2] == ["treated_cancer", "finding_above_1"]        # eligibility, then the gate, then zone, dwi
    assert E.evaluate(pirads, {"treated_cancer": False}).needed[0] == "finding_above_1"


def test_assume_eligible_drafts_for_an_eligible_patient_and_a_stated_value_wins():
    fl = next(e for e in _packs() if e.id == "fleischner-pulmonary-nodule")
    t = E.evaluate(fl, {}, assume_eligible=True)
    assert set(t.assumed) == {"age", "exclusion"} and t.assumed["age"].band == "ge35"      # a number: by its band
    assert not {"age", "exclusion"} & set(t.needed) and "does_not_apply" not in t.possible
    t = E.evaluate(fl, {"age": 30}, assume_eligible=True)                                 # stated: excludes
    assert t.outcome == "does_not_apply" and "age" not in t.assumed
    assert E.evaluate(fl, {}).assumed == {}                                               # off by default


def test_an_exclusion_reading_an_unknown_clinical_input_does_not_block_the_in_scope_assumption():
    """BTS: an opacity over 3 cm is a mass (does_not_apply reads diameter_mm). With the size unknown, the eligible
    value of proven_malignant is still the in-scope one; with a 38 mm size the card is excluded."""
    e = _bts()
    t = E.evaluate(e, {"nodule_type": "solid"}, assume_eligible=True)
    assert t.assumed["proven_malignant"].value is False and "diameter_mm" in t.needed
    assert E.evaluate(e, {"nodule_type": "solid", "diameter_mm": 38, "age": 60, "proven_malignant": False,
                          "prior_study": False}).outcome == "does_not_apply"
