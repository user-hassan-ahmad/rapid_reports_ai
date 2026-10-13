"""template_evidence: stored examples, chat turns, generation stamps (template pipeline spec, block 4)

Revision ID: 20261013090000
Revises: 20261012090000
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261013090000"
down_revision: Union[str, Sequence[str], None] = "20261012090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB if pg else sa.JSON
    uuid_type = postgresql.UUID(as_uuid=True) if pg else sa.String(36)
    op.create_table(
        "template_examples",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("template_id", uuid_type, sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="pasted"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "template_chat_turns",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("template_id", uuid_type, sa.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sheet_hash_before", sa.String(64), nullable=True),
        sa.Column("sheet_hash_after", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("reports", sa.Column("generation_stamp", json_type(), nullable=True))
    op.add_column("dictation_stack_logs", sa.Column("template_id", sa.String(64), nullable=True))
    op.add_column("dictation_stack_logs", sa.Column("stamp", json_type(), nullable=True))


def downgrade() -> None:
    op.drop_column("dictation_stack_logs", "stamp")
    op.drop_column("dictation_stack_logs", "template_id")
    op.drop_column("reports", "generation_stamp")
    op.drop_table("template_chat_turns")
    op.drop_table("template_examples")
