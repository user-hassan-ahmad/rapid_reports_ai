"""create_enhancement_cache_table

Revision ID: 20260108230525
Revises: 20260103094159
Create Date: 2026-01-08 23:05:25.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '20260108230525'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - create enhancement_cache table."""
    # Detect database type
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == 'postgresql'
    
    # Create table
    op.create_table(
        'enhancement_cache',
        sa.Column('cache_key', sa.String(500), primary_key=True),
        sa.Column('findings_hash', sa.String(64), nullable=False),
        sa.Column('cache_type', sa.String(50), nullable=False),
        sa.Column('cached_value', postgresql.JSONB() if is_postgresql else sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_accessed', sa.DateTime(), nullable=False),
        sa.Column('access_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
    )
    
    # Create indexes
    op.create_index('ix_enhancement_cache_cache_key', 'enhancement_cache', ['cache_key'])
    op.create_index('ix_enhancement_cache_findings_hash', 'enhancement_cache', ['findings_hash'])
    op.create_index('ix_enhancement_cache_cache_type', 'enhancement_cache', ['cache_type'])
    op.create_index('ix_enhancement_cache_created_at', 'enhancement_cache', ['created_at'])
    op.create_index('ix_enhancement_cache_last_accessed', 'enhancement_cache', ['last_accessed'])
    op.create_index('ix_enhancement_cache_expires_at', 'enhancement_cache', ['expires_at'])
    op.create_index('idx_findings_hash_type', 'enhancement_cache', ['findings_hash', 'cache_type'])


def downgrade() -> None:
    """Downgrade schema - drop enhancement_cache table."""
    op.drop_index('idx_findings_hash_type', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_expires_at', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_last_accessed', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_created_at', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_cache_type', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_findings_hash', 'enhancement_cache')
    op.drop_index('ix_enhancement_cache_cache_key', 'enhancement_cache')
    op.drop_table('enhancement_cache')
