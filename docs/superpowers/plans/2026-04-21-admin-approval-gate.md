# Admin Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate new user login behind manual admin approval; capture role/institution/reason at sign-up; one-click approve/reject from an HMAC-signed admin email.

**Architecture:** Alembic migration adds four columns to `users` (`is_approved`, `signup_reason`, `role`, `institution`). Register handler persists the new fields, creates user with `is_approved=FALSE`, and sends an admin notification email containing HMAC-signed approve/reject URLs. Login handler adds `is_approved` as a gate before `is_verified`. Two new `GET` endpoints validate the HMAC in the URL and either flip the flag or hard-delete the user. Frontend register page gains three form controls; login page gains a distinct pending-approval message.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic v2, Resend/SMTP (existing), Svelte 5 (frontend), pytest (new — bootstrapped by this plan).

**Spec:** `docs/superpowers/specs/2026-04-21-admin-approval-gate-design.md`

---

## File Structure

### Files created

| Path | Purpose |
|---|---|
| `backend/migrations/versions/20260421120000_add_user_approval_gate.py` | Alembic migration adding 4 columns, grandfathering existing rows |
| `backend/src/rapid_reports_ai/admin_routes.py` | FastAPI router with `/api/admin/approve` and `/api/admin/reject` endpoints |
| `backend/tests/conftest.py` | Pytest fixtures: isolated SQLite test DB, `TestClient`, helper factories |
| `backend/tests/test_auth_flow.py` | Integration tests for register + login gates |
| `backend/tests/test_admin_routes.py` | Integration tests for approve/reject endpoints |
| `backend/tests/test_admin_signing.py` | Unit tests for HMAC helper |

### Files modified

| Path | Change |
|---|---|
| `backend/pyproject.toml` | Add pytest + httpx dev dependencies; add `[tool.pytest.ini_options]` |
| `backend/src/rapid_reports_ai/database/models.py` | Add 4 columns to `User` model; extend `to_dict()` |
| `backend/src/rapid_reports_ai/database/crud.py` | Extend `create_user()` signature to accept new fields |
| `backend/src/rapid_reports_ai/auth.py` | Add `sign_admin_action()` + `verify_admin_token()` helpers |
| `backend/src/rapid_reports_ai/email_utils.py` | Add `send_admin_signup_notification()` function |
| `backend/src/rapid_reports_ai/main.py` | Update `RegisterRequest` schema; update register handler; add login `is_approved` gate; include admin router |
| `backend/.env.example` | Add `ADMIN_NOTIFICATION_EMAIL` |
| `frontend/src/routes/register/+page.svelte` | Add role dropdown, institution input, signup_reason textarea, update success banner |
| `frontend/src/routes/login/+page.svelte` | Add pending-approval blue banner path |

---

## Task 0: Pre-flight — create worktree and branch

**Files:** none touched yet.

- [ ] **Step 0.1: Create a worktree for this feature**

Run:

```bash
cd /Users/hassan/Code/rapid_reports_ai
git worktree add -b feat/admin-approval-gate .claude/worktrees/admin-approval-gate main
cd .claude/worktrees/admin-approval-gate
```

Expected: new worktree directory, branch `feat/admin-approval-gate` checked out.

- [ ] **Step 0.2: Confirm HEAD matches main**

Run: `git log --oneline -3`
Expected: top line matches `main`.

- [ ] **Step 0.3: Verify the spec is readable from this worktree**

Run: `ls docs/superpowers/specs/2026-04-21-admin-approval-gate-design.md`
Expected: file exists (it was committed to main before this branch was cut).

All subsequent tasks run inside this worktree.

---

## Task 1: Bootstrap pytest + test DB harness

The backend currently has no pytest configuration (only ad-hoc `test_*.py` scripts at repo root). Every task from Task 2 onwards depends on this, so it ships first.

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1.1: Add pytest config + dev deps to `backend/pyproject.toml`**

After the closing `]` of the `dependencies` list, add (or extend the existing `[tool.poetry.group.dev.dependencies]` block if it exists — check first with `grep -n "group.dev" backend/pyproject.toml`):

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.3.0"
pytest-asyncio = "^0.24.0"
httpx = "^0.27.0"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

Run: `cd backend && poetry install --with dev`
Expected: installs pytest, pytest-asyncio, httpx without error.

- [ ] **Step 1.2: Create `backend/tests/conftest.py`**

```python
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
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-do-not-use-in-prod")
os.environ.setdefault("ADMIN_NOTIFICATION_EMAIL", "admin@test.local")
os.environ.setdefault("FRONTEND_URL", "http://test.local")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from rapid_reports_ai.database import Base, get_db  # noqa: E402
from rapid_reports_ai.main import app  # noqa: E402


@pytest.fixture
def db_engine():
    """Fresh in-memory SQLite engine for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
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

    # Attach sent_emails so tests can inspect it: `client.sent_emails`
    client = TestClient(app)
    client.sent_emails = sent_emails  # type: ignore[attr-defined]

    try:
        yield client
    finally:
        app.dependency_overrides.clear()
```

