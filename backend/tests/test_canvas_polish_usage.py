"""Lab /process responses carry the polish call's token usage (data only)."""
from __future__ import annotations

import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


class _U:
    input_tokens, output_tokens = 1500, 80


class _R:
    def __init__(self):
        self.output = cr.CanvasProcessResponse(scratchpad="No effusion.", covered_sections=[])

    def usage(self):
        return _U()


@pytest.fixture
def stub_model(monkeypatch):
    monkeypatch.setattr(cr, "_get_model_provider", lambda m: "groq")
    monkeypatch.setattr(cr, "_get_api_key_for_provider", lambda p: "k")

    async def _run(**kw):
        return _R()
    monkeypatch.setattr(cr, "_run_agent_with_model", _run)


BODY = {"session_transcript": "no effusion", "scratchpad_content": "", "last_utterance": "no effusion"}


def test_lab_response_carries_polish_usage(authed_client, stub_model, monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    d = authed_client.post("/api/canvas/process", json=BODY).json()
    assert d["scratchpad"] == "No effusion."
    assert d["polish_usage"]["input_tokens"] == 1500 and d["polish_usage"]["output_tokens"] == 80


def test_production_response_is_unchanged(authed_client, stub_model, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    d = authed_client.post("/api/canvas/process", json=BODY).json()
    assert set(d) == {"scratchpad", "covered_sections"}
