"""Fetch and cache guideline criteria via Firecrawl search + JSON extraction (no GLM in this layer)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from .enhancement_models import ApplicableGuideline
from .database.crud import get_cached_guideline, upsert_cached_guideline
from .guideline_payload import MAX_GUIDELINE_SYSTEM_LEN

if TYPE_CHECKING:
    from firecrawl.v2.types import ScrapeOptions

logger = logging.getLogger(__name__)

EXPIRY_SUCCESS_DAYS = 90
EXPIRY_UNAVAILABLE_DAYS = 7
# Outer cap must cover worst-case serial Firecrawl searches (classification: web + research + fallback).
FETCH_TIMEOUT_SECONDS = 60
SEARCH_LIMIT = 2
SEARCH_TIMEOUT_MS = 18000
# Skip refetch when an unavailable row was written moments ago (same audit / same session).
RECENT_UNAVAILABLE_SKIP_SECONDS = 300
CRITERIA_SUMMARY_API_MAX_LEN = 800
# When multiple authoritative hits (e.g. Bosniak 2005 vs 2019), merge top two after recency sort.
MERGED_CRITERIA_MAX_CHARS = 4000

_YEAR_IN_TEXT_RE = re.compile(r"\b(19[89]\d|20\d{2})\b")


@dataclass(frozen=True)
class GuidelineResolution:
    """Result of cache lookup + optional Firecrawl fetch for one applicable guideline."""

    content: Optional[str]
    source_url: Optional[str]
    injected: bool


def truncate_criteria_summary_for_api(text: str, max_len: int = CRITERIA_SUMMARY_API_MAX_LEN) -> Tuple[str, bool]:
    """Return (excerpt, was_truncated). Breaks on last space before max_len when possible."""
    if not text or not text.strip():
        return "", False
    t = text.strip()
    if len(t) <= max_len:
        return t, False
    cut = t[:max_len]
    sp = cut.rfind(" ")
    if sp > max_len * 2 // 3:
        cut = cut[:sp]
    return cut.rstrip() + "…", True


EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "is_authoritative": {
            "type": "boolean",
            "description": (
                "True ONLY if this page is a primary clinical guideline document, "
                "NHS/NICE/SIGN/RCR publication, peer-reviewed journal article, or "
                "specialist medical society guideline. "
                "Must be False for: news articles, press releases, campaign pages, "
                "programme announcements, advocacy organisation posts, blog posts, "
                "or secondary write-ups — even from legitimate medical organisations. "
                "A coalition or charity announcing an NHS programme is NOT authoritative. "
                "A BTS/NICE/RCR guideline document IS authoritative."
            ),
        },
        "criteria_summary": {
            "type": "string",
            "description": (
                "Classification categories with imaging criteria and measurement thresholds "
                "per category. Management or follow-up recommendations per category where stated. "
                "UK NHS context where applicable. Target up to 400 words; include key measurement thresholds where present."
            ),
        },
        "source_type": {
            "type": "string",
            "description": "One of: society guideline, journal publication, educational, patient info, other (informational only)",
        },
    },
    "required": ["is_authoritative", "criteria_summary"],
}

EXTRACTION_PROMPT = (
    "Extract classification criteria, imaging thresholds, category definitions, and management "
    "recommendations for the named guideline system. UK NHS clinical context. "
    "Set is_authoritative=true ONLY for primary guideline documents from medical societies "
    "(BTS, NICE, RCR, ACR, ESR, ESUR), NHS England, or peer-reviewed journals. "
    "Set is_authoritative=false for news articles, press releases, campaign announcements, "
    "programme promotion pages, or advocacy content — regardless of publishing organisation."
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


def _query_core(system: str, search_keywords: Optional[str]) -> str:
    tail = f" {search_keywords}" if search_keywords else ""
    return f'"{system}"{tail}'.strip()


def _doc_url(doc: Any) -> str:
    md = getattr(doc, "metadata", None)
    if md is not None:
        u = getattr(md, "source_url", None) or getattr(md, "url", None)
        if u:
            return str(u)
    u2 = getattr(doc, "url", None)
    return str(u2 or "")


def _recency_score(url: str, criteria_summary: str) -> int:
    """Prefer newer guideline versions when multiple authoritative hits exist (URL + summary years)."""
    blob = f"{url} {criteria_summary}"
    years: List[int] = []
    for m in _YEAR_IN_TEXT_RE.finditer(blob):
        y = int(m.group(1))
        if 1990 <= y <= 2035:
            years.append(y)
    return max(years) if years else 0


# URL path segments that usually indicate non-protocol content (news, PR, blogs).
# /article/ is intentionally excluded — journals and societies use it for legitimate papers.
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


def _first_authoritative(search_data: Any) -> Optional[Tuple[str, str]]:
    """
    Collect all authoritative docs with criteria text, rank by recency (max year in URL/summary),
    then return the best alone or merge the top two (capped) so e.g. Bosniak 2019 leads but 2005
    detail can supplement when both appear in web results.
    """
    hits: List[Tuple[int, int, str, str]] = []
    for i, doc in enumerate(search_data.web or []):
        j = getattr(doc, "json", None)
        if not isinstance(j, dict):
            continue
        summary = (j.get("criteria_summary") or "").strip()
        if not (j.get("is_authoritative") and summary):
            continue
        url = _doc_url(doc)
        url_lower = url.lower()
        if any(p in url_lower for p in _DISQUALIFYING_URL_PATHS):
            print(
                f"[GUIDELINE_PIPELINE] _first_authoritative SKIP non-protocol URL: {url!r}"
            )
            continue
        sc = _recency_score(url, summary)
        hits.append((sc, i, summary, url))
    if not hits:
        return None
    hits.sort(key=lambda x: (-x[0], x[1]))
    _, _, top_text, top_url = hits[0]
    if len(hits) >= 2:
        _, _, second_text, _second_url = hits[1]
        combined = f"{top_text}\n\nAdditional version criteria:\n{second_text}"
        if len(combined) > MERGED_CRITERIA_MAX_CHARS:
            combined = combined[: MERGED_CRITERIA_MAX_CHARS - 1].rstrip() + "…"
        print(
            f"[GUIDELINE_PIPELINE] first_authoritative merged 2 hits "
            f"recency_scores=({hits[0][0]}, {hits[1][0]}) combined_chars={len(combined)} "
            f"primary_url={top_url!r}"
        )
        return (combined, top_url)
    return (top_text, top_url)


def _scrape_options() -> "ScrapeOptions":
    from firecrawl.v2.types import ScrapeOptions

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


def _web_result_count(search_data: Any) -> int:
    return len(search_data.web or [])


async def fetch_guideline(guideline: ApplicableGuideline) -> Optional[Tuple[str, str]]:
    core = _query_core(guideline.system, guideline.search_keywords)
    t = guideline.type
    print(
        f"[GUIDELINE_PIPELINE] fetch_guideline START system={guideline.system!r} "
        f"type={t!r} core={core[:120]!r}{'…' if len(core) > 120 else ''}"
    )
    try:
        from .firecrawl_client import get_async_firecrawl

        client = get_async_firecrawl()
    except ModuleNotFoundError as e:
        print(f"[GUIDELINE_PIPELINE] fetch_guideline ABORT (firecrawl not installed): {e}")
        logger.warning("guideline fetch skipped: %s", e)
        return None
    except ValueError as e:
        print(f"[GUIDELINE_PIPELINE] fetch_guideline ABORT (no client): {e}")
        logger.warning("guideline fetch skipped: %s", e)
        return None

    scrape_opts = _scrape_options()

    async def run_search(
        query: str,
        *,
        categories: Optional[List[str]] = None,
        location: Optional[str] = None,
        label: str = "",
    ) -> Any:
        kw: dict = {
            "limit": SEARCH_LIMIT,
            "scrape_options": scrape_opts,
            "timeout": SEARCH_TIMEOUT_MS,
        }
        if categories:
            kw["categories"] = categories
        if location:
            kw["location"] = location
        qpv = query[:100]
        qdots = "…" if len(query) > 100 else ""
        print(
            f"[GUIDELINE_PIPELINE]   Firecrawl.search [{label}] "
            f"categories={categories!r} location={location!r} "
            f"query_len={len(query)} query_preview={qpv!r}{qdots}"
        )
        sd = await client.search(query, **kw)
        n = _web_result_count(sd)
        print(f"[GUIDELINE_PIPELINE]   Firecrawl.search [{label}] → web_results={n}")
        return sd

    if t == "classification":
        q_rp = QUERY_TEMPLATES["classification"].format(core=core)
        sd1 = await run_search(q_rp, label="classification web (no category)")
        hit = _first_authoritative(sd1)
        if hit:
            print(
                f"[GUIDELINE_PIPELINE] fetch_guideline HIT authoritative "
                f"criteria_chars={len(hit[0])} url={hit[1]!r}"
            )
            return hit
        sd2 = await run_search(q_rp, categories=["research"], label="classification research")
        hit = _first_authoritative(sd2)
        if hit:
            print(
                f"[GUIDELINE_PIPELINE] fetch_guideline HIT authoritative (research) "
                f"criteria_chars={len(hit[0])} url={hit[1]!r}"
            )
            return hit
    else:
        q1 = QUERY_TEMPLATES[t].format(core=core)
        loc = "United Kingdom" if t == "uk_pathway" else None
        sd3 = await run_search(q1, location=loc, label=f"typed primary ({t})")
        hit = _first_authoritative(sd3)
        if hit:
            print(
                f"[GUIDELINE_PIPELINE] fetch_guideline HIT authoritative "
                f"criteria_chars={len(hit[0])} url={hit[1]!r}"
            )
            return hit

    q2 = QUERY_FALLBACKS[t].format(core=core)
    loc2 = "United Kingdom" if t == "uk_pathway" else None
    sd4 = await run_search(q2, location=loc2, label=f"fallback ({t})")
    hit = _first_authoritative(sd4)
    if hit:
        print(
            f"[GUIDELINE_PIPELINE] fetch_guideline HIT authoritative (fallback) "
            f"criteria_chars={len(hit[0])} url={hit[1]!r}"
        )
    else:
        print("[GUIDELINE_PIPELINE] fetch_guideline MISS (no authoritative JSON after all attempts)")
    return hit


async def ensure_guideline_cached(
    guideline: ApplicableGuideline,
    db: Session,
) -> GuidelineResolution:
    print(f"[GUIDELINE_PIPELINE] ensure_guideline_cached ENTER system={guideline.system!r}")
    if len(guideline.system) > MAX_GUIDELINE_SYSTEM_LEN:
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached SKIP system too long "
            f"len={len(guideline.system)}"
        )
        return GuidelineResolution(None, None, False)

    entry = get_cached_guideline(db, guideline.system)
    if entry is not None:
        c = (entry.content or "").strip() if entry.content else ""
        ok = bool(c) and entry.is_available
        if ok:
            print(
                f"[GUIDELINE_PIPELINE] ensure_guideline_cached CACHE HIT (usable) "
                f"content_chars={len(c)} source_url={entry.source_url!r}"
            )
            return GuidelineResolution(c, entry.source_url, True)
        # Unavailable row written very recently — avoid a second Firecrawl attempt in the same run.
        if not entry.is_available:
            fa = entry.fetched_at
            if fa is not None and fa.tzinfo is None:
                fa = fa.replace(tzinfo=timezone.utc)
            if fa is not None:
                age_seconds = (datetime.now(timezone.utc) - fa).total_seconds()
                if age_seconds < RECENT_UNAVAILABLE_SKIP_SECONDS:
                    print(
                        f"[GUIDELINE_PIPELINE] ensure_guideline_cached RECENT MISS skip refetch "
                        f"({age_seconds:.0f}s < {RECENT_UNAVAILABLE_SKIP_SECONDS}s) "
                        f"system={guideline.system!r}"
                    )
                    return GuidelineResolution(None, None, False)
        # Stale miss: row exists but fetch failed earlier (or empty). Retry Firecrawl instead of
        # treating 7d unavailable TTL as permanent — otherwise UI shows "Not retrieved" forever.
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached CACHE ROW unusable → will refetch "
            f"is_available={entry.is_available} content_len={len(c)} "
            f"expires_at={entry.expires_at}"
        )
        logger.debug(
            "guideline cache bypass for retry: system=%r is_available=%s content_len=%s",
            guideline.system,
            entry.is_available,
            len(c or ""),
        )

    print(
        f"[GUIDELINE_PIPELINE] ensure_guideline_cached FETCH wait_timeout={FETCH_TIMEOUT_SECONDS}s"
    )
    try:
        result = await asyncio.wait_for(
            fetch_guideline(guideline),
            timeout=FETCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        print(f"[GUIDELINE_PIPELINE] ensure_guideline_cached TIMEOUT after {FETCH_TIMEOUT_SECONDS}s: {exc!r}")
        logger.debug("guideline fetch failed for %r: %s", guideline.system, exc)
        result = None
    except Exception as exc:
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached EXCEPTION: "
            f"{type(exc).__name__}: {exc!s}"
        )
        logger.debug("guideline fetch failed for %r: %s", guideline.system, exc)
        result = None

    now = datetime.now(timezone.utc)
    if result:
        content, source_url = result
        upsert_cached_guideline(
            db,
            system=guideline.system,
            content=content,
            source_url=source_url,
            is_available=True,
            expires_at=now + timedelta(days=EXPIRY_SUCCESS_DAYS),
        )
        cc = (content or "").strip()
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached UPSERT OK "
            f"content_chars={len(cc)} source_url={source_url!r}"
        )
        return GuidelineResolution(cc, source_url or None, bool(cc))

    upsert_cached_guideline(
        db,
        system=guideline.system,
        content=None,
        source_url=None,
        is_available=False,
        unavailable_reason="fetch_failed_or_unverified",
        expires_at=now + timedelta(days=EXPIRY_UNAVAILABLE_DAYS),
    )
    print(
        f"[GUIDELINE_PIPELINE] ensure_guideline_cached UPSERT unavailable "
        f"(7d) system={guideline.system!r}"
    )
    return GuidelineResolution(None, None, False)
