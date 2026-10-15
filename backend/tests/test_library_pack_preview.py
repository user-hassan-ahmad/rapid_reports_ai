import pytest
from types import SimpleNamespace

from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot.library import engine as E
from rapid_reports_ai.hybrid_stack.copilot.library import pack_preview as PP
from tests.test_library_quantity import ALONE, OTHER_NUMBER

FINDINGS = "7 mm solid nodule in the right upper lobe."


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _ids(assumptions) -> list[str]:
    return [a.input for a in assumptions]


@pytest.fixture
def jev(monkeypatch):
    st = {"score": 0.9, "fail": False, "fail_if": None, "deny": [], "scores": {}, "calls": 0, "payloads": [],
          "stated": {}, "stated_default": ("not_mentioned", 0.95)}

    def score(text):
        if any(d in text for d in st["deny"]):
            return 0.1
        return next((v for k, v in st["scores"].items() if k in text), st["score"])

    async def post(payload, key, timeout, transport=None):
        st["calls"] += 1
        st["payloads"].append(payload)
        if st["fail"] or (st["fail_if"] and st["fail_if"] in payload["state"]):
            raise TimeoutError("jev slow")
        def answer(q):
            if q["type"] == "choice":      # a yes/no's four-way question: by a label fragment, else the default
                v = next((v for k, v in st["stated"].items() if k in q["instructions"]), st["stated_default"])
                c, conf = v(q) if callable(v) else v       # a callable answers from the question (date picks)
                return {"choice": c, "confidence": conf}
            return {"noul": score(q["instructions"])}
        return _Resp({"answers": {k: answer(q) for k, q in payload["questions"].items()}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def _model(monkeypatch, *items, prompts=None):
    async def call(system, prompt):
        if prompts is not None:
            prompts.append(prompt)
        return PP.RawSettle(settled=[PP.RawItem(**i) for i in items])
    monkeypatch.setattr(PP, "_call", call)


def _states(out) -> dict[str, str]:
    """input -> its value state on the draft card (spec §7.5)."""
    return {d.input: d.state for d in out.draft}


def _why(out, k: str) -> list[str]:
    return next(d.why for d in out.draft if d.input == k)


KIND = {"input": "kind", "value": "solid", "quote": "solid"}
SIZE = {"input": "size", "value": 7, "quote": "7 mm"}


async def test_settled_inputs_reach_a_proposal_copied_from_the_entry(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Smoker.", {}, finding=FINDINGS)
    assert [(s.input, s.value) for s in out.settled] == [("kind", "solid"), ("size", "7 mm"), ("risk", "high")]
    assert out.missing == [] and out.draft_outcome.recommendation == "CT at 6 months"
    assert out.draft_outcome.classification == "Toy 2020 · solid nodule 6-8 mm, high risk"
    assert out.draft_outcome.line == "Toy 2020: solid nodule 6-8 mm, high risk."
    assert out.trace["outcome"] == "ct6" and jev["calls"] == 2     # one batch per scope, no per-quote call
    assert out.draft_outcome.normal is False


async def test_missing_input_shows_possible_outcomes(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
    assert out.draft_outcome is None and out.missing == ["risk"]
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
    assert (risk.value, risk.quote) == ("low", "") and out.draft_outcome.recommendation == "CT at 12 months"


async def test_band_label_answer(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, "solid nodule", "", {"size": "6-8 mm", "risk": "low"}, finding="solid nodule")
    assert out.draft_outcome.recommendation == "CT at 12 months"


async def test_unconfirmed_values_are_prefilled_never_read(toy_entry, monkeypatch, jev):
    jev["fail"] = True
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "heavy smoker"})
    out = await PP.preview_pack(toy_entry, FINDINGS, "Heavy smoker.", {}, finding=FINDINGS)
    assert out.degraded is True and out.proposal is None                # a failed check reads nothing (spec §7.5)
    assert {k: _states(out)[k] for k in ("kind", "size", "risk")} == dict.fromkeys(("kind", "size", "risk"), "prefilled")
    assert all(PP.WHY_NO_CHECK in _why(out, k) for k in ("kind", "size", "risk"))


async def test_model_failure_uses_answers_only(toy_entry, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {"kind": "subsolid"}, finding=FINDINGS)
    assert out.draft_outcome.recommendation == "CT in 12 months"
    assert out.degraded is True


async def test_entry_defect_gives_no_proposal(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given, **kw):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
    assert out.draft_outcome is None


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
    assert out.draft_outcome is None


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
    """Reads the one pack's source entry, never the whole guidelines folder: another pack in progress cannot break it."""
    import json
    from pathlib import Path
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    src = Path(__file__).resolve().parents[2] / "guidelines" / "bosniak-renal-cyst" / "entry.json"
    e = Entry.model_validate(json.loads(src.read_text()))
    assert "no when the mass is described by its features" in e.input("too_small").how_stated


async def test_an_unbounded_preview_says_so_and_asks_every_reaching_input(monkeypatch, jev):
    from tests.test_library_partial import BTS_BROCK, _bts
    e = _bts()
    _model(monkeypatch, {"input": "diameter_mm", "value": 10, "quote": "10 mm"},
           {"input": "nodule_type", "value": "solid", "quote": "solid"},
           {"input": "benign_features", "value": False, "quote": "no benign features"},
           {"input": "prior_study", "value": False, "quote": "no prior"})
    out = await PP.preview_pack(e, "10 mm solid nodule, no benign features, no prior imaging.", "", {}, finding="10 mm solid nodule, no benign features, no prior imaging.")
    signs = {"spiculation"}                              # visible signs: assumed absent when unstated (silence policy)
    assert out.draft_outcome is None and out.bounded is False and BTS_BROCK - signs <= set(out.missing)
    assert signs <= set(_ids(out.assumptions)) and not signs & set(out.missing)


async def test_the_preview_carries_the_waiting_inputs(toy_entry, monkeypatch, jev):
    _model(monkeypatch, SIZE)
    out = await PP.preview_pack(toy_entry, FINDINGS, "", {}, finding=FINDINGS)
    assert out.missing == ["kind"] and out.waiting == ["risk"]          # risk waits behind its parent kind


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
    assert out.draft_outcome.caveats == ["Only for high risk adults."]
    cites = out.draft_outcome.citations
    assert {**P3, "step": "plan"} in cites and {**P2, "step": "size_band"} in cites
    assert {**P2, "step": "outcome"} in cites
    assert all(c["title"] == "Toy guideline" for c in cites)


async def test_a_caveat_with_an_unfilled_placeholder_blocks_the_proposal(toy, monkeypatch, jev):
    e = _with_caveat(toy, "Only for {margin} margins.")
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(e, FINDINGS, "Smoker.", {}, TOY_SOURCES, finding=FINDINGS)
    assert out.draft_outcome is None


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
    brock = BTS_BROCK - {"spiculation"}                   # the visible sign is assumed absent, not asked
    assert brock <= set(asks) and [a["input"] for a in out.asks] == out.missing
    for k in brock:
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
    assert out.draft_outcome.recommendation == "CT at 6 months"


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
                                                 "The FINDING states Diameter: 7 mm", PP.ONE_LESION]
    assert not any(s.startswith("QUOTE") for s in by_state)              # the per-quote claim is retired
    patient = next(s for s in by_state if s.startswith("CLINICAL HISTORY"))
    assert by_state[patient] == ["The CLINICAL HISTORY or DICTATION state Patient risk: high"]


@pytest.mark.parametrize("verdict,settles", [(0.79, False), (0.8, True)])
async def test_an_enum_is_read_when_the_finding_claim_reaches_point_eight(toy_entry, monkeypatch, jev, verdict,
                                                                          settles):
    jev["scores"] = {"The FINDING states Nodule type": verdict}
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert (_states(out)["kind"] == "read") is settles and (PP.WHY_UNCONFIRMED in _why(out, "kind")) is not settles


@pytest.mark.parametrize("key,finding,inp,value,quote,claim", [
    # lab #29: proven_malignant = No from a quote that says nothing of histology (live Jev 0.57/0.62: asked)
    ("bts-pulmonary-nodule", "6 mm smooth triangular nodule abutting the right horizontal fissure, typical of an "
     "intrapulmonary lymph node.", "proven_malignant", False, "typical of an intrapulmonary lymph node",
     "The FINDING states Nodule already proven to be lung cancer or a metastasis: No"),
    # lab #13: too_small = no from a quote that is not the size
    ("bosniak-renal-cyst", "4 cm well-defined cyst in the right lower pole with a single thin (1 mm) septum and a "
     "fleck of calcification.", "too_small", "no", "a single thin (1 mm) septum and a fleck of calcification",
     "The FINDING states Too small to characterise: no")])
async def test_lab_weak_settles_are_prefilled_when_the_finding_does_not_state_them(monkeypatch, jev, key, finding,
                                                                                  inp, value, quote, claim):
    jev["scores"] = {claim: 0.6}
    _model(monkeypatch, {"input": inp, "value": value, "quote": quote})
    out = await PP.preview_pack(_pack(key), finding, "", {}, finding=finding)
    assert _states(out)[inp] == "prefilled" and PP.WHY_UNCONFIRMED in _why(out, inp)
    state = next(p["state"] for p in jev["payloads"] if claim in str(p["questions"]))
    assert state == f"FINDING:\n{finding}"                    # the scope's batch: the finding is the evidence


async def test_a_value_jev_does_not_find_stated_is_prefilled(toy_entry, monkeypatch, jev):
    jev["score"] = P.SETTLED_MIN - 0.1
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert _states(out)["kind"] == _states(out)["size"] == "prefilled" and out.degraded is False
    assert PP.WHY_UNCONFIRMED in _why(out, "kind") and PP.WHY_UNCONFIRMED in _why(out, "size")


async def test_a_jev_failure_on_one_scope_prefills_only_that_scopes_values(toy_entry, monkeypatch, jev):
    jev["fail_if"] = "CLINICAL HISTORY"
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    out = await PP.preview_pack(toy_entry, FINDING, "Smoker.", {}, finding=FINDING)
    assert _states(out)["kind"] == _states(out)["size"] == "read" and out.degraded is True
    assert _states(out)["risk"] == "prefilled" and PP.WHY_NO_CHECK in _why(out, "risk")


@pytest.mark.parametrize("model_value,quote,want", [
    (12, "1.2 cm", "12 mm"), (1.2, "1.2 cm", "12 mm"), (120, "12 mm", None), (9, "7 mm", None), (None, "8mm", "8 mm"),
    (7, "9 x 7 mm", None), (8, "9 x 7 mm", None), (7, "6-8 mm", None), (7, "seven millimetres", None)])
async def test_the_number_is_read_from_its_quote_never_taken_from_the_model(toy_entry, monkeypatch, jev,
                                                                           model_value, quote, want):
    _model(monkeypatch, KIND, {"input": "size", "value": model_value, "quote": quote})
    out = await PP.preview_pack(toy_entry, f"{quote} solid nodule.", "", {}, finding=f"{quote} solid nodule.")
    assert {s.input: s.value for s in out.settled}.get("size") == want


async def test_the_settle_prompts_finding_is_the_finding_alone(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, KIND, SIZE, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {"risk": "low"}, finding=FINDING)
    assert prompts[0].endswith(f"FINDING:\n{FINDING}") and "granuloma" not in prompts[0].split("FINDING:")[-1]


async def test_the_settle_prompt_offers_the_history_and_dictation_for_patient_inputs(toy_entry, monkeypatch, jev):
    prompts = []
    _model(monkeypatch, prompts=prompts)
    await PP.preview_pack(toy_entry, TWO, "Smoker.", {}, finding=FINDING)
    assert "- risk [patient]:" in prompts[0] and "- kind [lesion]:" in prompts[0]
    assert "CLINICAL HISTORY: Smoker." in prompts[0] and f"DICTATION:\n{TWO}" in prompts[0]


async def test_answers_override_settled_values_and_never_skip_the_one_read(toy_entry, monkeypatch, jev):
    """The dictation is read once whatever is answered (the settlement is cached without answers); answers win."""
    prompts = []
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"}, prompts=prompts)
    out = await PP.preview_pack(toy_entry, FINDING, "Smoker.", {"kind": "solid", "size": "7", "risk": "low",
                                                                "margin": "smooth"}, finding=FINDING)
    assert out.draft_outcome.recommendation == "CT at 12 months" and out.degraded is False and len(prompts) == 1
    assert {s.input: s.quote for s in out.settled}["risk"] == ""                # the answer, not the quote


def test_a_typed_answer_is_read_like_a_quote(toy_entry):
    i = toy_entry.input("size")
    assert PP._answer(toy_entry, i, "1.2 cm").value == 12 and PP._answer(toy_entry, i, "7").value == 7
    assert PP._answer(toy_entry, i, "6-8 mm").band == "6to8" and PP._answer(toy_entry, i, "big") is None


def _elig(toy):
    from tests.test_library_verify import _eligible_toy
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    return Entry.model_validate(_eligible_toy(toy))


async def test_an_unknown_eligibility_input_is_assumed_in_scope_and_the_draft_outcome_shown(toy, monkeypatch, jev):
    """Hassan 2026-10-13: the card never leads with eligibility; it drafts for an eligible patient, visibly."""
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING)
    assert out.state == "check_first" and out.assumed_eligible is True and _ids(out.assumptions) == ["known_cancer"]
    assert out.draft_outcome.recommendation == "CT at 6 months" and out.missing == [] and out.proposal is None
    d = next(x for x in out.draft if x.input == "known_cancer")
    assert (d.state, d.value, d.why, d.quote) == ("assumed", "No", [PP.WHY_ASSUMED], "")
    assert "known_cancer" not in {x.input for x in out.settled}                 # never stated, never settled
    assert _states(out)["kind"] == _states(out)["size"] == "read"               # the read values stay on the card


