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


def test_only_the_doubtful_value_leaves_the_draft_other_prefilled_values_stay():
    """Review I-b: a Jev outage pre-fills everything; age 64 stays in the draft, only proven_malignant is the doubt."""
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    P = lambda v, q: PP.Drafted(InputValue(value=v), q, "prefilled", [PP.WHY_NO_CHECK])   # noqa: E731
    s = PP.Settlement(values={"age": P(64.0, "64-year-old"), "proven_malignant": P(True, "biopsy-proven"),
                              "nodule_type": P("solid", "solid"), "diameter_mm": P(4.0, "4 mm"),
                              "benign_features": P(False, "no calcification"), "prior_study": P(False, "no previous")})
    p = PP.finish(e, s, {}, None, [])
    assert p.scope_doubt == ["proven_malignant"] and p.state == "check_first" and p.exclusion is None
    assert "age" not in p.missing and p.draft_outcome is not None
    by = {d.input: d for d in p.draft}
    assert by["age"].state == "prefilled" and by["age"].needed is False


@pytest.mark.parametrize("pack,extra", [
    ("bts-pulmonary-nodule", {"age": "64", "proven_malignant": "No", "nodule_type": "solid", "prior_study": "No",
                              "benign_features": "No"}),
    ("fleischner-pulmonary-nodule", {"age": "64", "exclusion": "No", "nodule_type": "solid", "count": "single",
                                     "risk": "low"})])
def test_a_prefilled_clinical_value_never_excludes_but_a_read_one_does(pack, extra):
    """Review I-c: a pre-filled diameter over 3 cm is a scope doubt, never an exclusion; read, it excludes."""
    e = next(x for x in _tier1() if x.id == pack)
    for tier, want in (("prefilled", "check_first"), ("read", "does_not_apply")):
        s = PP.Settlement(values={"diameter_mm": PP.Drafted(InputValue(value=35.0), "35 mm", tier,
                                                            [PP.WHY_OTHER_NUMBER] if tier == "prefilled" else [])})
        p = PP.finish(e, s, extra, None, [])
        assert p.state == want, (pack, tier)
        assert (p.scope_doubt == ["diameter_mm"]) is (tier == "prefilled") and (p.exclusion is None) is (
            tier == "prefilled")
        if tier == "prefilled":
            d = next(x for x in p.draft if x.input == "diameter_mm")
            assert d.value == "35 mm" and PP.WHY_WOULD_EXCLUDE in d.why


def test_the_hedge_backstop_reads_the_sentence_around_a_short_quote():
    e = next(x for x in _tier1() if x.id == "ese-adrenal-incidentaloma")
    i = e.input("known_primary_cancer")
    texts = ["1.4 cm left adrenal nodule. Separate 3 cm right renal mass, suspicious for RCC.", ""]
    assert PP._hedged_cancer(i, InputValue(value=True), "RCC", texts)
    assert not PP._hedged_cancer(i, InputValue(value=True), "RCC", ["Known metastatic RCC on treatment.", ""])


@pytest.mark.parametrize("text,quote,hedged", [
    ("Breast ca ?liver mets.", "Breast ca", False),                     # the cancer is stated; the mets are queried
    ("Lung ca ?mets.", "Lung ca", False),
    ("Colorectal cancer, likely nodal recurrence.", "Colorectal cancer", False),
    ("Renal mass 3.5 cm, suspicious for RCC.", "RCC", True),            # a decimal never cuts the sentence
    ("Liver lesions ?primary.", "primary", True),
    ("Known metastatic RCC on treatment.", "RCC", False)])
def test_the_hedge_backstop_reads_only_the_quote_and_the_words_before_it(text, quote, hedged):
    e = next(x for x in _tier1() if x.id == "ese-adrenal-incidentaloma")
    assert PP._hedged_cancer(e.input("known_primary_cancer"), InputValue(value=True), quote, [text, ""]) is hedged


async def test_the_draft_outcome_and_the_result_carry_the_display_fields(toy_entry, monkeypatch, jev):
    s = await _s(toy_entry, monkeypatch, KIND, SIZE, RISK)
    p = PP.finish(toy_entry, s, {}, None, [])
    o = p.draft_outcome
    assert (o.headline, o.action, o.category) == ("Solid nodule, high risk", "CT at 6 months", "surveillance")
    c = PP.calculate(toy_entry, s, {"kind": "solid", "size": "7 mm", "risk": "low"}, None, [], "b1")
    assert (c.result.headline, c.result.category) == ("Solid nodule, low risk", "surveillance")


