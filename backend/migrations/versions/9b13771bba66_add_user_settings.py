"""add_user_settings

Revision ID: 9b13771bba66
Revises: c9116e0655a4
Create Date: 2025-10-28 15:25:52.158025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b13771bba66'
down_revision: Union[str, Sequence[str], None] = 'be6c2732a3d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('settings', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'settings')
