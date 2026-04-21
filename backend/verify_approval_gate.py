"""End-to-end verification of the admin approval gate.

Exercises every piece built in Tasks 1–9 against a real SQLite file:
1. Migration applies cleanly on top of a seeded pre-migration schema
2. Existing rows are grandfathered to is_approved=TRUE
3. Register: persists all new fields, triggers admin email with signed URLs
4. Login: blocks pending approval, then blocks unverified, then succeeds
5. Admin approve: flips flag via real HMAC check; idempotent
6. Admin reject: deletes user
7. HMAC: approve-token cannot be used to reject, tampered token rejected
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="radflow-verify-"))
DB_FILE = TMP / "test.sqlite"
DB_URL = f"sqlite:///{DB_FILE}"

# Configure env BEFORE importing the app
os.environ["SECRET_KEY"] = "verify-script-secret"
os.environ["DATABASE_URL"] = DB_URL
os.environ["ADMIN_NOTIFICATION_EMAIL"] = "admin@verify.com"
os.environ["ADMIN_API_BASE_URL"] = "https://api.verify.local"
os.environ["FRONTEND_URL"] = "https://app.verify.local"

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config


# ---------- 1. Seed pre-migration state ----------
print("\n=== STEP 1: Seed pre-migration users table ===")
engine = create_engine(DB_URL)
with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE users (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(200),
            signature TEXT,
            settings TEXT,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            is_verified BOOLEAN NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """))
    conn.execute(text(
        "CREATE TABLE password_reset_tokens ("
        "id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, "
        "token VARCHAR(255) NOT NULL UNIQUE, "
        "expires_at TIMESTAMP NOT NULL, "
        "is_used BOOLEAN NOT NULL DEFAULT 0, "
        "token_type VARCHAR(20) NOT NULL DEFAULT 'password_reset', "
        "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)"
    ))
    conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    conn.execute(text("INSERT INTO alembic_version VALUES ('b8c9d0e1f2a3')"))
    conn.execute(text(
        "INSERT INTO users (id, email, password_hash, is_active, is_verified, created_at) "
        "VALUES ('00000000-0000-0000-0000-000000000001', 'legacy@verify.com', 'x', 1, 1, CURRENT_TIMESTAMP)"
    ))
print("  ✓ users + password_reset_tokens seeded with 1 legacy user")


# ---------- 2. Apply migration ----------
print("\n=== STEP 2: Apply migration 20260421120000 ===")
backend_dir = Path(__file__).resolve().parent
cfg = Config(str(backend_dir / "alembic.ini"))
cfg.set_main_option("script_location", str(backend_dir / "migrations"))
cfg.set_main_option("sqlalchemy.url", DB_URL)
command.upgrade(cfg, "20260421120000")

cols = {c["name"] for c in inspect(engine).get_columns("users")}
assert {"is_approved", "signup_reason", "role", "institution"}.issubset(cols), \
    f"missing columns after migration: got {cols}"
print(f"  ✓ columns present: is_approved, signup_reason, role, institution")

with engine.connect() as conn:
    row = conn.execute(text(
        "SELECT is_approved FROM users WHERE email='legacy@verify.com'"
    )).fetchone()
assert row and bool(row[0]) is True, "legacy user should be grandfathered to TRUE"
print(f"  ✓ legacy user grandfathered: is_approved=True")


# ---------- 3. Spin up app with TestClient ----------
print("\n=== STEP 3: Spin up FastAPI TestClient ===")

# Late import to pick up env
from rapid_reports_ai.database.models import Base  # noqa: E402
from rapid_reports_ai.database import get_db  # noqa: E402
from rapid_reports_ai.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Capture admin emails + magic-link emails
sent_emails: list[dict] = []

from rapid_reports_ai import email_utils  # noqa: E402
from rapid_reports_ai import main as main_mod  # noqa: E402

original_plain = email_utils._send_plain_email


