#!/usr/bin/env python3
"""
Simulate the planned guideline-fetch architecture before full integration.

Stages exercised (with debug logging):
  0 — Simulated report-generation output: ApplicableGuideline records (system, context, type, search_keywords).
  1 — Query construction (_query_core + templates / fallbacks) exactly as in the implementation plan.
  2 — Firecrawl search (+ optional JSON scrape per result).
  3 — Parse web results: URL, title, extracted json (is_authoritative, criteria_summary, source_type).
  4 — First authoritative hit → what would be cached for audit injection.

Usage (from backend/):
  poetry run python scripts/simulate_guideline_fetch_flow.py
  poetry run python scripts/simulate_guideline_fetch_flow.py --dry-run
  poetry run python scripts/simulate_guideline_fetch_flow.py --search-only --limit 2
  poetry run python scripts/simulate_guideline_fetch_flow.py --case bosniak

Requires FIRECRAWL_API_KEY for live calls (load backend/.env via dotenv if present).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

# -----------------------------------------------------------------------------
# Stage 0: stand-in for ReportOutput.applicable_guidelines (plan schema)
# -----------------------------------------------------------------------------


@dataclass
class ApplicableGuideline:
    system: str
    context: str
    type: Literal["classification", "uk_pathway", "other"]
    search_keywords: Optional[str] = None


# -----------------------------------------------------------------------------
# Mirrors planned guideline_fetcher.py constants
# -----------------------------------------------------------------------------

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_authoritative": {
            "type": "boolean",
            "description": (
                "True if this page is from a medical society, peer-reviewed journal, "
                "authoritative clinical registry, or specialist society. "
                "False for patient information pages, blogs, news articles, or commercial sites."
            ),
        },
        "criteria_summary": {
            "type": "string",
            "description": (
                "Classification categories with imaging criteria and measurement thresholds "
                "per category. Management or follow-up recommendations per category where stated. "
                "UK NHS context where applicable. Maximum 400 words."
            ),
        },
        "source_type": {
            "type": "string",
            "description": (
                "One of: society guideline, journal publication, educational, patient info, other"
            ),
        },
    },
    "required": ["is_authoritative", "criteria_summary"],
}

EXTRACTION_PROMPT = (
    "Extract classification criteria, imaging thresholds, category definitions, and management "
    "recommendations for the named guideline system. UK NHS clinical context. "
    "Assess whether this is an authoritative medical/clinical source."
)

QUERY_TEMPLATES = {
    "classification": "{core} classification criteria categories site:radiopaedia.org",
    "uk_pathway": "{core} guideline criteria UK NHS recommendations",
    "other": "{core} radiology guideline criteria",
}

QUERY_FALLBACKS = {
    "classification": "{core} classification imaging criteria categories 2015 2024",
    "uk_pathway": "{core} UK clinical guideline criteria recommendations",
    "other": "{core} radiology guideline criteria",
}


def _query_core(system: str, search_keywords: str | None) -> str:
    tail = f" {search_keywords}" if search_keywords else ""
    return f'"{system}"{tail}'.strip()


def _debug(title: str, body: Any = None) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n[DEBUG] {title}\n{bar}")
    if body is not None:
        if isinstance(body, str):
            print(body)
        else:
            print(json.dumps(body, indent=2, default=str))


def _result_url(item: Any) -> str:
    if hasattr(item, "metadata") and item.metadata is not None:
        md = item.metadata
        if hasattr(md, "source_url") and md.source_url:
            return str(md.source_url)
        if hasattr(md, "url") and md.url:
            return str(md.url)
    if hasattr(item, "url") and item.url:
        return str(item.url)
    return ""


def _result_title(item: Any) -> str:
    if hasattr(item, "metadata") and item.metadata is not None:
        md = item.metadata
        if hasattr(md, "title") and md.title:
            return str(md.title)
    if hasattr(item, "title") and item.title:
        return str(item.title)
    return ""


def _iter_web_results(search_data: Any) -> list[Any]:
    web = getattr(search_data, "web", None) or []
    return list(web)


def _quality_note(guideline: ApplicableGuideline) -> None:
    issues: list[str] = []
    if len(guideline.system) > 60:
        issues.append("system name > 60 chars (planned fetcher will skip)")
    if len(guideline.system.split()) > 8:
        issues.append("system looks like a sentence, not a canonical name")
    if guideline.type == "classification" and not guideline.search_keywords:
        issues.append("no search_keywords — recall may be weaker for ambiguous systems")
    if issues:
        _debug("Stage 0 quality hints", {"issues": issues})
    else:
        _debug("Stage 0 quality hints", "No obvious red flags on synthetic guideline row.")


def build_scrape_options(search_only: bool) -> Any:
    from firecrawl.v2.types import ScrapeOptions

    if search_only:
        return ScrapeOptions(formats=["markdown"], only_main_content=True)
    return ScrapeOptions(
        formats=[
            {
                "type": "json",
                "schema": EXTRACTION_SCHEMA,
                "prompt": EXTRACTION_PROMPT,
            }
        ],
        only_main_content=True,
    )


async def run_firecrawl_search(
    client: Any,
    *,
    query: str,
    limit: int,
    scrape_options: Any,
    timeout_ms: int,
    categories: list[str] | None = None,
    location: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {
        "limit": limit,
        "timeout": timeout_ms,
        "scrape_options": scrape_options,
    }
    if categories:
        kwargs["categories"] = categories
    if location:
        kwargs["location"] = location
    return await client.search(query, **kwargs)


def first_authoritative_hit(
    search_data: Any, search_only: bool
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Returns (criteria_summary_or_markdown_snippet, url, raw_json_or_none)."""
    for i, item in enumerate(_iter_web_results(search_data)):
        url = _result_url(item)
        title = _result_title(item)
        j = getattr(item, "json", None)
        md = getattr(item, "markdown", None)
        _debug(
            f"Stage 3 — result[{i}]",
            {
                "url": url,
                "title": title,
                "has_json": j is not None,
                "markdown_chars": len(md or "") if md else 0,
                "json_preview": j if isinstance(j, dict) else str(j)[:500] if j else None,
            },
        )
        if search_only:
            if md and len(md.strip()) > 80:
                snippet = md.strip()[:1200]
                return snippet, url, None
            continue
        if isinstance(j, dict):
            if j.get("is_authoritative") and (j.get("criteria_summary") or "").strip():
                return str(j["criteria_summary"]), url, j
    return None, None, None


