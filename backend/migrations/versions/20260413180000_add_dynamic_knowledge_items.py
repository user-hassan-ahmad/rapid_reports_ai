"""add_dynamic_knowledge_items

Adds dynamic_knowledge_items table for persisting prefetch pipeline
knowledge, and normalisation_cache for canonical finding label mapping.

Revision ID: 20260413180000
Revises: 20260413120000
Create Date: 2026-04-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.dialects import postgresql


revision: str = "20260413180000"
down_revision: Union[str, Sequence[str], None] = "20260413120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sqlalchemy_inspect(connection)
    existing_tables = inspector.get_table_names()

    # ── 1. dynamic_knowledge_items ────────────────────────────────────────
    if "dynamic_knowledge_items" not in existing_tables:
        op.create_table(
            "dynamic_knowledge_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),

            # Finding identity
            sa.Column("finding_label", sa.Text(), nullable=False),
            sa.Column("finding_label_normalized", sa.Text(), nullable=False),
            sa.Column("finding_short_label", sa.Text(), nullable=False),
            sa.Column("branch", sa.String(length=50), nullable=False),

            # Content
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("domain", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("content_chars", sa.Integer(), nullable=True),
            sa.Column("extraction_type", sa.String(length=30), nullable=True),

            # Evidence quality
            sa.Column("evidence_quality", sa.String(length=20), nullable=True),

            # Provenance
            sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("prefetch_id", sa.Text(), nullable=True),

            # Search
            sa.Column("search_text", sa.Text(), nullable=True),

            # Lifecycle
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("canonical_node_uri", sa.Text(), nullable=True),

            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("finding_label_normalized", "url", name="uq_dki_finding_url"),
        )
        op.create_index("ix_dki_finding_normalized", "dynamic_knowledge_items", ["finding_label_normalized"])
        op.create_index("ix_dki_branch", "dynamic_knowledge_items", ["branch"])
        op.create_index("ix_dki_seen_count", "dynamic_knowledge_items", ["seen_count"])

    # ── 2. normalisation_cache ────────────────────────────────────────────
    if "normalisation_cache" not in existing_tables:
        op.create_table(
            "normalisation_cache",
            sa.Column("raw_label", sa.Text(), nullable=False),
            sa.Column("canonical_form", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.PrimaryKeyConstraint("raw_label"),
        )


def downgrade() -> None:
    op.drop_table("normalisation_cache")
    op.drop_index("ix_dki_seen_count", table_name="dynamic_knowledge_items")
    op.drop_index("ix_dki_branch", table_name="dynamic_knowledge_items")
    op.drop_index("ix_dki_finding_normalized", table_name="dynamic_knowledge_items")
    op.drop_table("dynamic_knowledge_items")
