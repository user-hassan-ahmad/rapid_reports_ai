"""Integration tests for register + login against the approval gate."""
from __future__ import annotations

from typing import Any

from rapid_reports_ai.database.crud import get_user_by_email


VALID_SIGNUP = {
    "email": "alice@test.com",
    "password": "s3cretpass!",
    "full_name": "Alice",
    "role": "registrar",
    "institution": "St George's",
    "signup_reason": "Want to speed up on-call CT reporting during overnights",
}


def test_register_persists_new_fields_and_defaults_unapproved(client, db_session):
    response = client.post("/api/auth/register", json=VALID_SIGNUP)
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True, response.json()

    user = get_user_by_email(db_session, "alice@test.com")
    assert user is not None
    assert user.is_approved is False
    assert user.is_verified is False
    assert user.role == "registrar"
    assert user.institution == "St George's"
    assert "CT reporting" in (user.signup_reason or "")


def test_register_sends_admin_notification(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_notify(user) -> bool:
        captured["user_email"] = user.email
        captured["role"] = user.role
        return True

    monkeypatch.setattr(
        "rapid_reports_ai.main.send_admin_signup_notification", fake_notify
    )

    response = client.post("/api/auth/register", json=VALID_SIGNUP)
    assert response.status_code == 200
    assert captured["user_email"] == "alice@test.com"
    assert captured["role"] == "registrar"


def test_register_rejects_invalid_role(client):
    bad = {**VALID_SIGNUP, "role": "brain_surgeon"}
    response = client.post("/api/auth/register", json=bad)
    assert response.status_code == 422


def test_register_rejects_short_reason(client):
    bad = {**VALID_SIGNUP, "signup_reason": "yo"}
    response = client.post("/api/auth/register", json=bad)
    assert response.status_code == 422


def test_register_rejects_missing_role(client):
    bad = {k: v for k, v in VALID_SIGNUP.items() if k != "role"}
    response = client.post("/api/auth/register", json=bad)
    assert response.status_code == 422


def _create_user_with_flags(
    db_session, *, is_verified: bool, is_approved: bool, email: str = "bob@test.com"
):
    from rapid_reports_ai.auth import get_password_hash
    from rapid_reports_ai.database.crud import create_user
    user = create_user(
        db=db_session,
        email=email,
        password_hash=get_password_hash("s3cretpass!"),
        full_name="Bob",
        role="registrar",
        institution="X",
        signup_reason="some reason here",
    )
    user.is_verified = is_verified
    user.is_approved = is_approved
    db_session.commit()
    return user


def _login(client, email: str, password: str = "s3cretpass!"):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def test_login_blocked_when_pending_approval(client, db_session):
    _create_user_with_flags(db_session, is_verified=True, is_approved=False)
    response = _login(client, "bob@test.com")
    assert response.status_code == 200  # existing handler returns 200 with success=False
    data = response.json()
    assert data["success"] is False
    assert "approval" in data["error"].lower()


def test_login_still_blocked_when_unverified_after_approval(client, db_session):
    _create_user_with_flags(db_session, is_verified=False, is_approved=True)
    response = _login(client, "bob@test.com")
    data = response.json()
    assert data["success"] is False
    assert "verify" in data["error"].lower()


def test_login_succeeds_when_both_flags_true(client, db_session):
    _create_user_with_flags(db_session, is_verified=True, is_approved=True)
    response = _login(client, "bob@test.com")
    data = response.json()
    assert data["success"] is True, data
    assert "access_token" in data
