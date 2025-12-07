"""add_user_signature

Revision ID: be6c2732a3d1
Revises: 
Create Date: 2025-10-28 15:14:37.552714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be6c2732a3d1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if column already exists (idempotent migration)
    # This handles cases where the column was created via Base.metadata.create_all()
    from sqlalchemy import inspect
    
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('users')]
    
    if 'signature' not in columns:
        op.add_column('users', sa.Column('signature', sa.Text(), nullable=True))
    else:
        print("Column 'signature' already exists in 'users' table, skipping...")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'signature')