def test_every_tier_1_pack_outcome_has_display_fields_and_info_marks_no_management():
    cats = {}
    for e in _tier1():
        for o in e.outcomes:
            assert o.headline and o.action and o.category, (e.key, o.id)
            cats[(e.id, o.id)] = o.category
    assert cats[("salter-harris", "sh4_through_plate")] == "info" and cats[("sins", "b0_6")] == "info"
    assert cats[("cad-rads-2", "stable_3_e")] == "info" and cats[("pi-rads-2-1", "pirads_3")] == "info"
    assert cats[("pi-rads-2-1", "pirads_1")] == "none" and cats[("bts-pulmonary-nodule", "discharge_small")] == "none"


# Hassan 2026-10-13: silence policy for visible signs; most likely + the deciding question
def _bts6(**extra):
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    R = lambda v, q: PP.Drafted(InputValue(value=v), q, "read")                       # noqa: E731
    return e, PP.Settlement(values={"diameter_mm": R(6.0, "6 mm"), "nodule_type": R("solid", "solid"),
                                    "age": R(65.0, "65"), **extra})


def test_an_unstated_visible_sign_is_assumed_absent_and_the_most_likely_outcome_follows():
    e, s = _bts6(prior_study=PP.Drafted(InputValue(value=False), "no previous imaging", "prefilled", [PP.WHY_KIND]))
    p = PP.finish(e, s, {}, None, [])
    by = {d.input: d for d in p.draft}
    assert (by["benign_features"].state, by["benign_features"].value) == ("assumed", "No")
    assert by["benign_features"].why == [PP.WHY_ASSUMED_ABSENT] and "benign_features" in p.assumptions
    assert p.draft_outcome.category == "surveillance" and p.most_likely.category == "surveillance"
    assert p.most_likely.headline == p.draft_outcome.headline and p.deciding == [] and p.deciding_input is None
    assert len(p.possible) == 2                                    # "show all": benign discharge is still possible
    assert p.assumed_eligible is True and p.state == "check_first"  # proven_malignant; the signs are not eligibility
    stated = PP.finish(e, s, {"benign_features": "Yes"}, None, [])  # a stated value wins over the assumption
    assert "benign_features" not in stated.assumptions and stated.most_likely.category == "none"


def test_with_several_outcomes_left_the_deciding_question_splits_them():
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    R = lambda v, q: PP.Drafted(InputValue(value=v), q, "read")                       # noqa: E731
    s = PP.Settlement(values={"diameter_mm": R(6.0, "6 mm"), "age": R(65.0, "65")})
    p = PP.finish(e, s, {"prior_study": "No"}, None, [])
    assert p.most_likely is None and p.deciding_input.input == "nodule_type"
    assert p.deciding_input.label == e.input("nodule_type").label and 1 <= len(p.deciding) <= PP.MAX_DECIDING
    solid = next(d for d in p.deciding if "solid" in d.answer.split(" / "))
    assert solid.category == "surveillance" and solid.headline
    e, s = _bts6()
    p = PP.finish(e, s, {}, None, [])                     # prior CT unknown: unbounded, too costly to weigh (I-3)
    assert p.deciding_input is None and p.deciding == []


def test_ese_and_bosniak_deciding_and_signs():
    e = next(x for x in _tier1() if x.id == "ese-adrenal-incidentaloma")
    s = PP.Settlement(values={"size_cm": PP.Drafted(InputValue(value=2.4), "2.4 cm", "read")})
    p = PP.finish(e, s, {}, None, [])
    assert p.deciding_input.input == "appearance"
    assert any(d.answer == "clearly_benign" and d.category == "none" for d in p.deciding)
    b = next(x for x in _tier1() if x.id == "bosniak-renal-cyst")
    p = PP.finish(b, PP.Settlement(), {}, None, [])
    shown = {d.input: (d.state, d.value) for d in p.draft}
    assert shown["calcification"] == ("assumed", "none") and "calcification" in p.assumptions
    assert shown["septa"][0] == shown["protrusion"][0] == "asked"     # review I-1: septa and protrusion stay asked


def test_calculate_labels_a_sign_sent_back_as_assumed_and_gives_the_deciding_question():
    e, s = _bts6()
    sent = {"diameter_mm": "6 mm", "age": "65", "benign_features": "No", "prior_study": "No", "proven_malignant": "No"}
    c = PP.calculate(e, s, sent, None, [], "b1")
    assert {v.input: v.state for v in c.values}["benign_features"] == "assumed"
    s2 = PP.Settlement(values={k: v for k, v in s.values.items() if k != "nodule_type"})
    c = PP.calculate(e, s2, sent, None, [], "b1")
    assert c.outcome is None and c.deciding_input.input == "nodule_type" and c.deciding
    # review M-3: an explicit "No" is answered, never assumed, even though it equals the assumption
    c = PP.calculate(e, s, sent, None, [], "b1", answered={"benign_features": "No"})
    assert {v.input: v.state for v in c.values}["benign_features"] == "answered"