async def test_an_assumed_eligibility_input_is_not_asked_and_the_clinical_asks_remain(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.missing == ["risk"] and [a["input"] for a in out.asks] == out.missing
    assert _ids(out.assumptions) == ["known_cancer"] and out.state == "check_first"


async def test_a_read_eligibility_value_is_never_an_assumption(toy, monkeypatch, jev):
    e = _elig(toy)
    base = {"kind": PP.Drafted(PP.InputValue(value="solid"), "solid", "read"),
            "size": PP.Drafted(PP.InputValue(value=7.0), "7 mm", "read")}
    excluded = PP.finish(e, PP.Settlement(values={**base, "known_cancer": PP.Drafted(
        PP.InputValue(value=True), "known lung cancer", "prefilled", [PP.WHY_KIND])}), {"risk": "high"})
    # a pre-filled excluding value is a scope doubt, never an exclusion (Hassan 2026-10-13); answered, it excludes
    assert excluded.state == "check_first" and excluded.scope_doubt == ["known_cancer"] and excluded.exclusion is None
    assert excluded.draft_outcome.recommendation == "CT at 6 months" and _states(excluded)["kind"] == "read"
    answered = PP.finish(e, PP.Settlement(values=base), {"risk": "high", "known_cancer": "Yes"})
    assert answered.state == "does_not_apply" and _ids(answered.assumptions) == [] and answered.exclusion is not None
    eligible = PP.finish(e, PP.Settlement(values={**base, "known_cancer": PP.Drafted(
        PP.InputValue(value=False), "no history of cancer", "prefilled", [PP.WHY_KIND])}), {"risk": "high"})
    assert eligible.state == "applies" and _ids(eligible.assumptions) == [] and eligible.assumed_eligible is False
    assert _states(eligible)["known_cancer"] == "prefilled" and eligible.draft_outcome.recommendation == "CT at 6 months"


def test_an_assumed_value_sent_back_counts_as_sent_and_stays_assumed(toy):
    e = _elig(toy)
    s = PP.Settlement(values={"kind": PP.Drafted(PP.InputValue(value="solid"), "solid", "read"),
                              "size": PP.Drafted(PP.InputValue(value=7.0), "7 mm", "read")})
    c = PP.calculate(e, s, {"kind": "solid", "size": "7 mm", "risk": "high", "known_cancer": "No"}, None, [], "b1")
    assert c.result.recommendation == "CT at 6 months" and {v.input: v.state for v in c.values}["known_cancer"] == "assumed"
    c = PP.calculate(e, s, {"kind": "solid", "size": "7 mm", "risk": "high"}, None, [], "b1")      # not sent: unknown
    assert c.result is None and c.outcome is None and "known_cancer" in c.needed


async def test_a_shared_patient_answer_excludes_with_a_reason_and_no_apply(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "does_not_apply" and out.draft_outcome is None
    assert out.exclusion.classification == "Toy 2020 · the toy guideline does not apply"
    assert out.exclusion.citations and out.exclusion.recommendation == "Manage per the clinical context."
    assert any(c.get("step") == "outcome" and c.get("section") == "Scope" for c in out.exclusion.citations)
    assert next(s for s in out.settled if s.input == "known_cancer").fact == "known_primary_cancer"


async def test_an_eligible_patient_gets_the_normal_card(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "No"})
    assert out.state == "applies" and out.draft_outcome.recommendation == "CT at 6 months" and out.exclusion is None


async def test_the_cards_own_answer_beats_the_shared_one(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"known_cancer": "No", "risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "Yes"})
    assert out.state == "applies"


async def test_a_patient_answer_the_pack_cannot_take_is_ignored(toy, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {"risk": "high"}, finding=FINDING,
                                patient={"known_primary_cancer": "seventy", "age_years": "60"})
    assert out.state == "check_first" and _ids(out.assumptions) == ["known_cancer"] and out.missing == []


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
    assert _states(out)["size"] == "prefilled" and PP.WHY_UNCONFIRMED in _why(out, "size")
    assert PP.WHY_OTHER_NUMBER in _why(out, "size") and _states(out)["kind"] == "read"


async def test_swapped_volumes_are_asked(monkeypatch, jev):
    from tests.test_library_partial import _bts
    e = _bts()
    finding = "Solid nodule, volume 180 mm3, previously 120 mm3."
    jev["deny"] = ["Baseline volume: 180 mm3", "Current volume: 120 mm3"]
    _model(monkeypatch, {"input": "prior_volume_mm3", "value": 180, "quote": "180 mm3"},
           {"input": "current_volume_mm3", "value": 120, "quote": "120 mm3"})
    out = await PP.preview_pack(e, finding, "", {"prior_study": "Yes", "growth": "volumetry"}, finding=finding)
    for k in ("prior_volume_mm3", "current_volume_mm3"):
        assert _states(out)[k] == "prefilled" and PP.WHY_UNCONFIRMED in _why(out, k)


async def test_an_errored_preview_is_check_first_when_the_pack_has_eligibility(toy, toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE)

    def broken(entry, given, **kw):
        raise E.EvaluationError("two cases hold")
    monkeypatch.setattr(PP.engine, "evaluate", broken)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "check_first"
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "applies"


def test_failed_gives_the_state_of_a_preview_that_never_ran(toy, toy_entry):
    assert PP.failed(_elig(toy)).state == "check_first" and PP.failed(_elig(toy)).degraded is True
    assert PP.failed(toy_entry).state == "applies"


async def test_a_degraded_settle_still_assumes_eligibility_visibly(toy, monkeypatch, jev):
    async def boom(system, prompt):
        raise TimeoutError("slow")
    monkeypatch.setattr(PP, "_call", boom)
    out = await PP.preview_pack(_elig(toy), FINDING, "", {}, finding=FINDING)
    assert out.degraded is True and out.state == "check_first" and _ids(out.assumptions) == ["known_cancer"]


@pytest.mark.parametrize("finding,quote,unit,dims", OTHER_NUMBER)
def test_a_lesion_number_in_a_finding_with_another_number_is_prefilled(finding, quote, unit, dims):
    """Spec §7.5: apart from its own measurement (and image numbers, dates, anatomical labels, the same reading again,
    "single"/"solitary"), any other number in the finding makes a read size pre-filled (WHY_OTHER_NUMBER), even when
    the model agrees. A quote code cannot read as one value is still dropped (asked)."""
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    if unit == "count":
        pytest.skip("a count keeps its own rule")
    i = InputDef(id="n", label="N", type="number", unit=unit, dims=dims)
    for model in (None, PP.Q.settle(quote, [finding], unit, dims)):
        v = PP._value(i, PP.RawItem(input="n", value=model, quote=quote), [finding])
        if v is not None:
            e = SimpleNamespace(applies_to=SimpleNamespace(finding_type=["nodule"]))
            assert PP.WHY_OTHER_NUMBER in PP._read_reasons(e, i, v, quote, [finding])


@pytest.mark.parametrize("finding,quote,unit,dims,want", ALONE)
def test_a_lesion_number_alone_in_its_finding_still_settles(finding, quote, unit, dims, want):
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    i = InputDef(id="n", label="N", type="number", unit=unit, dims=dims)
    assert PP._value(i, PP.RawItem(input="n", value=want, quote=quote), [finding]).value == want


def test_a_patient_number_is_not_held_to_one_measurement():
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import InputDef
    i = InputDef(id="a", label="Age", type="number", unit="years", scope="patient")
    assert PP._value(i, PP.RawItem(input="a", value=65, quote="65 years"),
                     ["Aged 65 years, smoker for 40 years."]).value == 65


async def test_only_a_failure_fails_the_settlement(toy_entry, monkeypatch, jev):
    _model(monkeypatch, {"input": "risk", "value": "high", "quote": "smoker"})
    s = await PP.settle_pack(toy_entry, TWO, "Smoker.")
    assert s.no_unit is True and s.failed is False
    assert PP.finish(toy_entry, s, {}).degraded is True                     # no unit: still said on the card
    jev["fail"] = True
    assert (await PP.settle_pack(toy_entry, TWO, "Smoker.")).failed is True
    jev["fail"] = False
    s = await PP.settle_pack(toy_entry, FINDING, "Smoker.", finding=FINDING)
    assert s.failed is False and s.no_unit is False


async def test_bts_with_eligibility_unknown_drafts_under_assumptions(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch)
    out = await PP.preview_pack(_bts(), "7 mm solid nodule.", "", {"nodule_type": "solid", "diameter_mm": "7",
                                                                  "benign_features": "Yes", "prior_study": "No"},
                                finding="7 mm solid nodule.")
    assert out.state == "check_first" and out.missing == []
    assert _ids(out.assumptions) == ["age", "proven_malignant", "spiculation"]     # eligibility, then the sign
    assert _states(out)["proven_malignant"] == "assumed" and _states(out)["age"] == "assumed"
    # spec §7.12 item 2: age is assumed at its band ("18 years or over"); a stated age replaces the assumption
    out = await PP.preview_pack(_bts(), "7 mm solid nodule.", "", {"nodule_type": "solid", "diameter_mm": "7",
                                                                  "benign_features": "Yes", "prior_study": "No",
                                                                  "age": "60"}, finding="7 mm solid nodule.")
    assert _ids(out.assumptions) == ["proven_malignant", "spiculation"] and out.draft_outcome is not None
    assert out.missing == []


# fix round 5: a lesion number settles only for a finding that describes one lesion
MANY = ["4 mm solid nodule in the right upper lobe; a further larger nodule in the left lower lobe.",
        "4 mm solid nodule in the right upper lobe. Further subcentimetre nodules bilaterally.",
        "Scattered solid pulmonary nodules, the index nodule measuring 4 mm.",
        "4 mm solid nodule in the right upper lobe. Other nodules are larger."]
ONE_CLAIM = "describes only one"


def _pack(key):
    import json
    from rapid_reports_ai.hybrid_stack.copilot.library import bundle as LB
    return LB.Library(json.loads(LB.BUNDLE.read_text())).lookup(key)


async def _fleischner(monkeypatch, finding, quote, value):
    _model(monkeypatch, {"input": "nodule_type", "value": "solid", "quote": "solid"} if "solid" in finding.lower()
           else {"input": "nodule_type", "value": "solid", "quote": "nodule"},
           {"input": "diameter_mm", "value": value, "quote": quote})
    return await PP.preview_pack(_pack("fleischner-pulmonary-nodule"), finding, "", {}, finding=finding)


@pytest.mark.parametrize("finding", MANY)
@pytest.mark.parametrize("verdict", [0.1, 0.7])                      # Jev says no, or is unsure
async def test_a_finding_with_several_lesions_prefills_its_size(monkeypatch, jev, finding, verdict):
    jev["scores"] = {ONE_CLAIM: verdict}
    out = await _fleischner(monkeypatch, finding, "4 mm", 4)
    assert _states(out)["diameter_mm"] == "prefilled" and PP.WHY_SEVERAL in _why(out, "diameter_mm")


@pytest.mark.parametrize("finding", MANY)
async def test_a_multiplicity_word_no_longer_asks_when_jev_says_one(monkeypatch, jev, finding):
    jev["scores"] = {ONE_CLAIM: 0.95}
    out = await _fleischner(monkeypatch, finding, "4 mm", 4)
    assert {"diameter_mm", "nodule_type"} <= {x.input for x in out.settled}      # drafted: never an ask now
    for k in ("diameter_mm", "nodule_type"):                     # review M1: a multiplicity word pre-fills, never reads
        assert _states(out)[k] == "prefilled" and PP.WHY_SEVERAL in _why(out, k)


@pytest.mark.parametrize("verdict,settles", [(0.95, True), (0.8, True), (0.79, False), (0.1, False)])
async def test_jev_decides_one_lesion_when_no_backstop_word_is_there(monkeypatch, jev, verdict, settles):
    finding = "4 mm solid nodule in the right upper lobe and a bigger nodular opacity at the left base."
    jev["scores"] = {ONE_CLAIM: verdict}
    out = await _fleischner(monkeypatch, finding, "4 mm", 4)
    assert (_states(out)["diameter_mm"] == "read") is settles
    assert (PP.WHY_SEVERAL in _why(out, "diameter_mm")) is not settles      # never asked: pre-filled, with why


@pytest.mark.parametrize("key,finding,inp,quote,value,want", [
    ("fleischner-pulmonary-nodule", "Solitary 8 mm nodule.", "diameter_mm", "8 mm", 8, "8 mm"),
    ("fleischner-pulmonary-nodule", "8 mm nodule in segment 6.", "diameter_mm", "8 mm", 8, "8 mm"),
    ("fleischner-pulmonary-nodule", "12 x 7 mm nodule.", "diameter_mm", "12 x 7 mm", 9.5, "9.5 mm"),
    ("bosniak-renal-cyst", "Left renal cyst of -20 HU.", "hu", "-20 HU", -20, "-20 HU")])
async def test_one_lesion_still_settles_its_number(monkeypatch, jev, key, finding, inp, quote, value, want):
    _model(monkeypatch, {"input": inp, "value": value, "quote": quote})
    out = await PP.preview_pack(_pack(key), finding, "", {}, finding=finding)
    assert {x.input: x.value for x in out.settled}.get(inp) == want


async def test_the_one_lesion_claim_rides_in_the_lesion_batch(monkeypatch, jev):
    out = await _fleischner(monkeypatch, "Solitary 8 mm solid nodule.", "8 mm", 8)
    assert jev["calls"] == 1 and "diameter_mm" in {x.input for x in out.settled}     # the lesion batch alone
    lesion = next(p for p in jev["payloads"] if p["state"].startswith("FINDING"))
    assert [q["instructions"] for q in lesion["questions"].values()] == [
        "The FINDING states Nodule type: solid", "The FINDING states Nodule diameter: 8 mm", PP.ONE_LESION]


def test_the_one_lesion_claim_names_a_lesion_of_any_kind_not_the_packs_noun():
    assert "lesion of any kind" in PP.ONE_LESION
    assert all(w in PP.ONE_LESION for w in ("nodule", "granuloma", "mass", "cyst", "scar"))


async def test_an_enum_alone_still_carries_the_one_lesion_claim(monkeypatch, jev):
    finding = "Solid nodule in the right upper lobe."
    _model(monkeypatch, {"input": "nodule_type", "value": "solid", "quote": "solid"})
    out = await PP.preview_pack(_pack("fleischner-pulmonary-nodule"), finding, "", {}, finding=finding)
    claims = [q["instructions"] for p in jev["payloads"] for q in p["questions"].values()]
    assert PP.ONE_LESION in claims and "nodule_type" in {x.input for x in out.settled}


async def test_a_multiplicity_word_no_longer_asks_an_enum(monkeypatch, jev):
    jev["scores"] = {ONE_CLAIM: 0.95}
    _model(monkeypatch, {"input": "nodule_type", "value": "solid", "quote": "solid"})
    out = await PP.preview_pack(_pack("fleischner-pulmonary-nodule"), "Scattered solid nodules.", "", {},
                                finding="Scattered solid nodules.")
    assert _states(out)["nodule_type"] == "prefilled" and PP.WHY_SEVERAL in _why(out, "nodule_type")   # review M1


# lab fix round item 1: lab case #36, a granuloma (not the pack's noun) lending its lobe and type to the nodule
LAB_36 = ("6 mm solid nodule with no calcification in the right lower lobe and a 12 mm densely calcified granuloma "
          "in the left upper lobe.")


async def test_lab_case_36_two_lesions_in_one_sentence_prefills_never_reads(monkeypatch, jev):
    from tests.test_library_partial import _bts
    jev["scores"] = {ONE_CLAIM: 0.01}                                  # live Jev: 0.01 (see lab-fix-report.md)
    _model(monkeypatch, {"input": "upper_lobe", "value": True, "quote": "left upper lobe"},
           {"input": "nodule_type", "value": "solid", "quote": "densely calcified granuloma"},
           {"input": "spiculation", "value": False, "quote": "no calcification"},
           {"input": "diameter_mm", "value": 6, "quote": "6 mm"})
    out = await PP.preview_pack(_bts(), LAB_36 + " No previous imaging.", "64-year-old woman.", {}, finding=LAB_36)
    for k in ("upper_lobe", "nodule_type", "spiculation", "diameter_mm"):   # the granuloma's lobe and type: shown
        assert _states(out)[k] == "prefilled" and PP.WHY_SEVERAL in _why(out, k)   # highlighted, never read
    assert PP.WHY_NOT_OPTION_WORD in _why(out, "nodule_type") and PP.WHY_NOT_IN_WORDS in _why(out, "upper_lobe")


@pytest.mark.parametrize("item,inp", [({"input": "upper_lobe", "value": True, "quote": "right upper lobe"}, "upper_lobe"),
                                      ({"input": "nodule_type", "value": "solid", "quote": "solid"}, "nodule_type"),
                                      ({"input": "diameter_mm", "value": 6, "quote": "6 mm"}, "diameter_mm")])
@pytest.mark.parametrize("verdict,settles", [(0.79, False), (0.8, True)])
async def test_below_the_one_lesion_bar_every_lesion_value_is_prefilled(monkeypatch, jev, item, inp, verdict,
                                                                        settles):
    from tests.test_library_partial import _bts
    finding = "6 mm solid nodule in the right upper lobe."
    jev["scores"] = {ONE_CLAIM: verdict}
    _model(monkeypatch, item)
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    assert inp in {x.input for x in out.settled} and (PP.WHY_SEVERAL in _why(out, inp)) is not settles


@pytest.mark.parametrize("finding", ["Renal cysts, the largest -20 HU.", "Cystic renal masses, the dominant -20 HU."])
async def test_a_plural_finding_still_drafts_its_number(monkeypatch, jev, finding):
    jev["scores"] = {ONE_CLAIM: 0.3}
    _model(monkeypatch, {"input": "hu", "value": -20, "quote": "-20 HU"})
    out = await PP.preview_pack(_pack("bosniak-renal-cyst"), finding, "", {}, finding=finding)
    assert _states(out)["hu"] == "prefilled" and PP.WHY_SEVERAL in _why(out, "hu")


@pytest.mark.parametrize("key,finding,inp,quote,value", [
    ("fleischner-pulmonary-nodule", "8 mm solid nodule in the RUL. No other pulmonary nodules.", "diameter_mm", "8 mm", 8),
    ("fleischner-pulmonary-nodule", "8 mm solid nodule in the RUL; no further nodules.", "diameter_mm", "8 mm", 8),
    ("fleischner-pulmonary-nodule", "8 mm solid nodule. No additional nodules are seen.", "diameter_mm", "8 mm", 8),
    ("fleischner-pulmonary-nodule", "8 mm solid nodule. No further pulmonary nodules or masses.", "diameter_mm",
     "8 mm", 8),
    ("bosniak-renal-cyst", "Left renal cyst of -20 HU. No other renal lesions.", "hu", "-20 HU", -20)])
async def test_an_unqualified_negation_settles_when_jev_says_one(monkeypatch, jev, key, finding, inp, quote, value):
    jev["scores"] = {ONE_CLAIM: 0.95}
    _model(monkeypatch, {"input": inp, "value": value, "quote": quote})
    out = await PP.preview_pack(_pack(key), finding, "", {}, finding=finding)
    assert inp in {x.input for x in out.settled}


@pytest.mark.parametrize("finding", [
    "4 mm solid nodule. No other new nodules.", "4 mm solid nodule. No other enlarging nodules.",
    "New 4 mm solid nodule. No other nodules have changed.",
    "4 mm solid nodule. No other nodules apart from stable subpleural nodularity."])
async def test_a_qualified_negation_no_longer_asks(monkeypatch, jev, finding):
    jev["scores"] = {ONE_CLAIM: 0.95}
    out = await _fleischner(monkeypatch, finding, "4 mm", 4)
    assert _states(out)["diameter_mm"] == "prefilled" and PP.WHY_SEVERAL in _why(out, "diameter_mm")   # drafted


# prior_study is a whole-study fact (Hassan 2026-10-13): patient-scoped, so the model may propose Yes or No with a quote
# from anywhere in the history or the dictation; read only when stated in words (four-way), else pre-filled or asked
PRIOR_FINDING = "7 mm solid nodule in the right upper lobe."


async def test_no_previous_imaging_in_another_paragraph_drafts_prior_study(monkeypatch, jev):
    from tests.test_library_partial import _bts
    dictation = f"{PRIOR_FINDING}\n\nLiver normal.\n\nComparison: No previous imaging."
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "No previous imaging"})
    out = await PP.preview_pack(_bts(), dictation, "", {}, finding=PRIOR_FINDING)
    d = next(x for x in out.draft if x.input == "prior_study")
    assert (d.state, d.value, d.quote) == ("prefilled", "No", "No previous imaging") and PP.WHY_NOT_IN_WORDS in d.why
    assert "prior_study" not in out.missing
    prompts = []
    _model(monkeypatch, prompts=prompts)
    await PP.preview_pack(_bts(), dictation, "", {}, finding=PRIOR_FINDING)
    assert "- prior_study [patient]" in prompts[0] and "Comparison: No previous imaging." in prompts[0]