> **Note:** `get_db` is re-exported from `rapid_reports_ai.database.__init__` (lives in `database/connection.py`). `Base` is re-exported from the same module. The import above matches verified layout.

- [ ] **Step 1.3: Create `backend/tests/test_smoke.py`**

```python
"""Verifies the test harness itself works before any feature tests are added."""


def test_db_engine_creates_users_table(db_engine):
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    assert "users" in inspector.get_table_names()


def test_client_reaches_app(client):
    # Any cheap endpoint. If none exists, use /openapi.json which FastAPI always serves.
    response = client.get("/openapi.json")
    assert response.status_code == 200
```

- [ ] **Step 1.4: Run the smoke suite**

Run: `cd backend && poetry run pytest tests/test_smoke.py -v`
Expected: 2 passed.

If `import rapid_reports_ai.main` fails because of a missing env var at module load, add the missing default to the `os.environ.setdefault` block at the top of `conftest.py` and re-run. Do NOT work around it by mocking the import.

- [ ] **Step 1.5: Commit**

```bash
git add backend/pyproject.toml backend/tests/conftest.py backend/tests/test_smoke.py backend/poetry.lock
git commit -m "test(backend): bootstrap pytest harness with in-memory SQLite + TestClient"
```

---

## Task 2: Database migration

**Files:**
- Create: `backend/migrations/versions/20260421120000_add_user_approval_gate.py`
- Test: `backend/tests/test_migration_approval_gate.py`

- [ ] **Step 2.1: Write the failing migration test**

Create `backend/tests/test_migration_approval_gate.py`:

```python
"""Verifies the admin-approval-gate migration adds columns and grandfathers existing users."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from alembic import command
from alembic.config import Config
import pathlib


def _alembic_config(db_url: str) -> Config:
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_migration_upgrade_adds_columns_and_grandfathers_existing_users(tmp_path):
    db_file = tmp_path / "test.sqlite"
    db_url = f"sqlite:///{db_file}"

    # Upgrade to the revision *before* ours, seed a user, then upgrade to ours.
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "b8c9d0e1f2a3")  # head prior to this migration

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, email, password_hash, is_active, is_verified, created_at) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'pre@test.com', 'x', 1, 1, CURRENT_TIMESTAMP)"
        ))

    command.upgrade(cfg, "20260421120000")

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert {"is_approved", "signup_reason", "role", "institution"}.issubset(cols)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT is_approved FROM users WHERE email='pre@test.com'")
        ).fetchone()
    assert row is not None
    assert bool(row[0]) is True, "pre-existing user should be grandfathered to is_approved=TRUE"


def test_migration_downgrade_drops_columns(tmp_path):
    db_file = tmp_path / "test.sqlite"
    db_url = f"sqlite:///{db_file}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "20260421120000")
    command.downgrade(cfg, "b8c9d0e1f2a3")

    engine = create_engine(db_url)
    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "is_approved" not in cols
    assert "signup_reason" not in cols
    assert "role" not in cols
    assert "institution" not in cols
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_migration_approval_gate.py -v`
Expected: FAIL with `FileNotFoundError` or `KeyError` on revision `20260421120000` (migration file not written yet).

- [ ] **Step 2.3: Write the migration file**

Create `backend/migrations/versions/20260421120000_add_user_approval_gate.py`:

```python
"""add_user_approval_gate

Revision ID: 20260421120000
Revises: b8c9d0e1f2a3
Create Date: 2026-04-21 12:00:00.000000

Adds is_approved, signup_reason, role, institution to users.
Grandfathers all pre-existing rows to is_approved=TRUE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421120000"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add approval gate columns to users."""
    # server_default='false' ensures NOT NULL works on existing rows; we then
    # explicitly grandfather them to TRUE below. New rows still default FALSE
    # because the model-level default (set in Task 3) overrides the server default.
    op.add_column(
        "users",
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("signup_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("institution", sa.String(length=200), nullable=True))

    # Grandfather every row that existed before this migration.
    op.execute("UPDATE users SET is_approved = TRUE")

    # Drop server_default so application code owns the default for new rows.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("is_approved", server_default=None)


def downgrade() -> None:
    """Downgrade schema - drop approval gate columns."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("institution")
        batch_op.drop_column("role")
        batch_op.drop_column("signup_reason")
        batch_op.drop_column("is_approved")
```

- [ ] **Step 2.4: Run the test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_migration_approval_gate.py -v`
Expected: 2 passed.

- [ ] **Step 2.5: Commit**

```bash
git add backend/migrations/versions/20260421120000_add_user_approval_gate.py backend/tests/test_migration_approval_gate.py
git commit -m "feat(db): add is_approved + signup context columns to users"
```

---

## Task 3: Update User model + CRUD

**Files:**
- Modify: `backend/src/rapid_reports_ai/database/models.py`
- Modify: `backend/src/rapid_reports_ai/database/crud.py`
- Test: extends `backend/tests/test_smoke.py` with a model-level check, and adds the next file:
- Create: `backend/tests/test_user_model.py`

- [ ] **Step 3.1: Write the failing model test**

Create `backend/tests/test_user_model.py`:

```python
"""Tests for the User model's new approval-gate fields."""
from __future__ import annotations