async def fetch_guideline_simulated(
    client: Any,
    guideline: ApplicableGuideline,
    *,
    limit: int,
    search_only: bool,
    timeout_ms: int,
) -> tuple[str | None, str | None]:
    """
    Same control flow as planned fetch_guideline(); verbose logging.
    """
    core = _query_core(guideline.system, guideline.search_keywords)
    t = guideline.type
    scrape_opts = build_scrape_options(search_only)

    _debug(
        "Stage 1 — query core",
        {"system": guideline.system, "search_keywords": guideline.search_keywords, "core": core, "type": t},
    )

    async def attempt(label: str, query: str, **kwargs: Any) -> tuple[str | None, str | None]:
        _debug(
            f"Stage 2 — Firecrawl.search ({label})",
            {"query": query, "kwargs": {k: v for k, v in kwargs.items() if v is not None}},
        )
        data = await run_firecrawl_search(
            client,
            query=query,
            limit=limit,
            scrape_options=scrape_opts,
            timeout_ms=timeout_ms,
            categories=kwargs.get("categories"),
            location=kwargs.get("location"),
        )
        n = len(_iter_web_results(data))
        _debug(f"Stage 2 — response summary ({label})", {"web_results": n})
        hit_url: str | None
        payload: str | None
        raw: dict[str, Any] | None
        payload, hit_url, raw = first_authoritative_hit(data, search_only)
        if payload:
            _debug(
                "Stage 4 — SELECTED for cache / audit context",
                {
                    "url": hit_url,
                    "criteria_or_markdown_len": len(payload),
                    "raw_json_keys": list(raw.keys()) if raw else None,
                },
            )
        return payload, hit_url

    # Classification: Radiopaedia-biased query, web index first, then research category
    if t == "classification":
        q_rp = QUERY_TEMPLATES["classification"].format(core=core)
        content, url = await attempt("classification web (no category)", q_rp)
        if content:
            return content, url
        content, url = await attempt("classification + categories=['research']", q_rp, categories=["research"])
        if content:
            return content, url
    else:
        q1 = QUERY_TEMPLATES[t].format(core=core)
        loc = "United Kingdom" if t == "uk_pathway" else None
        content, url = await attempt(f"type={t} primary", q1, location=loc)
        if content:
            return content, url

    q2 = QUERY_FALLBACKS[t].format(core=core)
    loc2 = "United Kingdom" if t == "uk_pathway" else None
    content, url = await attempt("fallback (broadened)", q2, location=loc2)
    return content, url


