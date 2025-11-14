"""add_report_versions

Revision ID: e21c4d8be0f2
Revises: 3fcedd492a26
Create Date: 2025-11-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e21c4d8be0f2'
down_revision: Union[str, Sequence[str], None] = 'cdfae12d9cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema by adding report version history table."""
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)

    existing_tables = inspector.get_table_names()
    if 'report_versions' in existing_tables:
        return

    op.create_table(
        'report_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('report_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('report_content', sa.Text(), nullable=False),
        sa.Column('actions_applied', postgresql.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id', 'version_number', name='uq_report_version')
    )

    op.create_index(op.f('ix_report_versions_id'), 'report_versions', ['id'], unique=False)
    op.create_index(op.f('ix_report_versions_report_id'), 'report_versions', ['report_id'], unique=False)
    op.create_index(op.f('ix_report_versions_created_at'), 'report_versions', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema by dropping report version history."""
    op.drop_index(op.f('ix_report_versions_created_at'), table_name='report_versions')
    op.drop_index(op.f('ix_report_versions_report_id'), table_name='report_versions')
    op.drop_index(op.f('ix_report_versions_id'), table_name='report_versions')
    op.drop_table('report_versions')

