"""add_validation_status_to_reports

Revision ID: e315d7dc70b
Revises: f123456789ab
Create Date: 2025-01-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e315d7dc70b'
down_revision: Union[str, Sequence[str], None] = 'f123456789ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add validation_status JSON column to reports table."""
    # Add validation_status column (JSON, nullable)
    # For PostgreSQL use JSONB, for SQLite use JSON
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql':
        op.add_column('reports', sa.Column('validation_status', postgresql.JSONB, nullable=True))
    else:
        # SQLite uses JSON type
        op.add_column('reports', sa.Column('validation_status', sa.JSON, nullable=True))


def downgrade() -> None:
    """Remove validation_status column from reports table."""
    op.drop_column('reports', 'validation_status')