SAMPLE_CASES: dict[str, ApplicableGuideline] = {
    "bosniak": ApplicableGuideline(
        system="Bosniak",
        context="Complex renal cystic lesion with septa on contrast CT.",
        type="classification",
        search_keywords="renal cyst CT contrast septa",
    ),
    "fleischner": ApplicableGuideline(
        system="Fleischner Society pulmonary nodule",
        context="Solitary pulmonary nodule on CT chest.",
        type="classification",
        search_keywords="pulmonary nodule CT solid",
    ),
    "nice": ApplicableGuideline(
        system="NICE suspected cancer pathway",
        context="Patient with new unexplained weight loss and imaging for malignancy.",
        type="uk_pathway",
        search_keywords="weight loss referral",
    ),
    "bad_system_name": ApplicableGuideline(
        system="This is a deliberately long non-canonical system name that should trigger the length guard",
        context="Test row.",
        type="other",
        search_keywords=None,
    ),
}


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[1]
        env_path = root / ".env"
        if env_path.is_file():
            load_dotenv(env_path)
            _debug("Environment", f"Loaded {env_path}")
    except ImportError:
        pass


async def main_async(args: argparse.Namespace) -> int:
    load_env()

    if args.dry_run:
        guidelines = (
            [SAMPLE_CASES[c] for c in args.case]
            if args.case
            else list(SAMPLE_CASES.values())
        )
        for g in guidelines:
            core = _query_core(g.system, g.search_keywords)
            _debug(
                "DRY RUN — queries that would be attempted",
                {
                    "guideline": {
                        "system": g.system,
                        "type": g.type,
                        "context": g.context,
                        "search_keywords": g.search_keywords,
                    },
                    "classification_q1": QUERY_TEMPLATES["classification"].format(core=core),
                    "classification_fallback": QUERY_FALLBACKS["classification"].format(core=core),
                    "typed_primary": QUERY_TEMPLATES[g.type].format(core=core),
                    "typed_fallback": QUERY_FALLBACKS[g.type].format(core=core),
                },
            )
            _quality_note(g)
        print("\n[DRY RUN] No HTTP calls. Set FIRECRAWL_API_KEY and omit --dry-run to go live.\n")
        return 0

    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        print("ERROR: FIRECRAWL_API_KEY not set. Use --dry-run or configure .env", file=sys.stderr)
        return 2

    from firecrawl import AsyncFirecrawl

    client = AsyncFirecrawl(api_key=key)

    if args.case:
        guidelines = [SAMPLE_CASES[name] for name in args.case]
    else:
        guidelines = [SAMPLE_CASES["bosniak"], SAMPLE_CASES["fleischner"], SAMPLE_CASES["nice"]]

    for g in guidelines:
        print("\n" + "#" * 72)
        print(f"# CASE: system={g.system!r} type={g.type}")
        print("#" * 72)
        _quality_note(g)
        if len(g.system) > 60:
            _debug("Fetcher guard", "Would skip fetch (system > 60 chars).")
            continue
        try:
            content, url = await fetch_guideline_simulated(
                client,
                g,
                limit=args.limit,
                search_only=args.search_only,
                timeout_ms=args.timeout * 1000,
            )
        except Exception as exc:
            _debug("Stage ERROR — exception from Firecrawl", {"type": type(exc).__name__, "message": str(exc)})
            print("\n[FAIL] See exception above.\n")
            continue
        if content:
            _debug(
                "Stage 4 — FINAL snippet (first 800 chars)",
                content[:800] + ("…" if len(content) > 800 else ""),
            )
            print(f"\n[OK] url={url}\n")
        else:
            _debug("Stage 4 — MISS", "No authoritative JSON hit (or no markdown in --search-only mode).")
            print("\n[MISS]\n")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Print planned queries only; no API calls")
    p.add_argument(
        "--search-only",
        action="store_true",
        help="Search + markdown only (no JSON extraction). Cheaper; tests Stage 2 wiring.",
    )
    p.add_argument("--limit", type=int, default=3, help="Firecrawl search limit per attempt")
    p.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds (sent as ms to API)")
    p.add_argument(
        "--case",
        nargs="+",
        choices=list(SAMPLE_CASES.keys()),
        help="Run specific named sample case(s) instead of the default trio",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
