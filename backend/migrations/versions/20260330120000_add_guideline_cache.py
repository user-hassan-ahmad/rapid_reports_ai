"""add_guideline_cache

Revision ID: 20260330120000
Revises: 20260307120000
Create Date: 2026-03-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260330120000"
down_revision: Union[str, Sequence[str], None] = "20260307120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_guideline_cache_expires_at", table_name="guideline_cache")
    op.drop_table("guideline_cache")
