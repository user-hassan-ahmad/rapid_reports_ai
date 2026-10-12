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
    st = {"score": 0.9, "fail": False, "fail_if": None, "deny": [], "calls": 0, "payloads": []}

    async def post(payload, key, timeout, transport=None):
        st["calls"] += 1
        st["payloads"].append(payload)
        if st["fail"] or (st["fail_if"] and st["fail_if"] in payload["state"]):
            raise TimeoutError("jev slow")
        return _Resp({"answers": {k: {"noul": 0.1 if any(d in q["instructions"] for d in st["deny"]) else st["score"]}
                                  for k, q in payload["questions"].items()}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def _model(monkeypatch, *items, prompts=None):
    async def call(system, prompt):
        if prompts is not None:
            prompts.append(prompt)
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items])
    monkeypatch.setattr(PP, "_call", call)


KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}


async def test_settled_inputs_reach_a_proposal_copied_from_the_entry(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {}, finding=FINDINGS)
    assert [(s.input, s.value) for s in out.settled] == [("kind", "solid"), ("size", "7 mm"), ("risk", "high")]
    assert out.missing == [] and out.proposal.recommendation == "CT at 6 months"
    assert out.proposal.classification == "Toy 2020 · solid nodule 6-8 mm, high risk"
    assert out.proposal.line == "Toy 2020: solid nodule 6-8 mm, high risk."
    assert out.trace["outcome"] == "ct6" and jev["calls"] == 2       # one batched value check per scope


