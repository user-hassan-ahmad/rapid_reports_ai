# tests/test_review_engine_migration.py
"""Review engine storage (spec §10.2): migration on SQLite, ORM models in the test DB."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

MIG = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20261003120000_add_review_engine_tables.py"


def _load():
    spec = importlib.util.spec_from_file_location("mig_review_engine", MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_chain_and_upgrade_on_sqlite():
    mod = _load()
    assert mod.revision == "20261003120000" and mod.down_revision == "20261001120000"
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text("create table users (id varchar(36) primary key)"))
        conn.execute(sa.text("create table reports (id varchar(36) primary key)"))
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        insp = sa.inspect(conn)
        assert {"report_review_runs", "report_review_items", "report_chat_messages"} <= set(insp.get_table_names())
        assert "evidence" in {c["name"] for c in insp.get_columns("report_review_items")}
        assert "workspace_state" in {c["name"] for c in insp.get_columns("reports")}
        assert {"ix_report_review_items_report_id", "ix_report_review_items_run_id"} <= \
            {i["name"] for i in insp.get_indexes("report_review_items")}
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        assert "report_review_items" not in sa.inspect(conn).get_table_names()


def test_orm_models_round_trip(db_session, test_user):
    from rapid_reports_ai.database.models import Report, ReportReviewItem, ReportReviewRun
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=test_user.id)
    db_session.add(r)
    db_session.commit()
    run = ReportReviewRun(report_id=r.id, mode="shadow", engine_version="0.1.0", pathway="quick", lanes={"coverage": "done"})
    db_session.add(run)
    db_session.commit()
    it = ReportReviewItem(report_id=r.id, run_id=run.id, key="k", lane="coverage", detectors=["jev"], kind="partial",
                          cls="minor", label="l", reason="r", status="open", history=[], engine_version="0.1.0",
                          evidence={"check_reason": "uncertain", "pointer": "p"})
    db_session.add(it)
    db_session.commit()
    got = db_session.query(ReportReviewItem).filter_by(run_id=run.id).one()
    assert got.kind == "partial" and got.evidence == {"check_reason": "uncertain", "pointer": "p"}


def test_report_orm_maps_workspace_state(db_session, test_user):
    """Mapped since plan Task E1, once production had applied the migration (L-58). Deferred, nullable: a plain
    report insert still works and leaves it NULL."""
    from rapid_reports_ai.database.models import Report
    assert "workspace_state" in Report.__table__.columns
    r = Report(report_type="quick", model_used="m", report_content="FINDINGS:\nx", user_id=test_user.id)
    db_session.add(r)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Report, r.id).workspace_state is None
