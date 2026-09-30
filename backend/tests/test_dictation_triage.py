"""Unit tests for the System 1 triage candidates. Offline: Jev is exercised through
an httpx MockTransport; Qwen through an injected runner."""
from __future__ import annotations

import json

import httpx
import pytest

from rapid_reports_ai.dictation_triage import (
    ACTION_DESCRIPTIONS,
    JEV_MODEL,
    JEV_URL,
    TRIAGE_ACTIONS,
    JevTriager,
    TriageError,
    TriageState,
)

STATE = TriageState(
    committed="- 12 mm hypodense lesion segment 7",
    active="- 6 mm nodule right upper lobe",
    latest_utterance="actually make that the left upper lobe",
    scan_type="CT chest",
)


def _jev_response(action="correct_previous_finding", confidence=0.97, extra=None):
    probs = {a: 0.0 for a in TRIAGE_ACTIONS}
    probs[action] = 1.0
    body = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "action": {"type": "choice", "choice": action, "confidence": confidence, "probabilities": probs},
            "is_correction": {"type": "noul", "noul": 0.94},
            "needs_committed_edit": {"type": "noul", "noul": 0.03},
        },
        "usage": {"input_tokens": 578, "output_tokens": 40, "cost": 2.4e-05},
    }
    if extra:
        body.update(extra)
    return body


def _transport(handler):
    return httpx.MockTransport(handler)


def test_action_set_has_six_entries_with_descriptions():
    assert len(TRIAGE_ACTIONS) == 6
    assert set(ACTION_DESCRIPTIONS) == set(TRIAGE_ACTIONS)


async def test_jev_sends_expected_request_shape():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_jev_response())

    triager = JevTriager(api_key="sk-test", transport=_transport(handler))
    await triager.classify(STATE)

    assert captured["url"] == JEV_URL
    assert captured["auth"] == "Bearer sk-test"
    body = captured["body"]
    assert body["model"] == JEV_MODEL
    assert body["state"] == {
        "committed": STATE.committed,
        "active": STATE.active,
        "latest_utterance": STATE.latest_utterance,
        "scan_type": STATE.scan_type,
    }
    q = body["questions"]
    assert q["action"]["type"] == "choice"
    assert q["action"]["criteria"] == ACTION_DESCRIPTIONS
    assert q["is_correction"]["type"] == "noul"
    assert q["needs_committed_edit"]["type"] == "noul"


async def test_jev_parses_success_into_decision():
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=_jev_response())))
    d = await triager.classify(STATE)
    assert d.candidate == "jev"
    assert d.action == "correct_previous_finding"
    assert d.confidence == 0.97
    assert d.probabilities["correct_previous_finding"] == 1.0
    assert d.is_correction == 0.94
    assert d.needs_committed_edit == 0.03
    assert d.input_tokens == 578
    assert d.cost_usd == 2.4e-05
    assert d.latency_ms >= 0


@pytest.mark.parametrize(
    "status, body",
    [
        (400, {"error": {"message": "bad"}}),
        (500, {"error": {"message": "boom"}}),
    ],
)
async def test_jev_raises_on_non_2xx(status, body):
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(status, json=body)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_missing_answer():
    resp = _jev_response()
    del resp["answers"]["needs_committed_edit"]
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=resp)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_unknown_choice():
    triager = JevTriager(
        api_key="k", transport=_transport(lambda r: httpx.Response(200, json=_jev_response(action="explode")))
    )
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_out_of_range_values():
    resp = _jev_response()
    resp["answers"]["is_correction"]["noul"] = 1.4
    triager = JevTriager(api_key="k", transport=_transport(lambda r: httpx.Response(200, json=resp)))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


async def test_jev_raises_on_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    triager = JevTriager(api_key="k", transport=_transport(handler))
    with pytest.raises(TriageError):
        await triager.classify(STATE)


def test_jev_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TriageError):
        JevTriager()


# --- Qwen candidate, registry, traces -------------------------------------------


class _FakeResult:
    def __init__(self, output):
        self.output = output


