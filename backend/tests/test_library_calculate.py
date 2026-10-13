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
