import pytest

from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot import tnm
from rapid_reports_ai.hybrid_stack.copilot.types import Branch, Entry, GuidelineContent, Input, Output, Settled

BR = Branch(name="Solid", state="checked",
            inputs=[Input(id="risk", question="Risk", options=["Low risk", "High risk"]),
                    Input(id="count", question="Number of nodules", options=["Single", "Multiple"])],
            rule="Solid 6-8 mm: high risk CT at 6-12 months, then 18-24 months",
            outputs=[Output(when="6-8 mm, low risk", classification="", recommendation="CT at 6-12 months", quote="q"),
                     Output(when="6-8 mm, high risk", classification="High risk",
                            recommendation="CT at 6-12 months, then CT at 18-24 months", quote="q")])
ENTRY = Entry(key="fleischner@2017", name="Fleischner", version="2017", content=GuidelineContent(branches=[BR]))
GOOD = P.RawPreview(settled=[Settled(input="risk", value="High risk", quote="smoker")], not_needed=["count"],
                    output=2, line="7 mm solid nodule; Fleischner 2017 high risk.")


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _model(raw):
    async def call(system, prompt):
        return raw
    return call


@pytest.fixture
def jev(monkeypatch):
    """Jev answers every settled-value question with `score` (or raises); records the payloads."""
    st = {"score": 0.9, "fail": False, "payloads": []}

    async def post(payload, key, timeout, transport=None):
        st["payloads"].append(payload)
        if st["fail"]:
            raise TimeoutError("jev slow")
        return _Resp({"answers": {k: {"noul": st["score"]} for k in payload["questions"]}})
    monkeypatch.setattr(P, "jev_post", post)
    return st


def test_line_numbers_ok_maps_number_words():
    assert P.line_numbers_ok("7 mm nodule; Fleischner 2017.", ENTRY, BR, "7 mm solid nodule")
    assert not P.line_numbers_ok("Three nodules; Fleischner 2017.", ENTRY, BR, "7 mm solid nodule")
    assert P.line_numbers_ok("Two nodules; Fleischner 2017.", ENTRY, BR, "2 solid nodules")
    assert P.line_numbers_ok("2 nodules; Fleischner 2017.", ENTRY, BR, "two solid nodules")
    assert not P.line_numbers_ok("twenty-one nodules", ENTRY, BR, "twenty nodules")


def test_validate_rejected_value_becomes_missing_even_if_not_needed():
    raw = P.RawPreview(settled=[Settled(input="risk", value="Medium"), Settled(input="ghost", value="x")],
                       not_needed=["risk", "count"])
    out, _ = P.validate(raw, ENTRY, BR, answered={})
    assert out.settled == [] and out.missing == ["risk"]


def test_validate_missing_is_computed_in_code():
    out, _ = P.validate(P.RawPreview(), ENTRY, BR, answered={"risk": "High risk"})
    assert [s.value for s in out.settled] == ["High risk"] and out.missing == ["count"]
    out, _ = P.validate(P.RawPreview(not_needed=["count"]), ENTRY, BR, answered={"risk": "High risk"})
    assert out.missing == []


async def test_preview_not_checked_branch_has_no_proposal():
    nb = BR.model_copy(update={"state": "not_available"})
    e = ENTRY.model_copy(update={"content": GuidelineContent(branches=[nb])})
    out = await P.preview(e, "Solid", "7 mm solid nodule.", "", {})
    assert out.proposal is None and out.missing == []


async def test_output_index_is_copied_verbatim(monkeypatch, jev):
    monkeypatch.setattr(P, "_call", _model(GOOD))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal.classification == "Fleischner 2017 · High risk"
    assert out.proposal.recommendation == "CT at 6-12 months, then CT at 18-24 months"
    assert out.proposal.line == GOOD.line
    q = jev["payloads"][0]["questions"]["s0"]["instructions"]
    assert q == "The FINDINGS or CLINICAL HISTORY state this: Risk: High risk"
    assert jev["payloads"][0]["state"] == "CLINICAL HISTORY:\nnone given\n\nFINDINGS:\n7 mm solid nodule, smoker."


async def test_output_without_category_uses_identity(monkeypatch, jev):
    monkeypatch.setattr(P, "_call", _model(GOOD.model_copy(update={"output": 1})))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal.classification == "Fleischner 2017" and out.proposal.recommendation == "CT at 6-12 months"


@pytest.mark.parametrize("idx", [None, 0, 3, -1])
async def test_invalid_output_index_has_no_proposal(monkeypatch, jev, idx):
    monkeypatch.setattr(P, "_call", _model(GOOD.model_copy(update={"output": idx})))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal is None and out.missing == []


async def test_foreign_number_in_line_drops_proposal(monkeypatch, jev):
    monkeypatch.setattr(P, "_call", _model(GOOD.model_copy(update={"line": "Fleischner 2017; follow up in 3 months."})))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal is None and out.settled[0].value == "High risk"


