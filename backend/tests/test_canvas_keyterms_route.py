from __future__ import annotations

import uuid

import pytest

import rapid_reports_ai.canvas_routes as cr
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app

BODY = {"scan_type": "CT chest, abdomen and pelvis", "clinical_history": "Staging, lung mass.",
        "sections": ["LUNGS", "ADRENAL GLANDS", "LIVER"]}


@pytest.fixture
def authed_client(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
                is_active=True, is_verified=True, is_approved=True)
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("RR_TRIAGE_DEBUG", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    cr._KEYTERM_CACHE.clear()
    calls = []

    async def fake(primary, fallback, *, output_type, system_prompt, user_prompt, model_settings,
                   use_thinking=False, label="canvas", usage_out=None):
        calls.append(user_prompt)
        return output_type(terms=["adrenal glands", "Normal", "hypodense", "paratracheal", "the liver"])
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", fake)
    return calls


def test_404_without_the_lab_flag(authed_client, monkeypatch):
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    assert authed_client.post("/api/canvas/keyterms", json=BODY).status_code == 404


def test_terms_are_generated_filtered_and_cached(authed_client, lab):
    d = authed_client.post("/api/canvas/keyterms", json=BODY).json()
    assert d["terms"] == ["adrenal glands", "hypodense", "paratracheal", "liver"] and d["source"] == "model"
    assert "ADRENAL GLANDS" in lab[0] and "Staging" in lab[0]
    d2 = authed_client.post("/api/canvas/keyterms", json=BODY).json()
    assert d2["terms"] == d["terms"] and d2["source"] == "cache" and len(lab) == 1


def test_a_model_failure_returns_no_terms_not_an_error(authed_client, lab, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(cr, "_run_canvas_with_fallback", boom)
    r = authed_client.post("/api/canvas/keyterms", json=BODY)
    assert r.status_code == 200 and r.json()["terms"] == [] and r.json()["error"] == "RuntimeError"
