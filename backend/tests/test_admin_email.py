"""Tests for the admin signup-notification email helper."""
from __future__ import annotations

import uuid

from rapid_reports_ai import email_utils
from rapid_reports_ai.database.models import User


def _user(**overrides) -> User:
    u = User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="new@test.com",
        password_hash="x",
        full_name="Dr New User",
        is_active=True,
        is_verified=False,
        is_approved=False,
        role="registrar",
        institution="St George's",
        signup_reason="I want to speed up on-call CT reporting during overnights",
    )
    for k, v in overrides.items():
        setattr(u, k, v)
    return u


def test_build_admin_notification_body_includes_context_and_signed_links(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_API_BASE_URL", "https://api.test.local")

    subject, body = email_utils.build_admin_signup_notification(_user())

    assert "Dr New User" in body
    assert "new@test.com" in body
    assert "Registrar" in body  # humanised label
    assert "St George's" in body
    assert "on-call CT reporting" in body

    # approve + reject links present and contain the user id
    assert "https://api.test.local/api/admin/approve?uid=11111111-1111-1111-1111-111111111111&token=" in body
    assert "https://api.test.local/api/admin/reject?uid=11111111-1111-1111-1111-111111111111&token=" in body

    # subject names the role for one-glance triage
    assert "Registrar" in subject
    assert "Dr New User" in subject


def test_send_admin_signup_notification_routes_to_admin_email(monkeypatch):
    monkeypatch.setenv("ADMIN_NOTIFICATION_EMAIL", "admin@test.local")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_API_BASE_URL", "https://api.test.local")

    captured = {}

    def fake_send(to: str, subject: str, body: str) -> bool:
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body
        return True

    monkeypatch.setattr(email_utils, "_send_plain_email", fake_send)

    ok = email_utils.send_admin_signup_notification(_user())
    assert ok is True
    assert captured["to"] == "admin@test.local"
    assert "new@test.com" in captured["body"]
