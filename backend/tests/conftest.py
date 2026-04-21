"""Shared pytest fixtures for the Radflow backend test suite.

Each test gets a fresh, empty SQLite database and a TestClient configured
to use that DB. FastAPI's dependency overrides keep this isolated from the
real app-level DB session.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set env BEFORE importing the app so any module-level config reads test values.
os.environ.setdefault("SECRET_KEY", "test-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_NOTIFICATION_EMAIL", "admin@test.local")
os.environ.setdefault("ADMIN_API_BASE_URL", "http://test.local")
os.environ.setdefault("FRONTEND_URL", "http://test.local")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from rapid_reports_ai.database import Base, get_db  # noqa: E402
from rapid_reports_ai.database.models import (  # noqa: E402
    User,
    PasswordResetToken,
)
from rapid_reports_ai.main import app  # noqa: E402

# SQLite cannot compile Postgres-specific column types (TSVECTOR, JSONB) used by
# other tables in the schema. The approval-gate feature only touches users and
# password_reset_tokens, so we create exactly those two against SQLite.
_TEST_TABLES = [User.__table__, PasswordResetToken.__table__]


@pytest.fixture
def db_engine():
    """Fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine, tables=_TEST_TABLES)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    """SQLAlchemy session bound to the per-test engine."""
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session, monkeypatch) -> Iterator[TestClient]:
    """FastAPI TestClient with DB dependency overridden to the per-test session.

    Also stubs out email sending so tests never try to reach Resend/SMTP.
    """
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Stub email senders — tests that want to assert on email go through mocks.
    sent_emails: list[dict[str, Any]] = []

    def _fake_send_magic_link(email: str, token: str, link_type: str = "password_reset") -> bool:
        sent_emails.append({"kind": "magic_link", "email": email, "token": token, "link_type": link_type})
        return True

    monkeypatch.setattr(
        "rapid_reports_ai.main.send_magic_link_email", _fake_send_magic_link
    )

    test_client = TestClient(app)
    test_client.sent_emails = sent_emails  # type: ignore[attr-defined]

    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
