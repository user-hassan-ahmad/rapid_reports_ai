"""P2c Task 8: the converted-template banner's dismissal lives in User.settings (no migration, every browser)."""
import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app


@pytest.fixture
def user(db_session):
    u = User(id=uuid.uuid4(), email="banner@nhs.net", password_hash="x", full_name="T",
             is_active=True, is_verified=True, is_approved=True)
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def authed(client, user):
    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_banner_dismissal_round_trips(authed):
    assert authed.get("/api/settings").json()["banner_template_upgrade_dismissed"] is False
    r = authed.post("/api/settings", json={"banner_template_upgrade_dismissed": True})
    assert r.status_code == 200
    assert authed.get("/api/settings").json()["banner_template_upgrade_dismissed"] is True


def test_other_settings_leave_the_dismissal_alone(authed):
    authed.post("/api/settings", json={"banner_template_upgrade_dismissed": True})
    authed.post("/api/settings", json={"auto_save": False})
    data = authed.get("/api/settings").json()
    assert data["banner_template_upgrade_dismissed"] is True and data["auto_save"] is False