from sqlalchemy import inspect

from rapid_reports_ai.database.models import User
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
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_user_model.py -v`
Expected: FAIL — columns missing, or `create_user()` doesn't accept new kwargs.

- [ ] **Step 3.3: Update `backend/src/rapid_reports_ai/database/models.py`**

In the `User` class (currently around line 34), add these columns directly after the existing `is_verified` column:

```python
    # Admin approval gate
    is_approved = Column(Boolean, default=False, nullable=False)

    # Signup context (captured for admin triage)
    signup_reason = Column(Text, nullable=True)
    role = Column(String(32), nullable=True)
    institution = Column(String(200), nullable=True)
```

Then extend `to_dict()` (currently around line 66) to include `is_approved`, `role`, `institution` — but NOT `signup_reason` (which is admin-only):

```python
    def to_dict(self):
        return {
            "id": str(self.id),
            "email": self.email,
            "full_name": self.full_name,
            "signature": self.signature,
            "settings": self.settings or {},
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "is_approved": self.is_approved,
            "role": self.role,
            "institution": self.institution,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
```

- [ ] **Step 3.4: Update `backend/src/rapid_reports_ai/database/crud.py`**

Replace the existing `create_user` function (around lines 25–42) with:

```python
def create_user(
    db: Session,
    email: str,
    password_hash: str,
    full_name: Optional[str] = None,
    role: Optional[str] = None,
    institution: Optional[str] = None,
    signup_reason: Optional[str] = None,
) -> User:
    """Create a new user. New sign-ups default to is_approved=False."""
    user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        is_active=True,
        is_verified=False,
        is_approved=False,
        role=role,
        institution=institution,
        signup_reason=signup_reason,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
```

- [ ] **Step 3.5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_user_model.py tests/test_smoke.py -v`
Expected: all tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add backend/src/rapid_reports_ai/database/models.py backend/src/rapid_reports_ai/database/crud.py backend/tests/test_user_model.py
git commit -m "feat(user): add approval + signup-context fields to User model"
```

---

## Task 4: HMAC signing helper for admin action URLs

**Files:**
- Modify: `backend/src/rapid_reports_ai/auth.py`
- Test: `backend/tests/test_admin_signing.py`

- [ ] **Step 4.1: Write the failing helper test**

Create `backend/tests/test_admin_signing.py`:

```python
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
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_admin_signing.py -v`
Expected: FAIL with `ImportError` — helpers not yet defined.

- [ ] **Step 4.3: Add signing helpers to `backend/src/rapid_reports_ai/auth.py`**

Append to the end of the file:

```python
# ---------------------------------------------------------------------------
# Admin action URL signing (approve / reject from email)
# ---------------------------------------------------------------------------
import hmac as _hmac
import hashlib as _hashlib
from typing import Literal as _Literal
import uuid as _uuid

AdminAction = _Literal["approve", "reject"]
_ALLOWED_ADMIN_ACTIONS: tuple[str, ...] = ("approve", "reject")


def _admin_hmac(user_id: _uuid.UUID, action: str) -> str:
    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY not set; cannot sign admin action token")
    msg = f"{user_id}:{action}".encode()
    return _hmac.new(secret.encode(), msg, _hashlib.sha256).hexdigest()


def sign_admin_action(user_id: _uuid.UUID, action: AdminAction) -> str:
    """Produce an HMAC token authorising a one-off admin action for a user."""
    if action not in _ALLOWED_ADMIN_ACTIONS:
        raise ValueError(f"Unknown admin action: {action}")
    return _admin_hmac(user_id, action)


def verify_admin_token(user_id: _uuid.UUID, action: AdminAction, token: str) -> bool:
    """Constant-time compare of a supplied token against the expected HMAC."""
    if action not in _ALLOWED_ADMIN_ACTIONS:
        return False
    expected = _admin_hmac(user_id, action)
    return _hmac.compare_digest(expected, token)
```

> **Import note:** `auth.py` likely already imports `os`. If not, add `import os` at the top.

- [ ] **Step 4.4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_admin_signing.py -v`
Expected: 5 passed.

- [ ] **Step 4.5: Commit**

```bash
git add backend/src/rapid_reports_ai/auth.py backend/tests/test_admin_signing.py
git commit -m "feat(auth): add HMAC helpers for signed admin action URLs"
```

---

## Task 5: Admin signup-notification email helper

**Files:**
- Modify: `backend/src/rapid_reports_ai/email_utils.py`
- Test: `backend/tests/test_admin_email.py`

- [ ] **Step 5.1: Write the failing email test**

Create `backend/tests/test_admin_email.py`:

```python
"""Tests for the admin signup-notification email helper."""
from __future__ import annotations

import os
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
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
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
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
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
```

- [ ] **Step 5.2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_admin_email.py -v`
Expected: FAIL — `build_admin_signup_notification` / `send_admin_signup_notification` / `_send_plain_email` not defined.

- [ ] **Step 5.3: Add the helpers to `backend/src/rapid_reports_ai/email_utils.py`**

Append to the end of the file:

```python
# ---------------------------------------------------------------------------
# Admin notification on new sign-up
# ---------------------------------------------------------------------------

_ROLE_LABELS = {
    "consultant_radiologist": "Consultant radiologist",
    "registrar": "Registrar",
    "reporting_radiographer": "Reporting radiographer",
    "medical_student": "Medical student",
    "other_healthcare_professional": "Other healthcare professional",
    "other": "Other",
}


def _humanise_role(role: Optional[str]) -> str:
    if not role:
        return "Unknown"
    return _ROLE_LABELS.get(role, role)


def _send_plain_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via Resend, falling back to SMTP. Returns success."""
    resend_api_key = os.getenv("RESEND_API_KEY")
    if RESEND_AVAILABLE and resend_api_key:
        try:
            resend.api_key = resend_api_key
            from_email = os.getenv("RESEND_FROM_EMAIL", "RadFlow <onboarding@resend.dev>")
            emails = resend.emails._emails.Emails()
            emails.send({
                "from": from_email,
                "to": [to],
                "subject": subject,
                "text": body,
            })
            return True
        except Exception as exc:
            print(f"[admin-email] Resend failed: {exc}; falling back to SMTP")

    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    if not smtp_user or not smtp_password:
        print("[admin-email] No SMTP credentials; email not sent.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as exc:
        print(f"[admin-email] SMTP failed: {exc}")
        return False


def build_admin_signup_notification(user) -> tuple[str, str]:
    """Return (subject, body) for the admin notification email for a new user.

    `user` must have id, email, full_name, role, institution, signup_reason
    attributes. We import the signer lazily to avoid a circular import.
    """
    from .auth import sign_admin_action  # local import to avoid cycles

    role_label = _humanise_role(user.role)
    subject = f"[Radflow] New sign-up: {user.full_name or user.email} ({role_label})"

    api_base = os.getenv("ADMIN_API_BASE_URL", "https://radflow.app")
    approve_token = sign_admin_action(user.id, "approve")
    reject_token = sign_admin_action(user.id, "reject")
    approve_url = f"{api_base}/api/admin/approve?uid={user.id}&token={approve_token}"
    reject_url = f"{api_base}/api/admin/reject?uid={user.id}&token={reject_token}"

    body = (
        "A new user signed up for Radflow:\n"
        "\n"
        f"Name:        {user.full_name or '-'}\n"
        f"Email:       {user.email}\n"
        f"Role:        {role_label}\n"
        f"Institution: {user.institution or '-'}\n"
        "\n"
        "Why Radflow?\n"
        f"{user.signup_reason or '-'}\n"
        "\n"
        f"Approve:  {approve_url}\n"
        f"Reject:   {reject_url}\n"
    )
    return subject, body


def send_admin_signup_notification(user) -> bool:
    """Send the admin signup notification. Returns True on success."""
    admin_email = os.getenv("ADMIN_NOTIFICATION_EMAIL")
    if not admin_email:
        print("[admin-email] ADMIN_NOTIFICATION_EMAIL not set; skipping notification.")
        return False
    subject, body = build_admin_signup_notification(user)
    return _send_plain_email(admin_email, subject, body)
```

> **Imports:** `Optional` likely isn't yet imported in this module — add `from typing import Optional` at the top if missing.

- [ ] **Step 5.4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_admin_email.py -v`
Expected: 2 passed.

- [ ] **Step 5.5: Commit**

```bash
git add backend/src/rapid_reports_ai/email_utils.py backend/tests/test_admin_email.py
git commit -m "feat(email): add signed admin signup-notification helper"
```

---

## Task 6: Register handler — accept new fields, notify admin

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py`
- Test: `backend/tests/test_auth_flow.py`

- [ ] **Step 6.1: Write the failing register test**

Create `backend/tests/test_auth_flow.py`:

```python
"""Integration tests for register + login against the approval gate."""
from __future__ import annotations

from typing import Any

import pytest

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
    assert response.json()["success"] is True

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
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_auth_flow.py -v`
Expected: FAIL — schema rejects extra fields (`role`, `institution`, `signup_reason`) or 422 isn't raised for missing role.

- [ ] **Step 6.3: Update `RegisterRequest` in `backend/src/rapid_reports_ai/main.py`**

Replace the existing `RegisterRequest` class (around line 602) with:

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    full_name: Optional[str] = None
    role: Literal[
        "consultant_radiologist",
        "registrar",
        "reporting_radiographer",
        "medical_student",
        "other_healthcare_professional",
        "other",
    ]
    institution: Optional[str] = Field(default=None, max_length=200)
    signup_reason: str = Field(min_length=10, max_length=1000)
```

> **Imports:** ensure the following are imported at the top of `main.py`:
> ```python
> from typing import Literal, Optional
> from pydantic import BaseModel, EmailStr, Field
> ```
> `Optional` and `BaseModel` are already there; `Literal`, `EmailStr`, `Field` may need adding. Check with `grep -n "^from typing\|^from pydantic" backend/src/rapid_reports_ai/main.py`.

- [ ] **Step 6.4: Update the register handler in `backend/src/rapid_reports_ai/main.py`**

Replace the `register` handler (around lines 1177–1215) with:

```python
@app.post("/api/auth/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user. Creates unapproved user, emails user for verification
    and admin for approval."""
    try:
        existing_user = get_user_by_email(db, request.email)
        if existing_user:
            return {"success": False, "error": "Email already registered"}

        password_hash = get_password_hash(request.password)
        user = create_user(
            db=db,
            email=request.email,
            password_hash=password_hash,
            full_name=request.full_name,
            role=request.role,
            institution=request.institution,
            signup_reason=request.signup_reason,
        )

        # Email verification token (user flow — unchanged)
        verification_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        create_reset_token(
            db=db,
            user_id=str(user.id),
            token=verification_token,
            expires_at=expires_at,
            token_type="email_verification",
        )
        send_magic_link_email(request.email, verification_token, "email_verification")

        # Admin notification — best-effort; failure must not block registration.
        try:
            send_admin_signup_notification(user)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[register] admin notification failed: {exc}")

        return {
            "success": True,
            "message": (
                "Thanks — your account is pending admin approval. "
                "You'll receive an email once approved. "
                "We've also sent a verification email so you can confirm your address in the meantime."
            ),
            "user_id": str(user.id),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
```

Add the import near the top of `main.py` alongside existing email-utils imports:

```python
from .email_utils import send_magic_link_email, send_admin_signup_notification
```

- [ ] **Step 6.5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_auth_flow.py -v`
Expected: 5 passed.

- [ ] **Step 6.6: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_auth_flow.py
git commit -m "feat(auth): capture signup context + notify admin on register"
```

---

## Task 7: Login handler — add `is_approved` gate

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py`
- Test: extends `backend/tests/test_auth_flow.py`

- [ ] **Step 7.1: Add the failing login tests**

Append to `backend/tests/test_auth_flow.py`:

```python
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
    assert data["success"] is True
    assert "access_token" in data
```

> **Note:** the existing `login` handler returns HTTP 200 with `{"success": False, "error": ...}` for rejected logins rather than raising `HTTPException`. These tests match that contract. (The spec described a `403` — we will keep the existing 200-with-success-false contract to avoid breaking frontend, but use the spec's wording for the error string.)

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_auth_flow.py::test_login_blocked_when_pending_approval -v`
Expected: FAIL — approved-gate not yet enforced, so a `is_approved=False, is_verified=True` user logs in successfully.

- [ ] **Step 7.3: Add the gate to the login handler in `backend/src/rapid_reports_ai/main.py`**

In the `login` handler (around lines 1218–1259), insert the new check **after** the `is_active` check and **before** the `is_verified` check:

```python
        if not user.is_active:
            return {"success": False, "error": "Account is inactive"}

        # NEW: pending admin approval takes priority over email verification
        if not user.is_approved:
            return {
                "success": False,
                "error": "Account pending admin approval. You'll receive an email once it's approved.",
            }

        if not user.is_verified:
            return {
                "success": False,
                "error": "Please verify your email address before logging in. Check your inbox for the verification link.",
            }
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_auth_flow.py -v`
Expected: all 8 tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_auth_flow.py
git commit -m "feat(auth): add is_approved gate before email-verified gate at login"
```

---

## Task 8: Admin approve/reject endpoints

**Files:**
- Create: `backend/src/rapid_reports_ai/admin_routes.py`
- Modify: `backend/src/rapid_reports_ai/main.py` (register the router)
- Test: `backend/tests/test_admin_routes.py`

- [ ] **Step 8.1: Write the failing endpoint tests**

Create `backend/tests/test_admin_routes.py`:

```python
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
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_admin_routes.py -v`
Expected: FAIL — endpoints not yet defined.

- [ ] **Step 8.3: Create `backend/src/rapid_reports_ai/admin_routes.py`**

```python
"""Admin approve/reject endpoints. Authentication is by HMAC-in-URL only —
no session required, so the admin can action from their email client.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .auth import verify_admin_token
from .database import get_db
from .database.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _html(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        status_code=status,
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>body{font-family:system-ui;padding:3rem;max-width:40rem;margin:auto;}"
            "h1{font-size:1.25rem;margin-bottom:0.5rem;}"
            ".ok{color:#0a7d23;}.err{color:#a4262c;}</style></head>"
            f"<body>{body}</body></html>"
        ),
    )


def _parse_uid(uid: str) -> uuid.UUID:
    try:
        return uuid.UUID(uid)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")


@router.get("/approve", response_class=HTMLResponse)
async def approve_user(
    uid: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_id = _parse_uid(uid)
    if not verify_admin_token(user_id, "approve", token):
        return _html("Invalid", "<h1 class='err'>❌ Invalid or expired approval link</h1>", status=403)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return _html("Not found", "<h1 class='err'>❌ User not found</h1>", status=404)

    if user.is_approved:
        return _html(
            "Already approved",
            f"<h1 class='ok'>✅ {user.email} is already approved</h1>",
        )

    user.is_approved = True
    db.commit()
    return _html(
        "Approved",
        f"<h1 class='ok'>✅ {user.email} approved</h1>"
        f"<p>They can now verify their email and log in.</p>",
    )


@router.get("/reject", response_class=HTMLResponse)
async def reject_user(
    uid: str = Query(...),
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    user_id = _parse_uid(uid)
    if not verify_admin_token(user_id, "reject", token):
        return _html("Invalid", "<h1 class='err'>❌ Invalid or expired rejection link</h1>", status=403)

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return _html(
            "Already removed",
            "<h1 class='ok'>✅ User already removed</h1>",
        )

    email = user.email
    db.delete(user)
    db.commit()
    return _html(
        "Rejected",
        f"<h1 class='ok'>✅ {email} rejected and removed</h1>",
    )
```

> **Import note:** `get_db` is re-exported from `rapid_reports_ai.database.__init__`; the import above matches the verified layout.

- [ ] **Step 8.4: Register the router in `backend/src/rapid_reports_ai/main.py`**

Near the top of `main.py`, after the existing router imports, add:

```python
from .admin_routes import router as admin_router
```

After the `app = FastAPI(...)` construction (search for it with `grep -n "^app = FastAPI" backend/src/rapid_reports_ai/main.py`), add:

```python
app.include_router(admin_router)
```

- [ ] **Step 8.5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_admin_routes.py -v`
Expected: 7 passed.

- [ ] **Step 8.6: Run the full backend suite**

Run: `cd backend && poetry run pytest -v`
Expected: all tests pass (approx. 25 tests across six files).

- [ ] **Step 8.7: Commit**

```bash
git add backend/src/rapid_reports_ai/admin_routes.py backend/src/rapid_reports_ai/main.py backend/tests/test_admin_routes.py
git commit -m "feat(admin): add HMAC-signed approve/reject endpoints"
```

---

## Task 9: Env config

**Files:**
- Modify: `backend/.env.example` (create if missing)
- Modify: `backend/.env` (local only; don't commit)

- [ ] **Step 9.1: Check whether `.env.example` exists**

Run: `ls backend/.env.example 2>/dev/null || echo MISSING`

- [ ] **Step 9.2: Add `ADMIN_NOTIFICATION_EMAIL` and `ADMIN_API_BASE_URL`**

If `.env.example` exists, append:

```bash
# Admin approval gate
ADMIN_NOTIFICATION_EMAIL=hass.ahmad.95@gmail.com
ADMIN_API_BASE_URL=https://radflow.app
```

If it doesn't exist, skip this step — the defaults in code handle missing env gracefully at runtime, and you'll set them directly in the production environment (Railway dashboard).

- [ ] **Step 9.3: Set the vars in local `.env`**

Append to `backend/.env` (if not already present):

```bash
ADMIN_NOTIFICATION_EMAIL=hass.ahmad.95@gmail.com
ADMIN_API_BASE_URL=http://localhost:8000
```

Do NOT commit `backend/.env`.

- [ ] **Step 9.4: Commit (if .env.example was modified)**

```bash
git add backend/.env.example
git commit -m "chore(env): document admin approval env vars"
```

---

## Task 10: Frontend register page — new fields + updated banner

**Files:**
- Modify: `frontend/src/routes/register/+page.svelte`

- [ ] **Step 10.1: Update the `<script>` block**

Replace the `<script>` block of `frontend/src/routes/register/+page.svelte` with:

```svelte
<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAuthenticated } from '$lib/stores/auth';
	import logo from '$lib/assets/radflow-logo.png';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { API_URL } from '$lib/config';

	let email = '';
	let password = '';
	let fullName = '';
	let role = '';
	let institution = '';
	let signupReason = '';
	let error = '';
	let loading = false;
	let message = '';

	const ROLE_OPTIONS = [
		{ value: 'consultant_radiologist', label: 'Consultant radiologist' },
		{ value: 'registrar', label: 'Registrar' },
		{ value: 'reporting_radiographer', label: 'Reporting radiographer' },
		{ value: 'medical_student', label: 'Medical student' },
		{ value: 'other_healthcare_professional', label: 'Other healthcare professional' },
		{ value: 'other', label: 'Other' }
	];

	// Redirect if already logged in
	onMount(() => {
		if ($isAuthenticated) {
			goto('/');
		}
	});

	function validate() {
		if (!role) return 'Please select your role.';
		if (signupReason.trim().length < 10) return 'Please tell us a bit more (at least 10 characters).';
		if (signupReason.length > 1000) return 'Reason is too long (max 1000 characters).';
		return '';
	}

	async function handleRegister() {
		loading = true;
		error = '';
		message = '';

		const clientErr = validate();
		if (clientErr) {
			error = clientErr;
			loading = false;
			return;
		}

		try {
			const res = await fetch(`${API_URL}/api/auth/register`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email,
					password,
					full_name: fullName,
					role,
					institution: institution || null,
					signup_reason: signupReason
				})
			});

			const data = await res.json();

			if (res.ok && data.success) {
				message = data.message || 'Thanks — your account is pending admin approval. We\'ll email you when it\'s approved.';
			} else if (res.status === 422) {
				error = 'Please check the form — some fields look invalid.';
			} else {
				error = data.error || 'Registration failed. Please try again.';
			}
		} catch (err) {
			const errorMessage = err instanceof Error ? err.message : String(err);
			if (errorMessage.includes('Failed to fetch') || errorMessage.includes('NetworkError')) {
				error = 'Failed to connect. Please try again.';
			} else {
				error = 'Registration failed. Please try again.';
			}
		} finally {
			loading = false;
		}
	}
