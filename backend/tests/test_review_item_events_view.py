# tests/test_review_item_events_view.py
"""Metabase view v_review_item_events (plan Task E3): one row per report_review_items.history event."""
import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
COLUMNS = ["item_id", "report_id", "run_id", "lane", "kind", "cls", "status", "event", "actor", "at", "text_hash",
           "detail"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), VERSIONS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _view_mod():
    return _load("20261005120000_add_v_review_item_events.py")


def test_revision_chain():
    mod = _view_mod()
    assert mod.revision == "20261005120000" and mod.down_revision == "20261003120000"


def test_postgres_sql_unnests_history_with_expected_columns():
    sql = _view_mod().POSTGRES_SQL
    assert "jsonb_array_elements" in sql and "report_review_items" in sql
    for col in COLUMNS:
        assert f" AS {col}" in sql, col
    assert "::timestamptz" in sql


def test_upgrade_creates_view_on_sqlite_and_downgrade_drops_it():
    tables = _load("20261003120000_add_review_engine_tables.py")
    mod = _view_mod()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("create table users (id varchar(36) primary key)"))
        conn.execute(sa.text("create table reports (id varchar(36) primary key)"))
        with Operations.context(MigrationContext.configure(conn)):
            tables.upgrade()
            mod.upgrade()
        conn.execute(sa.text("insert into reports (id) values ('r1')"))
        conn.execute(sa.text(
            "insert into report_review_runs (id, report_id, mode, engine_version, pathway, created_at) "
            "values ('run1', 'r1', 'live', '0.1.0', 'quick', '2026-10-05')"))
        history = [
            {"at": "2026-10-05T10:00:00+00:00", "event": "created", "actor": "engine", "text_hash": "47597f087ff5d076",
             "detail": {"detectors": ["jev"]}},
            {"at": "2026-10-05T10:01:00+00:00", "event": "apply", "actor": "user", "text_hash": "e3b0c44298fc1c14"},
        ]
        conn.execute(sa.text(
            "insert into report_review_items (id, report_id, run_id, key, lane, kind, cls, status, history, "
            "created_at, updated_at) values ('i1', 'r1', 'run1', 'k', 'coverage', 'partial', 'minor', 'applied', "
            ":h, '2026-10-05', '2026-10-05')"), {"h": json.dumps(history)})
        conn.execute(sa.text(
            "insert into report_review_items (id, report_id, run_id, key, lane, kind, cls, status, history, "
            "created_at, updated_at) values ('i2', 'r1', 'run1', 'k2', 'coverage', 'partial', 'minor', 'open', "
            "NULL, '2026-10-05', '2026-10-05')"))
        assert "v_review_item_events" in sa.inspect(conn).get_view_names()
        res = conn.execute(sa.text("select * from v_review_item_events order by at"))
        assert list(res.keys()) == COLUMNS
        rows = [dict(r._mapping) for r in res]
        assert [(r["item_id"], r["event"], r["actor"], r["text_hash"]) for r in rows] == [
            ("i1", "created", "engine", "47597f087ff5d076"), ("i1", "apply", "user", "e3b0c44298fc1c14")]
        assert rows[0]["report_id"] == "r1" and rows[0]["run_id"] == "run1" and rows[0]["status"] == "applied"
        assert json.loads(rows[0]["detail"]) == {"detectors": ["jev"]} and rows[1]["detail"] is None
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        assert "v_review_item_events" not in sa.inspect(conn).get_view_names()
