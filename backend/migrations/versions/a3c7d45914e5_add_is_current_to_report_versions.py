"""add_is_current_to_report_versions

Revision ID: a3c7d45914e5
Revises: e21c4d8be0f2
Create Date: 2025-11-09 18:10:32.895507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c7d45914e5'
down_revision: Union[str, Sequence[str], None] = 'e21c4d8be0f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_current column to report_versions table
    op.add_column('report_versions', sa.Column('is_current', sa.Boolean(), nullable=False, server_default='0'))
    
    # Set the most recent version for each report as current
    op.execute("""
        UPDATE report_versions
        SET is_current = 1
        WHERE (report_id, version_number) IN (
            SELECT report_id, MAX(version_number)
            FROM report_versions
            GROUP BY report_id
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove is_current column from report_versions table
    op.drop_column('report_versions', 'is_current')