async def test_prior_study_from_the_history_is_drafted_too(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch, {"input": "prior_study", "value": True, "quote": "nodule on CT 2023"})
    out = await PP.preview_pack(_bts(), PRIOR_FINDING, "Follow-up of nodule on CT 2023.", {}, finding=PRIOR_FINDING)
    assert _states(out)["prior_study"] == "prefilled"


async def test_prior_study_is_asked_when_nothing_is_said(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch)
    out = await PP.preview_pack(_bts(), f"{PRIOR_FINDING} Liver normal.", "Cough.", {}, finding=PRIOR_FINDING)
    assert _states(out)["prior_study"] == "asked" and "prior_study" in out.missing


async def test_a_prior_study_quote_found_nowhere_is_still_asked(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "first CT to show it"})
    out = await PP.preview_pack(_bts(), PRIOR_FINDING, "", {}, finding=PRIOR_FINDING)
    assert _states(out)["prior_study"] == "asked"                       # never from inference: a verbatim quote


async def test_the_model_may_propose_prior_study_no_from_the_finding(monkeypatch, jev):
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right upper lobe, new since the previous CT."
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "new"})
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    assert _states(out)["prior_study"] == "prefilled" and PP.WHY_NOT_IN_WORDS in _why(out, "prior_study")


