"""
TNM Hybrid Search — BM25 + Semantic over UICC 9th Edition
==========================================================
Provides deterministic TNM staging evidence to the S4 classification
synthesis pass, replacing reliance on web-fetched guidelines for staging.

Architecture:
  • 60 pre-embedded tumour rows stored in PostgreSQL with pgvector
  • BM25 leg: ts_rank over tsvector GIN index
  • Semantic leg: cosine similarity over vector(1536) HNSW index
  • Reciprocal Rank Fusion (RRF) merges both ranked lists
  • Confidence gate: if top RRF score < threshold → return empty
    (signals the caller to fall back to Tavily evidence)

Runtime query embedding: OpenAI text-embedding-3-small via API.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EMBEDDINGS_FILE = Path(__file__).parent / "resources" / "tnm_embeddings.json"
EMBEDDING_MODEL = "text-embedding-3-small"
RRF_K = 60  # standard RRF constant
CONFIDENCE_THRESHOLD = 0.015  # minimum RRF score to consider a hit reliable


@dataclass
class TnmResult:
    """A single hybrid-search result row."""
    tumour: str
    icd_o: str
    edition_uicc: str
    edition_ajcc: Optional[str]
    tnm_json: Dict[str, Any]
    stage_grouping: List[Dict[str, Any]]
    rules: str
    rrf_score: float
    bm25_rank: Optional[int] = None
    semantic_rank: Optional[int] = None


# ── Seeding ──────────────────────────────────────────────────────────────────

def seed_tnm_if_empty(db: Session) -> int:
    """Load pre-computed embeddings into tnm_staging if the table is empty.

    Called from the FastAPI lifespan event. Returns the number of rows
    inserted (0 if already seeded or not on PostgreSQL).
    """
    try:
        dialect = db.bind.dialect.name if db.bind else ""
        if dialect != "postgresql":
            logger.info("[TNM] Skipping seed — not PostgreSQL (dialect=%s)", dialect)
            return 0
    except Exception:
        return 0

    row = db.execute(text("SELECT count(*) FROM tnm_staging")).scalar()
    if row and row > 0:
        logger.info("[TNM] tnm_staging already has %d rows — skipping seed", row)
        return 0

    if not EMBEDDINGS_FILE.exists():
        logger.warning("[TNM] %s not found — cannot seed", EMBEDDINGS_FILE)
        return 0

    with open(EMBEDDINGS_FILE) as f:
        payload = json.load(f)

    records = payload.get("records", [])
    if not records:
        logger.warning("[TNM] tnm_embeddings.json has no records")
        return 0

    logger.info("[TNM] Seeding %d tumour rows into tnm_staging…", len(records))
    inserted = 0
    for rec in records:
        embedding_list = rec.get("embedding", [])
        embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

        db.execute(text("""
            INSERT INTO tnm_staging
                (tumour, icd_o, edition_uicc, edition_ajcc, rules,
                 tnm_json, stage_grouping, search_text, search_vector, embedding)
            VALUES
                (:tumour, :icd_o, :edition_uicc, :edition_ajcc, :rules,
                 :tnm_json, :stage_grouping, :search_text,
                 to_tsvector('english', :search_text),
                 CAST(:embedding AS vector))
            ON CONFLICT (tumour) DO NOTHING
        """), {
            "tumour": rec["tumour"],
            "icd_o": rec.get("icd_o", ""),
            "edition_uicc": rec.get("edition_uicc", "9th"),
            "edition_ajcc": rec.get("edition_ajcc"),
            "rules": rec.get("rules", ""),
            "tnm_json": json.dumps(rec.get("tnm_json", {})),
            "stage_grouping": json.dumps(rec.get("stage_grouping", [])),
            "search_text": rec.get("search_text", ""),
            "embedding": embedding_str,
        })
        inserted += 1

    db.commit()
    logger.info("[TNM] Seeded %d rows", inserted)
    return inserted


# ── Query embedding ──────────────────────────────────────────────────────────

def _embed_query(text_input: str) -> Optional[List[float]]:
    """Embed a query string using OpenAI text-embedding-3-small."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[TNM] OPENAI_API_KEY not set — semantic search disabled")
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=[text_input])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("[TNM] Embedding API error: %s", e)
        return None


# ── Hybrid search ────────────────────────────────────────────────────────────