def fake_plain(to, subject, body):
    sent_emails.append({"kind": "admin", "to": to, "subject": subject, "body": body})
    return True


def fake_magic(email, token, link_type="password_reset"):
    sent_emails.append({"kind": "magic", "to": email, "token": token, "type": link_type})
    return True


email_utils._send_plain_email = fake_plain
main_mod.send_magic_link_email = fake_magic

app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)
print("  ✓ app + client ready; email senders stubbed")


# ---------- 4. Register a new user ----------
print("\n=== STEP 4: Register — persists fields, fires admin email ===")
resp = client.post("/api/auth/register", json={
    "email": "newuser@verify.com",
    "password": "supersecret!",
    "full_name": "Dr New User",
    "role": "registrar",
    "institution": "St George's",
    "signup_reason": "Trying Radflow for on-call CT reporting",
})
assert resp.status_code == 200, resp.text
body = resp.json()
assert body["success"] is True, body
assert "pending admin approval" in body["message"].lower()
print(f"  ✓ register returned success=True with pending-approval message")

# DB state
with SessionLocal() as s:
    u = s.execute(text(
        "SELECT email, is_approved, is_verified, role, institution, signup_reason "
        "FROM users WHERE email='newuser@verify.com'"
    )).fetchone()
assert u is not None
assert u.is_approved == 0, f"expected is_approved=0, got {u.is_approved}"
assert u.is_verified == 0
assert u.role == "registrar"
assert u.institution == "St George's"
assert "on-call CT reporting" in u.signup_reason
print(f"  ✓ DB row correct: is_approved=0, role=registrar, institution='St George's'")

# Email capture
admin_emails = [e for e in sent_emails if e["kind"] == "admin"]
magic_emails = [e for e in sent_emails if e["kind"] == "magic"]
assert len(admin_emails) == 1, f"expected 1 admin email, got {len(admin_emails)}"
assert len(magic_emails) == 1, f"expected 1 magic-link email, got {len(magic_emails)}"

admin = admin_emails[0]
assert admin["to"] == "admin@verify.com"
assert "Dr New User" in admin["subject"] and "Registrar" in admin["subject"]
assert "https://api.verify.local/api/admin/approve?uid=" in admin["body"]
assert "https://api.verify.local/api/admin/reject?uid=" in admin["body"]
assert "on-call CT reporting" in admin["body"]
print(f"  ✓ admin email sent to {admin['to']}")
print(f"      subject: {admin['subject']}")
print(f"      body contains signed approve + reject URLs")


# ---------- 5. Login flow: approval gate ordering ----------
print("\n=== STEP 5: Login — approval gate ordering ===")


def login(email, password):
    return client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# 5a: unapproved
r = login("newuser@verify.com", "supersecret!")
assert r.json()["success"] is False and "approval" in r.json()["error"].lower(), r.json()
print(f"  ✓ is_approved=F → blocked: {r.json()['error']}")

# 5b: approved but not verified
with engine.begin() as conn:
    conn.execute(text("UPDATE users SET is_approved=1 WHERE email='newuser@verify.com'"))
r = login("newuser@verify.com", "supersecret!")
assert r.json()["success"] is False and "verify" in r.json()["error"].lower(), r.json()
print(f"  ✓ is_approved=T, is_verified=F → blocked: {r.json()['error']}")

# 5c: both true
with engine.begin() as conn:
    conn.execute(text("UPDATE users SET is_verified=1 WHERE email='newuser@verify.com'"))
r = login("newuser@verify.com", "supersecret!")
body = r.json()
assert body["success"] is True and "access_token" in body, body
print(f"  ✓ both flags true → login succeeds, got JWT")


# ---------- 6. Admin approve endpoint ----------
print("\n=== STEP 6: Admin approve — HMAC + idempotency ===")

