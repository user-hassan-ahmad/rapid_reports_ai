"""Verifies the admin-approval-gate migration adds columns and grandfathers existing users.

The full historical migration chain uses Postgres-specific types (JSONB, TSVECTOR, UUID)
that SQLite cannot compile, so we can't run every migration from zero. Instead we
pre-create a minimal users table that mimics the schema as of revision `b8c9d0e1f2a3`,
stamp Alembic at that revision, then run only this migration.
"""
from __future__ import annotations

import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _alembic_config(db_url: str) -> Config:
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


_USERS_TABLE_AT_B8C9 = """
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
"""


def _seed_users_table(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(_USERS_TABLE_AT_B8C9))
        conn.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        conn.execute(text("INSERT INTO alembic_version VALUES ('b8c9d0e1f2a3')"))


def test_migration_upgrade_adds_columns_and_grandfathers_existing_users(tmp_path):
    db_file = tmp_path / "test.sqlite"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    _seed_users_table(engine)

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, email, password_hash, is_active, is_verified, created_at) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'pre@test.com', 'x', 1, 1, CURRENT_TIMESTAMP)"
        ))

    cfg = _alembic_config(db_url)
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

    # A new row inserted after migration should not be grandfathered; it gets the
    # application-level default (False) once Task 3 lands. Here we only verify that
    # the column has no lingering server-side TRUE default that would poison prod.
    with engine.connect() as conn:
        default = conn.execute(text(
            "SELECT dflt_value FROM pragma_table_info('users') WHERE name='is_approved'"
        )).scalar()
    # SQLite reports the column default after migration. We require it to be either
    # NULL/None (dropped by batch_alter_table) or 0/false — never 1/true.
    assert default in (None, "0", "FALSE", "false", 0), (
        f"is_approved column must not carry a server-side TRUE default after migration; got {default!r}"
    )


def test_migration_downgrade_drops_columns(tmp_path):
    db_file = tmp_path / "test.sqlite"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    _seed_users_table(engine)

    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "20260421120000")
    command.downgrade(cfg, "b8c9d0e1f2a3")

    cols = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "is_approved" not in cols
    assert "signup_reason" not in cols
    assert "role" not in cols
    assert "institution" not in cols
