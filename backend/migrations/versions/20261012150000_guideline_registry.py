"""guideline_registry table and dictation_stack_logs.copilot (scratchpad copilot §5.1, §5.7)

Revision ID: 20261012150000
Revises: 20261013090000
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261012150000"
down_revision: Union[str, Sequence[str], None] = "20261013090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = postgresql.JSONB if op.get_bind().dialect.name == "postgresql" else sa.JSON
    op.create_table(
        "guideline_registry",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="uk"),
        sa.Column("publication", json_type(), nullable=True),
        sa.Column("aliases", json_type(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("content", json_type(), nullable=False),
        sa.Column("sources", json_type(), nullable=False),
        sa.Column("chunks", json_type(), nullable=False),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column("dictation_stack_logs", sa.Column("copilot", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("dictation_stack_logs", "copilot")
    op.drop_table("guideline_registry")
