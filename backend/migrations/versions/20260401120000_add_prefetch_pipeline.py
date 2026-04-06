"""add_prefetch_pipeline

Adds the prefetch_results table, reports.enhancement_json column, and
report_audits.prefetch_used column that support the parallel guideline
prefetch pipeline.

Also drops the legacy enhancement_cache and guideline_cache tables,
which are superseded by prefetch_results.

Revision ID: 20260401120000
Revises: 20260330120000
Create Date: 2026-04-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


revision: str = "20260401120000"
down_revision: Union[str, Sequence[str], None] = "20260330120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    existing_tables = inspector.get_table_names()

    # ── 1. prefetch_results ────────────────────────────────────────────────────
    if "prefetch_results" not in existing_tables:
        op.create_table(
            "prefetch_results",
            sa.Column("findings_hash", sa.String(length=64), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("output_json", postgresql.JSON(), nullable=False),
            sa.Column("pipeline_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("findings_hash"),
        )
        op.create_index("ix_prefetch_results_user_id", "prefetch_results", ["user_id"])
        op.create_index("ix_prefetch_results_expires_at", "prefetch_results", ["expires_at"])

    # ── 2. reports.enhancement_json ───────────────────────────────────────────
    existing_cols = {c["name"] for c in inspector.get_columns("reports")}
    if "enhancement_json" not in existing_cols:
        op.add_column("reports", sa.Column("enhancement_json", postgresql.JSON(), nullable=True))

    # ── 3. report_audits.prefetch_used ────────────────────────────────────────
    audit_cols = {c["name"] for c in inspector.get_columns("report_audits")}
    if "prefetch_used" not in audit_cols:
        op.add_column("report_audits", sa.Column("prefetch_used", sa.Boolean(), nullable=True))

    # ── 4. Drop legacy cache tables (superseded by prefetch_results) ───────────
    # Use raw SQL with IF EXISTS to avoid poisoning the PG transaction
    # (op.drop_index inside try/except still aborts the transactional DDL block).
    connection.execute(sa.text("DROP INDEX IF EXISTS ix_guideline_cache_expires_at"))
    connection.execute(sa.text("DROP TABLE IF EXISTS guideline_cache"))
    connection.execute(sa.text("DROP INDEX IF EXISTS idx_expires_at"))
    connection.execute(sa.text("DROP INDEX IF EXISTS idx_findings_hash_type"))
    connection.execute(sa.text("DROP TABLE IF EXISTS enhancement_cache"))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    existing_tables = inspector.get_table_names()

    # Remove prefetch additions
    op.drop_column("report_audits", "prefetch_used")
    op.drop_column("reports", "enhancement_json")
    if "prefetch_results" in existing_tables:
        op.drop_index("ix_prefetch_results_expires_at", table_name="prefetch_results")
        op.drop_index("ix_prefetch_results_user_id", table_name="prefetch_results")
        op.drop_table("prefetch_results")

    # Re-create guideline_cache
    op.create_table(
        "guideline_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("system", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("unavailable_reason", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("system", name="uq_guideline_cache_system"),
    )
    op.create_index("ix_guideline_cache_expires_at", "guideline_cache", ["expires_at"])

    # Re-create enhancement_cache
    op.create_table(
        "enhancement_cache",
        sa.Column("cache_key", sa.String(length=500), nullable=False),
        sa.Column("findings_hash", sa.String(length=64), nullable=True),
        sa.Column("cache_type", sa.String(length=50), nullable=True),
        sa.Column("cached_value", postgresql.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_accessed", sa.DateTime(), nullable=False),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("cache_key"),
    )
    op.create_index("idx_findings_hash_type", "enhancement_cache", ["findings_hash", "cache_type"])
    op.create_index("idx_expires_at", "enhancement_cache", ["expires_at"])
