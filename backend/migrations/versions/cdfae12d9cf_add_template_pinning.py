"""add_template_pinning

Revision ID: cdfae12d9cf
Revises: 3fcedd492a26
Create Date: 2025-01-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect


# revision identifiers, used by Alembic.
revision: str = 'cdfae12d9cf'
down_revision: Union[str, Sequence[str], None] = '3fcedd492a26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_pinned column to templates table (if it doesn't exist)
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    templates_columns = [col['name'] for col in inspector.get_columns('templates')]
    
    if 'is_pinned' not in templates_columns:
        op.add_column('templates', sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default='0'))
        
        # Create index for is_pinned (if it doesn't exist)
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('templates')]
        if 'ix_templates_is_pinned' not in existing_indexes:
            op.create_index(op.f('ix_templates_is_pinned'), 'templates', ['is_pinned'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index first, then column
    op.drop_index(op.f('ix_templates_is_pinned'), table_name='templates')
    op.drop_column('templates', 'is_pinned')

