#!/usr/bin/env python3
"""One-time local script: reads tnm_9th_clean.json, calls OpenAI
text-embedding-3-small for each tumour, and writes tnm_embeddings.json
which ships with the codebase for production seeding."""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "rapid_reports_ai" / "resources"
INPUT_FILE = RESOURCES / "tnm_9th_clean.json"
OUTPUT_FILE = RESOURCES / "tnm_embeddings.json"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def build_search_text(entry: dict) -> str:
    """Concatenate tumour fields into a single searchable text block."""
    parts = [f"Tumour: {entry['tumour']}"]
    if entry.get("icd_o"):
        parts.append(f"ICD-O: {entry['icd_o']}")
    if entry.get("rules"):
        parts.append(f"Rules: {entry['rules'][:500]}")

    tnm = entry.get("tnm", {})
    for axis in ("T", "N", "M"):
        categories = tnm.get(axis, {})
        if categories:
            lines = [f"  {k}: {v}" for k, v in categories.items()]
            parts.append(f"{axis}-stage:\n" + "\n".join(lines))

    sg = entry.get("stage_grouping", [])
    if sg:
        sg_lines = [
            f"  {g['stage']}: T={g.get('T','?')} N={g.get('N','?')} M={g.get('M','?')}"
            for g in sg
        ]
        parts.append("Stage grouping:\n" + "\n".join(sg_lines))

    return "\n".join(parts)


def main():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    with open(INPUT_FILE) as f:
        data = json.load(f)

    tumours = data.get("tumours", {})
    print(f"Processing {len(tumours)} tumour types…")

    records = []
    texts_to_embed = []

    for name, entry in tumours.items():
        search_text = build_search_text(entry)
        edition = entry.get("edition", {})
        records.append({
            "tumour": entry["tumour"],
            "icd_o": entry.get("icd_o", ""),
            "edition_uicc": edition.get("uicc", "9th"),
            "edition_ajcc": edition.get("ajcc_alignment"),
            "rules": entry.get("rules", ""),
            "tnm_json": entry.get("tnm", {}),
            "stage_grouping": entry.get("stage_grouping", []),
            "search_text": search_text,
        })
        texts_to_embed.append(search_text)

    # Batch embed (OpenAI supports up to 2048 inputs per call)
    print(f"Embedding {len(texts_to_embed)} texts with {EMBEDDING_MODEL}…")
    t0 = time.time()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts_to_embed,
    )
    elapsed = time.time() - t0
    print(f"Embeddings received in {elapsed:.1f}s")

    for i, emb_data in enumerate(response.data):
        records[i]["embedding"] = emb_data.embedding

    with open(OUTPUT_FILE, "w") as f:
        json.dump({
            "model": EMBEDDING_MODEL,
            "dimensions": EMBEDDING_DIM,
            "source": str(INPUT_FILE.name),
            "count": len(records),
            "records": records,
        }, f)

    size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUTPUT_FILE} ({size_mb:.1f} MB, {len(records)} records)")


if __name__ == "__main__":
    main()
