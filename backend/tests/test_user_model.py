"""Tests for the User model's new approval-gate fields."""
from __future__ import annotations

from sqlalchemy import inspect

from rapid_reports_ai.database.crud import create_user


def test_user_model_has_approval_fields(db_engine):
    cols = {c["name"] for c in inspect(db_engine).get_columns("users")}
    assert {"is_approved", "signup_reason", "role", "institution"}.issubset(cols)


def test_create_user_defaults_is_approved_false(db_session):
    user = create_user(
        db=db_session,
        email="new@test.com",
        password_hash="x",
        full_name="New User",
        role="registrar",
        institution="Test Hospital",
        signup_reason="Want to try it for on-call reporting",
    )
    assert user.is_approved is False
    assert user.is_verified is False
    assert user.role == "registrar"
    assert user.institution == "Test Hospital"
    assert user.signup_reason == "Want to try it for on-call reporting"


def test_create_user_accepts_no_optional_signup_context(db_session):
    # Backward compat: existing callers pass only email/password/full_name
    user = create_user(
        db=db_session,
        email="legacy@test.com",
        password_hash="x",
        full_name="Legacy",
    )
    assert user.role is None
    assert user.institution is None
    assert user.signup_reason is None


def test_user_to_dict_exposes_new_fields(db_session):
    user = create_user(
        db=db_session, email="d@test.com", password_hash="x",
        role="consultant_radiologist", institution="St Thomas'", signup_reason="Testing",
    )
    d = user.to_dict()
    assert d["is_approved"] is False
    assert d["role"] == "consultant_radiologist"
    assert d["institution"] == "St Thomas'"
    # signup_reason intentionally not exposed to self-serve user response (admin-only).
    assert "signup_reason" not in d
