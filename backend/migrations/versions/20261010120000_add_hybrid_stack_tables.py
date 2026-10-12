"""add hybrid stack tables (stack_schema_families, dictation_stack_logs)

Revision ID: 20261010120000
Revises: 20261005120000
Create Date: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261010120000"
down_revision: Union[str, Sequence[str], None] = "20261005120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    json_type = postgresql.JSONB if is_postgres else sa.JSON
    op.create_table(
        "stack_schema_families",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=False),
        sa.Column("regions", json_type(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "dictation_stack_logs",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("user_id", uuid_type, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("scan_type", sa.Text(), nullable=True),
        sa.Column("schema_key", sa.Text(), nullable=True),
        sa.Column("schema_source", sa.String(length=32), nullable=True),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("units", json_type(), nullable=True),
        sa.Column("pills_derived", json_type(), nullable=True),
        sa.Column("pills_jev", json_type(), nullable=True),
        sa.Column("sections", json_type(), nullable=True),
        sa.Column("structured_text", sa.Text(), nullable=True),
        sa.Column("manual_moves", sa.Integer(), nullable=False),
        sa.Column("latency_ms", json_type(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dictation_stack_logs_user_id", "dictation_stack_logs", ["user_id"], unique=False)
    op.create_index("ix_dictation_stack_logs_session_id", "dictation_stack_logs", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dictation_stack_logs_session_id", table_name="dictation_stack_logs")
    op.drop_index("ix_dictation_stack_logs_user_id", table_name="dictation_stack_logs")
    op.drop_table("dictation_stack_logs")
    op.drop_table("stack_schema_families")
