#!/usr/bin/env python3
"""
Test the hybrid TNM search pipeline against a real PostgreSQL instance.

Usage:
  # 1. Start local pgvector PostgreSQL (one-time):
  #    docker run -d --name pgvector -p 5433:5432 \
  #      -e POSTGRES_PASSWORD=test -e POSTGRES_DB=tnm_test \
  #      pgvector/pgvector:pg16
  #
  # 2. Run this script:
  #    DATABASE_URL=postgresql://postgres:test@localhost:5433/tnm_test \
  #      poetry run python scripts/test_tnm_search.py
  #
  # Or against Railway (read-only test):
  #    DATABASE_URL=postgresql://... poetry run python scripts/test_tnm_search.py
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

TEST_QUERIES = [
    "lung carcinoma staging",
    "4.8cm lung mass T-stage",
    "renal cell carcinoma",
    "breast cancer TNM",
    "colorectal tumour staging",
    "pancreatic head mass",
    "hepatocellular carcinoma",
    "prostate cancer",
    "bladder tumour",
    "thyroid nodule carcinoma",
]


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set.")
        print()
        print("Quick start with Docker:")
        print("  docker run -d --name pgvector -p 5433:5432 \\")
        print("    -e POSTGRES_PASSWORD=test -e POSTGRES_DB=tnm_test \\")
        print("    pgvector/pgvector:pg16")
        print()
        print("Then run:")
        print("  DATABASE_URL=postgresql://postgres:test@localhost:5433/tnm_test \\")
        print("    poetry run python scripts/test_tnm_search.py")
        sys.exit(1)

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)

    # ── Setup: extension + table + seed ──────────────────────────────────────
    print("=" * 70)
    print("TNM Hybrid Search — Test Suite")
    print("=" * 70)
    print(f"Database: {db_url.split('@')[-1]}")

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        print("✓ pgvector extension ready")

    inspector = inspect(engine)
    if "tnm_staging" not in inspector.get_table_names():
        print("Creating tnm_staging table…")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE tnm_staging (
                    id SERIAL PRIMARY KEY,
                    tumour VARCHAR(200) UNIQUE NOT NULL,
                    icd_o VARCHAR(200),
                    edition_uicc VARCHAR(10) NOT NULL DEFAULT '9th',
                    edition_ajcc VARCHAR(10),
                    rules TEXT,
                    tnm_json JSONB NOT NULL,
                    stage_grouping JSONB,
                    search_text TEXT NOT NULL,
                    search_vector TSVECTOR,
                    embedding vector(1536)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tnm_staging_tumour "
                "ON tnm_staging (tumour)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tnm_staging_search_vector "
                "ON tnm_staging USING gin (search_vector)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_tnm_staging_embedding "
                "ON tnm_staging USING hnsw (embedding vector_cosine_ops)"
            ))
            conn.commit()
        print("✓ Table and indexes created")

    # Seed
    from rapid_reports_ai.tnm_lookup import seed_tnm_if_empty
    db = Session()
    count = seed_tnm_if_empty(db)
    if count > 0:
        print(f"✓ Seeded {count} tumour rows")
    else:
        row_count = db.execute(text("SELECT count(*) FROM tnm_staging")).scalar()
        print(f"✓ Already seeded ({row_count} rows)")

    # ── Run test queries ─────────────────────────────────────────────────────
    from rapid_reports_ai.tnm_lookup import hybrid_tnm_search, format_tnm_evidence

    print()
    print("─" * 70)
    print("Running test queries…")
    print("─" * 70)

    total_time = 0
    for i, query in enumerate(TEST_QUERIES):
        t0 = time.perf_counter()
        results = hybrid_tnm_search(query, db, top_k=3)
        elapsed = (time.perf_counter() - t0) * 1000
        total_time += elapsed

        print(f"\n[{i+1}] Query: \"{query}\" ({elapsed:.0f}ms)")
        if not results:
            print("    → No confident match")
        else:
            for j, r in enumerate(results):
                rank_info = []
                if r.bm25_rank:
                    rank_info.append(f"BM25 #{r.bm25_rank}")
                if r.semantic_rank:
                    rank_info.append(f"Sem #{r.semantic_rank}")
                print(f"    {j+1}. {r.tumour} (RRF={r.rrf_score:.4f}, {', '.join(rank_info)})")

                tnm = r.tnm_json
                t_stages = list(tnm.get("T", {}).keys())
                print(f"       T-stages: {', '.join(t_stages[:8])}")

    print()
    print("─" * 70)
    print(f"Total query time: {total_time:.0f}ms ({total_time/len(TEST_QUERIES):.0f}ms avg)")

    # ── Show formatted evidence for the lung staging case ────────────────────
    print()
    print("=" * 70)
    print("Sample: formatted evidence for '4.8cm lung mass T-stage'")
    print("=" * 70)
    results = hybrid_tnm_search("4.8cm lung mass T-stage", db, top_k=1)
    if results:
        print(format_tnm_evidence(results[0]))
    else:
        print("(no match)")

    db.close()
    print("\n✓ All tests complete")


if __name__ == "__main__":
    main()
