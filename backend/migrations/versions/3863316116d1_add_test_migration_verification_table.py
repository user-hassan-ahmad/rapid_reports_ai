"""add_test_migration_verification_table

Revision ID: 3863316116d1
Revises: a1b2c3d4e5f6
Create Date: 2026-01-08 09:35:02.751462

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3863316116d1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create a test table to verify migrations are working on Railway
    op.create_table(
        'migration_test_table',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('test_message', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('deployment_timestamp', sa.String(50), nullable=True),
    )
    
    # Insert a test row with current timestamp
    from datetime import datetime
    op.execute(
        f"INSERT INTO migration_test_table (test_message, deployment_timestamp) "
        f"VALUES ('Migration system is working!', '{datetime.utcnow().isoformat()}')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('migration_test_table')
