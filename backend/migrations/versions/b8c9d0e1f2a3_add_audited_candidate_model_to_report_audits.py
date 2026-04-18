"""add_audited_candidate_model_to_report_audits

Per-candidate audit tracking for dual-model quick reports.

Adds a nullable ``audited_candidate_model`` column to ``report_audits`` so
that for dual-candidate generations we can persist two audit rows per
report (one per candidate draft) and the frontend can switch audit state
in lockstep with the candidate toggle. Legacy single-candidate audits
keep a NULL value and continue to be queried as "the" audit for the
report.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-04-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'report_audits',
        sa.Column('audited_candidate_model', sa.String(length=100), nullable=True),
    )
    op.create_index(
        'ix_report_audits_audited_candidate_model',
        'report_audits',
        ['audited_candidate_model'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_report_audits_audited_candidate_model', table_name='report_audits')
    op.drop_column('report_audits', 'audited_candidate_model')
