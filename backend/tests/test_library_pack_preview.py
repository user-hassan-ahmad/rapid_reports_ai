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


def test_settled_list_returned_as_json_text_is_parsed():
    raw = PP.RawSettle.model_validate({"settled": '[{"input": "kind", "value": "solid", "quote": "solid"}]'})
    assert [(r.input, r.value) for r in raw.settled] == [("kind", "solid")]


@pytest.mark.parametrize("unit,value,quote,ok", [
    ("count", 1, "Solitary nodule", True), ("count", 2, "two nodules", True), ("count", 3, "two nodules", False),
    ("count", 1, "No other nodules", False), ("count", 1, "no other abnormality", False),
    ("mm", 7, "seven millimetres", False), ("mm", 1, "single nodule", False), ("", 1, "single nodule", False),
    ("nodules", 1, "Solitary nodule", False)])
def test_a_count_may_be_dictated_in_words_but_a_measurement_may_not(unit, value, quote, ok):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    i = InputDef(id="n", label="N", type="number", unit=unit, min_value=0, min_inclusive=False)
    assert (PP._value(i, PP.RawItem(input="n", value=value, quote=quote)) is not None) is ok


def test_bosniak_says_a_described_mass_is_not_too_small():
    from rapid_reports_ai.hybrid_stack.copilot.library.bundle import compile_bundle, Library
    e = Library(compile_bundle()).lookup("bosniak-renal-cyst")
    assert "no when the mass is described by its features" in e.input("too_small").how_stated


async def test_an_unbounded_preview_says_so_and_asks_every_reaching_input(monkeypatch, jev):
    from tests.test_library_partial import BTS_BROCK, _bts
    e = _bts()
    _model(monkeypatch, {"input": "diameter_mm", "value": 10, "quote": "10 mm"},
           {"input": "nodule_type", "value": "solid", "quote": "solid"},
           {"input": "benign_features", "value": False, "quote": "no benign features"},
           {"input": "prior_study", "value": False, "quote": "no prior"})
    out = await PP.preview_pack(e, "10 mm solid nodule, no benign features, no prior imaging.", "", {})
    assert out.proposal is None and out.bounded is False and BTS_BROCK <= set(out.missing)


async def test_a_bounded_preview_says_so(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    assert (await PP.preview_pack(toy_entry, FINDINGS, "", {})).bounded is True


@pytest.mark.parametrize("input_id", ["diameter_mm", "interval_days"])
def test_a_number_that_feeds_a_formula_offers_no_band_labels(input_id):
    """I5: a band answer cannot feed the formula the number also feeds (size_term, vdt_days), so it would dead-end.
    Only a typed value is offered and accepted."""
    from tests.test_library_partial import _bts
    e = _bts()
    i = e.input(input_id)
    labels = [b.label for s in e.logic if getattr(s, "ref", None) == input_id for b in s.bands]
    assert labels                                                  # the pack does band this number
    assert PP.display_options(e, i) == [PP._STATE_LABEL[s] for s in i.states]
    assert all(PP._answer(e, i, lab) is None for lab in labels)
    assert PP._answer(e, i, "10").value == 10


def test_a_number_that_feeds_band_steps_only_keeps_its_band_labels(toy_entry):
    assert PP.display_options(toy_entry, toy_entry.input("size")) == ["<6 mm", "6-8 mm", ">8 mm"]
    assert PP._answer(toy_entry, toy_entry.input("size"), "6-8 mm").band == "6to8"


# ── I6 and citations: caveats travel with the proposal; every ask and outcome carries its citation ─────────────────

TOY_SOURCES = [{"id": "S1", "role": "primary", "title": "Toy guideline", "issuer": "TOY", "edition": "2020",
                "url": "https://example.org/toy"},
               {"id": "S2", "role": "explanatory", "title": "Toy review", "issuer": "Other", "edition": "2021",
                "url": ""}]
P2 = {"source": "S1", "title": "Toy guideline", "issuer": "TOY", "edition": "2020", "url": "https://example.org/toy",
      "page": 2}
P3 = {**P2, "page": 3}


def _with_caveat(toy, caveat):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    d = {**toy, "outcomes": [{**o, "caveats": [caveat]} if o["id"] == "ct6" else o for o in toy["outcomes"]]}
    return Entry.model_validate(d)


async def test_the_proposal_carries_rendered_caveats_and_the_fired_citations(toy, monkeypatch, jev):
    e = _with_caveat(toy, "Only for {risk} risk adults.")
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(e, FINDINGS, "Smoker.", {}, TOY_SOURCES)
    assert out.proposal.caveats == ["Only for high risk adults."]
    cites = out.proposal.citations
    assert {**P3, "step": "plan"} in cites and {**P2, "step": "size_band"} in cites
    assert {**P2, "step": "outcome"} in cites
    assert all(c["title"] == "Toy guideline" for c in cites)


async def test_a_caveat_with_an_unfilled_placeholder_blocks_the_proposal(toy, monkeypatch, jev):
    e = _with_caveat(toy, "Only for {margin} margins.")
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(e, FINDINGS, "Smoker.", {}, TOY_SOURCES)
    assert out.proposal is None


async def test_each_missing_input_is_asked_with_its_definition_outcomes_and_citations(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, TOY_SOURCES)
    assert out.missing == ["risk"]                                        # kept for compatibility
    assert out.asks == [{
        "input": "risk", "label": "Patient risk", "definition": {"text": "", "citation": {}},
        "options": ["low", "high"],
        "decides_between": [{"outcome": "ct12", "classification": "solid nodule 6-8 mm, … risk", "citation": P2},
                            {"outcome": "ct6", "classification": "solid nodule 6-8 mm, … risk", "citation": P2}],
        "citations": [P3]}]


async def test_bts_asks_carry_citations_for_every_brock_input(monkeypatch, jev):
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    from tests.test_library_partial import BTS_BROCK
    lib = LB.Library(json.loads(LB.BUNDLE.read_text()))
    e = lib.lookup("bts-pulmonary-nodule")
    _model(monkeypatch, {"input": "diameter_mm", "value": 10, "quote": "10 mm"},
           {"input": "nodule_type", "value": "solid", "quote": "solid"},
           {"input": "benign_features", "value": False, "quote": "no benign features"},
           {"input": "prior_study", "value": False, "quote": "no prior"})
    out = await PP.preview_pack(e, "10 mm solid nodule, no benign features, no prior imaging.", "", {},
                                lib.sources(e.key))
    asks = {a["input"]: a for a in out.asks}
    assert BTS_BROCK <= set(asks) and [a["input"] for a in out.asks] == out.missing
    for k in BTS_BROCK:
        assert asks[k]["citations"] and all(c.get("title") for c in asks[k]["citations"])
        assert asks[k]["decides_between"] and all("{" not in d["classification"] for d in asks[k]["decides_between"])


def test_a_count_shows_as_a_bare_number():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry, InputDef, InputValue
    from tests.test_library_partial import _bts
    e = _bts()
    assert PP._show(e, e.input("nodule_count"), InputValue(value=1.0)) == "1"
    assert PP._show(e, e.input("diameter_mm"), InputValue(value=9.0)) == "9 mm"
