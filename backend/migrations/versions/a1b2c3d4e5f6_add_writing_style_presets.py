"""add_writing_style_presets

Revision ID: a1b2c3d4e5f6
Revises: 20260103094159
Create Date: 2025-01-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '20260103094159'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add writing_style_presets table."""
    # Detect database type
    bind = op.get_bind()
    inspector = inspect(bind)
    is_postgres = bind.dialect.name == 'postgresql'
    
    # Check if table already exists
    if 'writing_style_presets' in inspector.get_table_names():
        print("✓ writing_style_presets table already exists, skipping creation")
        return
    
    # Use JSONB for PostgreSQL, JSON for SQLite
    if is_postgres:
        settings_type = postgresql.JSONB
        id_type = postgresql.UUID(as_uuid=True)
        user_id_type = postgresql.UUID(as_uuid=True)
        id_default = sa.text('gen_random_uuid()')
    else:
        settings_type = sa.JSON
        id_type = sa.String(36)
        user_id_type = sa.String(36)
        id_default = None
    
    # Create writing_style_presets table
    op.create_table(
        'writing_style_presets',
        sa.Column('id', id_type, primary_key=True, server_default=id_default),
        sa.Column('user_id', user_id_type, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('icon', sa.String(10), nullable=True, server_default='⭐'),
        sa.Column('description', sa.String(200), nullable=True),
        sa.Column('settings', settings_type, nullable=False),
        sa.Column('section_type', sa.String(20), nullable=False, server_default='findings'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'name', 'section_type', name='uix_user_preset_section')
    )
    
    # Create indexes (check if they exist first to avoid errors on re-run)
    try:
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('writing_style_presets')]
    except:
        existing_indexes = []
    
    if 'ix_writing_style_presets_id' not in existing_indexes:
        op.create_index('ix_writing_style_presets_id', 'writing_style_presets', ['id'], unique=False)
    if 'ix_writing_style_presets_user_id' not in existing_indexes:
        op.create_index('ix_writing_style_presets_user_id', 'writing_style_presets', ['user_id'], unique=False)
    if 'idx_presets_user_section' not in existing_indexes:
        op.create_index('idx_presets_user_section', 'writing_style_presets', ['user_id', 'section_type'], unique=False)
    
    print("✓ Created writing_style_presets table")


def downgrade() -> None:
    """Downgrade schema - remove writing_style_presets table."""
    # Drop indexes first
    op.drop_index('idx_presets_user_section', table_name='writing_style_presets')
    op.drop_index('ix_writing_style_presets_user_id', table_name='writing_style_presets')
    op.drop_index('ix_writing_style_presets_id', table_name='writing_style_presets')
    
    # Drop table
    op.drop_table('writing_style_presets')

