"""Spec §7.12 item 2 (amends §3.6): an eligibility number is assumed at its in-scope band even when the number also
feeds a formula (BTS age, in Brock). The formula still needs the exact number, so it stays asked only when that
formula can still change the outcome. The real case: "Compared with the CT thorax of 12 March 2025. The solid nodule
in the right lower lobe now measures 9 mm, previously 6 mm." BTS was one assumption away from clear growth."""
import json

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import DOES_NOT_APPLY, InputValue


def _lib():
    return LB.Library(json.loads(LB.BUNDLE.read_text()))


def _bts():
    return _lib().lookup("bts-pulmonary-nodule")


def _band_label(e, step_id, band_id):
    return next(b.label for b in e.step(step_id).bands if b.id == band_id)


_GROWTH = {"nodule_type": "solid", "diameter_mm": 9.0, "benign_features": False, "prior_study": True,
           "resolved": False, "growth": "diameter_clear_growth", "spiculation": False, "upper_lobe": False}


def test_bts_growth_case_reaches_growth_workup_2d():
    e = _bts()
    t = E.evaluate(e, _GROWTH, assume_eligible=True)
    assert t.outcome == "growth_workup_2d"
    assert t.assumed["age"] == InputValue(band="ge18")
    assert t.assumed["proven_malignant"] == InputValue(value=False)
    assert t.needed == []


def test_bts_no_prior_still_asks_age_for_brock():
    e = _bts()
    g = {k: v for k, v in _GROWTH.items() if k not in ("growth", "resolved")}
    g["prior_study"] = False
    t = E.evaluate(e, g, assume_eligible=True)
    assert t.outcome is None
    assert "age" in t.needed                                   # Brock needs the exact age
    assert t.assumed["age"] == InputValue(band="ge18")
    assert DOES_NOT_APPLY not in t.possible                    # the age band is assumed in scope, not held out


def test_bts_age_band_answer_pins_the_band_and_brock_still_asks_the_number():
    """An age sent back as its assumed band (Calculate) pins the band: the growth path needs nothing more, while a
    Brock path still asks the exact age (never a dead end)."""
    e = _bts()
    t = E.evaluate(e, {**_GROWTH, "age": InputValue(band="ge18"), "proven_malignant": False})
    assert t.outcome == "growth_workup_2d"
    g = {k: v for k, v in _GROWTH.items() if k not in ("growth", "resolved")}
    t = E.evaluate(e, {**g, "prior_study": False, "age": InputValue(band="ge18"), "proven_malignant": False})
    assert t.outcome is None and "age" in t.needed
    assert E.evaluate(e, {**g, "age": InputValue(band="lt18")}).outcome == DOES_NOT_APPLY


def test_fleischner_age_unchanged():
    f = _lib().lookup("fleischner-pulmonary-nodule")
    g = {"nodule_type": "solid", "count": "single", "diameter_mm": 7, "risk": "low", "exclusion": False,
         "prior_growth": False}
    t = E.evaluate(f, g, assume_eligible=True)
    assert t.outcome == "solid_single_6to8_low" and t.assumed == {"age": InputValue(band="ge35")}
    assert E.evaluate(f, {**g, "age": 30}, assume_eligible=True).outcome == DOES_NOT_APPLY
    assert E.evaluate(f, {**g, "age": 60}).outcome == "solid_single_6to8_low"


def _drafted():
    read = {"nodule_type": "solid", "diameter_mm": 9.0, "growth": "diameter_clear_growth"}
    pre = {"benign_features": False, "prior_study": True, "resolved": False, "upper_lobe": False}
    out = {k: PP.Drafted(InputValue(value=v), str(v), "read") for k, v in read.items()}
    out.update({k: PP.Drafted(InputValue(value=v), str(v), "prefilled", [PP.WHY_KIND]) for k, v in pre.items()})
    return out


def test_preview_shows_age_assumed_at_its_band_and_drafts_clear_growth():
    e = _bts()
    p = PP.finish(e, PP.Settlement(values=_drafted()), {}, {}, [])
    age = next(d for d in p.draft if d.input == "age")
    assert age.state == "assumed" and age.value == _band_label(e, "age_band", "ge18")
    assert age.decisive is True
    assert p.trace["outcome"] == "growth_workup_2d" and p.draft_outcome is not None
    assert p.most_likely is not None and p.most_likely.headline == e.outcome("growth_workup_2d").headline
    assert "age" in {a.input for a in p.assumptions if a.decisive}


def test_calculate_takes_the_assumed_band_back_unchanged():
    e = _bts()
    s = PP.Settlement(values=_drafted())
    p = PP.finish(e, s, {}, {}, [])
    values = {d.input: d.value for d in p.draft if d.value}
    c = PP.calculate(e, s, values, {}, [], "b1")
    assert c.outcome == "growth_workup_2d"
    age = next(v for v in c.values if v.input == "age")
    assert age.state == "assumed" and age.value == _band_label(e, "age_band", "ge18")
