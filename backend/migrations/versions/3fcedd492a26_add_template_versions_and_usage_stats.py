"""add_template_versions_and_usage_stats

Revision ID: 3fcedd492a26
Revises: abc123def456
Create Date: 2025-11-01 15:18:53.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3fcedd492a26'
down_revision: Union[str, Sequence[str], None] = 'abc123def456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add usage statistics columns to templates table (if they don't exist)
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    templates_columns = [col['name'] for col in inspector.get_columns('templates')]
    
    if 'usage_count' not in templates_columns:
        op.add_column('templates', sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'))
    if 'last_used_at' not in templates_columns:
        op.add_column('templates', sa.Column('last_used_at', sa.DateTime(), nullable=True))
    
    # Create template_versions table (if it doesn't exist)
    existing_tables = inspector.get_table_names()
    if 'template_versions' not in existing_tables:
        op.create_table(
            'template_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', postgresql.JSON(), nullable=True),
        sa.Column('template_content', sa.Text(), nullable=False),
        sa.Column('variables', postgresql.JSON(), nullable=True),
        sa.Column('master_prompt_instructions', sa.Text(), nullable=True),
        sa.Column('model_compatibility', postgresql.JSON(), nullable=True),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('template_id', 'version_number', name='uq_template_version')
        )
        
        # Create indexes for efficient querying (if table was just created)
        existing_indexes = [idx['name'] for idx in inspector.get_indexes('template_versions')]
        if 'ix_template_versions_template_id' not in existing_indexes:
            op.create_index(op.f('ix_template_versions_template_id'), 'template_versions', ['template_id'], unique=False)
        if 'ix_template_versions_created_at' not in existing_indexes:
            op.create_index(op.f('ix_template_versions_created_at'), 'template_versions', ['created_at'], unique=False)
        if 'ix_template_versions_id' not in existing_indexes:
            op.create_index(op.f('ix_template_versions_id'), 'template_versions', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop template_versions table and indexes
    op.drop_index(op.f('ix_template_versions_id'), table_name='template_versions')
    op.drop_index(op.f('ix_template_versions_created_at'), table_name='template_versions')
    op.drop_index(op.f('ix_template_versions_template_id'), table_name='template_versions')
    op.drop_table('template_versions')
    
    # Remove usage statistics columns from templates
    op.drop_column('templates', 'last_used_at')
    op.drop_column('templates', 'usage_count')

