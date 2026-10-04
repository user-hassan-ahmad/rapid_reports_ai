# migrations/versions/20261003120000_add_review_engine_tables.py
"""add review engine tables (runs, items, chat messages) and reports.workspace_state

Revision ID: 20261003120000
Revises: 20261001120000
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261003120000"
down_revision: Union[str, Sequence[str], None] = "20261001120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB if is_postgres else sa.JSON
    op.create_table(
        "report_review_runs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("pathway", sa.String(length=16), nullable=False),
        sa.Column("lanes", json_type(), nullable=True),
        sa.Column("timings_ms", json_type(), nullable=True),
        sa.Column("cost", json_type(), nullable=True),
        sa.Column("errors", json_type(), nullable=True),
        sa.Column("shadow_log", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_review_runs_report_id", "report_review_runs", ["report_id"], unique=False)
    op.create_table(
        "report_review_items",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("run_id", uuid_type, nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("detectors", json_type(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("cls", sa.String(length=16), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("anchor", json_type(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("edit", json_type(), nullable=True),
        sa.Column("verified", json_type(), nullable=True),
        sa.Column("probe", sa.Text(), nullable=True),
        sa.Column("citation", json_type(), nullable=True),
        sa.Column("source_line", sa.Text(), nullable=True),
        sa.Column("evidence", json_type(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("history", json_type(), nullable=True),
        sa.Column("engine_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["report_review_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_review_items_report_id", "report_review_items", ["report_id"], unique=False)
    op.create_index("ix_report_review_items_run_id", "report_review_items", ["run_id"], unique=False)
    op.create_table(
        "report_chat_messages",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("edits", json_type(), nullable=True),
        sa.Column("applied_item_ids", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_chat_messages_report_id", "report_chat_messages", ["report_id"], unique=False)
    op.add_column("reports", sa.Column("workspace_state", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "workspace_state")
    op.drop_index("ix_report_chat_messages_report_id", table_name="report_chat_messages")
    op.drop_table("report_chat_messages")
    op.drop_index("ix_report_review_items_run_id", table_name="report_review_items")
    op.drop_index("ix_report_review_items_report_id", table_name="report_review_items")
    op.drop_table("report_review_items")
    op.drop_index("ix_report_review_runs_report_id", table_name="report_review_runs")
    op.drop_table("report_review_runs")
