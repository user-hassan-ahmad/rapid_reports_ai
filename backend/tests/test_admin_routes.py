"""Integration tests for /api/admin/approve and /api/admin/reject."""
from __future__ import annotations

import uuid

from rapid_reports_ai.auth import sign_admin_action, get_password_hash
from rapid_reports_ai.database.crud import create_user, get_user_by_email


def _seed_unapproved_user(db_session, email: str = "pending@test.com"):
    return create_user(
        db=db_session,
        email=email,
        password_hash=get_password_hash("s3cretpass!"),
        full_name="Pending User",
        role="registrar",
        institution="X",
        signup_reason="ten chars minimum reason",
    )


def test_approve_with_valid_token_flips_flag(client, db_session):
    user = _seed_unapproved_user(db_session)
    token = sign_admin_action(user.id, "approve")
    response = client.get(f"/api/admin/approve?uid={user.id}&token={token}")
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.is_approved is True
    assert b"approved" in response.content.lower()


def test_approve_with_invalid_token_rejected(client, db_session):
    user = _seed_unapproved_user(db_session)
    response = client.get(f"/api/admin/approve?uid={user.id}&token=deadbeef")
    assert response.status_code == 403
    db_session.refresh(user)
    assert user.is_approved is False


def test_approve_idempotent(client, db_session):
    user = _seed_unapproved_user(db_session)
    token = sign_admin_action(user.id, "approve")
    first = client.get(f"/api/admin/approve?uid={user.id}&token={token}")
    second = client.get(f"/api/admin/approve?uid={user.id}&token={token}")
    assert first.status_code == 200
    assert second.status_code == 200
    db_session.refresh(user)
    assert user.is_approved is True


def test_approve_token_cannot_reject(client, db_session):
    user = _seed_unapproved_user(db_session)
    approve_token = sign_admin_action(user.id, "approve")
    response = client.get(f"/api/admin/reject?uid={user.id}&token={approve_token}")
    assert response.status_code == 403
    db_session.refresh(user)
    assert user.is_approved is False
    assert get_user_by_email(db_session, "pending@test.com") is not None


def test_reject_deletes_user(client, db_session):
    user = _seed_unapproved_user(db_session)
    token = sign_admin_action(user.id, "reject")
    response = client.get(f"/api/admin/reject?uid={user.id}&token={token}")
    assert response.status_code == 200
    assert get_user_by_email(db_session, "pending@test.com") is None


def test_reject_idempotent_on_missing_user(client):
    ghost_id = uuid.uuid4()
    token = sign_admin_action(ghost_id, "reject")
    response = client.get(f"/api/admin/reject?uid={ghost_id}&token={token}")
    assert response.status_code == 200
    assert b"already" in response.content.lower() or b"removed" in response.content.lower()


def test_approve_unknown_user_returns_404(client):
    ghost_id = uuid.uuid4()
    token = sign_admin_action(ghost_id, "approve")
    response = client.get(f"/api/admin/approve?uid={ghost_id}&token={token}")
    assert response.status_code == 404
