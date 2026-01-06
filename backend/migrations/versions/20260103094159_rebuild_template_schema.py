"""rebuild_template_schema

Revision ID: 20260103094159
Revises: cdfae12d9cf
Create Date: 2026-01-03 09:41:59.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '20260103094159'
down_revision: Union[str, Sequence[str], None] = 'e315d7dc70b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - rebuild template system with JSON config."""
    # Detect database type
    bind = op.get_bind()
    inspector = inspect(bind)
    is_postgres = bind.dialect.name == 'postgresql'
    
    # Use JSONB for PostgreSQL, JSON for SQLite
    if is_postgres:
        template_config_type = postgresql.JSONB(astext_type=sa.Text())
    else:
        template_config_type = sa.JSON()
    
    # Check if template_config column already exists
    existing_columns = [col['name'] for col in inspector.get_columns('templates')]
    
    # Add template_config column if it doesn't exist
    if 'template_config' not in existing_columns:
        op.add_column('templates', sa.Column('template_config', template_config_type, nullable=True))
    
    # Drop old columns (after migration, templates will use template_config only)
    # Check if columns exist before dropping (for safety)
    existing_columns = [col['name'] for col in inspector.get_columns('templates')]
    if 'template_content' in existing_columns:
        op.drop_column('templates', 'template_content')
    if 'variables' in existing_columns:
        op.drop_column('templates', 'variables')
    if 'variable_config' in existing_columns:
        op.drop_column('templates', 'variable_config')
    if 'master_prompt_instructions' in existing_columns:
        op.drop_column('templates', 'master_prompt_instructions')
    if 'model_compatibility' in existing_columns:
        op.drop_column('templates', 'model_compatibility')
    
    # Also update template_versions table to match
    existing_version_columns = [col['name'] for col in inspector.get_columns('template_versions')] if 'template_versions' in inspector.get_table_names() else []
    if 'template_config' not in existing_version_columns:
        op.add_column('template_versions', sa.Column('template_config', template_config_type, nullable=True))
    existing_version_columns = [col['name'] for col in inspector.get_columns('template_versions')]
    if 'template_content' in existing_version_columns:
        op.drop_column('template_versions', 'template_content')
    if 'variables' in existing_version_columns:
        op.drop_column('template_versions', 'variables')
    if 'master_prompt_instructions' in existing_version_columns:
        op.drop_column('template_versions', 'master_prompt_instructions')
    if 'model_compatibility' in existing_version_columns:
        op.drop_column('template_versions', 'model_compatibility')


def downgrade() -> None:
    """Downgrade schema - restore old template columns."""
    # Detect database type
    bind = op.get_bind()
    inspector = inspect(bind)
    is_postgres = bind.dialect.name == 'postgresql'
    
    # Use JSONB for PostgreSQL, JSON for SQLite
    if is_postgres:
        json_type = postgresql.JSON(astext_type=sa.Text())
    else:
        json_type = sa.JSON()
    
    # Restore template_versions columns first
    op.add_column('template_versions', sa.Column('model_compatibility', json_type, nullable=True))
    op.add_column('template_versions', sa.Column('master_prompt_instructions', sa.Text(), nullable=True))
    op.add_column('template_versions', sa.Column('variables', json_type, nullable=True))
    op.add_column('template_versions', sa.Column('template_content', sa.Text(), nullable=False))
    op.drop_column('template_versions', 'template_config')
    
    # Restore templates columns
    op.add_column('templates', sa.Column('model_compatibility', json_type, nullable=True))
    op.add_column('templates', sa.Column('master_prompt_instructions', sa.Text(), nullable=True))
    op.add_column('templates', sa.Column('variable_config', json_type, nullable=True))
    op.add_column('templates', sa.Column('variables', json_type, nullable=True))
    op.add_column('templates', sa.Column('template_content', sa.Text(), nullable=False))
    op.drop_column('templates', 'template_config')

