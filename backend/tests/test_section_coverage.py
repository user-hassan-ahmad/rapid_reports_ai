from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.canvas_routes import CANVAS_COVERAGE_SYSTEM_PROMPT
from rapid_reports_ai.dictation_triage import JEV_MODEL, JEV_URL, TriageError
from rapid_reports_ai.section_coverage import (
    COVERAGE_CRITERIA,
    CoverageCandidateTrace,
    JevCoverage,
    coverage_questions,
    decision_to_coverage_trace,
)

SECTIONS = ["LUNGS", "PLEURA", "MEDIASTINUM"]
PAD = "- 6 mm nodule right upper lobe\n- no pleural effusion\n- mediastinum"


def _resp(scores: dict[str, float]):
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {k: {"type": "noul", "noul": v} for k, v in scores.items()},
        "usage": {"input_tokens": 410, "output_tokens": 30, "cost": 1.7e-05},
    }


def test_one_noul_per_section_with_section_substituted():
    q = coverage_questions(SECTIONS)
    assert list(q) == SECTIONS
    for s in SECTIONS:
        assert q[s]["type"] == "noul"
        assert s in q[s]["instructions"]
        assert s in q[s]["criteria"]["true"] and s in q[s]["criteria"]["false"]
        assert "{SECTION}" not in q[s]["criteria"]["true"]


@pytest.mark.parametrize(
    "phrase",
    ["bare mention", "collective", "adjacent", "abbreviation", "normality", "incidental co-mention", "vague filler"],
)
def test_criteria_share_key_phrases_with_the_qwen_prompt(phrase):
    joined = (COVERAGE_CRITERIA["true"] + " " + COVERAGE_CRITERIA["false"]).lower()
    assert phrase in joined
    assert phrase.split()[0] in CANVAS_COVERAGE_SYSTEM_PROMPT.lower()


async def test_jev_request_and_decision():
    captured = {}

    def handler(req: httpx.Request):
        captured["body"] = json.loads(req.content)
        captured["url"] = str(req.url)
        return httpx.Response(200, json=_resp({"LUNGS": 0.97, "PLEURA": 0.9, "MEDIASTINUM": 0.12}))

    cov = JevCoverage(api_key="k", transport=httpx.MockTransport(handler))
    d = await cov.classify(PAD, SECTIONS, "CT chest")

    assert captured["url"] == JEV_URL
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {"scan_type": "CT chest", "checklist": SECTIONS, "scratchpad": PAD}
    assert list(body["questions"]) == SECTIONS
    assert d.candidate == "jev"
    assert d.scores == {"LUNGS": 0.97, "PLEURA": 0.9, "MEDIASTINUM": 0.12}
    assert d.covered == ["LUNGS", "PLEURA"]
    assert d.input_tokens == 410 and d.cost_usd == 1.7e-05 and d.latency_ms >= 0


async def test_jev_empty_checklist_makes_no_call():
    def handler(req):
        raise AssertionError("must not be called")

    d = await JevCoverage(api_key="k", transport=httpx.MockTransport(handler)).classify(PAD, [], "")
    assert d.scores == {} and d.covered == []


async def test_jev_raises_on_missing_section():
    cov = JevCoverage(
        api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_resp({"LUNGS": 0.5})))
    )
    with pytest.raises(TriageError):
        await cov.classify(PAD, SECTIONS, "")


async def test_jev_raises_on_out_of_range_and_http_error():
    bad = JevCoverage(
        api_key="k",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=_resp({"LUNGS": 1.3, "PLEURA": 0, "MEDIASTINUM": 0}))
        ),
    )
    with pytest.raises(TriageError):
        await bad.classify(PAD, SECTIONS, "")
    err = JevCoverage(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": "x"})))
    with pytest.raises(TriageError):
        await err.classify(PAD, SECTIONS, "")


async def test_jev_raises_on_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(TriageError):
        await JevCoverage(api_key="k", transport=httpx.MockTransport(handler)).classify(PAD, SECTIONS, "")


def test_trace_from_exception():
    t = decision_to_coverage_trace(TriageError("boom"))
    assert isinstance(t, CoverageCandidateTrace) and t.error == "TriageError" and t.scores is None
    assert decision_to_coverage_trace(None) is None
