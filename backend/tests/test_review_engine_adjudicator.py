# tests/test_review_engine_adjudicator.py
"""Adjudicator (spec §7): flat Judgement, one call per group, caps, failure → minor/no fix, brief-option rules."""
import asyncio
from pathlib import Path

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai.generation_artifacts import GenerationArtifacts
from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine import adjudicator as adj
from rapid_reports_ai.review_engine.items import Candidate, Edit, ReviewInput, ReviewItem, Span

LABS = Path(eu.__file__).parent / "scripts" / "review_labs" / "prompts"

J = dict(cls="action", kind="partial", label="Size missing", reason="r", edit_mode="replace", edit_find="a cyst",
         edit_replace="a 14 mm cyst", edit_after=None, edit_section="FINDINGS", probe="The FINDINGS section states the size.")


# Local copies of the shared fakes (tests/review_engine_fakes.py lands with Task 6).
def inp(report, dictation, history="", scan="CT abdomen", title=None):
    art = GenerationArtifacts(report=report, dictated_findings=dictation, sections=quick_section_names(report),
                              options=[], brief=None, quality_check=None)
    return ReviewInput(report_id="00000000-0000-0000-0000-000000000001", pathway="quick", artifacts=art,
                       clinical_history=history, scan_type=scan, study_title=title)


def model(output, calls=None):
    class R:
        pass

    async def fake(**kw):
        if calls is not None:
            calls.append(kw)
        r = R()
        r.output = output(kw) if callable(output) else output
        return r
    return fake


@pytest.fixture(autouse=True)
def _no_live_models(monkeypatch):
    async def boom(**kw):
        raise AssertionError("unstubbed model call")
    monkeypatch.setattr(adj, "_run_agent_with_model", boom)


def C(kind="partial", preclassed=None, detector="jev.classify_first", unsure=False, lane="coverage", evidence=None):
    ev = {"jev_unsure": {"question": "classify_first"}} if unsure else {}
    ev.update(evidence or {})
    return Candidate(lane=lane, kind=kind, preclassed=preclassed, detector=detector, line_text="line", evidence=ev)


def test_judgement_is_flat_and_prompt_present():
    assert all(f.annotation not in (dict, list) for f in adj.Judgement.model_fields.values())
    p = adj.prompt()
    assert "Uncertain means minor" in p and "When in doubt, suppress" not in p


def test_prompts_are_verbatim_lab_copies():
    assert adj.PROMPT_PATH.read_text() == (LABS / "adjudicator_v4.txt").read_text()
    assert adj.ADDITIONS_PROMPT_PATH.read_text() == (LABS / "adjudicator_v4_1.txt").read_text()


def test_additions_prompt_only_when_every_candidate_is_additions():
    v4, v41 = adj.prompt(), adj.prompt(additions=True)
    assert v4 != v41 and "Decide gradability first" in v41 and "Decide gradability first" not in v4
    assert adj.system_prompt_for([C(lane="additions", kind="grade", detector="s4")]) == v41
    assert adj.system_prompt_for([C(lane="additions", kind="grade", detector="s4"), C()]) == v4
    assert adj.system_prompt_for([C()]) == v4


def test_render_candidate_names_kind_not_lane_as_kind():
    s = adj.render_candidate(C(unsure=True, evidence={"missing_detail": "12 mm"}))
    assert 'Flag kind "partial" (from the coverage check, detector jev.classify_first)' in s
    assert "coverage/" not in s and "unsure" in s and "12 mm" in s and 'Dictated line: "line"' in s


def test_render_candidate_anchor_and_grade_zero():
    c = Candidate(lane="additions", kind="grade", detector="s4", anchor=Span(start=0, end=5, text="A cyst"),
                  evidence={"system": "CAD-RADS", "grade": 0, "criteria": "crit"})
    s = adj.render_candidate(c)
    assert 'Report statement: "A cyst"' in s and "grade: 0" in s and "Criteria text for this system: crit" in s


def test_q_conveys_not_imported():
    assert not hasattr(adj, "Q_CONVEYS")


def test_needs_judgement():
    assert adj.needs_judgement([C()])
    assert not adj.needs_judgement([C(preclassed="minor", detector="brief.option")])
    assert adj.needs_judgement([C(preclassed="minor", detector="brief.option", unsure=True)])


async def test_adjudicate_calls_per_group_and_skips_preclassed(monkeypatch):
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(**J), calls))
    out = await adj.adjudicate(inp("FINDINGS:\nA cyst.", "- 14 mm cyst"),
                               [[C()], [C(preclassed="minor", detector="brief.option")]])
    assert len(calls) == 1 and out[0].judgement.cls == "action" and out[1].judgement is None and out[1].error is None
    assert calls[0]["model_settings"]["reasoning_effort"] == "medium" and "DICTATION" in calls[0]["user_prompt"]
    assert calls[0]["retries"] == 0            # binding correction 1: no pydantic-ai output retries