async def test_prior_study_yes_is_drafted_from_the_finding_or_elsewhere_in_the_dictation(monkeypatch, jev):
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right upper lobe, unchanged from the 2023 CT."
    _model(monkeypatch, {"input": "prior_study", "value": True, "quote": "unchanged from the 2023 CT"})
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    assert next(x for x in out.settled if x.input == "prior_study").value == "Yes"
    assert _states(out)["prior_study"] == "prefilled"
    _model(monkeypatch, {"input": "prior_study", "value": True, "quote": "Comparison with CT 2023"})
    out = await PP.preview_pack(_bts(), f"{PRIOR_FINDING} Comparison with CT 2023.", "", {}, finding=PRIOR_FINDING)
    assert _states(out)["prior_study"] == "prefilled"      # a whole-study fact: elsewhere in the dictation counts


async def test_the_finding_saying_yes_is_drafted_whatever_the_dictation_says(monkeypatch, jev):
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right upper lobe, unchanged from the 2023 CT."
    _model(monkeypatch, {"input": "prior_study", "value": True, "quote": "unchanged from the 2023 CT"})
    out = await PP.preview_pack(_bts(), f"{finding} No previous imaging.", "", {}, finding=finding)
    assert _states(out)["prior_study"] == "prefilled"         # no cross-check any more: shown, highlighted


