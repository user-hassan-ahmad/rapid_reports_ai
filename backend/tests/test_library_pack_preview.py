import pytest

from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP

FINDINGS = "7 mm solid nodule in the right upper lobe."


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.fixture
def jev(monkeypatch):
    st = {"score": 0.9, "fail": False, "calls": 0}

    async def post(payload, key, timeout, transport=None):
        st["calls"] += 1
        if st["fail"]:
            raise TimeoutError("jev slow")
        return _Resp({"answers": {k: {"noul": st["score"]} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def _model(monkeypatch, *items):
    async def call(system, prompt):
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items])
    monkeypatch.setattr(PP, "_call", call)


KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}


async def test_settled_inputs_reach_a_proposal_copied_from_the_entry(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {})
    assert [(s.input, s.value) for s in out.settled] == [("kind", "solid"), ("size", "7 mm"), ("risk", "high")]
    assert out.missing == [] and out.proposal.recommendation == "CT at 6 months"
    assert out.proposal.classification == "Toy 2020 · solid nodule 6-8 mm, high risk"
    assert out.proposal.line == "Toy 2020: solid nodule 6-8 mm, high risk."
    assert out.trace["outcome"] == "ct6" and jev["calls"] == 0       # every quote verbatim: no Jev call


async def test_missing_input_shows_possible_outcomes(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {})
    assert out.proposal is None and out.missing == ["risk"]
    assert out.possible == ["solid nodule 6-8 mm, … risk"] * 2      # ct12 and ct6 render alike while risk is unknown


@pytest.mark.parametrize("value,quote,ok", [(12, "1.2 cm", True), (120, "12 mm", False), (9, "7 mm", False), (1.2, "1.2 cm", False),
                                           (12, "1.2cm", True), (1.2, "1.2cm", False), (8, "8mm", True)])
async def test_number_must_come_from_its_quote(toy_entry, monkeypatch, jev, value, quote, ok):
    _model(monkeypatch, KIND, {"input": "size", "value": value, "quote": quote})
    out = await PP.preview_pack(toy_entry, f"{quote} solid nodule.", "", {})
    assert ("size" in {s.input for s in out.settled}) is ok


async def test_bad_options_and_disallowed_states_are_dropped(toy_entry, monkeypatch, jev):
    _model(monkeypatch, {"input": "kind", "value": "cystic", "quote": "cystic"},
           {"input": "margin", "state": "absent", "quote": "no spiculation"},
           {"input": "ghost", "value": "x", "quote": "x"})
    out = await PP.preview_pack(toy_entry, "cystic lesion, no spiculation, x", "", {})
    assert out.settled == [] and "kind" in out.missing


async def test_the_radiologists_answer_wins(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {"risk": "low"})
    risk = next(s for s in out.settled if s.input == "risk")
    assert (risk.value, risk.quote) == ("low", "") and out.proposal.recommendation == "CT at 12 months"


async def test_band_label_answer(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, "solid nodule", "", {"size": "6-8 mm", "risk": "low"})
    assert out.proposal.recommendation == "CT at 12 months"


async def test_unconfirmed_quote_is_asked(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "heavy smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {})
    assert out.missing == ["risk"] and out.proposal is None


async def test_model_failure_uses_answers_only(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {"kind": "subsolid"})
    assert out.proposal.recommendation == "CT in 12 months"


async def test_entry_defect_gives_no_proposal(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {})
    assert out.proposal is None


def test_as_entry_shows_inputs_as_choices(toy_entry):
    e = PP.as_entry(toy_entry, [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY",
                                 "edition": "2020", "url": "https://example.org/toy"}])
    b = e.content.branches[0]
    assert (e.key, e.status, b.name, b.state) == ("toy-nodule@1.0", "verified", "Pack", "checked")
    opts = {i.id: i.options for i in b.inputs}
    assert opts["size"] == ["<6 mm", "6-8 mm", ">8 mm"] and opts["margin"] == ["smooth", "spiculated", "Not assessable"]
    assert e.sources[0].url == "https://example.org/toy"


async def test_number_quote_not_verbatim_is_asked_even_if_jev_agrees(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, {"input": "size", "value": 7, "quote": "seven millimetres"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {})
    assert "size" in out.missing


async def test_a_settled_outcome_that_cites_an_unknown_input_is_not_proposed(toy_entry, monkeypatch, jev):
    e = toy_entry.model_copy(deep=True)
    e.outcome("subsolid").classification = "subsolid nodule, {risk} risk"     # risk is never asked for subsolid
    _model(monkeypatch)
    out = await PP.preview_pack(e, FINDINGS, "", {"kind": "subsolid"})
    assert out.proposal is None


def test_an_out_of_range_number_is_dropped_so_the_input_is_asked(toy):
    toy["inputs"][1].update(min_value=0, min_inclusive=False)
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    e = Entry.model_validate(toy)
    i = e.input("size")
    assert PP._value(i, PP.RawItem(input="size", value=0, quote="0 mm")) is None
    assert PP._value(i, PP.RawItem(input="size", value=7, quote="7 mm")).value == 7
    assert PP._answer(e, i, "0") is None and PP._answer(e, i, "7").value == 7