async def test_jev_below_threshold_makes_input_missing(monkeypatch, jev):
    jev["score"] = 0.3
    monkeypatch.setattr(P, "_call", _model(GOOD))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule.", "", {})
    assert out.settled == [] and out.missing == ["risk"] and out.proposal is None


async def test_jev_failure_asks_every_model_value(monkeypatch, jev):
    jev["fail"] = True
    monkeypatch.setattr(P, "_call", _model(GOOD))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {"count": "Single"})
    assert [s.input for s in out.settled] == ["count"] and out.missing == ["risk"] and out.proposal is None


async def test_answered_values_are_not_jev_checked(monkeypatch, jev):
    monkeypatch.setattr(P, "_call", _model(GOOD.model_copy(update={"settled": []})))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule.", "", {"risk": "High risk"})
    assert jev["payloads"] == [] and out.proposal.classification == "Fleischner 2017 · High risk"


async def test_model_disagreeing_with_answer_has_no_proposal(monkeypatch, jev):
    monkeypatch.setattr(P, "_call", _model(GOOD.model_copy(update={"settled": [Settled(input="risk", value="Low risk")]})))
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule.", "", {"risk": "High risk"})
    assert out.settled[0].value == "High risk" and out.missing == [] and out.proposal is None


async def test_tnm_preview_proposal_comes_from_code(monkeypatch, jev):
    e = tnm.entry("Lung")
    seen = {}

    async def call(system, prompt):
        seen["system"] = system
        assert "TX" in prompt
        return P.RawPreview(settled=[Settled(input="T", value="T2b"), Settled(input="N", value="N1"),
                                     Settled(input="M", value="M0")], output=1, line="model text")
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(e, "Staging", "4.5 cm right upper lobe mass with ipsilateral hilar node.", "", {})
    assert out.proposal.line == "Staging (UICC TNM 9th): cT2b N1 M0, Stage IIB."
    assert "never X" in seen["system"]
    assert len(jev["payloads"][0]["questions"]) == 3


async def test_x_option_sentence_only_for_tnm(monkeypatch, jev):
    seen = {}

    async def call(system, prompt):
        seen["system"] = system
        return GOOD
    monkeypatch.setattr(P, "_call", call)
    await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert "TX" not in seen["system"] and "never X" not in seen["system"]


async def test_tnm_undictated_x_is_missing(monkeypatch, jev):
    """An X value Jev cannot confirm from the dictation is asked, not assumed."""
    e = tnm.entry("Lung")

    async def post(payload, key, timeout, transport=None):
        qs = payload["questions"]
        return _Resp({"answers": {k: {"noul": 0.1 if q["instructions"].endswith("NX") else 0.9} for k, q in qs.items()}})
    monkeypatch.setattr(P, "jev_post", post)
    monkeypatch.setattr(P, "_call", _model(P.RawPreview(settled=[Settled(input="T", value="T2b"),
                                                                 Settled(input="N", value="NX"),
                                                                 Settled(input="M", value="M0")])))
    out = await P.preview(e, "Staging", "4.5 cm lung mass.", "", {})
    assert out.missing == ["N"] and out.proposal is None


async def test_tnm_single_option_axis_is_never_missing(monkeypatch, jev):
    """A site whose clinical T has one option (TX: T is classified only after excision) settles it by itself, even
    when the model never settles it; it is not Jev-checked."""
    e = tnm.entry("Melanoma of Skin")
    assert [i.options for i in e.content.branches[0].inputs if i.id == "T"] == [["TX"]]
    monkeypatch.setattr(P, "_call", _model(P.RawPreview(settled=[Settled(input="N", value="N0"),
                                                                 Settled(input="M", value="M0")])))
    out = await P.preview(e, "Staging", "f", "", {})
    assert out.missing == [] and {s.input: s.value for s in out.settled}["T"] == "TX"
    assert out.proposal is not None and "cTX N0 M0" in out.proposal.line
    assert len(jev["payloads"][0]["questions"]) == 2


async def test_tnm_not_needed_cannot_skip_an_axis(monkeypatch, jev):
    e = tnm.entry("Lung")
    monkeypatch.setattr(P, "_call", _model(P.RawPreview(settled=[Settled(input="T", value="T2b"),
                                                                 Settled(input="M", value="M0")], not_needed=["N"])))
    out = await P.preview(e, "Staging", "f", "", {})
    assert out.missing == ["N"] and out.proposal is None


async def test_preview_failure_returns_missing_inputs(monkeypatch):
    async def call(system, prompt):
        raise RuntimeError("x")
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(ENTRY, "Solid", "f", "", {"count": "Single"})
    assert out.proposal is None and out.missing == ["risk"]