# Register a second user to approve via endpoint
resp = client.post("/api/auth/register", json={
    "email": "approveme@verify.com",
    "password": "supersecret!",
    "full_name": "Approve Me",
    "role": "consultant_radiologist",
    "institution": "General Hospital",
    "signup_reason": "wanting to try radflow for thoracic ct reporting",
})
assert resp.status_code == 200 and resp.json()["success"], resp.text
with SessionLocal() as s:
    target = s.execute(text("SELECT id, is_approved FROM users WHERE email='approveme@verify.com'")).fetchone()
    target_id = uuid.UUID(target.id) if isinstance(target.id, str) else target.id
assert target.is_approved == 0
print(f"  ✓ seeded approveme@verify.com (is_approved=0)")

from rapid_reports_ai.auth import sign_admin_action  # noqa: E402
good_token = sign_admin_action(target_id, "approve")

r = client.get(f"/api/admin/approve?uid={target_id}&token={good_token}")
assert r.status_code == 200 and b"approved" in r.content.lower(), r.text
with engine.connect() as conn:
    is_approved = conn.execute(text(
        "SELECT is_approved FROM users WHERE email='approveme@verify.com'"
    )).scalar()
assert is_approved == 1, f"approve endpoint failed to flip flag, got {is_approved}"
print(f"  ✓ valid token → flag flipped to TRUE")

# Idempotent second call
r2 = client.get(f"/api/admin/approve?uid={target_id}&token={good_token}")
assert r2.status_code == 200 and b"already" in r2.content.lower()
print(f"  ✓ idempotent: second call returns 200 'already approved'")

# Bad token
r3 = client.get(f"/api/admin/approve?uid={target_id}&token=deadbeef")
assert r3.status_code == 403
print(f"  ✓ tampered token → 403")

# Approve-signed token cannot be used to reject
r4 = client.get(f"/api/admin/reject?uid={target_id}&token={good_token}")
assert r4.status_code == 403
with engine.connect() as conn:
    still_there = conn.execute(text(
        "SELECT COUNT(*) FROM users WHERE email='approveme@verify.com'"
    )).scalar()
assert still_there == 1, "reject endpoint accepted an approve token!"
print(f"  ✓ approve-signed token rejected when used against /reject")


# ---------- 7. Admin reject endpoint ----------
print("\n=== STEP 7: Admin reject — deletes user ===")
resp = client.post("/api/auth/register", json={
    "email": "rejectme@verify.com",
    "password": "supersecret!",
    "full_name": "Reject Me",
    "role": "other",
    "institution": "Somewhere",
    "signup_reason": "spam account probably",
})
assert resp.json()["success"], resp.text
with SessionLocal() as s:
    r_row = s.execute(text("SELECT id FROM users WHERE email='rejectme@verify.com'")).fetchone()
    r_id = uuid.UUID(r_row.id) if isinstance(r_row.id, str) else r_row.id

reject_token = sign_admin_action(r_id, "reject")
r = client.get(f"/api/admin/reject?uid={r_id}&token={reject_token}")
assert r.status_code == 200 and b"rejected" in r.content.lower(), r.text

with engine.connect() as conn:
    count = conn.execute(text(
        "SELECT COUNT(*) FROM users WHERE email='rejectme@verify.com'"
    )).scalar()
assert count == 0, f"user should be deleted, still have {count} rows"
print(f"  ✓ reject endpoint deleted rejectme@verify.com")

# Idempotent
r2 = client.get(f"/api/admin/reject?uid={r_id}&token={reject_token}")
assert r2.status_code == 200 and (b"already" in r2.content.lower() or b"removed" in r2.content.lower())
print(f"  ✓ idempotent: second call returns 200 'already removed'")


# ---------- 8. Restore email senders + cleanup ----------
email_utils._send_plain_email = original_plain
app.dependency_overrides.clear()

print(f"\n{'=' * 60}")
print(f"ALL CHECKS PASSED — admin approval gate backend is working end-to-end")
print(f"{'=' * 60}\n")
print(f"Temp DB: {DB_FILE}")
print(f"(delete this directory when done: rm -rf {TMP})")
