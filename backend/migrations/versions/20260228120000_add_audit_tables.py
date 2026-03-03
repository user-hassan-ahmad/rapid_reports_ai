"""add_audit_tables

Revision ID: 20260228120000
Revises: 20260108230525
Create Date: 2026-02-28 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260228120000'
down_revision: Union[str, Sequence[str], None] = '20260108230525'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema by adding report audit tables."""
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)

    existing_tables = inspector.get_table_names()
    if 'report_audits' in existing_tables:
        return

    # Create report_audits table
    op.create_table(
        'report_audits',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('overall_status', sa.String(length=10), nullable=False),
        sa.Column('scan_type', sa.String(length=200), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=False),
        sa.Column('clinical_history', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('report_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_reviewed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['report_version_id'], ['report_versions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('ix_report_audits_id', 'report_audits', ['id'], unique=False)
    op.create_index('ix_report_audits_report_id', 'report_audits', ['report_id'], unique=False)
    op.create_index('ix_report_audits_user_id', 'report_audits', ['user_id'], unique=False)
    op.create_index('ix_report_audits_overall_status', 'report_audits', ['overall_status'], unique=False)
    op.create_index('ix_report_audits_scan_type', 'report_audits', ['scan_type'], unique=False)
    op.create_index('ix_report_audits_created_at', 'report_audits', ['created_at'], unique=False)

    # Create report_audit_criteria table
    op.create_table(
        'report_audit_criteria',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('audit_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('criterion', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('highlighted_spans', postgresql.JSON(), nullable=True),
        sa.Column('flags_json', postgresql.JSON(), nullable=True),
        sa.Column('acknowledged', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('resolution_method', sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(['audit_id'], ['report_audits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('ix_report_audit_criteria_id', 'report_audit_criteria', ['id'], unique=False)
    op.create_index('ix_report_audit_criteria_audit_id', 'report_audit_criteria', ['audit_id'], unique=False)
    op.create_index('ix_report_audit_criteria_criterion', 'report_audit_criteria', ['criterion'], unique=False)
    op.create_index('ix_report_audit_criteria_status', 'report_audit_criteria', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema by dropping report audit tables."""
    # Drop report_audit_criteria indexes and table first (due to FK)
    op.drop_index('ix_report_audit_criteria_status', table_name='report_audit_criteria')
    op.drop_index('ix_report_audit_criteria_criterion', table_name='report_audit_criteria')
    op.drop_index('ix_report_audit_criteria_audit_id', table_name='report_audit_criteria')
    op.drop_index('ix_report_audit_criteria_id', table_name='report_audit_criteria')
    op.drop_table('report_audit_criteria')

    # Drop report_audits indexes and table
    op.drop_index('ix_report_audits_created_at', table_name='report_audits')
    op.drop_index('ix_report_audits_scan_type', table_name='report_audits')
    op.drop_index('ix_report_audits_overall_status', table_name='report_audits')
    op.drop_index('ix_report_audits_user_id', table_name='report_audits')
    op.drop_index('ix_report_audits_report_id', table_name='report_audits')
    op.drop_index('ix_report_audits_id', table_name='report_audits')
    op.drop_table('report_audits')
