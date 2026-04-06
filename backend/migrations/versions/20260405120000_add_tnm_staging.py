"""add_tnm_staging

Creates the tnm_staging table with pgvector extension for hybrid
BM25 + semantic search over UICC TNM 9th Edition staging data.

Revision ID: 20260405120000
Revises: 20260401120000
Create Date: 2026-04-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect, text
from sqlalchemy.dialects import postgresql


revision: str = "20260405120000"
down_revision: Union[str, Sequence[str], None] = "20260401120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    existing_tables = inspector.get_table_names()

    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    if "tnm_staging" not in existing_tables:
        op.create_table(
            "tnm_staging",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("tumour", sa.String(length=200), nullable=False),
            sa.Column("icd_o", sa.String(length=200), nullable=True),
            sa.Column("edition_uicc", sa.String(length=10), nullable=False, server_default="9th"),
            sa.Column("edition_ajcc", sa.String(length=10), nullable=True),
            sa.Column("rules", sa.Text(), nullable=True),
            sa.Column("tnm_json", postgresql.JSONB(), nullable=False),
            sa.Column("stage_grouping", postgresql.JSONB(), nullable=True),
            sa.Column("search_text", sa.Text(), nullable=False),
            sa.Column("search_vector", postgresql.TSVECTOR()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tumour", name="uq_tnm_staging_tumour"),
        )
        op.create_index("ix_tnm_staging_tumour", "tnm_staging", ["tumour"])

        # vector column via raw DDL (pgvector type not natively expressible in Alembic)
        connection.execute(text(
            "ALTER TABLE tnm_staging ADD COLUMN embedding vector(1536)"
        ))

        connection.execute(text(
            "CREATE INDEX ix_tnm_staging_search_vector "
            "ON tnm_staging USING gin (search_vector)"
        ))
        connection.execute(text(
            "CREATE INDEX ix_tnm_staging_embedding "
            "ON tnm_staging USING hnsw (embedding vector_cosine_ops)"
        ))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    if "tnm_staging" in inspector.get_table_names():
        op.drop_table("tnm_staging")
