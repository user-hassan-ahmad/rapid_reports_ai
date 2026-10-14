"""The tripwire (integration spec §9.5): every legacy entry point logs [legacy.call] while the stack is on."""
import logging
import uuid
from pathlib import Path

import pytest

from rapid_reports_ai import legacy_guard as LG
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app

SRC = Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai"


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="rad@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user, monkeypatch):
    monkeypatch.delenv("RR_STACK", raising=False)
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_mark_logs_only_with_the_stack_on(caplog, monkeypatch):
    monkeypatch.delenv("RR_STACK", raising=False)
    with caplog.at_level(logging.WARNING, logger="rapid_reports_ai.legacy"):
        LG.mark("canvas.sections", "u1", "/api/canvas/sections")
        assert "[legacy.call] canvas.sections user=u1 route=/api/canvas/sections" in caplog.text
        caplog.clear()
        monkeypatch.setenv("RR_STACK", "0")
        LG.mark("canvas.sections")
        assert caplog.text == ""


@pytest.mark.parametrize("name", LG.MARKS)
def test_every_mark_is_placed(name):
    hits = [p for p in SRC.rglob("*.py") if f'mark("{name}"' in p.read_text()]
    assert len(hits) == 1, f"{name}: {hits}"
    assert hits[0].read_text().count(f'mark("{name}"') == 1


def test_sections_route_logs(authed, caplog, monkeypatch):
    from rapid_reports_ai import canvas_routes as C

    def no_key(provider):
        raise ValueError("no key")
    monkeypatch.setattr(C, "_get_api_key_for_provider", no_key)   # no model call: the route stops at 503
    with caplog.at_level(logging.WARNING, logger="rapid_reports_ai.legacy"):
        authed.post("/api/canvas/sections", json={"scan_type": "CT", "clinical_history": ""})
    assert "[legacy.call] canvas.sections" in caplog.text


def test_structured_process_is_marked_and_clean_is_not(authed, caplog, monkeypatch):
    from rapid_reports_ai import canvas_routes as C

    async def fake(request, incremental, usage_out=None):
        return C.CanvasProcessResponse(scratchpad="x")
    monkeypatch.setattr(C, "_run_live_or_fallback", fake)
    body = {"session_transcript": "liver normal", "scratchpad_content": ""}
    with caplog.at_level(logging.WARNING, logger="rapid_reports_ai.legacy"):
        authed.post("/api/canvas/process", json={**body, "mode": "clean"})
        assert "[legacy.call]" not in caplog.text
        authed.post("/api/canvas/process", json={**body, "mode": "structured"})
        assert "[legacy.call] canvas.process.structured" in caplog.text


def test_clean_process_is_not_marked(authed, caplog, monkeypatch):
    from rapid_reports_ai import canvas_routes as C

    async def fake(request, incremental, usage_out=None):
        return C.CanvasProcessResponse(scratchpad="x")
    monkeypatch.setattr(C, "_run_live_or_fallback", fake)
    with caplog.at_level(logging.WARNING, logger="rapid_reports_ai.legacy"):
        authed.post("/api/canvas/process", json={"session_transcript": "liver normal", "scratchpad_content": "",
                                                 "mode": "clean"})
    assert "[legacy.call]" not in caplog.text


def test_copilot_match_is_not_marked(authed, caplog):
    with caplog.at_level(logging.WARNING, logger="rapid_reports_ai.legacy"):
        authed.post("/api/canvas/stack/guidelines/match", json={"scan_type": "CT", "findings": [], "dictation": ""})
    assert "[legacy.call]" not in caplog.text
