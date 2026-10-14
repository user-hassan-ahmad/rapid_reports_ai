"""A stale tab sending stack fields to an old Generate endpoint gets 409 "reload", never a report that ignores the
removed sentences (integration spec §5 Old endpoints)."""
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import Template, User
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


@pytest.mark.parametrize("extra", [{"stack": True}, {"stack_removed": ["a"]}, {"stack_declined": ["a"]},
                                   {"stack_conclusion": "c"}, {"stack_sheet_id": "s"}])
def test_old_quick_generate_409_on_stack_fields(authed, extra):
    r = authed.post("/api/quick-report/generate", json={"findings": "x", **extra})
    assert r.status_code == 409 and r.json()["detail"] == "reload"


def _template(db_session, user):
    t = Template(name="T", template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": "x"},
                 user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    return t


@pytest.mark.parametrize("extra", [{"stack": True, "stack_declined": ["a"]}, {"stack_conclusion": "c"},
                                   {"stack_values_na": ["RVEF"]}, {"stack_values_filled": ["LVEF"]}])
def test_old_template_generate_409(authed, db_session, user, extra):
    t = _template(db_session, user)
    r = authed.post(f"/api/templates/{t.id}/generate", json={"user_inputs": {"FINDINGS": "x"}, **extra})
    assert r.status_code == 409 and r.json()["detail"] == "reload"


def test_empty_stack_fields_are_not_a_stack_request():
    from rapid_reports_ai.legacy_guard import is_stale_stack_request
    from rapid_reports_ai.main import TemplateGenerateRequest
    from rapid_reports_ai.quick_report_api import GenerateRequest
    assert not is_stale_stack_request(GenerateRequest(findings="x", stack_removed=[], stack_conclusion=""))
    assert not is_stale_stack_request(TemplateGenerateRequest(user_inputs={}, stack_values_na=[]))


def test_old_quick_generate_without_stack_fields_is_not_409(authed, monkeypatch):
    from rapid_reports_ai import quick_report_api as Q
    monkeypatch.setattr(Q, "get_ephemeral_skill_sheet", lambda *a, **k: None)
    r = authed.post("/api/quick-report/generate", json={"findings": "x", "sheet_id": "nope"})
    assert r.status_code == 200      # the old SSE flow (its own error event), not 409
