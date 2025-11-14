"""create_reports_table

Revision ID: c9116e0655a4
Revises: be6c2732a3d1
Create Date: 2025-10-28 15:14:39.291197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9116e0655a4'
down_revision: Union[str, Sequence[str], None] = ['be6c2732a3d1', '9b13771bba66']
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'reports',
        sa.Column('id', sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('report_type', sa.String(50), nullable=False),
        sa.Column('use_case', sa.String(200), nullable=True),
        sa.Column('model_used', sa.String(50), nullable=False),
        sa.Column('input_data', sa.JSON(), nullable=True),
        sa.Column('report_content', sa.Text(), nullable=False),
        sa.Column('user_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', sa.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reports_id', 'reports', ['id'])
    op.create_index('ix_reports_user_id', 'reports', ['user_id'])
    op.create_index('ix_reports_template_id', 'reports', ['template_id'])
    op.create_index('ix_reports_report_type', 'reports', ['report_type'])
    op.create_index('ix_reports_created_at', 'reports', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_reports_created_at', 'reports')
    op.drop_index('ix_reports_report_type', 'reports')
    op.drop_index('ix_reports_template_id', 'reports')
    op.drop_index('ix_reports_user_id', 'reports')
    op.drop_index('ix_reports_id', 'reports')
    op.drop_table('reports')
