import json

import pytest

from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputValue
from tests.test_library_pack_preview import FINDINGS, _model, jev  # noqa: F401  (fixture)

KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}
RISK = {"input": "risk", "value": "high", "quote": "smoker"}


def _lib(key):
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(key)


async def _s(toy_entry, monkeypatch, *items, history="Smoker."):
    _model(monkeypatch, *items)
    return await PP.settle_pack(toy_entry, FINDINGS, history, finding=FINDINGS)


async def test_a_code_read_number_and_an_option_word_are_read_others_prefilled(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    assert s.values["size"].tier == "read" and s.values["kind"].tier == "read"
    assert s.values["risk"].tier == "prefilled" and PP.WHY_NOT_OPTION_WORD in s.values["risk"].why


async def test_a_jev_failure_reads_nothing_but_keeps_every_proposal(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    assert {k: d.tier for k, d in s.values.items()} == {"kind": "prefilled", "size": "prefilled", "risk": "prefilled"}
    assert all(PP.WHY_NO_CHECK in d.why for d in s.values.values()) and s.failed


async def test_a_low_jev_score_prefills_with_its_reason(toy_entry, monkeypatch, jev):
    jev["score"] = 0.1
    s = await _s(toy_entry, monkeypatch, KIND, SIZE)
    assert s.values["size"].tier == "prefilled" and PP.WHY_UNCONFIRMED in s.values["size"].why
    assert PP.WHY_SEVERAL in s.values["size"].why          # ONE_LESION is in the same batch: also below its bar


async def test_a_quote_not_in_scope_is_still_asked(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, {"input": "kind", "value": "solid", "quote": "solid mass elsewhere"})
    assert "kind" not in s.values


async def test_the_preview_shows_a_draft_and_never_an_apply_able_proposal(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    p = PP.finish(toy_entry, s, {}, None, [])
    assert p.proposal is None and p.draft_outcome.recommendation == "CT at 6 months"
    by = {d.input: d for d in p.draft}
    assert by["size"].state == "read" and by["risk"].state == "prefilled" and by["margin"].state == "asked"
    assert by["margin"].needed is False and PP.NOT_STATED in by["kind"].options
    assert by["size"].quote == "7 mm" and by["risk"].why and by["size"].why == []


async def test_an_answer_wins_over_a_draft_and_not_stated_clears_it(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    p = PP.finish(toy_entry, s, {"risk": "low", "size": PP.NOT_STATED}, None, [])
    by = {d.input: d for d in p.draft}
    assert by["risk"].state == "answered" and by["risk"].value == "low" and by["risk"].quote == ""
    assert by["size"].state == "asked" and by["size"].value == "" and "size" in p.missing


async def test_calculate_uses_only_the_values_sent(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": "7 mm"}, None, [], "b1")   # risk not sent
    assert c.outcome is None and c.result is None and c.needed == ["risk"]
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": "7 mm", "risk": "low"}, None, [], "b1")
    assert c.outcome == "ct12" and c.result.recommendation and c.pack.startswith(toy_entry.key)
    states = {v.input: v.state for v in c.values}
    assert states == {"kind": "read", "size": "read", "risk": "edited", "margin": "asked"}
    assert c.bundle == "b1" and c.trace["outcome"] == "ct12" and c.result.citations


async def test_not_stated_clears_a_drafted_value(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": PP.NOT_STATED, "risk": "high"}, None, [], "b1")
    assert c.outcome is None and "size" in c.needed


def test_calculate_never_fills_an_unsent_input_from_a_shared_patient_answer():
    e = _lib("nhs-aaa-surveillance")
    c = PP.calculate(e, PP.Settlement(), {}, {"sex": "male"}, [], "b1")
    assert {v.input: v.state for v in c.values}["sex"] == "asked"          # not sent: unknown
    c = PP.calculate(e, PP.Settlement(), {"sex": "male"}, {"sex": "male"}, [], "b1")
    assert {v.input: v.state for v in c.values}["sex"] == "answered"       # sent, equal to the shared answer


def test_a_does_not_apply_calculation_is_an_exclusion_never_a_result():
    e = _lib("fleischner-pulmonary-nodule")
    c = PP.calculate(e, PP.Settlement(), {"age": "30"}, None, [], "b1")
    assert c.result is None and c.exclusion is not None and c.outcome == "does_not_apply"


def test_an_exam_preset_is_prefilled_by_the_exam_in_the_draft_and_in_calculate():
    e = _lib("nhs-aaa-surveillance")
    pre = dict(e.exam_presets)
    s = PP.Settlement(values={"diameter_cm": PP.Drafted(InputValue(value=2.4), "aorta 2.4 cm", "read")})
    p = PP.finish(e, s, {}, None, [], presets=pre)
    by = {d.input: d for d in p.draft}
    assert pre and all(by[k].state == "prefilled" and by[k].by == "exam" and by[k].quote == "" for k in pre)
    assert by["diameter_cm"].by == "" and by["diameter_cm"].state == "read"
    shown = {d.input: d.value for d in p.draft if d.value}
    c = PP.calculate(e, s, shown, None, [], "b1", presets=pre)
    cv = {v.input: v for v in c.values}
    assert all(cv[k].state == "prefilled" and cv[k].by == "exam" for k in pre)


def test_not_stated_is_unknown_for_every_input_type(toy_entry):
    for i in toy_entry.inputs:
        assert PP._answer(toy_entry, i, PP.NOT_STATED) == InputValue(state="unknown")


def _tier1():
    raw = json.loads(LB.BUNDLE.read_text())
    lib = LB.Library(raw)
    return [e for e in {lib.lookup(k.split("@")[0]).key: lib.lookup(k.split("@")[0]) for k in raw["entries"]}.values()
            if e.result]


def test_every_assumed_value_round_trips_through_calculate_on_every_pack():
    """Review I1: a value the draft shows as assumed is one Calculate accepts back, as assumed; sending every shown
    value reaches the draft's own outcome; no input is both assumed and still needed."""
    seen = 0
    for e in _tier1():
        for presets in ({}, PP.exam_presets(e, PP.EXAM_CARD)):
            p = PP.finish(e, PP.Settlement(), {}, None, [], presets=presets)
            assumed = {d.input for d in p.draft if d.state == "assumed"}
            assert assumed == set(p.assumptions) and not assumed & set(p.missing), e.key
            assert all(d.value for d in p.draft if d.state == "assumed"), e.key
            shown = {d.input: d.value for d in p.draft if d.value}
            c = PP.calculate(e, PP.Settlement(), shown, None, [], "b1", presets=presets)
            states = {v.input: v.state for v in c.values}
            assert all(states[k] == "assumed" for k in assumed) and set(c.assumptions) == assumed, e.key
            assert c.outcome == (p.trace or {}).get("outcome") and c.needed == p.missing, e.key
            seen += len(assumed)
    assert seen                                                       # some pack assumes something


def test_bts_age_feeds_brock_so_it_is_asked_never_assumed():
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    p = PP.finish(e, PP.Settlement(), {}, None, [])
    by = {d.input: d for d in p.draft}
    assert by["age"].state == "asked" and "age" in p.missing and "age" not in p.assumptions
    assert by["proven_malignant"].state == "assumed"


def test_the_reviewers_bts_repro_reaches_the_same_answer_in_the_draft_and_in_calculate():
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    s = PP.Settlement(values={"nodule_type": PP.Drafted(InputValue(value="solid"), "solid", "read"),
                              "diameter_mm": PP.Drafted(InputValue(value=4.0), "4 mm", "read"),
                              "prior_study": PP.Drafted(InputValue(value=False), "first CT", "prefilled",
                                                        [PP.WHY_KIND])})
    p = PP.finish(e, s, {"benign_features": "No"}, None, [])
    shown = {d.input: d.value for d in p.draft if d.value}
    c = PP.calculate(e, s, shown, None, [], "b1")
    assert c.outcome == (p.trace or {}).get("outcome") and c.needed == p.missing and "age" in p.missing


# Hassan 2026-10-13: only a read, answered or stated eligibility value may exclude; a pre-filled one is a scope doubt
def test_a_prefilled_excluding_eligibility_value_is_a_scope_doubt_not_an_exclusion():
    e = next(x for x in _tier1() if x.id == "rcog-ovarian-mass-premenopausal")
    s = PP.Settlement(values={"pregnant_or_acute": PP.Drafted(InputValue(value=True), "Pelvic pain", "prefilled",
                                                              [PP.WHY_KIND, PP.WHY_UNCONFIRMED])})
    p = PP.finish(e, s, {}, None, [])
    assert p.state == "check_first" and p.exclusion is None and p.scope_doubt == ["pregnant_or_acute"]
    assert (p.trace or {}).get("outcome") != "does_not_apply"
    d = next(x for x in p.draft if x.input == "pregnant_or_acute")
    assert (d.state, d.value, d.quote) == ("prefilled", "Yes", "Pelvic pain") and PP.WHY_WOULD_EXCLUDE in d.why
    assert "pregnant_or_acute" not in p.assumptions
    c = PP.calculate(e, s, {"pregnant_or_acute": "Yes"}, None, [], "b1")       # confirmed by the radiologist
    assert c.outcome == "does_not_apply" and c.exclusion is not None


def test_a_prefilled_known_cancer_never_excludes_and_a_suspicion_is_never_drafted(monkeypatch):
    e = next(x for x in _tier1() if x.id == "ese-adrenal-incidentaloma")
    s = PP.Settlement(values={"known_primary_cancer": PP.Drafted(InputValue(value=True), "renal cancer", "prefilled",
                                                                 [PP.WHY_KIND])})
    p = PP.finish(e, s, {}, None, [])
    assert p.state == "check_first" and p.exclusion is None and p.scope_doubt == ["known_primary_cancer"]
    i = e.input("known_primary_cancer")
    assert PP._hedged_cancer(i, InputValue(value=True), "suspicious for RCC")
    assert not PP._hedged_cancer(i, InputValue(value=True), "known renal cell carcinoma")
    assert not PP._hedged_cancer(i, InputValue(value=False), "suspicious for RCC")
    assert "suspected, possible or differential diagnosis" in PP.SETTLE_SYS


async def test_the_settler_never_drafts_known_cancer_from_a_suspicion_about_another_lesion(monkeypatch, jev):
    e = next(x for x in _tier1() if x.id == "ese-adrenal-incidentaloma")
    finding = "1.4 cm left adrenal nodule."
    dictation = f"{finding} Separate 3 cm right renal mass, suspicious for RCC."
    _model(monkeypatch, {"input": "known_primary_cancer", "value": True, "quote": "suspicious for RCC"})
    s = await PP.settle_pack(e, dictation, "", finding=finding)
    assert "known_primary_cancer" not in s.values                       # asked, never pre-filled yes


def test_a_read_excluding_eligibility_value_still_excludes():
    e = next(x for x in _tier1() if x.id == "fleischner-pulmonary-nodule")
    s = PP.Settlement(values={"age": PP.Drafted(InputValue(value=30.0), "30-year-old", "read")})
    p = PP.finish(e, s, {}, None, [])
    assert p.state == "does_not_apply" and p.exclusion is not None and p.scope_doubt == []
    p = PP.finish(e, PP.Settlement(), {"exclusion": "Yes"}, None, [])                # answered: excludes too
    assert p.state == "does_not_apply"