async def test_failure_and_overflow_become_errors(monkeypatch):
    async def bad(**kw):
        raise ValueError("validation")
    monkeypatch.setattr(adj, "_run_agent_with_model", bad)
    monkeypatch.setattr(adj, "GROUP_CAP", 2)
    out = await adj.adjudicate(inp("FINDINGS:\nA.", "- a"), [[C()], [C()], [C()]])
    assert [o.error.split(":")[0] for o in out] == ["ValueError", "ValueError", "overflow"]
    assert [o.error_kind for o in out] == ["transport", "transport", "overflow"]


async def test_fallback_judgement_carries_every_field(monkeypatch):
    class ValidationError(Exception):
        pass

    async def bad(**kw):
        raise ValidationError("bad output")
    monkeypatch.setattr(adj, "_run_agent_with_model", bad)
    o = await adj.judge(inp("FINDINGS:\nA.", "- a"), [C(kind="absent")])
    assert o.error_kind == "validation" and o.error.startswith("ValidationError")
    j = o.judgement
    assert j.model_dump() == dict(cls="minor", kind="absent", label="", reason="", edit_mode="none", edit_find=None,
                                  edit_replace=None, edit_after=None, edit_section=None, probe=None)
    assert adj.to_edit(j) is None


async def test_concurrency_cap(monkeypatch):
    live, peak = 0, 0

    async def slow(**kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1

        class R:
            output = adj.Judgement(**J)
        return R()
    monkeypatch.setattr(adj, "_run_agent_with_model", slow)
    await adj.adjudicate(inp("FINDINGS:\nA.", "- a"), [[C()] for _ in range(12)])
    assert peak <= adj.CONCURRENCY


def test_cap_brief_never_raises_a_brief_option():
    j = adj.cap_brief(adj.Judgement(**J), [C(detector="brief.option")])
    assert j.cls == "minor"
    assert adj.cap_brief(adj.Judgement(**J), [C()]).cls == "action"


def test_to_edit():
    assert adj.to_edit(adj.Judgement(**{**J, "edit_mode": "none"})) is None
    e = adj.to_edit(adj.Judgement(**{**J, "edit_after": ""}))
    assert e == Edit(mode="replace", find="a cyst", replace="a 14 mm cyst", after=None, section="FINDINGS")


async def test_reprepare_lowers_but_never_raises_brief(monkeypatch):
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(**J)))
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="additions", detectors=["brief.option"], kind="option",
                    cls="minor", source_line="Sentence.")
    o = await adj.reprepare(inp("FINDINGS:\nA cyst.", "- a"), it)
    assert o.judgement.cls == "minor"


# --- enhancement_utils._run_agent_with_model: the retries keyword (binding correction 1) ------------------------

def _capture_agent(monkeypatch):
    seen = {}

    class FakeAgent:
        def __init__(self, *a, **kw):
            seen.update(kw)

        async def run(self, user_prompt, model_settings=None):
            class R:
                output = "ok"
            return R()
    monkeypatch.setattr(eu, "Agent", FakeAgent)
    monkeypatch.setattr(eu, "_create_pydantic_model", lambda *a, **k: object())
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda p: "k")
    return seen


async def test_run_agent_default_retries_unchanged(monkeypatch):
    seen = _capture_agent(monkeypatch)
    await eu._run_agent_with_model(model_name="qwen-3.8-27b", output_type=str, system_prompt="s", user_prompt="u",
                                   api_key="", model_settings={"temperature": 0})
    assert seen["retries"] == 2


async def test_run_agent_forwards_retries(monkeypatch):
    seen = _capture_agent(monkeypatch)
    await eu._run_agent_with_model(model_name="qwen-3.8-27b", output_type=str, system_prompt="s", user_prompt="u",
                                   api_key="", model_settings={"temperature": 0}, retries=0)
    assert seen["retries"] == 0


def test_cap_brief_only_when_every_candidate_is_a_brief_option():
    mixed = [C(detector="brief.option"), C(kind="contradicted", lane="accuracy", detector="jev.contradiction")]
    assert adj.cap_brief(adj.Judgement(**J), mixed).cls == "action"


def test_cap_additions_lane_at_minor():
    assert adj.cap_brief(adj.Judgement(**J), [C(lane="additions", detector="jev.addition")]).cls == "minor"
    mixed = [C(lane="additions"), C(lane="accuracy", kind="contradicted")]
    assert adj.cap_brief(adj.Judgement(**J), mixed).cls == "action"


async def test_reprepare_carries_evidence_and_renders_labels(monkeypatch):
    calls = []
    monkeypatch.setattr(adj, "_run_agent_with_model", model(adj.Judgement(**J), calls))
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="additions", detectors=["jev.addition"], kind="added",
                    cls="minor", label="Old label", source_line="Sentence.", probe="p",
                    evidence={"sentence": "Proposed X.", "numbers": ["5 mm"]})
    await adj.reprepare(inp("FINDINGS:\nA cyst.", "- a"), it)
    msg = calls[0]["user_prompt"]
    assert "Proposed sentence: \"Proposed X.\"" in msg and "numbers: ['5 mm']" in msg
    assert "Previous label: Old label" in msg
    assert "Dictated line" not in msg and "previous_label" not in msg