def hybrid_tnm_search(
    query: str,
    db: Session,
    top_k: int = 3,
    confidence: float = CONFIDENCE_THRESHOLD,
) -> List[TnmResult]:
    """Run hybrid BM25 + semantic search and return top-k results via RRF.

    Returns an empty list when:
    - Not running on PostgreSQL (local SQLite dev)
    - The confidence gate is not met (top score < threshold)
    - Any unexpected database error occurs
    """
    try:
        dialect = db.bind.dialect.name if db.bind else ""
        if dialect != "postgresql":
            return []
    except Exception:
        return []

    # BM25 leg
    bm25_rows = db.execute(text("""
        SELECT id, tumour, icd_o, edition_uicc, edition_ajcc,
               rules, tnm_json, stage_grouping,
               ts_rank(search_vector, plainto_tsquery('english', :q)) AS rank
        FROM tnm_staging
        WHERE search_vector @@ plainto_tsquery('english', :q)
        ORDER BY rank DESC
        LIMIT :k
    """), {"q": query, "k": top_k * 3}).fetchall()

    # Semantic leg
    query_embedding = _embed_query(query)
    sem_rows = []
    if query_embedding:
        emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        sem_rows = db.execute(text("""
            SELECT id, tumour, icd_o, edition_uicc, edition_ajcc,
                   rules, tnm_json, stage_grouping,
                   1 - (embedding <=> CAST(:emb AS vector)) AS similarity
            FROM tnm_staging
            ORDER BY embedding <=> CAST(:emb AS vector)
            LIMIT :k
        """), {"emb": emb_str, "k": top_k * 3}).fetchall()

    # RRF fusion
    bm25_ids = [r.id for r in bm25_rows]
    sem_ids = [r.id for r in sem_rows]

    all_ids = set(bm25_ids) | set(sem_ids)
    if not all_ids:
        return []

    row_map: Dict[int, Any] = {}
    for r in bm25_rows:
        row_map[r.id] = r
    for r in sem_rows:
        if r.id not in row_map:
            row_map[r.id] = r

    rrf_scores: Dict[int, float] = {}
    bm25_rank_map: Dict[int, int] = {}
    sem_rank_map: Dict[int, int] = {}

    for rank_idx, rid in enumerate(bm25_ids):
        rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank_idx + 1)
        bm25_rank_map[rid] = rank_idx + 1
    for rank_idx, rid in enumerate(sem_ids):
        rrf_scores[rid] = rrf_scores.get(rid, 0) + 1.0 / (RRF_K + rank_idx + 1)
        sem_rank_map[rid] = rank_idx + 1

    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    if rrf_scores[sorted_ids[0]] < confidence:
        logger.info("[TNM] Top RRF score %.4f below threshold %.4f — no confident match",
                     rrf_scores[sorted_ids[0]], confidence)
        return []

    results = []
    for rid in sorted_ids[:top_k]:
        r = row_map[rid]
        tnm_json = r.tnm_json if isinstance(r.tnm_json, dict) else json.loads(r.tnm_json)
        sg = r.stage_grouping if isinstance(r.stage_grouping, list) else json.loads(r.stage_grouping or "[]")
        results.append(TnmResult(
            tumour=r.tumour,
            icd_o=r.icd_o,
            edition_uicc=r.edition_uicc,
            edition_ajcc=r.edition_ajcc,
            tnm_json=tnm_json,
            stage_grouping=sg,
            rules=r.rules or "",
            rrf_score=rrf_scores[rid],
            bm25_rank=bm25_rank_map.get(rid),
            semantic_rank=sem_rank_map.get(rid),
        ))

    logger.info("[TNM] Hybrid search for %r → %d results (top: %s, score=%.4f)",
                query, len(results), results[0].tumour if results else "—",
                results[0].rrf_score if results else 0)
    return results


# ── Evidence formatter ───────────────────────────────────────────────────────

def format_tnm_evidence(result: TnmResult) -> str:
    """Format a TnmResult as a text block suitable for LLM injection."""
    lines = [
        f"══ AUTHORITATIVE TNM REFERENCE (UICC {result.edition_uicc} Edition) ══",
        f"Tumour type: {result.tumour}",
    ]
    if result.icd_o:
        lines.append(f"ICD-O: {result.icd_o}")

    tnm = result.tnm_json
    for axis in ("T", "N", "M"):
        categories = tnm.get(axis, {})
        if categories:
            lines.append(f"\n{axis}-stage definitions:")
            for cat, desc in categories.items():
                lines.append(f"  {cat}: {desc}")

    if result.stage_grouping:
        lines.append("\nStage grouping:")
        for g in result.stage_grouping:
            lines.append(f"  {g.get('stage','?')}: T={g.get('T','?')} N={g.get('N','?')} M={g.get('M','?')}")

    lines.append("══ END TNM REFERENCE ══")
    return "\n".join(lines)