async def test_an_answered_prior_study_overrides_the_dictation(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch)
    out = await PP.preview_pack(_bts(), f"{PRIOR_FINDING} No previous imaging.", "", {"prior_study": "Yes"},
                                finding=PRIOR_FINDING)
    assert next(x for x in out.settled if x.input == "prior_study").value == "Yes"


# lab fix round item 4: an attenuation is blocked only by another attenuation; review M2: and settles only when the
# finding states it was measured unenhanced (live Jev on the unenhanced claim in the comments)
@pytest.mark.parametrize("finding,quote,value,phase,settles", [
    ("3 cm left renal cyst, 45 HU post contrast.", "45 HU", 45, 0.02, False),            # live Jev 0.02
    ("3 cm left renal cyst measuring 10 HU on the unenhanced series.", "10 HU", 10, 0.98, True),   # 0.98
    ("Left renal cyst 3 cm, 40 HU.", "40 HU", 40, 0.40, False),                           # no phase: 0.40
    ("Left renal cyst, 20 HU unenhanced, enhancing by 25 HU.", "25 HU", 25, 0.95, False),   # same family: blocked
    ("Left renal cyst, 20 HU unenhanced, enhancing by 25 HU.", "20 HU", 20, 0.95, False)])
async def test_hu_meaning_probes(monkeypatch, jev, finding, quote, value, phase, settles):
    jev["scores"] = {"unenhanced (non-contrast) series": phase}
    _model(monkeypatch, {"input": "hu", "value": value, "quote": quote})
    out = await PP.preview_pack(_pack("bosniak-renal-cyst"), finding, "", {}, finding=finding)
    assert (_states(out)["hu"] == "read") is settles         # never read unless stated unenhanced and alone
    assert settles or _states(out)["hu"] == "asked" or {PP.WHY_PHASE, PP.WHY_OTHER_NUMBER} & set(_why(out, "hu"))


