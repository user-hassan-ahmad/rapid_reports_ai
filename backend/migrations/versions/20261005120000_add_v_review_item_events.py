# migrations/versions/20261005120000_add_v_review_item_events.py
"""add view v_review_item_events: one row per report_review_items.history event (Metabase)

Revision ID: 20261005120000
Revises: 20261003120000
Create Date: 2026-10-05

Production is Postgres (jsonb_array_elements over the JSONB history). The SQLite branch (tests, local dev) builds the
same columns from json_each so the view can be exercised in the test suite. Items whose history is NULL or not an
array contribute no rows.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261005120000"
down_revision: Union[str, Sequence[str], None] = "20261003120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

POSTGRES_SQL = """
CREATE OR REPLACE VIEW v_review_item_events AS
SELECT
    i.id AS item_id,
    i.report_id AS report_id,
    i.run_id AS run_id,
    i.lane AS lane,
    i.kind AS kind,
    i.cls AS cls,
    i.status AS status,
    e->>'event' AS event,
    e->>'actor' AS actor,
    (e->>'at')::timestamptz AS at,
    e->>'text_hash' AS text_hash,
    e->'detail' AS detail
FROM report_review_items i
CROSS JOIN LATERAL jsonb_array_elements(
    CASE WHEN jsonb_typeof(i.history) = 'array' THEN i.history ELSE '[]'::jsonb END
) AS e
"""

SQLITE_SQL = """
CREATE VIEW v_review_item_events AS
SELECT
    i.id AS item_id,
    i.report_id AS report_id,
    i.run_id AS run_id,
    i.lane AS lane,
    i.kind AS kind,
    i.cls AS cls,
    i.status AS status,
    json_extract(e.value, '$.event') AS event,
    json_extract(e.value, '$.actor') AS actor,
    json_extract(e.value, '$.at') AS at,
    json_extract(e.value, '$.text_hash') AS text_hash,
    json_extract(e.value, '$.detail') AS detail
FROM report_review_items i, json_each(i.history) AS e
WHERE json_type(i.history) = 'array'
"""


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    op.execute(POSTGRES_SQL if is_postgres else SQLITE_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_review_item_events")
