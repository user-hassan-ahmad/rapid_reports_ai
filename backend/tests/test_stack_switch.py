import uuid

import pytest

from rapid_reports_ai import stack_switch as SW
from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.dictation_v2 import v2_allowed
from rapid_reports_ai.hybrid_stack.copilot.routes import copilot_allowed
from rapid_reports_ai.main import app


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


def test_stack_on_by_default_and_off_by_rr_stack():
    assert SW.stack_allowed({}) is True
    assert SW.stack_allowed({"RR_STACK": "0"}) is False


def test_stack_brings_the_dictation_package():
    assert v2_allowed({}) is True                      # stack on → /bundle, /polish-span, /keyterms, socket
    assert v2_allowed({"RR_STACK": "0"}) is False


def test_stack_off_keeps_the_v2_package():
    assert v2_allowed({"RR_STACK": "0", "RR_DICTATION_V2": "1"}) is True
    assert copilot_allowed({"RR_STACK": "0", "RR_DICTATION_V2": "1"}) is False


def test_status_reports_stack(authed, monkeypatch):
    monkeypatch.setenv("RR_STACK", "0")
    data = authed.get("/api/settings/status").json()
    assert data["stack"] is False and data["hybrid_stack"] is False and data["hybrid_stack_shadow_rate"] == 0.0


def test_status_reports_stack_on_without_the_dictation_flag(authed, monkeypatch):
    monkeypatch.delenv("RR_DICTATION_V2", raising=False)
    monkeypatch.delenv("RR_TRIAGE_DEBUG", raising=False)
    data = authed.get("/api/settings/status").json()
    assert data["stack"] is True and data["hybrid_stack"] is True and data["dictation_v2"] is True
