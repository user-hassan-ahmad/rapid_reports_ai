from __future__ import annotations

import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_triage import TriageError
from rapid_reports_ai.main import app
from rapid_reports_ai.utterance_boundary import BoundaryDecision

BODY = {
    "scan_type": "CT chest",
    "buffered": "further satellite lesions noted in the",
    "chunk": "left lower lobe",
    "scratchpad_tail": "There is a 10 mm nodule.",
}


@pytest.fixture
def authed_client(client, db_session):
    user = User(
        id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
        is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class Fake:
    def __init__(self, boundary="complete", conf=0.9, raise_=False):
        self.boundary, self.conf, self.raise_, self.calls = boundary, conf, raise_, []

    async def classify(self, scan_type, buffered, chunk, scratchpad_tail):
        self.calls.append((scan_type, buffered, chunk, scratchpad_tail))
        if self.raise_:
            raise TriageError("boom")
        return BoundaryDecision(self.boundary, self.conf, {self.boundary: 1.0}, 0.1, 250, 200, 8e-06,
                                placement="extend_previous_line", placement_confidence=0.7)


def test_404_without_flag(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.post("/api/canvas/utterance", json=BODY).status_code == 404


def test_resolved_decision(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    fake = Fake("continues", 0.7)
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: fake)
    r = authed_client.post("/api/canvas/utterance", json=BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] == "continues" and body["boundary"] == "continues" and body["confidence"] == 0.7
    assert body["asr_risk"] == 0.1 and body["latency_ms"] == 250 and body["error"] is None
    assert body["placement"] == "extend_previous_line" and body["placement_confidence"] == 0.7
    assert fake.calls == [("CT chest", BODY["buffered"], "left lower lobe", "There is a 10 mm nodule.")]


def test_low_confidence_complete_resolves_to_continues(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: Fake("complete", 0.3))
    assert authed_client.post("/api/canvas/utterance", json=BODY).json()["resolved"] == "continues"


def test_error_fails_open(authed_client, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(cr, "get_jev_boundary", lambda: Fake(raise_=True))
    body = authed_client.post("/api/canvas/utterance", json=BODY).json()
    assert body["resolved"] == "complete" and body["error"] == "TriageError" and body["boundary"] is None
    assert body["placement"] == "new_line"
