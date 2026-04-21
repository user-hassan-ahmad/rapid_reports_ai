"""Tests for the HMAC helper used to sign admin approve/reject URLs."""
from __future__ import annotations

import uuid

import pytest

from rapid_reports_ai.auth import sign_admin_action, verify_admin_token


def test_sign_and_verify_roundtrip():
    uid = uuid.uuid4()
    token = sign_admin_action(uid, "approve")
    assert verify_admin_token(uid, "approve", token) is True


def test_verify_rejects_wrong_action():
    uid = uuid.uuid4()
    approve_token = sign_admin_action(uid, "approve")
    assert verify_admin_token(uid, "reject", approve_token) is False


def test_verify_rejects_wrong_user():
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    token = sign_admin_action(uid_a, "approve")
    assert verify_admin_token(uid_b, "approve", token) is False


def test_verify_rejects_tampered_token():
    uid = uuid.uuid4()
    token = sign_admin_action(uid, "approve")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert verify_admin_token(uid, "approve", tampered) is False


def test_invalid_action_raises():
    with pytest.raises(ValueError):
        sign_admin_action(uuid.uuid4(), "delete")  # type: ignore[arg-type]
