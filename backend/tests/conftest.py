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
from sqlalchemy.pool import StaticPool

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
    Report,
    EphemeralSkillSheet,
    Template,
    ReportQualityScore,
    TemplateCaseSheet,
    ReportReviewRun,
    ReportReviewItem,
    ReportChatMessage,
)
from rapid_reports_ai.main import app  # noqa: E402

# SQLite cannot compile Postgres-specific column types (TSVECTOR, Vector, ARRAY).
# We create the subset of tables whose columns are SQLite-compatible — enough for
# the approval-gate and quality-scoring tests. (report_feedback uses ARRAY and is
# intentionally excluded; JSONBType falls back to JSON on SQLite.)
_TEST_TABLES = [
    User.__table__,
    PasswordResetToken.__table__,
    Template.__table__,
    EphemeralSkillSheet.__table__,
    Report.__table__,
    ReportQualityScore.__table__,
    TemplateCaseSheet.__table__,
    ReportReviewRun.__table__,
    ReportReviewItem.__table__,
    ReportChatMessage.__table__,
]


@pytest.fixture
def db_engine():
    """Fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # all connections share the same in-memory DB
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


_QUALITY_MODULES = ("test_quick_report_quality", "test_report_review", "test_template_pipeline",
                    "test_golden_quick_pipeline")


@pytest.fixture(autouse=True)
def _no_live_quality_check(request, monkeypatch):
    """The post-generation check calls Jev over the network; unit tests outside the modules that
    stub it run the generators with it switched off."""
    if request.module.__name__.endswith(_QUALITY_MODULES):
        return
    monkeypatch.setenv("RR_QUALITY_CHECK", "0")


# ── Template endpoint fixtures (legacy retirement, generate endpoint) ──────────

@pytest.fixture
def test_user(db_session: Session) -> User:
    import uuid as _uuid
    user = User(
        id=_uuid.uuid4(), email=f"{_uuid.uuid4()}@nhs.net", password_hash="x", full_name="T",
        is_active=True, is_verified=True, is_approved=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    from rapid_reports_ai.auth import create_access_token
    return {"Authorization": f"Bearer {create_access_token({'sub': str(test_user.id)})}"}


def _make_template(db_session: Session, user: User, name: str, config: dict, tags=None) -> Template:
    template = Template(name=name, template_config=config, user_id=user.id, tags=tags or [], is_active=True)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def guided_template(db_session: Session, test_user: User) -> Template:
    """A current skill-sheet template."""
    return _make_template(db_session, test_user, "Guided", {
        "generation_mode": "skill_sheet_guided", "skill_sheet": "## FINDINGS\nDescribe the findings.",
        "scan_type": "CT"}, tags=["guided-tag"])


@pytest.fixture
def legacy_template(db_session: Session, test_user: User) -> Template:
    """A retired (section-based) template: hidden from lists, generation refused, never deleted."""
    return _make_template(db_session, test_user, "Legacy", {"sections": []}, tags=["legacy-tag"])
