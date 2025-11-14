"""add_report_description_field

Revision ID: 6abd0e255e66
Revises: c9116e0655a4
Create Date: 2025-10-28 20:21:27.712698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6abd0e255e66'
down_revision: Union[str, Sequence[str], None] = 'c9116e0655a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add description column to reports table
    op.add_column('reports', sa.Column('description', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove description column from reports table
    op.drop_column('reports', 'description')
