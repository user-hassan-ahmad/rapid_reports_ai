"""replace_category_with_tags

Revision ID: abc123def456
Revises: 6abd0e255e66
Create Date: 2025-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'abc123def456'
down_revision: Union[str, Sequence[str], None] = '6abd0e255e66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - replace category with tags."""
    import json
    
    # Add tags column as JSON array (nullable)
    op.add_column('templates', sa.Column('tags', sa.JSON(), nullable=True))
    
    # Migrate existing category data to tags
    # Use connection directly for SQLite compatibility
    connection = op.get_bind()
    dialect = connection.dialect.name
    
    if dialect == 'sqlite':
        # SQLite: manually construct JSON arrays
        conn = connection.connection
        cursor = conn.cursor()
        
        # Get all templates with categories
        cursor.execute("SELECT id, category FROM templates WHERE category IS NOT NULL AND category != ''")
        rows = cursor.fetchall()
        
        for template_id, category in rows:
            tags_json = json.dumps([category])
            cursor.execute("UPDATE templates SET tags = ? WHERE id = ?", (tags_json, template_id))
        
        # Set empty array for templates without category
        cursor.execute("UPDATE templates SET tags = ? WHERE tags IS NULL", (json.dumps([]),))
        conn.commit()
    else:
        # PostgreSQL: use op.execute for raw SQL
        op.execute(
            """
            UPDATE templates 
            SET tags = CASE 
                WHEN category IS NOT NULL AND category != '' 
                THEN ('["' || category || '"]')::jsonb
                ELSE '[]'::jsonb
            END
            WHERE tags IS NULL
            """
        )
    
    # Drop category column
    op.drop_column('templates', 'category')


def downgrade() -> None:
    """Downgrade schema - restore category column."""
    # Add category column back
    op.add_column('templates', sa.Column('category', sa.String(100), nullable=True))
    
    # Drop tags column
    op.drop_column('templates', 'tags')