</script>
```

- [ ] **Step 10.2: Add the three new form controls to the markup**

In the `<form>` block, insert these three fields between the existing `Email` block and the `Password` block:

```svelte
<div class="mb-4">
	<label class="block text-sm font-medium text-gray-300 mb-1">
		Role <span class="text-red-400">*</span>
	</label>
	<select bind:value={role} required class="input-dark">
		<option value="" disabled>Select your role…</option>
		{#each ROLE_OPTIONS as opt}
			<option value={opt.value}>{opt.label}</option>
		{/each}
	</select>
</div>

<div class="mb-4">
	<label class="block text-sm font-medium text-gray-300 mb-1">
		Institution <span class="text-gray-500">(optional)</span>
	</label>
	<input
		type="text"
		bind:value={institution}
		maxlength="200"
		class="input-dark"
		placeholder="e.g. Guy's and St Thomas'"
	/>
</div>

<div class="mb-4">
	<label class="block text-sm font-medium text-gray-300 mb-1">
		Why do you want to use Radflow? <span class="text-red-400">*</span>
	</label>
	<textarea
		bind:value={signupReason}
		required
		minlength="10"
		maxlength="1000"
		rows="4"
		class="input-dark"
		placeholder="What made you try Radflow? What are you hoping to use it for?"
	></textarea>
	<p class="text-xs text-gray-500 mt-1">{signupReason.length} / 1000</p>
</div>
```

- [ ] **Step 10.3: Manual smoke test**

Run the frontend dev server and the backend locally. Register a test user. Expected:
- All three new fields render.
- Required validation fires if role or reason is missing.
- On submit, success banner shows "Thanks — your account is pending admin approval…" (not the old "check your email").
- DB row has `is_approved=FALSE`, `role`, `institution`, `signup_reason` all populated.
- Admin email arrives at `ADMIN_NOTIFICATION_EMAIL` with approve/reject links.

- [ ] **Step 10.4: Commit**

```bash
git add frontend/src/routes/register/+page.svelte
git commit -m "feat(register): capture role, institution, reason; show pending-approval banner"
```

---

## Task 11: Frontend login page — pending-approval message path

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte`

- [ ] **Step 11.1: Read the current error-handling block**

Run: `sed -n '35,80p' frontend/src/routes/login/+page.svelte` to locate the existing error handling around the fetch response.

- [ ] **Step 11.2: Add pending-approval branch**

Find the block that sets `error` when `data.success === false` and modify it so a pending-approval error becomes an informational message rather than a red error banner. Add a new state variable `pendingApproval` and set it when the error string contains `"pending admin approval"`:

In `<script>`:

```svelte
	let pendingApproval = false;
```

Reset it at the top of `handleLogin`:

```svelte
	async function handleLogin() {
		loading = true;
		error = '';
		pendingApproval = false;
		showResendLink = false;
		// ... existing code
	}
```

After parsing `data`, before the existing error fallback:

```svelte
	if (res.ok && data.success) {
		// ... existing success branch unchanged
	} else if (data.error && data.error.toLowerCase().includes('pending admin approval')) {
		pendingApproval = true;
	} else {
		error = data.error || 'Login failed. Please try again.';
	}
```

In the markup, add (above the existing red error banner):

```svelte
{#if pendingApproval}
	<div class="mb-4 p-3 bg-blue-500/10 border border-blue-500/30 text-blue-300 rounded-lg">
		Your account is still awaiting admin approval. You'll receive an email once it's approved.
	</div>
{/if}
```

- [ ] **Step 11.3: Manual smoke test**

Attempt to log in as a user with `is_approved=FALSE, is_verified=TRUE`. Expected: blue info banner, not red error.
Attempt to log in as a user with `is_approved=FALSE, is_verified=FALSE`. Expected: blue info banner (approval takes priority in the backend).
Attempt to log in as a user with `is_approved=TRUE, is_verified=FALSE`. Expected: existing "verify email" red error (unchanged).

- [ ] **Step 11.4: Commit**

```bash
git add frontend/src/routes/login/+page.svelte
git commit -m "feat(login): show distinct info banner for pending-approval accounts"
```

---

## Task 12: Full-system verification

**Files:** none — verification only.

- [ ] **Step 12.1: Run the full backend suite one more time**

Run: `cd backend && poetry run pytest -v`
Expected: all tests green.

- [ ] **Step 12.2: End-to-end manual smoke**

1. Start backend locally: `cd backend && poetry run uvicorn rapid_reports_ai.main:app --reload`
2. Start frontend locally: `cd frontend && pnpm dev` (or whatever the existing command is)
3. Open the register page, submit with:
   - role = Registrar
   - institution = Test Hospital
   - reason = "Testing approval gate end-to-end"
4. Confirm the pending-approval banner appears.
5. Confirm the admin email arrives at `ADMIN_NOTIFICATION_EMAIL`. Click **Approve**. Confirm the returned HTML page says "✅ approved".
6. Confirm DB now shows `is_approved=TRUE` for the test user (use psql or the preview script from the earlier session).
7. Click the verification link the user received. Confirm `is_verified=TRUE`.
8. Log in as the test user. Confirm success.
9. Sign up a second user. This time click the **Reject** link in the admin email. Confirm the user row is gone from DB.

- [ ] **Step 12.3: Run the production migration against Railway**

Run (from local machine, pointed at production DB):

```bash
cd backend
DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run alembic upgrade head
```

Expected: migration applies, no errors, existing 11 users all have `is_approved=TRUE`.

Verify with psql:

```sql
SELECT email, is_approved FROM users ORDER BY created_at;
```

All rows should show `t`.

- [ ] **Step 12.4: Push the branch and open a PR**

```bash
git push -u origin feat/admin-approval-gate
gh pr create --title "feat: admin approval gate for Radflow sign-ups" --body "$(cat <<'EOF'
## Summary
- New users created with `is_approved=FALSE` and captured `role`, `institution`, `signup_reason`
- Admin notification email with HMAC-signed approve/reject links
- Login handler adds `is_approved` gate before `is_verified` gate
- Existing 11 users grandfathered via migration

## Test plan
- [x] Backend pytest suite green
- [x] End-to-end manual smoke (register → approve email → verify → login)
- [x] Reject path hard-deletes user
- [x] Production migration verified against Railway DB

Spec: docs/superpowers/specs/2026-04-21-admin-approval-gate-design.md
Plan: docs/superpowers/plans/2026-04-21-admin-approval-gate.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 12.5: Confirm rollout criteria**

- [ ] 11 grandfathered users can still log in.
- [ ] A new sign-up hits `is_approved=FALSE` and triggers the admin email.
- [ ] Admin approve link flips the flag; user can then verify email and log in.
- [ ] Admin reject link hard-deletes the user.
- [ ] All backend tests pass on CI.

---

## Self-review notes

### Spec coverage
Every requirement in `docs/superpowers/specs/2026-04-21-admin-approval-gate-design.md` maps to at least one task:

- DB migration + grandfathering → Task 2
- `User` model fields + `to_dict` exposure policy → Task 3
- HMAC signing → Task 4
- Admin email structure + recipient → Task 5
- Register schema changes + admin notification trigger → Task 6
- Login `is_approved` gate ordering → Task 7
- `/api/admin/approve` + `/reject` behaviour (HMAC verify, idempotency, cascade) → Task 8
- Env vars → Task 9
- Frontend register form + banner → Task 10
- Frontend login distinct pending-approval path → Task 11
- Production migration + rollout checks → Task 12

### Known deviations from spec

- **Login error contract:** spec said `HTTPException 403`; the existing `login` handler returns HTTP 200 with `{"success": False, "error": ...}`. Task 7 keeps the existing contract so the frontend's current success-flag branch continues to work. The error *wording* matches the spec.
- **Test infrastructure:** spec assumed pytest patterns already existed under `backend/tests/`. They didn't. Task 1 bootstraps pytest + a fresh in-memory SQLite harness. This is a one-off extra cost; all subsequent tasks follow the spec's test list.

### No placeholders
Every step shows exact code or exact commands. No "TBD", "similar to above", or "add appropriate error handling" left in the plan.

### Type / signature consistency check
- `sign_admin_action(user_id: UUID, action: Literal["approve","reject"])` — used consistently in Tasks 4, 5, 8.
- `verify_admin_token(user_id: UUID, action: Literal["approve","reject"], token: str) -> bool` — consistent.
- `create_user(..., role, institution, signup_reason)` — new kwargs consistent across Tasks 3, 6, 7, 8 tests.
- Admin endpoints path prefix `/api/admin` — consistent.
- Role enum values (snake_case backend, humanised labels in email + frontend) — consistent across Tasks 5, 6, 10.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-admin-approval-gate.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
