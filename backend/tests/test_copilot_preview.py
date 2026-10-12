from rapid_reports_ai.hybrid_stack.copilot import preview as P
from rapid_reports_ai.hybrid_stack.copilot.types import (Branch, Entry, GuidelineContent, Input, Output, Preview,
                                                         Proposal, Settled)

BR = Branch(name="Solid", state="checked", inputs=[Input(id="risk", question="Risk", options=["Low risk", "High risk"])],
            rule="Solid 6-8 mm: high risk CT at 6-12 months, then 18-24 months",
            outputs=[Output(when="6-8 mm, high risk", classification="", recommendation="CT at 6-12 months, then CT at 18-24 months", quote="q")])
ENTRY = Entry(key="fleischner@2017", name="Fleischner", version="2017", content=GuidelineContent(branches=[BR]))


def test_numbers_ok():
    p = Proposal(classification="Fleischner 2017", line="7 mm solid nodule; Fleischner 2017 high risk.",
                 recommendation="CT at 6-12 months, then CT at 18-24 months")
    assert P.numbers_ok(p, ENTRY, BR, "7 mm solid nodule")
    bad = p.model_copy(update={"recommendation": "CT at 3 months"})
    assert not P.numbers_ok(bad, ENTRY, BR, "7 mm solid nodule")


def test_validate_forces_answers_and_drops_bad_values():
    raw = Preview(settled=[Settled(input="risk", value="Medium"), Settled(input="ghost", value="x")],
                  missing=["risk", "ghost"],
                  proposal=Proposal(classification="c", line="l"))
    out = P.validate(raw, BR, answered={})
    assert out.settled == [] and out.missing == ["risk"] and out.proposal is None
    out2 = P.validate(Preview(missing=["risk"]), BR, answered={"risk": "High risk"})
    assert out2.settled[0].value == "High risk" and out2.missing == []


async def test_preview_not_checked_branch_has_no_proposal():
    nb = BR.model_copy(update={"state": "not_available"})
    e = ENTRY.model_copy(update={"content": GuidelineContent(branches=[nb])})
    out = await P.preview(e, "Solid", "7 mm solid nodule.", "", {})
    assert out.proposal is None and out.missing == []


async def test_preview_drops_proposal_with_foreign_number(monkeypatch):
    async def call(prompt):
        return Preview(settled=[Settled(input="risk", value="High risk", quote="smoker")],
                       proposal=Proposal(classification="Fleischner 2017", line="l", recommendation="CT at 3 months"))
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(ENTRY, "Solid", "7 mm solid nodule, smoker.", "", {})
    assert out.proposal is None and out.settled[0].value == "High risk"


async def test_tnm_preview_proposal_comes_from_code(monkeypatch):
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    e = tnm.entry("Lung")

    async def call(prompt):
        assert "TX" in prompt
        return Preview(settled=[Settled(input="T", value="T2b"), Settled(input="N", value="N1"), Settled(input="M", value="M0")],
                       proposal=Proposal(classification="Stage IIB", line="model text"))
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(e, "Staging", "4.5 cm right upper lobe mass with ipsilateral hilar node.", "", {})
    assert out.proposal.line == "Staging (UICC TNM 9th): cT2b N1 M0, Stage IIB."


async def test_tnm_single_option_axis_is_never_missing(monkeypatch):
    """A site whose clinical T has one option (TX: T is classified only after excision) settles it by itself, even
    when the model reports it missing."""
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    e = tnm.entry("Melanoma of Skin")
    assert [i.options for i in e.content.branches[0].inputs if i.id == "T"] == [["TX"]]

    async def call(prompt):
        return Preview(settled=[Settled(input="N", value="N0"), Settled(input="M", value="M0")], missing=["T"])
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(e, "Staging", "f", "", {})
    assert out.missing == [] and {s.input: s.value for s in out.settled}["T"] == "TX"
    assert out.proposal is not None and "cTX N0 M0" in out.proposal.line


async def test_tnm_still_missing_axis_has_no_proposal(monkeypatch):
    from rapid_reports_ai.hybrid_stack.copilot import tnm
    e = tnm.entry("Lung")

    async def call(prompt):
        return Preview(settled=[Settled(input="T", value="T2b"), Settled(input="M", value="M0")], missing=["N"])
    monkeypatch.setattr(P, "_call", call)
    out = await P.preview(e, "Staging", "f", "", {})
    assert out.missing == ["N"] and out.proposal is None


async def test_preview_failure_returns_empty(monkeypatch):
    async def call(prompt):
        raise RuntimeError("x")
    monkeypatch.setattr(P, "_call", call)
    assert (await P.preview(ENTRY, "Solid", "f", "", {})).proposal is None