async def test_a_size_in_another_family_no_longer_asks_the_attenuation(monkeypatch, jev):
    finding = "3 cm well-defined left renal cyst, 10 HU unenhanced."
    jev["scores"] = {"unenhanced (non-contrast) series": 0.95}
    _model(monkeypatch, {"input": "hu", "value": 10, "quote": "10 HU"})
    out = await PP.preview_pack(_pack("bosniak-renal-cyst"), finding, "", {}, finding=finding)
    assert {x.input: x.value for x in out.settled}.get("hu") == "10 HU"
    claims = [q["instructions"] for p in jev["payloads"] for q in p["questions"].values()]
    assert "The FINDING states that 10 HU was measured on an unenhanced (non-contrast) series" in claims



# lab fix round item 5: read once; an answer re-runs only the engine over the settlement
async def _settled_bts(monkeypatch, jev):
    from tests.test_library_partial import _bts
    e = _bts()
    finding = "Solitary 9 mm solid nodule in the right upper lobe with a spiculated margin. No previous imaging."
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "No previous imaging"},
           {"input": "nodule_type", "value": "solid", "quote": "solid"},
           {"input": "diameter_mm", "value": 9, "quote": "9 mm"},
           {"input": "upper_lobe", "value": True, "quote": "right upper lobe"},
           {"input": "spiculation", "value": True, "quote": "spiculated"},
           {"input": "age", "value": 68, "quote": "68 years"})
    s = await PP.settle_pack(e, finding, "Aged 68 years.", finding=finding)
    return e, s


def _no_model_no_jev(monkeypatch, calls):
    async def call(system, prompt):
        calls.append("model")
        raise AssertionError("an answer never calls the model")

    async def post(*a, **k):
        calls.append("jev")
        raise AssertionError("an answer never calls Jev")
    monkeypatch.setattr(PP, "_call", call)
    monkeypatch.setattr(P, "jev_post", post)


async def test_answering_an_input_makes_no_model_or_jev_call(monkeypatch, jev):
    e, s = await _settled_bts(monkeypatch, jev)
    calls = []
    _no_model_no_jev(monkeypatch, calls)
    for answered in ({"sex": "female"}, {"sex": "female", "family_history": "No"},
                     {"sex": "female", "family_history": "No", "emphysema": "Yes"}):
        PP.finish(e, s, answered)
    assert calls == []


async def test_settled_values_stay_identical_across_answers(monkeypatch, jev):
    e, s = await _settled_bts(monkeypatch, jev)
    calls = []
    _no_model_no_jev(monkeypatch, calls)
    first = {x.input: (x.value, x.quote) for x in PP.finish(e, s, {}).settled}
    assert {"nodule_type", "diameter_mm", "upper_lobe", "spiculation", "age", "prior_study"} <= set(first)
    for answered in ({"sex": "female"}, {"sex": "female", "family_history": "Yes", "emphysema": "No"}):
        later = {x.input: (x.value, x.quote) for x in PP.finish(e, s, answered).settled}
        assert {k: later[k] for k in first} == first


async def test_an_answer_overrides_the_settled_value_for_that_input(monkeypatch, jev):
    e, s = await _settled_bts(monkeypatch, jev)
    out = PP.finish(e, s, {"upper_lobe": "No"})
    assert {x.input: (x.value, x.quote) for x in out.settled}["upper_lobe"] == ("No", "")


async def test_the_answer_path_is_under_50_ms(monkeypatch, jev):
    import time
    e, s = await _settled_bts(monkeypatch, jev)
    answers = [{"sex": "female"}, {"sex": "female", "family_history": "No"},
               {"sex": "female", "family_history": "No", "emphysema": "Yes", "nodule_count": "1"}]
    worst = 0.0
    for answered in answers * 5:
        t0 = time.perf_counter()
        PP.finish(e, s, answered, sources=[])
        worst = max(worst, time.perf_counter() - t0)
    assert worst < 0.05


# review I1: an enum or boolean needs both the quote claim and the finding claim; a modifier before the quote asks
@pytest.mark.parametrize("finding,item,inp", [
    ("8 mm solid nodule in the right upper lobe, not spiculated.",
     {"input": "spiculation", "value": True, "quote": "spiculated"}, "spiculation"),
    ("12 mm part-solid nodule in the right upper lobe.", {"input": "nodule_type", "value": "solid", "quote": "solid"},
     "nodule_type"),
    ("12 mm ground-glass nodule, no solid component.",
     {"input": "nodule_type", "value": "solid", "quote": "solid component"}, "nodule_type"),
    ("8 mm nodule, possibly spiculated.", {"input": "spiculation", "value": True, "quote": "spiculated"},
     "spiculation")])
async def test_a_quote_stripped_of_its_modifier_is_never_read_even_when_jev_agrees(monkeypatch, jev, finding, item,
                                                                                   inp):
    from tests.test_library_partial import _bts
    jev["score"] = 0.95
    _model(monkeypatch, item)
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    assert _states(out)[inp] != "read"
    assert _states(out)[inp] == "asked" or PP.WHY_MODIFIED in _why(out, inp)   # else pre-filled, with why


async def test_a_context_stripped_quote_fails_the_finding_claim(monkeypatch, jev):
    """The reviewer's 'upper lobe' from 'separating it from the upper lobe': no modifier; the finding claim asks."""
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right lower lobe, adjacent to the oblique fissure separating it from the upper lobe."
    jev["stated"] = {"Upper lobe location": ("stated_no", 0.97)}       # the four-way: the finding says lower lobe
    _model(monkeypatch, {"input": "upper_lobe", "value": True, "quote": "upper lobe"})
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    assert _states(out)["upper_lobe"] == "prefilled" and PP.WHY_UNCONFIRMED in _why(out, "upper_lobe")


