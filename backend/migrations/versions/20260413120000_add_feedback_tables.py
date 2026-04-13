"""add_feedback_tables

Adds report_feedback and template_rating tables for the feedback
pipeline — capturing report diffs, lifecycle signals, and aggregate
template quality metrics.

Revision ID: 20260413120000
Revises: 20260405120000
Create Date: 2026-04-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


revision: str = "20260413120000"
down_revision: Union[str, Sequence[str], None] = "20260405120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    existing_tables = inspector.get_table_names()

    # ── 1. report_feedback ────────────────────────────────────────────────────
    if "report_feedback" not in existing_tables:
        op.create_table(
            "report_feedback",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("ai_output", sa.Text(), nullable=False),
            sa.Column("final_output", sa.Text(), nullable=True),
            sa.Column("lifecycle", sa.String(length=20), nullable=False, server_default="generated"),
            sa.Column("copy_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rating", sa.String(length=20), nullable=True),
            sa.Column("time_to_first_edit_ms", sa.Integer(), nullable=True),
            sa.Column("time_to_copy_ms", sa.Integer(), nullable=True),
            sa.Column("edit_distance", sa.Integer(), nullable=True),
            sa.Column("sections_modified", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_report_feedback_template_id", "report_feedback", ["template_id"])
        op.create_index("ix_report_feedback_user_template", "report_feedback", ["user_id", "template_id"])
        op.create_index("ix_report_feedback_lifecycle", "report_feedback", ["lifecycle"])

    # ── 2. template_rating ────────────────────────────────────────────────────
    if "template_rating" not in existing_tables:
        op.create_table(
            "template_rating",
            sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("total_uses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("positive_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_edit_distance", sa.Float(), nullable=False, server_default="0"),
            sa.Column("last_check_in_at", sa.DateTime(), nullable=True),
            sa.Column("last_check_in_uses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_rating", sa.String(length=30), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("template_id", "user_id"),
            sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )


def downgrade() -> None:
    op.drop_table("template_rating")
    op.drop_index("ix_report_feedback_lifecycle", table_name="report_feedback")
    op.drop_index("ix_report_feedback_user_template", table_name="report_feedback")
    op.drop_index("ix_report_feedback_template_id", table_name="report_feedback")
    op.drop_table("report_feedback")
