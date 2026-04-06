#!/usr/bin/env python3
"""
Simulate the planned guideline-fetch architecture before full integration.

Stages exercised (with debug logging):
  0 — Simulated report-generation output: ApplicableGuideline records (system, context, type, search_keywords).
  1 — Query construction (classification core vs topic-first uk_pathway/other) matching guideline_fetcher.py.
  2 — Firecrawl search (+ optional JSON scrape per result).
  3 — Parse web results: URL, title, extracted json (is_authoritative, criteria_summary, source_type).
  4 — First authoritative hit → what would be cached for audit injection.

Usage (from backend/):
  poetry run python scripts/simulate_guideline_fetch_flow.py
  poetry run python scripts/simulate_guideline_fetch_flow.py --dry-run
  poetry run python scripts/simulate_guideline_fetch_flow.py --search-only
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

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from rapid_reports_ai.guideline_fetcher import (
    EXTRACTION_SCHEMA,
    OTHER_FALLBACK_QUERY,
    OTHER_PRIMARY_QUERY,
    PDF_CATEGORY_QUERY,
    PDF_GUIDELINE_QUERY,
    QUERY_FALLBACKS,
    QUERY_TEMPLATES,
    SCRAPE_MAX_AGE_MS,
    SEARCH_LIMIT_BROAD,
    SEARCH_LIMIT_NARROW,
    SEARCH_TIMEOUT_RADIOPAEDIA_MS,
    UK_PATHWAY_FALLBACK_QUERY,
    UK_PATHWAY_PRIMARY_QUERY,
    _extraction_prompt_for_system,
    _query_core_classification,
    topic_line_for_pathway_or_other_search,
)

# -----------------------------------------------------------------------------
# Stage 0: stand-in for ReportOutput.applicable_guidelines (plan schema)
# -----------------------------------------------------------------------------


@dataclass
class ApplicableGuideline:
    system: str
    context: str
    type: Literal["classification", "uk_pathway", "other"]
    search_keywords: Optional[str] = None


# Mirrors guideline_fetcher._DISQUALIFYING_URL_PATHS
_DISQUALIFYING_URL_PATHS = (
    "/news/",
    "/blog/",
    "/campaign/",
    "/press-release/",
    "/press/",
    "/announcement/",
    "/post/",
    "/media/",
)

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


def build_scrape_options(search_only: bool, system: str) -> Any:
    from firecrawl.v2.types import ScrapeOptions

    if search_only:
        return ScrapeOptions(
            formats=["markdown"],
            only_main_content=True,
            max_age=SCRAPE_MAX_AGE_MS,
            proxy="basic",
            parsers=[],
        )
    return ScrapeOptions(
        formats=[
            {
                "type": "json",
                "schema": EXTRACTION_SCHEMA,
                "prompt": _extraction_prompt_for_system(system),
            }
        ],
        only_main_content=True,
        max_age=SCRAPE_MAX_AGE_MS,
        proxy="basic",
        parsers=[],
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
                url_lower = url.lower()
                if any(p in url_lower for p in _DISQUALIFYING_URL_PATHS):
                    _debug(
                        "Stage 3 — SKIP non-protocol URL",
                        {"url": url},
                    )
                    continue
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
    t = guideline.type
    scrape_opts = build_scrape_options(search_only, guideline.system)
    if t == "classification":
        core = _query_core_classification(guideline.system, guideline.search_keywords)
        _debug(
            "Stage 1 — query core",
            {"system": guideline.system, "search_keywords": guideline.search_keywords, "core": core, "type": t},
        )
    else:
        topic = topic_line_for_pathway_or_other_search(
            guideline.system, guideline.search_keywords, guideline.context
        )
        _debug(
            "Stage 1 — topic line",
            {"system": guideline.system, "search_keywords": guideline.search_keywords, "topic": topic, "type": t},
        )

    async def attempt(
        label: str,
        query: str,
        *,
        search_timeout_ms: int | None = None,
        result_limit: int | None = None,
        categories: list[str] | None = None,
        location: str | None = None,
    ) -> tuple[str | None, str | None]:
        tw = search_timeout_ms if search_timeout_ms is not None else timeout_ms
        lim = result_limit if result_limit is not None else limit
        _debug(
            f"Stage 2 — Firecrawl.search ({label})",
            {
                "query": query,
                "limit": lim,
                "categories": categories,
                "location": location,
                "timeout_ms": tw,
            },
        )
        data = await run_firecrawl_search(
            client,
            query=query,
            limit=lim,
            scrape_options=scrape_opts,
            timeout_ms=tw,
            categories=categories,
            location=location,
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

    if t == "classification":
        core = _query_core_classification(guideline.system, guideline.search_keywords)
        q_rp = QUERY_TEMPLATES["classification"].format(core=core)
        content, url = await attempt(
            "classification web (no category)",
            q_rp,
            search_timeout_ms=SEARCH_TIMEOUT_RADIOPAEDIA_MS,
        )
        if content:
            return content, url
        content, url = await attempt(
            "classification + categories=['research']",
            q_rp,
            categories=["research"],
            search_timeout_ms=SEARCH_TIMEOUT_RADIOPAEDIA_MS,
        )
        if content:
            return content, url
        q2 = QUERY_FALLBACKS["classification"].format(core=core)
        content, url = await attempt(
            "fallback (classification)",
            q2,
            result_limit=SEARCH_LIMIT_BROAD,
        )
        return content, url

    topic = topic_line_for_pathway_or_other_search(
        guideline.system, guideline.search_keywords, guideline.context
    )
    if t == "uk_pathway":
        loc = "United Kingdom"
        q1 = UK_PATHWAY_PRIMARY_QUERY.format(topic=topic)
        content, url = await attempt("uk_pathway primary", q1, location=loc)
        if content:
            return content, url
        content, url = await attempt(
            "uk_pathway research", q1, location=loc, categories=["research"]
        )
        if content:
            return content, url
        q2 = UK_PATHWAY_FALLBACK_QUERY.format(topic=topic)
        content, url = await attempt(
            "uk_pathway fallback",
            q2,
            location=loc,
            result_limit=SEARCH_LIMIT_BROAD,
        )
        if content:
            return content, url
        q_pdf = PDF_GUIDELINE_QUERY.format(topic=topic)
        content, url = await attempt(
            "uk_pathway pdf filetype (no location)",
            q_pdf,
            result_limit=SEARCH_LIMIT_BROAD,
        )
        if content:
            return content, url
        q_pdf_cat = PDF_CATEGORY_QUERY.format(topic=topic)
        content, url = await attempt(
            "uk_pathway pdf category (no location)",
            q_pdf_cat,
            categories=["pdf"],
            result_limit=SEARCH_LIMIT_BROAD,
        )
        return content, url

    q1 = OTHER_PRIMARY_QUERY.format(topic=topic)
    content, url = await attempt("other primary", q1)
    if content:
        return content, url
    content, url = await attempt("other research", q1, categories=["research"])
    if content:
        return content, url
    q2 = OTHER_FALLBACK_QUERY.format(topic=topic)
    content, url = await attempt(
        "other fallback",
        q2,
        result_limit=SEARCH_LIMIT_BROAD,
    )
    if content:
        return content, url
    q_pdf = PDF_GUIDELINE_QUERY.format(topic=topic)
    content, url = await attempt(
        "other pdf filetype (no location)",
        q_pdf,
        result_limit=SEARCH_LIMIT_BROAD,
    )
    if content:
        return content, url
    q_pdf_cat = PDF_CATEGORY_QUERY.format(topic=topic)
    content, url = await attempt(
        "other pdf category (no location)",
        q_pdf_cat,
        categories=["pdf"],
        result_limit=SEARCH_LIMIT_BROAD,
    )
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
            if g.type == "classification":
                core = _query_core_classification(g.system, g.search_keywords)
                planned = {
                    "search_limit_narrow": SEARCH_LIMIT_NARROW,
                    "search_limit_broad": SEARCH_LIMIT_BROAD,
                    "classification_q1": QUERY_TEMPLATES["classification"].format(core=core),
                    "classification_fallback": QUERY_FALLBACKS["classification"].format(core=core),
                }
            else:
                topic = topic_line_for_pathway_or_other_search(
                    g.system, g.search_keywords, g.context
                )
                if g.type == "uk_pathway":
                    planned = {
                        "search_limit_narrow": SEARCH_LIMIT_NARROW,
                        "search_limit_broad": SEARCH_LIMIT_BROAD,
                        "uk_pathway_primary": UK_PATHWAY_PRIMARY_QUERY.format(topic=topic),
                        "uk_pathway_fallback": UK_PATHWAY_FALLBACK_QUERY.format(topic=topic),
                        "uk_pathway_pdf_filetype": PDF_GUIDELINE_QUERY.format(topic=topic),
                        "uk_pathway_pdf_category": PDF_CATEGORY_QUERY.format(topic=topic),
                    }
                else:
                    planned = {
                        "search_limit_narrow": SEARCH_LIMIT_NARROW,
                        "search_limit_broad": SEARCH_LIMIT_BROAD,
                        "other_primary": OTHER_PRIMARY_QUERY.format(topic=topic),
                        "other_fallback": OTHER_FALLBACK_QUERY.format(topic=topic),
                        "other_pdf_filetype": PDF_GUIDELINE_QUERY.format(topic=topic),
                        "other_pdf_category": PDF_CATEGORY_QUERY.format(topic=topic),
                    }
            _debug(
                "DRY RUN — queries that would be attempted",
                {
                    "guideline": {
                        "system": g.system,
                        "type": g.type,
                        "context": g.context,
                        "search_keywords": g.search_keywords,
                    },
                    **planned,
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
    p.add_argument(
        "--limit",
        type=int,
        default=SEARCH_LIMIT_NARROW,
        help=(
            f"Default Firecrawl search limit for narrow attempts (matches production {SEARCH_LIMIT_NARROW}); "
            f"broad fallbacks use {SEARCH_LIMIT_BROAD} in guideline_fetcher."
        ),
    )
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
