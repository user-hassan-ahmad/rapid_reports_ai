"""stack_log_report_index: index dictation_stack_logs.report_id (the review engine reads the session by report)

Revision ID: 20261014120000
Revises: 20261014090000
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261014120000"
down_revision: Union[str, Sequence[str], None] = "20261014090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_dictation_stack_logs_report_id", "dictation_stack_logs", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_dictation_stack_logs_report_id", table_name="dictation_stack_logs")
