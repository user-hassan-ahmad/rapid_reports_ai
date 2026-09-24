from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import JEV_MODEL, TriageError
from rapid_reports_ai.utterance_boundary import (
    BOUNDARY_QUESTIONS,
    COMMAND_THRESHOLD,
    COMPLETE_THRESHOLD,
    BoundaryDecision,
    JevBoundary,
    resolve,
)


def _resp(boundary="complete", conf=0.9, asr=0.05):
    probs = {"complete": 0.0, "continues": 0.0, "command": 0.0}
    probs[boundary] = 1.0
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "boundary": {"type": "choice", "choice": boundary, "confidence": conf, "probabilities": probs},
            "asr_risk": {"type": "noul", "noul": asr},
        },
        "usage": {"input_tokens": 220, "output_tokens": 20, "cost": 9e-06},
    }


def test_questions_shape():
    assert set(BOUNDARY_QUESTIONS) == {"boundary", "asr_risk"}
    assert set(BOUNDARY_QUESTIONS["boundary"]["criteria"]) == {"complete", "continues", "command"}
    assert BOUNDARY_QUESTIONS["asr_risk"]["type"] == "noul"


async def test_request_and_parse():
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp())

    d = await JevBoundary(api_key="k", transport=httpx.MockTransport(handler)).classify(
        "CT chest", "further satellite lesions noted in the", "left lower lobe", "There is a 10 mm nodule."
    )
    b = captured["body"]
    assert b["model"] == JEV_MODEL
    assert b["state"] == {
        "scan_type": "CT chest",
        "buffered": "further satellite lesions noted in the",
        "chunk": "left lower lobe",
        "scratchpad_tail": "There is a 10 mm nodule.",
    }
    assert b["questions"] == BOUNDARY_QUESTIONS
    assert d.boundary == "complete" and d.confidence == 0.9 and d.asr_risk == 0.05 and d.input_tokens == 220


@pytest.mark.parametrize(
    "bad",
    [
        lambda: httpx.Response(500, json={"error": "x"}),
        lambda: httpx.Response(
            200, json={"answers": {"boundary": {"choice": "complete", "confidence": 1, "probabilities": {}}}}
        ),
        lambda: httpx.Response(200, json=_resp(boundary="maybe")),
        lambda: httpx.Response(200, json=_resp(asr=1.5)),
    ],
)
async def test_raises_on_invalid(bad):
    with pytest.raises(TriageError):
        await JevBoundary(api_key="k", transport=httpx.MockTransport(lambda r: bad())).classify("", "", "x", "")


def _d(boundary, conf):
    return BoundaryDecision(
        boundary=boundary, confidence=conf, probabilities={}, asr_risk=0.0, latency_ms=1, input_tokens=None, cost_usd=None
    )


def test_resolve_thresholds():
    assert resolve(_d("complete", COMPLETE_THRESHOLD)) == "complete"
    assert resolve(_d("complete", COMPLETE_THRESHOLD - 0.01)) == "continues"
    assert resolve(_d("command", COMMAND_THRESHOLD)) == "command"
    assert resolve(_d("command", COMMAND_THRESHOLD - 0.01)) == "continues"
    assert resolve(_d("continues", 1.0)) == "continues"


def test_resolve_fails_open_to_complete():
    assert resolve(TriageError("boom")) == "complete"
