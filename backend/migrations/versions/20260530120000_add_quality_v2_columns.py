"""add report_quality_scores v2 columns (dictation_fidelity, normal_fill_appropriateness)

Revision ID: 20260530120000
Revises: 20260529120000
Create Date: 2026-05-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260530120000"
down_revision: Union[str, Sequence[str], None] = "20260529120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("report_quality_scores", sa.Column("dictation_fidelity", sa.Integer(), nullable=True))
    op.add_column("report_quality_scores", sa.Column("normal_fill_appropriateness", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_quality_scores", "normal_fill_appropriateness")
    op.drop_column("report_quality_scores", "dictation_fidelity")