@pytest.mark.parametrize("finding_score,settles", [(0.95, True), (0.79, False), (0.8, True)])
async def test_an_enum_is_read_only_when_the_finding_claim_reaches_point_eight(toy_entry, monkeypatch, jev,
                                                                              finding_score, settles):
    jev["scores"] = {"The FINDING states Nodule type": finding_score}
    _model(monkeypatch, KIND)
    out = await PP.preview_pack(toy_entry, FINDING, "", {}, finding=FINDING)
    assert (_states(out)["kind"] == "read") is settles and (PP.WHY_UNCONFIRMED in _why(out, "kind")) is not settles


@pytest.mark.parametrize("quote,text,modified", [
    ("spiculated", "8 mm nodule, not spiculated.", True), ("spiculated", "8 mm nodule, not clearly spiculated.", True),
    ("solid", "12 mm part-solid nodule.", True), ("solid", "Non-solid nodule.", True),
    ("solid", "Semi-solid nodule.", True), ("spiculated", "Nodule, ?spiculated.", True),
    ("calcification", "Nodule without calcification.", True), ("emphysema", "No emphysema.", True),
    ("spiculated", "8 mm spiculated nodule.", False), ("solid", "8 mm solid nodule.", False),
    ("right upper lobe", "Nodule in the right upper lobe.", False), ("not spiculated", "8 mm, not spiculated.", False),
    ("solid", "Nodule is solid.", False)])
def test_the_modifier_guard(quote, text, modified):
    assert PP._modified(quote, [text]) is modified


# ── exam presets (spec §5.1): an exam card pre-fills what its exam binding implies, shown as set by the exam ─────────

def _aaa():
    from pathlib import Path
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    src = Path(__file__).resolve().parents[2] / "guidelines" / "nhs-aaa-surveillance" / "entry.json"
    return Entry.model_validate_json(src.read_text())


_PRESET_IDS = ("screening_programme", "sex", "previous_aaa_treatment")
_DIAMETER = {"diameter_cm": PP.Drafted(PP.InputValue(value=2.4), "aorta 2.4 cm", "read")}


def _exam_finish(e, values, answered=None, patient=None):
    return PP.finish(e, PP.Settlement(values=values), answered or {}, patient,
                     presets=PP.exam_presets(e, PP.EXAM_CARD))


def test_a_normal_aaa_screen_is_prefilled_by_the_exam_and_the_presets_say_so():
    e = _aaa()
    p = _exam_finish(e, _DIAMETER)
    by = {x.input: x for x in p.settled}
    assert {k: (by[k].value, by[k].quote, by[k].by) for k in _PRESET_IDS} == {
        "screening_programme": ("Yes", "", "exam"), "sex": ("male", "", "exam"),
        "previous_aaa_treatment": ("No", "", "exam")}
    draft = {d.input: d for d in p.draft}                  # R1: pre-filled by the exam, the marker on the draft
    assert {k: (draft[k].state, draft[k].by, draft[k].why) for k in _PRESET_IDS} == dict.fromkeys(
        _PRESET_IDS, ("prefilled", "exam", [PP.WHY_EXAM]))
    assert (by["diameter_cm"].value, by["diameter_cm"].quote, by["diameter_cm"].by) == ("2.4 cm", "aorta 2.4 cm", "")
    # initial screen or surveillance is not implied by the exam: the one input left is asked, never preset
    assert p.missing == ["prior_programme_scan"] and p.state == "applies" and p.draft_outcome is None
    stated = _exam_finish(e, {**_DIAMETER, "prior_programme_scan": PP.Drafted(PP.InputValue(value=False), "initial screen",
                                                                       "prefilled", [PP.WHY_KIND])})
    answered = _exam_finish(e, _DIAMETER, answered={"prior_programme_scan": "No"})
    for done in (stated, answered):
        assert done.trace["outcome"] == "no_aaa" and done.missing == []
        assert done.draft_outcome.classification == "NHS AAA Screening 2025 · No AAA found: aortic diameter less than 3.0 cm."
        assert done.draft_outcome.normal is True          # the framework's normal result: a quiet card (spec §5.3)


def test_a_dictated_value_or_an_answer_overrides_the_preset():
    e = _aaa()
    female = _exam_finish(e, {**_DIAMETER, "sex": PP.Drafted(PP.InputValue(value="female"), "female", "read")})
    sex = next(x for x in female.settled if x.input == "sex")
    assert (sex.value, sex.quote, sex.by) == ("female", "female", "") and female.state == "does_not_apply"
    for p in (_exam_finish(e, _DIAMETER, patient={"sex": "female"}),
              _exam_finish(e, _DIAMETER, answered={"screening_programme": "No"})):
        assert p.state == "does_not_apply" and p.draft_outcome is None


def _both_triggers():
    """The AAA pack as if it carried both triggers (the library has none with presets today): a toy for the rule."""
    from rapid_reports_ai.hybrid_stack.copilot.library.schema import Entry
    return Entry.model_validate({**_aaa().model_dump(mode="json", by_alias=True, exclude_none=True),
                                 "trigger": ["exam", "finding"]})


def test_a_finding_card_gets_no_presets():
    e = _both_triggers()
    assert PP.exam_presets(e, "u1") == {} and PP.exam_presets(e, PP.EXAM_CARD) == dict(e.exam_presets)
    p = PP.finish(e, PP.Settlement(values=_DIAMETER), {}, presets=PP.exam_presets(e, "u1"))
    assert [x.input for x in p.settled] == ["diameter_cm"] and all(x.by == "" for x in p.settled)
    assert all(d.by == "" and d.state in ("read", "asked", "assumed") for d in p.draft)
    assert p.state == "check_first" and set(_PRESET_IDS) <= set(_ids(p.assumptions)) | set(p.missing)


def test_presets_need_an_exam_level_entry(toy_entry):
    assert PP.exam_presets(toy_entry, PP.EXAM_CARD) == {}


# ── Task 4: the per-quote claim, _no_prior and quantity.many are retired; guards are highlight reasons ─────────────

async def test_each_scope_is_one_jev_call_and_there_is_no_per_quote_call(toy_entry, monkeypatch, jev):
    _model(monkeypatch, KIND, SIZE, {"input": "risk", "value": "high", "quote": "smoker"})
    await PP.settle_pack(toy_entry, FINDINGS, "Smoker.", finding=FINDINGS)
    assert jev["calls"] == 2                                     # lesion batch + patient batch


async def test_a_finding_naming_other_lesions_still_drafts_its_values(toy_entry, monkeypatch, jev):
    finding = "7 mm solid nodule in the right upper lobe. Further tiny nodules."
    _model(monkeypatch, {"input": "size", "value": 7, "quote": "7 mm"})
    s = await PP.settle_pack(toy_entry, finding, "", finding=finding)
    assert "size" in s.values                                   # no multiplicity-word refusal any more


def test_the_retired_guards_are_gone():
    from rapid_reports_ai.hybrid_stack.copilot.library import quantity as Q
    for name in ("_no_prior", "_quote_claim", "QUOTE_MIN", "_FOLLOW_UP", "_ELSEWHERE", "NO_PRIOR_INPUT"):
        assert not hasattr(PP, name)
    assert hasattr(Q, "many")                  # kept as a pre-fill reason (Task 4 review M1), never an ask


