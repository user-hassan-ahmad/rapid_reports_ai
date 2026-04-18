"""add_ephemeral_skill_sheets_and_quick_report_fields

Phase 1 of the quick-report-ephemeral production pipeline.

Creates the `ephemeral_skill_sheets` table (first-class, separate from templates
by design) and adds seven nullable columns to `reports` for the dual-model
candidate-selection flow. All additive — no existing data touched, no breaking
changes.

See project_quick_report_analyser.md → "Production plan" for full rationale.

Revision ID: a7b8c9d0e1f2
Revises: 20260413180000
Create Date: 2026-04-18 04:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = '20260413180000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ephemeral_skill_sheets table + add quick-report fields to reports."""
    connection = op.get_bind()
    is_postgres = connection.dialect.name == 'postgresql'
    jsonb_type = postgresql.JSONB if is_postgres else sa.JSON

    # ── Create ephemeral_skill_sheets table ──────────────────────────────
    op.create_table(
        'ephemeral_skill_sheets',
        sa.Column('id', postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36), nullable=False),
        sa.Column('scan_type', sa.Text(), nullable=False),
        sa.Column('scan_type_normalized', sa.String(length=255), nullable=False),
        sa.Column('clinical_history', sa.Text(), nullable=False),
        sa.Column('skill_sheet_markdown', sa.Text(), nullable=False),
        sa.Column('analyser_model', sa.String(length=100), nullable=False),
        sa.Column('analyser_latency_ms', sa.Integer(), nullable=True),
        sa.Column('analyser_prompt_version', sa.String(length=64), nullable=True),
        sa.Column('run_id', sa.String(length=64), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ephemeral_skill_sheets_id', 'ephemeral_skill_sheets', ['id'], unique=False)
    op.create_index('ix_ephemeral_skill_sheets_scan_type_normalized', 'ephemeral_skill_sheets', ['scan_type_normalized'], unique=False)
    op.create_index('ix_ephemeral_skill_sheets_run_id', 'ephemeral_skill_sheets', ['run_id'], unique=False)
    op.create_index('ix_ephemeral_skill_sheets_user_id', 'ephemeral_skill_sheets', ['user_id'], unique=False)
    op.create_index('ix_ephemeral_skill_sheets_created_at', 'ephemeral_skill_sheets', ['created_at'], unique=False)

    # ── Extend reports table with quick-report fields ────────────────────
    op.add_column('reports', sa.Column('generation_mode', sa.String(length=50), nullable=True))
    op.create_index('ix_reports_generation_mode', 'reports', ['generation_mode'], unique=False)

    op.add_column(
        'reports',
        sa.Column(
            'ephemeral_skill_sheet_id',
            postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        'fk_reports_ephemeral_skill_sheet_id',
        'reports',
        'ephemeral_skill_sheets',
        ['ephemeral_skill_sheet_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_reports_ephemeral_skill_sheet_id', 'reports', ['ephemeral_skill_sheet_id'], unique=False)

    op.add_column('reports', sa.Column('candidate_reports', jsonb_type, nullable=True))
    op.add_column('reports', sa.Column('selected_model', sa.String(length=100), nullable=True))
    op.add_column('reports', sa.Column('selection_ms_since_ready', sa.Integer(), nullable=True))
    op.add_column('reports', sa.Column('final_report_content', sa.Text(), nullable=True))
    op.add_column('reports', sa.Column('final_edit_diff', sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop quick-report fields from reports and drop ephemeral_skill_sheets table."""
    # ── Remove reports columns ────────────────────────────────────────────
    op.drop_column('reports', 'final_edit_diff')
    op.drop_column('reports', 'final_report_content')
    op.drop_column('reports', 'selection_ms_since_ready')
    op.drop_column('reports', 'selected_model')
    op.drop_column('reports', 'candidate_reports')
    op.drop_index('ix_reports_ephemeral_skill_sheet_id', table_name='reports')
    op.drop_constraint('fk_reports_ephemeral_skill_sheet_id', 'reports', type_='foreignkey')
    op.drop_column('reports', 'ephemeral_skill_sheet_id')
    op.drop_index('ix_reports_generation_mode', table_name='reports')
    op.drop_column('reports', 'generation_mode')

    # ── Drop ephemeral_skill_sheets table ─────────────────────────────────
    op.drop_index('ix_ephemeral_skill_sheets_created_at', table_name='ephemeral_skill_sheets')
    op.drop_index('ix_ephemeral_skill_sheets_user_id', table_name='ephemeral_skill_sheets')
    op.drop_index('ix_ephemeral_skill_sheets_run_id', table_name='ephemeral_skill_sheets')
    op.drop_index('ix_ephemeral_skill_sheets_scan_type_normalized', table_name='ephemeral_skill_sheets')
    op.drop_index('ix_ephemeral_skill_sheets_id', table_name='ephemeral_skill_sheets')
    op.drop_table('ephemeral_skill_sheets')
