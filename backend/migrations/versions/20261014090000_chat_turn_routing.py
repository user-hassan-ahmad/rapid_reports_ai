"""chat_turn_routing: the chat-edit router's evidence on each stored chat turn (tags, verdicts, cards)

Revision ID: 20261014090000
Revises: 20261012150000
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261014090000"
down_revision: Union[str, Sequence[str], None] = "20261012150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB if pg else sa.JSON
    op.add_column("template_chat_turns", sa.Column("routing", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_chat_turns", "routing")