async def test_prior_study_is_proposed_like_any_input(monkeypatch, jev):
    """prior_study is an ordinary lesion boolean: the model may propose Yes or No with a quote; read only when Jev's
    four-way choice says it is stated in words (here not: pre-filled)."""
    from tests.test_library_partial import _bts
    e = _bts()
    assert e.input("prior_study").type == "boolean"
    finding = "7 mm solid nodule in the right upper lobe. No previous imaging."
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "No previous imaging"})
    s = await PP.settle_pack(e, finding, "", finding=finding)
    assert s.values["prior_study"].value.value is False and s.values["prior_study"].tier == "prefilled"
    assert PP.WHY_NOT_IN_WORDS in s.values["prior_study"].why and jev["calls"] == 1


# re-review I-a: a generic comparison line is not "this nodule on an earlier study"
NEW_ON_FOLLOW_UP = "New 7 mm solid nodule in the right upper lobe."


def test_the_prior_study_definition_never_offers_a_comparison_line_as_yes():
    from tests.test_library_partial import _bts
    how = _bts().input("prior_study").how_stated
    assert "this nodule itself is described on an earlier study" in how and "unchanged since" in how
    assert "new since the prior study" in how and "no previous imaging" in how
    assert "'Comparison: CT 2023') settles neither" in how


async def test_the_settle_prompt_carries_the_prior_study_definition(monkeypatch, jev):
    from tests.test_library_partial import _bts
    prompts = []
    _model(monkeypatch, prompts=prompts)
    await PP.preview_pack(_bts(), f"{NEW_ON_FOLLOW_UP} Comparison: CT 2023.", "", {}, finding=NEW_ON_FOLLOW_UP)
    assert "settles neither" in prompts[0] and "- prior_study [patient]" in prompts[0]


async def test_unchanged_since_an_earlier_ct_drafts_yes(monkeypatch, jev):
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right upper lobe, unchanged since the CT of 2023."
    _model(monkeypatch, {"input": "prior_study", "value": True, "quote": "unchanged since the CT of 2023"})
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    d = next(x for x in out.draft if x.input == "prior_study")
    assert (d.state, d.value) == ("prefilled", "Yes")


async def test_new_since_the_prior_study_drafts_no(monkeypatch, jev):
    from tests.test_library_partial import _bts
    finding = "7 mm solid nodule in the right upper lobe, new since the prior study."
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "new since the prior study"})
    out = await PP.preview_pack(_bts(), finding, "", {}, finding=finding)
    d = next(x for x in out.draft if x.input == "prior_study")
    assert (d.state, d.value) == ("prefilled", "No") and "resolved" not in out.missing


async def test_a_comparison_line_that_does_not_mention_the_nodule_leaves_it_asked(monkeypatch, jev):
    from tests.test_library_partial import _bts
    _model(monkeypatch)                    # the model follows the definition: nothing proposed for prior_study
    out = await PP.preview_pack(_bts(), f"{NEW_ON_FOLLOW_UP}\n\nComparison: CT 2023.", "", {},
                                finding=NEW_ON_FOLLOW_UP)
    assert _states(out)["prior_study"] == "asked" and "prior_study" in out.missing


# live checkpoint 3: Fleischner risk from a smoking history
def test_fleischner_risk_definition_counts_a_former_smoker_as_high():
    how = _pack("fleischner-pulmonary-nodule").input("risk").how_stated
    assert "ex-smoker" in how and "intermediate risk counts as high" in how and "Low: only when" in how


async def test_an_ex_smoker_history_prefills_fleischner_risk_high(monkeypatch, jev):
    finding = "6 mm solid nodule in the left lower lobe."
    prompts = []
    _model(monkeypatch, {"input": "risk", "value": "high", "quote": "ex-smoker"}, prompts=prompts)
    out = await PP.preview_pack(_pack("fleischner-pulmonary-nodule"), finding, "65 year old ex-smoker", {},
                                finding=finding)
    d = next(x for x in out.draft if x.input == "risk")
    assert (d.state, d.value, d.quote) == ("prefilled", "high", "ex-smoker")       # never read: not the option word
    assert "ex-smoker" in prompts[0]


# reading lab 2026-10-15 (Hassan approved): a yes/no is read when Jev's four-way choice says the text states it in words,
# in the drafted direction, at STATED_MIN; implied, not mentioned, the other direction or a lower confidence pre-fill it
RLL = "7 mm solid nodule in the right upper lobe."


@pytest.mark.parametrize("pick,conf,state,why", [
    ("stated_yes", 0.95, "read", None),
    ("stated_yes", 0.89, "prefilled", "WHY_UNCONFIRMED"),
    ("stated_no", 0.99, "prefilled", "WHY_UNCONFIRMED"),
    ("implied", 0.99, "prefilled", "WHY_NOT_IN_WORDS"),
    ("not_mentioned", 0.99, "prefilled", "WHY_NOT_IN_WORDS")])
async def test_a_yes_no_is_read_only_when_jev_says_it_is_stated_in_words(monkeypatch, jev, pick, conf, state, why):
    from tests.test_library_partial import _bts
    jev["scores"] = {ONE_CLAIM: 0.95}
    jev["stated"] = {"Upper lobe location": (pick, conf)}
    _model(monkeypatch, {"input": "upper_lobe", "value": True, "quote": "right upper lobe"})
    out = await PP.preview_pack(_bts(), RLL, "", {}, finding=RLL)
    d = next(x for x in out.draft if x.input == "upper_lobe")
    assert d.state == state and PP.WHY_KIND not in d.why
    assert (why is None and d.why == []) or getattr(PP, why) in d.why


async def test_a_stated_no_is_read_and_the_four_way_rides_in_the_scope_batch(monkeypatch, jev):
    from tests.test_library_partial import _bts
    dictation = f"{PRIOR_FINDING}\n\nComparison: No previous imaging."
    jev["stated"] = {"Prior CT": ("stated_no", 0.96)}
    _model(monkeypatch, {"input": "prior_study", "value": False, "quote": "No previous imaging"})
    out = await PP.preview_pack(_bts(), dictation, "", {}, finding=PRIOR_FINDING)
    d = next(x for x in out.draft if x.input == "prior_study")
    assert (d.state, d.value) == ("read", "No")
    q = next(q for p in jev["payloads"] for q in p["questions"].values() if "Prior CT" in q["instructions"])
    assert q["type"] == "choice" and set(q["criteria"]) == {"stated_yes", "stated_no", "implied", "not_mentioned"}


async def test_an_eligibility_yes_no_is_never_read_even_when_jev_says_stated(monkeypatch, jev):
    from tests.test_library_suspected_cancer import _fleischner
    jev["stated"] = {"": ("stated_yes", 1.0)}
    e, s, p = await _fleischner(monkeypatch, "Known breast cancer.", "Known breast cancer")
    d = s.values["exclusion"]
    assert d.tier == "prefilled" and PP.WHY_SCOPE_KIND in d.why and "exclusion" in p.scope_doubt


async def test_a_malformed_four_way_answer_is_an_outage_never_a_read(monkeypatch, jev):
    from tests.test_library_partial import _bts
    jev["scores"] = {ONE_CLAIM: 0.95}
    jev["stated"] = {"Upper lobe location": (None, 0.99)}
    _model(monkeypatch, {"input": "upper_lobe", "value": True, "quote": "right upper lobe"})
    out = await PP.preview_pack(_bts(), RLL, "", {}, finding=RLL)
    d = next(x for x in out.draft if x.input == "upper_lobe")
    assert d.state == "prefilled" and PP.WHY_NO_CHECK in d.why
