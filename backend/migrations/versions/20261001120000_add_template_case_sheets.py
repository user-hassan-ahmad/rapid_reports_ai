"""add template_case_sheets (templated pipeline Phase 1 output per case)

Revision ID: 20261001120000
Revises: 20260530120000
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261001120000"
down_revision: Union[str, Sequence[str], None] = "20260530120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB if is_postgres else sa.JSON
    op.create_table(
        "template_case_sheets",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("template_id", uuid_type, nullable=False),
        sa.Column("sheet_hash", sa.String(length=64), nullable=False),
        sa.Column("history_hash", sa.String(length=64), nullable=False),
        sa.Column("clinical_history", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("master_sheet", sa.Text(), nullable=True),
        sa.Column("case_result", json_type(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_template_case_sheets_user_id", "template_case_sheets", ["user_id"], unique=False)
    op.create_index("ix_template_case_sheets_template_id", "template_case_sheets", ["template_id"], unique=False)
    op.create_index("uq_template_case_sheet_key", "template_case_sheets",
                    ["user_id", "template_id", "sheet_hash", "history_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_template_case_sheet_key", table_name="template_case_sheets")
    op.drop_index("ix_template_case_sheets_template_id", table_name="template_case_sheets")
    op.drop_index("ix_template_case_sheets_user_id", table_name="template_case_sheets")
    op.drop_table("template_case_sheets")
