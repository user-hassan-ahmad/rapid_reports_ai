"""stack_slim_sheets: the checklist slim sheet per scan-type family and contrast facet

Revision ID: 20261012090000
Revises: 20261011120000
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261012090000"
down_revision: Union[str, Sequence[str], None] = "20261011120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB if pg else sa.JSON
    uuid_type = postgresql.UUID(as_uuid=True) if pg else sa.String(36)
    op.create_table(
        "stack_slim_sheets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("contrast", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="provisional"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("scan_type", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("region_normals", json_type(), nullable=False),
        sa.Column("not_assessable", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stack_slim_sheets_key", "stack_slim_sheets", ["family", "contrast", "prompt_version"])


def downgrade() -> None:
    op.drop_index("ix_stack_slim_sheets_key", table_name="stack_slim_sheets")
    op.drop_table("stack_slim_sheets")
