"""Route-level tests for the three triage modes on POST /api/canvas/process.

The live model and both triagers are replaced with fakes. What is under test is
the wiring: which mode runs, that production responses are byte-identical when no
flag is set, that the lab fields are honoured only under RR_TRIAGE_DEBUG, and that
the shadow log carries no utterance text.
"""
from __future__ import annotations

import json
import logging
import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageDecision, TriageError, TriageState
from rapid_reports_ai.main import app

UTTERANCE = "actually make that the left upper lobe"
ACTIVE = "- 6 mm nodule right upper lobe"
BASE = {
    "session_transcript": f"there is a six millimetre nodule in the right upper lobe {UTTERANCE}",
    "scratchpad_content": ACTIVE,
    "scan_type": "CT chest",
    "clinical_history": "",
    "mode": "clean",
}


@pytest.fixture
def authed_client(client, db_session):
    user = User(
        id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x",
        full_name="Test Radiologist", is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class FakeTriager:
    def __init__(self, name, action="correct_previous_finding", confidence=0.97, raise_=False):
        self.name = name
        self.action = action
        self.confidence = confidence
        self.raise_ = raise_
        self.calls: list[TriageState] = []

    async def classify(self, state):
        self.calls.append(state)
        if self.raise_:
            raise TriageError("boom")
        return TriageDecision(
            candidate=self.name, action=self.action,
            confidence=self.confidence if self.name == "jev" else None,
            probabilities=None, is_correction=0.9, needs_committed_edit=0.1,
            latency_ms=5, input_tokens=None, cost_usd=None,
        )


@pytest.fixture
def fakes(monkeypatch):
    jev = FakeTriager("jev")
    qwen = FakeTriager("qwen")
    monkeypatch.setattr(cr, "get_triager", lambda name: {"jev": jev, "qwen": qwen}[name])
    return jev, qwen


@pytest.fixture
def live(monkeypatch):
    calls = []

    async def fake_live(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings,
                        use_thinking=False, label="canvas"):
        calls.append(label)
        return output_type(scratchpad=ACTIVE.replace("right", "left"), covered_sections=[])

    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake_live)
    return calls


def _post(client, **extra):
    return client.post("/api/canvas/process", json={**BASE, **extra})


# --- no flags: production behaviour --------------------------------------------

def test_no_flags_ignores_lab_fields_and_calls_no_triager(authed_client, fakes, live, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    monkeypatch.delenv("RR_TRIAGE_SHADOW", raising=False)
    plain = _post(authed_client).json()
    with_fields = _post(
        authed_client, last_utterance=UTTERANCE, triage_debug=True,
        triage_route={"candidate": "jev", "threshold": 0.5},
    ).json()
    assert plain == with_fields
    assert "triage" not in plain or plain["triage"] is None
    jev, qwen = fakes
    assert jev.calls == [] and qwen.calls == []
    assert live == ["canvas.process", "canvas.process"]


# --- shadow --------------------------------------------------------------------

def test_shadow_runs_both_and_logs_without_text(authed_client, fakes, live, monkeypatch, caplog):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")

    r = _post(authed_client, last_utterance=UTTERANCE)
    assert r.status_code == 200
    body = r.json()
    assert body.get("triage") is None
    assert body["scratchpad"] == ACTIVE.replace("right", "left")

    jev, qwen = fakes
    assert len(jev.calls) == 1 and len(qwen.calls) == 1
    st = jev.calls[0]
    assert st.latest_utterance == UTTERANCE and st.active == ACTIVE and st.committed == ""

    records = [rec.getMessage() for rec in caplog.records if "canvas.triage.shadow" in rec.getMessage()]
    assert len(records) == 1
    payload = json.loads(records[0].split(" ", 1)[1])
    assert payload["derived"] == "correct"
    assert payload["jev"]["action"] == "correct_previous_finding" and payload["jev"]["agrees"] is True
    assert payload["utterance_len"] == len(UTTERANCE)
    assert UTTERANCE not in records[0]
    assert ACTIVE not in records[0]


def test_shadow_jev_error_is_recorded_and_qwen_still_logged(authed_client, fakes, live, monkeypatch, caplog):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    caplog.set_level(logging.INFO, logger="rapid_reports_ai.canvas_routes")
    jev, qwen = fakes
    jev.raise_ = True

    r = _post(authed_client, last_utterance=UTTERANCE)
    assert r.status_code == 200
    msgs = [m.getMessage() for m in caplog.records if "canvas.triage.shadow" in m.getMessage()]
    payload = json.loads(msgs[0].split(" ", 1)[1])
    assert payload["jev"]["error"] == "TriageError" and payload["jev"]["action"] is None
    assert payload["qwen"]["action"] == "correct_previous_finding"


def test_shadow_without_utterance_calls_nothing(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_SHADOW", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _post(authed_client)
    jev, qwen = fakes
    assert jev.calls == [] and qwen.calls == []


# --- debug ---------------------------------------------------------------------

def test_debug_attaches_both_candidates_and_derived(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = _post(authed_client, last_utterance=UTTERANCE, triage_debug=True)
    body = r.json()
    assert body["scratchpad"] == ACTIVE.replace("right", "left")
    t = body["triage"]
    assert t["mode"] == "debug" and t["routed"] == "model"
    assert t["derived"] == "correct"
    assert t["jev"]["action"] == "correct_previous_finding" and t["jev"]["confidence"] == 0.97
    assert t["qwen"]["action"] == "correct_previous_finding" and t["qwen"]["confidence"] is None
    assert isinstance(t["live_latency_ms"], int)


# --- route ---------------------------------------------------------------------

def test_route_deterministic_skips_live_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen = fakes
    jev.action = "delete_previous_utterance"
    r = _post(
        authed_client, last_utterance="scratch that",
        scratchpad_content=ACTIVE + "\n- no pleural effusion",
        triage_route={"candidate": "jev", "threshold": 0.9},
    )
    body = r.json()
    assert body["scratchpad"] == ACTIVE
    assert body["covered_sections"] == []
    t = body["triage"]
    assert t["mode"] == "route" and t["routed"] == "deterministic" and t["routed_by"] == "jev"
    assert t["jev"]["action"] == "delete_previous_utterance"
    assert t["qwen"] is None
    assert live == []
    assert qwen.calls == []


def test_route_below_threshold_falls_to_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, _ = fakes
    jev.action, jev.confidence = "ignore_noise", 0.4
    body = _post(authed_client, last_utterance="um", triage_route={"candidate": "jev", "threshold": 0.9}).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["action"] == "ignore_noise"
    assert live == ["canvas.process"]


def test_route_triager_error_falls_to_model(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, _ = fakes
    jev.raise_ = True
    body = _post(authed_client, last_utterance="um", triage_route={"candidate": "jev", "threshold": 0.9}).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["error"] == "TriageError"
    assert live == ["canvas.process"]


def test_route_plus_debug_runs_other_candidate_only_once(authed_client, fakes, live, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    jev, qwen = fakes
    body = _post(
        authed_client, last_utterance=UTTERANCE, triage_debug=True,
        triage_route={"candidate": "jev", "threshold": 0.9},
    ).json()
    assert body["triage"]["routed"] == "model"
    assert body["triage"]["jev"]["action"] and body["triage"]["qwen"]["action"]
    assert len(jev.calls) == 1 and len(qwen.calls) == 1


# --- fixtures endpoint ----------------------------------------------------------

def test_fixtures_endpoint_gated(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.get("/api/canvas/triage/fixtures").status_code == 404
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = authed_client.get("/api/canvas/triage/fixtures")
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert cases and {"id", "utterance", "expected_action"} <= set(cases[0])