async def test_missing_input_shows_possible_outcomes(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
    assert out.proposal is None and out.missing == ["risk"]
    assert out.possible == ["solid nodule 6-8 mm, … risk"] * 2      # ct12 and ct6 render alike while risk is unknown


async def test_bad_options_and_disallowed_states_are_dropped(toy_entry, monkeypatch, jev):
    _model(monkeypatch, {"input": "kind", "value": "cystic", "quote": "cystic"},
           {"input": "margin", "state": "absent", "quote": "no spiculation"},
           {"input": "ghost", "value": "x", "quote": "x"})
    out = await PP.preview_pack(toy_entry, "cystic lesion, no spiculation, x", "", {}, finding="cystic lesion, no spiculation, x")
    assert out.settled == [] and "kind" in out.missing


async def test_the_radiologists_answer_wins(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {"risk": "low"}, finding=FINDINGS)
    risk = next(s for s in out.settled if s.input == "risk")
    assert (risk.value, risk.quote) == ("low", "") and out.proposal.recommendation == "CT at 12 months"


async def test_band_label_answer(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, "solid nodule", "", {"size": "6-8 mm", "risk": "low"}, finding="solid nodule")
    assert out.proposal.recommendation == "CT at 12 months"


async def test_unconfirmed_values_are_asked(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "heavy smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Heavy smoker.", {}, finding=FINDINGS)
    assert "kind" in out.missing and out.proposal is None and out.degraded is True
    assert out.settled == []                                   # a number is put to Jev too: a failed check asks it


async def test_model_failure_uses_answers_only(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {"kind": "subsolid"}, finding=FINDINGS)
    assert out.proposal.recommendation == "CT in 12 months"
    assert out.degraded is True


async def test_entry_defect_gives_no_proposal(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
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
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
    assert "size" in out.missing


async def test_a_settled_outcome_that_cites_an_unknown_input_is_not_proposed(toy_entry, monkeypatch, jev):
    e = toy_entry.model_copy(deep=True)
    e.outcome("subsolid").classification = "subsolid nodule, {risk} risk"     # risk is never asked for subsolid
    _model(monkeypatch)
    out = await PP.preview_pack(e, FINDINGS, "", {"kind": "subsolid"}, finding=FINDINGS)
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


@pytest.mark.parametrize("unit,quote,want", [
    ("count", "Solitary nodule", 1), ("count", "two nodules", 2), ("count", "No other nodules", None),
    ("count", "no other abnormality", None), ("mm", "seven millimetres", None), ("mm", "single nodule", None),
    ("", "single nodule", None), ("nodules", "Solitary nodule", None)])
def test_a_count_may_be_dictated_in_words_but_a_measurement_may_not(unit, quote, want):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    i = InputDef(id="n", label="N", type="number", unit=unit, min_value=0, min_inclusive=False)
    v = PP._value(i, PP.RawItem(input="n", value=None, quote=quote))
    assert (v.value if v is not None else None) == want


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
    out = await PP.preview_pack(e, "10 mm solid nodule, no benign features, no prior imaging.", "", {}, finding="10 mm solid nodule, no benign features, no prior imaging.")
    assert out.proposal is None and out.bounded is False and BTS_BROCK <= set(out.missing)


async def test_a_bounded_preview_says_so(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    assert (await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)).bounded is True


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
    out = await PP.preview_pack(e, FINDINGS, "Smoker.", {}, TOY_SOURCES, finding=FINDINGS)
    assert out.proposal.caveats == ["Only for high risk adults."]
    cites = out.proposal.citations
    assert {**P3, "step": "plan"} in cites and {**P2, "step": "size_band"} in cites
    assert {**P2, "step": "outcome"} in cites
    assert all(c["title"] == "Toy guideline" for c in cites)


async def test_a_caveat_with_an_unfilled_placeholder_blocks_the_proposal(toy, monkeypatch, jev):
    e = _with_caveat(toy, "Only for {margin} margins.")
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(e, FINDINGS, "Smoker.", {}, TOY_SOURCES, finding=FINDINGS)
    assert out.proposal is None


async def test_each_missing_input_is_asked_with_its_definition_outcomes_and_citations(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, TOY_SOURCES, finding=FINDINGS)
    assert out.missing == ["risk"]                                        # kept for compatibility
    assert out.asks == [{
        "input": "risk", "label": "Patient risk", "role": "clinical", "scope": "patient", "fact": "",
        "definition": {"text": "", "citation": {}},
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
                                lib.sources(e.key), finding="10 mm solid nodule, no benign features, no prior imaging.")
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


FINDING = "7 mm solid nodule in the right upper lobe."
TWO = FINDING + " Separately, a 12 mm densely calcified granuloma in the left lower lobe."


async def test_a_lesion_value_quoted_from_another_finding_is_asked(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, {"input": "size", "value": 12, "quote": "12 mm densely calcified granuloma"})
    out = await PP.preview_pack(toy_entry, TWO, "", {}, finding=FINDING)
    assert "size" not in {s.input for s in out.settled} and "size" in out.missing


async def test_a_patient_value_may_quote_the_history(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    assert out.proposal.recommendation == "CT at 6 months"


async def test_without_a_finding_lesion_inputs_are_asked_never_read_from_the_dictation(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, KIND, {"input": "size", "value": 12, "quote": "12 mm densely calcified granuloma"},
           {"input": "risk", "value": "high", "quote": "smoker"}, prompts=prompts)
    out = await PP.preview_pack(toy_entry, TWO, "Smoker.", {})
    assert not {"kind", "size"} & {s.input for s in out.settled} and "kind" in out.missing and out.degraded is True
    assert "- kind" not in prompts[0] and "- size" not in prompts[0] and "- risk [patient]" in prompts[0]


async def test_every_value_is_put_to_jev_with_its_scope_as_state(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    by_state = {p["state"]: [q["instructions"] for q in p["questions"].values()] for p in jev["payloads"]}
    assert by_state[f"FINDING:\n{FINDING}"] == ["The FINDING states Nodule type: solid",
                                                 "The FINDING states Diameter: 7 mm"]
    patient = next(s for s in by_state if s.startswith("CLINICAL HISTORY"))
    assert TWO in patient and by_state[patient] == ["The CLINICAL HISTORY or DICTATION state Patient risk: high"]


async def test_a_value_jev_does_not_find_stated_is_asked(toy_entry, monkeypatch, jev):
    jev["score"] = P.SETTLED_MIN - 0.1
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert out.settled == [] and "kind" in out.missing and out.degraded is False


async def test_a_jev_failure_on_one_scope_asks_only_that_scopes_values(toy_entry, monkeypatch, jev):
    jev["fail_if"] = "CLINICAL HISTORY"
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDING, "Smoker.", {}, finding=FINDING)
    assert {s.input for s in out.settled} == {"kind", "size"} and out.missing == ["risk"] and out.degraded is True


@pytest.mark.parametrize("model_value,quote,want", [
    (12, "1.2 cm", "12 mm"), (1.2, "1.2 cm", "12 mm"), (120, "12 mm", None), (9, "7 mm", None), (None, "8mm", "8 mm"),
    (7, "9 x 7 mm", None), (8, "9 x 7 mm", None), (7, "6-8 mm", None), (7, "seven millimetres", None)])
async def test_the_number_is_read_from_its_quote_never_taken_from_the_model(toy_entry, monkeypatch, jev,
                                                                           model_value, quote, want):
    _model(monkeypatch, KIND, {"input": "size", "value": model_value, "quote": quote})
    out = await PP.preview_pack(toy_entry, f"{quote} solid nodule.", "", {}, finding=f"{quote} solid nodule.")
    assert {s.input: s.value for s in out.settled}.get("size") == want


async def test_the_settle_prompt_is_the_finding_alone_when_no_patient_input_is_open(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, KIND, SIZE, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {"risk": "low"}, finding=FINDING)
    assert prompts[0].endswith(f"FINDING:\n{FINDING}")
    assert "granuloma" not in prompts[0] and "Smoker" not in prompts[0] and "- risk" not in prompts[0]


async def test_the_settle_prompt_offers_the_history_and_dictation_for_patient_inputs(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    assert "- risk [patient]:" in prompts[0] and "- kind [lesion]:" in prompts[0]
    assert "CLINICAL HISTORY: Smoker." in prompts[0] and f"DICTATION:\n{TWO}" in prompts[0]


async def test_nothing_open_calls_no_model(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise AssertionError("no open input: no settle call")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDING, "", {"kind": "solid", "size": "7", "risk": "low",
                                                         "margin": "smooth"}, finding=FINDING)
    assert out.proposal.recommendation == "CT at 12 months" and out.degraded is False


def test_a_typed_answer_is_read_like_a_quote(toy_entry):
    i = toy_entry.input("size")
    assert PP._answer(toy_entry, i, "1.2 cm").value == 12 and PP._answer(toy_entry, i, "7").value == 7
    assert PP._answer(toy_entry, i, "6-8 mm").band == "6to8" and PP._answer(toy_entry, i, "big") is None


def _elig(toy):
    from tests.test_library_verify import _eligible_toy
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    return Entry.model_validate(_eligible_toy(toy))


async def test_an_unknown_eligibility_input_puts_the_card_in_check_first(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING)
    assert out.state == "check_first" and out.proposal is None and out.missing == ["known_cancer"]
    assert out.asks[0]["role"] == "eligibility" and out.asks[0]["fact"] == "known_primary_cancer"


async def test_eligibility_asks_come_before_clinical_asks(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.missing == ["known_cancer", "risk"] and [a["input"] for a in out.asks] == out.missing


async def test_a_shared_patient_answer_excludes_with_a_reason_and_no_apply(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "does_not_apply" and out.proposal is None
    assert out.exclusion.classification == "Toy 2020 · the toy guideline does not apply"
    assert out.exclusion.citations and out.exclusion.recommendation == "Manage per the clinical context."
    assert any(c.get("step") == "outcome" and c.get("section") == "Scope" for c in out.exclusion.citations)
    assert next(s for s in out.settled if s.input == "known_cancer").fact == "known_primary_cancer"


async def test_an_eligible_patient_gets_the_normal_card(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "No"})
    assert out.state == "applies" and out.proposal.recommendation == "CT at 6 months" and out.exclusion is None


async def test_the_cards_own_answer_beats_the_shared_one(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"known_cancer": "No", "risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "applies"


async def test_a_patient_answer_the_pack_cannot_take_is_ignored(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "seventy", "age_years": "60"})
    assert out.state == "check_first" and out.missing == ["known_cancer"]


@pytest.mark.parametrize("finding,quote", [("Nodule measuring under 5 mm, solid.", "5 mm"),
                                           ("Solid nodule, 6 to 8 mm.", "8 mm"),
                                           ("Solid nodule up to 8 x 5 mm.", "5 mm")])
async def test_a_quote_inside_a_bound_or_range_is_asked(toy_entry, monkeypatch, jev, finding, quote):
    _model(monkeypatch, KIND, {"input": "size", "value": float(quote.split()[0]), "quote": quote})
    out = await PP.preview_pack(toy_entry, finding, "", {}, finding=finding)
    assert "size" not in {s.input for s in out.settled}


async def test_jev_saying_no_to_a_number_asks_it(toy_entry, monkeypatch, jev):
    """"was 5 mm, now 9 mm" read as the current size of the wrong time point: Jev's no unsettles it."""
    jev["deny"] = ["Diameter: 5 mm"]
    finding = "Solid nodule, was 5 mm, now 9 mm."
    _model(monkeypatch, KIND, {"input": "size", "value": 5, "quote": "5 mm"})
    out = await PP.preview_pack(toy_entry, finding, "", {}, finding=finding)
    assert "size" not in {s.input for s in out.settled} and "kind" in {s.input for s in out.settled}


async def test_swapped_volumes_are_asked(monkeypatch, jev):
    from tests.test_library_partial import _bts
    e = _bts()
    finding = "Solid nodule, volume 180 mm3, previously 120 mm3."
    jev["deny"] = ["Baseline volume: 180 mm3", "Current volume: 120 mm3"]
    _model(monkeypatch, {"input": "prior_volume_mm3", "value": 180, "quote": "180 mm3"},
           {"input": "current_volume_mm3", "value": 120, "quote": "120 mm3"})
    out = await PP.preview_pack(e, finding, "", {"prior_study": "Yes", "growth": "volumetry"}, finding=finding)
    assert not {"prior_volume_mm3", "current_volume_mm3"} & {s.input for s in out.settled}


async def test_an_errored_preview_is_check_first_when_the_pack_has_eligibility(toy, toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "check_first"
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "applies"


def test_failed_gives_the_state_of_a_preview_that_never_ran(toy, toy_entry):
    assert PP.failed(_elig(toy)).state == "check_first" and PP.failed(_elig(toy)).degraded is True
    assert PP.failed(toy_entry).state == "applies"


async def test_a_degraded_settle_leaves_eligibility_asked_first(toy, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "check_first" and out.missing[0] == "known_cancer"
