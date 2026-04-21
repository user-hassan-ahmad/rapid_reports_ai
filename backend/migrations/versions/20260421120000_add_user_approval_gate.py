"""add_user_approval_gate

Revision ID: 20260421120000
Revises: b8c9d0e1f2a3
Create Date: 2026-04-21 12:00:00.000000

Adds is_approved, signup_reason, role, institution to users.
Grandfathers all pre-existing rows to is_approved=TRUE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260421120000"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add approval gate columns to users."""
    # server_default='false' ensures NOT NULL works on existing rows; we then
    # explicitly grandfather them to TRUE below. New rows still default FALSE
    # because the model-level default (set in Task 3) overrides the server default.
    op.add_column(
        "users",
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("signup_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("institution", sa.String(length=200), nullable=True))

    # Grandfather every row that existed before this migration.
    op.execute("UPDATE users SET is_approved = TRUE")

    # Drop server_default so application code owns the default for new rows.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("is_approved", server_default=None)


def downgrade() -> None:
    """Downgrade schema - drop approval gate columns."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("institution")
        batch_op.drop_column("role")
        batch_op.drop_column("signup_reason")
        batch_op.drop_column("is_approved")
