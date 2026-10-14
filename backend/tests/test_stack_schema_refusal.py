"""D15: /stack/schema refuses a template it can't use, instead of falling through to free text (P2b review I1)."""
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


def test_unusable_template_is_refused_with_the_d15_message(authed, db_session, user):
    t = Template(name="Old", template_config={"sections": []}, user_id=user.id, tags=[], is_active=True)
    db_session.add(t)
    db_session.commit()
    r = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT", "template_id": str(t.id)})
    assert r.status_code == 422
    assert r.json()["detail"] == "This template can't be used with the scratchpad. Create a fresh one."


def test_unknown_or_foreign_template_is_404(authed):
    r = authed.post("/api/canvas/stack/schema", json={"scan_type": "CT", "template_id": str(uuid.uuid4())})
    assert r.status_code == 404 and r.json()["detail"] == "Template not found."