def test_not_stated_on_a_visible_sign_asks_it_and_never_re_assumes_it():
    """Review M-2."""
    e, s = _bts6(prior_study=PP.Drafted(InputValue(value=False), "no previous imaging", "prefilled", [PP.WHY_KIND]))
    p = PP.finish(e, s, {"benign_features": PP.NOT_STATED}, None, [])
    d = next(x for x in p.draft if x.input == "benign_features")
    assert d.state == "asked" and "benign_features" not in p.assumptions and "benign_features" in p.missing


def test_a_papillary_mention_without_a_count_is_unknown_never_assumed_no():
    """Review I-2: m3_four_papillary is not a visible sign (its definition leaves a count-less mention unknown)."""
    e = next(x for x in _tier1() if x.id == "rcog-ovarian-mass-premenopausal")
    assert not e.input("m3_four_papillary").visible_sign
    p = PP.finish(e, PP.Settlement(), {}, None, [])
    assert next(x for x in p.draft if x.input == "m3_four_papillary").state != "assumed"
    assert "m3_four_papillary" not in p.assumptions
    assert {"m2_ascites", "b3_acoustic_shadowing"} <= set(p.assumptions)


def test_the_bts_answer_path_with_prior_ct_unknown_stays_fast():
    """Review I-3: 10 mm solid, prior CT unknown: about 1 s a tap before the cap; generous bound."""
    import time
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    R = lambda v, q: PP.Drafted(InputValue(value=v), q, "read")                       # noqa: E731
    s = PP.Settlement(values={"diameter_mm": R(10.0, "10 mm"), "nodule_type": R("solid", "solid"),
                              "age": R(65.0, "65")})
    worst = 0.0
    for ans in ({}, {"sex": "female"}, {"sex": "female", "family_history": "No"}):
        t0 = time.perf_counter()
        PP.finish(e, s, ans, None, [])
        worst = max(worst, time.perf_counter() - t0)
    assert worst < 0.4


def test_a_visible_sign_is_a_yes_no_or_a_choice_naming_its_absent_option():
    import pydantic
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    assert InputDef(id="s", label="S", type="boolean", visible_sign=True).absent_value() == InputValue(value=False)
    assert InputDef(id="c", label="C", type="enum", options=["none", "present"], visible_sign=True,
                    absent_option="none").absent_value() == InputValue(value="none")
    for bad in ({"type": "number", "visible_sign": True}, {"type": "enum", "options": ["a"], "visible_sign": True},
                {"type": "boolean", "absent_option": "x"}):
        with pytest.raises(pydantic.ValidationError):
            InputDef(id="x", label="X", **bad)


# live checkpoint 4: say which value excludes
def test_a_bts_mass_says_its_diameter_is_the_reason():
    e = next(x for x in _tier1() if x.id == "bts-pulmonary-nodule")
    s = PP.Settlement(values={"diameter_mm": PP.Drafted(InputValue(value=38.0), "3.8 cm", "read")})
    p = PP.finish(e, s, {}, None, [])
    assert p.state == "does_not_apply" and p.exclusion_reason.model_dump() == {
        "input": "diameter_mm", "label": e.input("diameter_mm").label, "value": "38 mm"}
    c = PP.calculate(e, s, {"diameter_mm": "38 mm"}, None, [], "b1")
    assert c.exclusion is not None and c.exclusion_reason.input == "diameter_mm"


def test_fleischner_screening_and_age_exclusions_say_which():
    e = next(x for x in _tier1() if x.id == "fleischner-pulmonary-nodule")
    p = PP.finish(e, PP.Settlement(), {"exclusion": "Yes", "age": "60"}, None, [])
    assert p.state == "does_not_apply" and (p.exclusion_reason.input, p.exclusion_reason.value) == ("exclusion", "Yes")
    s = PP.Settlement(values={"age": PP.Drafted(InputValue(value=30.0), "30-year-old", "read")})
    p = PP.finish(e, s, {}, None, [])
    assert (p.exclusion_reason.input, p.exclusion_reason.value) == ("age", "30 years")
    p = PP.finish(e, PP.Settlement(), {"exclusion": "Yes", "age": "30"}, None, [])   # two reasons: none attributable
    assert p.state == "does_not_apply" and p.exclusion_reason is None


def test_an_eligibility_exclusion_names_its_input_and_an_open_card_has_none():
    e = next(x for x in _tier1() if x.id == "rcog-ovarian-mass-premenopausal")
    p = PP.finish(e, PP.Settlement(), {"pregnant_or_acute": "Yes"}, None, [])
    assert p.state == "does_not_apply" and p.exclusion_reason.input == "pregnant_or_acute"
    assert PP.finish(e, PP.Settlement(), {}, None, []).exclusion_reason is None
