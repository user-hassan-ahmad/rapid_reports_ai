"""dictation_stack_logs: gate record and report id (scratchpad v2 §5)

Revision ID: 20261011120000
Revises: 20261010120000
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261011120000"
down_revision: Union[str, Sequence[str], None] = "20261010120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = postgresql.JSONB if op.get_bind().dialect.name == "postgresql" else sa.JSON
    op.add_column("dictation_stack_logs", sa.Column("gate", json_type(), nullable=True))
    op.add_column("dictation_stack_logs", sa.Column("report_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("dictation_stack_logs", "report_id")
    op.drop_column("dictation_stack_logs", "gate")
