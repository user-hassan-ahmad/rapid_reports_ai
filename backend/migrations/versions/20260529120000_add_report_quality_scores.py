"""add report_quality_scores

Revision ID: 20260529120000
Revises: 20260421120000
Create Date: 2026-05-29

Stores LLM + objective quality scores for skill-sheet-driven reports, populated
offline by scripts/score_report_quality.py and read by Metabase.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260529120000"
down_revision: Union[str, Sequence[str], None] = "20260421120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    is_postgres = connection.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(36)
    jsonb_type = postgresql.JSONB if is_postgres else sa.JSON

    op.create_table(
        "report_quality_scores",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("report_id", uuid_type, nullable=False),
        sa.Column("pipeline", sa.String(length=16), nullable=False),
        sa.Column("sheet_fit", sa.Integer(), nullable=True),
        sa.Column("output_adherence", sa.Integer(), nullable=True),
        sa.Column("input_faithfulness", sa.Integer(), nullable=True),
        sa.Column("edit_burden", sa.Float(), nullable=True),
        sa.Column("dimensions_json", jsonb_type, nullable=True),
        sa.Column("judge_model", sa.String(length=100), nullable=False),
        sa.Column("rubric_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "rubric_version", name="uq_report_quality_rubric"),
    )
    op.create_index(
        "ix_report_quality_scores_report_id", "report_quality_scores", ["report_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_report_quality_scores_report_id", table_name="report_quality_scores")
    op.drop_table("report_quality_scores")
