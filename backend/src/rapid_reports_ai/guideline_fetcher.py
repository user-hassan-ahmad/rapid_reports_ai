"""Fetch and cache guideline criteria via Firecrawl search + JSON extraction (no GLM in this layer).

Search strategy: all queries for a given guideline type fire in parallel via asyncio.gather so
latency equals the slowest single search rather than the sum. Classification runs 3 concurrent
searches; uk_pathway and other each run 5 (primary, research, fallback, pdf-filetype, pdf-category).
Results are merged by _best_authoritative_from_multiple which deduplicates across searches and
ranks by recency before returning the best (or top-two merged) authoritative hit.

PDF handling: web searches use parsers=[] (HTML only, cheaper). PDF-targeted searches
(filetype:pdf query and Firecrawl pdf category) use _pdf_scrape_options which omits parsers=[],
enabling Firecrawl's default PDF text extraction for NHS Trust / society guideline PDFs.

Timing: every Firecrawl.search logs elapsed_ms. Set GUIDELINE_FETCH_PERF_DEBUG=1 (or enable DEBUG
for this logger) to print per-result metadata: cache_state, queue time, proxy, status, etc.

PubMed URLs: when full text exists in PMC, PMID is resolved via the PMC idconv API and the PMC
HTML article is scraped (more content than the PubMed abstract page). Optional env NCBI_EMAIL for idconv.

NICE landing pages: thin guidance root URLs trigger a Firecrawl map(search="recommendations") call
to discover chapter subpages dynamically; top-3 chapter URLs are scraped concurrently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from .enhancement_models import ApplicableGuideline
from .guideline_payload import MAX_GUIDELINE_SYSTEM_LEN

if TYPE_CHECKING:
    from firecrawl.v2.types import ScrapeOptions

logger = logging.getLogger(__name__)

# In-process session cache for ensure_guideline_cached (replaces dropped guideline_cache DB table).
# Maps cache_key → (content: Optional[str], source_url: Optional[str], expires_epoch: float).
# Populated by ensure_guideline_cached; shared across all requests in the same server process.
_GUIDELINE_SESSION_CACHE: dict = {}

# Success TTLs: classification systems (Bosniak, LI-RADS) update rarely; uk_pathway guidelines
# can change within months (NICE rapid updates, new specialist society guidance).
EXPIRY_SUCCESS_DAYS_CLASSIFICATION = 90
EXPIRY_SUCCESS_DAYS_UK_PATHWAY = 30
EXPIRY_SUCCESS_DAYS_OTHER = 60
# Keep legacy constant for any external callers; internal paths now use type-specific values.
EXPIRY_SUCCESS_DAYS = EXPIRY_SUCCESS_DAYS_CLASSIFICATION

# Unavailable TTLs: distinguish transient search failure from a genuine "no result found".
# Transient (timeout / exception): retry in 8 hours — Firecrawl may have been flaky.
# Genuine miss: don't waste credits for 7 days — the content probably doesn't exist in that form.
EXPIRY_UNAVAILABLE_DAYS_GENUINE_MISS = 7
EXPIRY_UNAVAILABLE_HOURS_TRANSIENT = 8
# Keep legacy constant; internal paths now use reason-code-specific values.
EXPIRY_UNAVAILABLE_DAYS = EXPIRY_UNAVAILABLE_DAYS_GENUINE_MISS

# Outer cap: parallel fan-out means worst case = slowest single search (~18s) + enrichment (~20s).
FETCH_TIMEOUT_SECONDS = 50
# Tight limit on narrow queries (site: / early pathway); broad on open web and PDF passes for recall.
SEARCH_LIMIT_NARROW = 2
SEARCH_LIMIT_BROAD = 4
SEARCH_TIMEOUT_MS = 18000
# Radiopaedia-scoped classification searches: fail fast so open-web fallback can run sooner.
SEARCH_TIMEOUT_RADIOPAEDIA_MS = 10000
CRITERIA_SUMMARY_API_MAX_LEN = 800
# When multiple authoritative hits (e.g. Bosniak 2005 vs 2019), merge top two after recency sort.
MERGED_CRITERIA_MAX_CHARS = 4000
# Firecrawl scrape cache: 7 days (ms). Guidelines change slowly; reduces repeat scrape latency.
SCRAPE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
# Topic line cap keeps search queries within Firecrawl limits and avoids bloated queries from long context.
MAX_TOPIC_SEARCH_CHARS = 160

_YEAR_IN_TEXT_RE = re.compile(r"\b(19[89]\d|20\d{2})\b")

_PERF_DEBUG_ENV = os.environ.get("GUIDELINE_FETCH_PERF_DEBUG", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _perf_debug_enabled() -> bool:
    return _PERF_DEBUG_ENV or logger.isEnabledFor(logging.DEBUG)


def _success_expiry_days(guideline_type: str) -> int:
    """Return cache TTL (days) for a successful fetch, differentiated by guideline type."""
    if guideline_type == "classification":
        return EXPIRY_SUCCESS_DAYS_CLASSIFICATION
    if guideline_type == "uk_pathway":
        return EXPIRY_SUCCESS_DAYS_UK_PATHWAY
    return EXPIRY_SUCCESS_DAYS_OTHER


def _log_web_results_perf(search_data: Any, label: str) -> None:
    """Log per-result Firecrawl metadata (cache, queue, proxy) when perf debug is on."""
    if not _perf_debug_enabled():
        return
    web = search_data.web or []
    for i, doc in enumerate(web):
        url = _doc_url(doc) or getattr(doc, "url", None) or ""
        preview = url[:140] + ("…" if len(url) > 140 else "")
        md = getattr(doc, "metadata", None)
        parts = [f"[GUIDELINE_PIPELINE]   perf web[{i}] [{label}] url={preview!r}"]
        if md is not None:
            for attr in (
                "cache_state",
                "concurrency_queue_duration_ms",
                "concurrency_limited",
                "proxy_used",
                "status_code",
                "credits_used",
                "error",
            ):
                v = getattr(md, attr, None)
                if v is not None:
                    parts.append(f"{attr}={v!r}")
        else:
            parts.append("metadata=<none>")
        j = getattr(doc, "json", None)
        parts.append(f"has_json={isinstance(j, dict)}")
        if isinstance(j, dict):
            parts.append(f"json_keys={sorted(j.keys())!r}")
        w = getattr(doc, "warning", None)
        if w:
            parts.append(f"warning={w!r}")
        print(" ".join(parts))


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


def _extraction_prompt_for_system(system: str) -> str:
    """JSON-extraction instructions; includes case label for verification (not quoted in web search)."""
    safe = system.replace('"', "'").strip()[:120]
    return (
        "Extract classification criteria, imaging thresholds, category definitions, and management "
        "recommendations for the named guideline system. UK NHS clinical context. "
        "Set is_authoritative=true ONLY for primary guideline documents from medical societies "
        "(BTS, NICE, RCR, ACR, ESR, ESUR), NHS England, or peer-reviewed journals. "
        "Set is_authoritative=false for news articles, press releases, campaign announcements, "
        "programme promotion pages, or advocacy content — regardless of publishing organisation. "
        f'The case references this framework label (may be approximate; verify against the page): "{safe}". '
        "If the page describes multiple versions of the same classification or guideline system, "
        "extract criteria from the most recent version only and state that version year in criteria_summary."
    )


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

QUERY_TEMPLATES = {
    "classification": "{core} classification criteria categories site:radiopaedia.org",
}

QUERY_FALLBACKS = {
    "classification": "{core} classification imaging criteria categories 2015 2024",
}

# uk_pathway / other: topic-first (no quoted NG number). Firecrawl extraction enforces authority.
UK_PATHWAY_PRIMARY_QUERY = "{topic} NHS NICE RCR clinical guideline criteria recommendations"
UK_PATHWAY_FALLBACK_QUERY = "{topic} UK clinical management pathway referral imaging"
OTHER_PRIMARY_QUERY = "{topic} radiology clinical guideline imaging criteria"
OTHER_FALLBACK_QUERY = "{topic} clinical imaging management guidelines"
# After pathway/other misses: PDF often hosts society guidelines.
PDF_GUIDELINE_QUERY = "{topic} clinical guideline filetype:pdf"
# Native pdf category (Firecrawl) — different ranking than filetype: in query; run after filetype pass.
PDF_CATEGORY_QUERY = "{topic} clinical guideline imaging criteria"

# NICE guidance landing (no /chapter/) — thin pages; enrich via map + recommendations chapters.
_NICE_GUIDANCE_LANDING_RE = re.compile(
    r"^https?://(?:www\.)?nice\.org\.uk/guidance/(?:cg|ng|ta|ipg|qs|es|ph|eh|dg|mtg|mpg)\d+/?$",
    re.IGNORECASE,
)
# Number of URLs to request from client.map() when enriching a NICE landing page.
_NICE_MAP_LIMIT = 8
# Timeout (seconds) passed to client.map() — separate from the per-scrape timeout.
_NICE_MAP_TIMEOUT_SEC = 10
# Maximum number of chapter URLs to scrape concurrently after a map call.
_NICE_MAX_CHAPTER_SCRAPES = 3

# PubMed citation page (abstract + metadata); full article may live on PMC.
_PUBMED_PMID_RE = re.compile(
    r"^https?://(?:(?:www\.)?ncbi\.nlm\.nih\.gov/pubmed/|pubmed\.ncbi\.nlm\.nih\.gov/)(\d+)/?$",
    re.IGNORECASE,
)
PMC_IDCONV_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
_IDCONV_TIMEOUT_SEC = 15


def _pubmed_pmid_from_url(url: str) -> Optional[str]:
    u = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    m = _PUBMED_PMID_RE.match(u)
    return m.group(1) if m else None


def _is_pmc_article_url(url: str) -> bool:
    return "pmc.ncbi.nlm.nih.gov/articles/" in url.lower()


async def _fetch_pmcid_for_pmid(pmid: str) -> Optional[str]:
    """
    Map PMID → PMCID (e.g. PMC13034689) via NCBI PMC idconv API when the article is in PMC.
    """
    import aiohttp

    params: dict = {
        "ids": pmid,
        "format": "json",
        "idtype": "pmid",
        "tool": "rapid_reports_ai",
    }
    email = os.environ.get("NCBI_EMAIL", "").strip()
    if email:
        params["email"] = email
    try:
        timeout = aiohttp.ClientTimeout(total=_IDCONV_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PMC_IDCONV_URL, params=params) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except Exception as exc:
        print(f"[GUIDELINE_PIPELINE] PMC idconv request failed pmid={pmid}: {type(exc).__name__}: {exc}")
        return None
    recs = data.get("records") if isinstance(data, dict) else None
    if not recs or not isinstance(recs, list):
        return None
    r0 = recs[0]
    if not isinstance(r0, dict):
        return None
    if r0.get("status") == "error":
        print(
            f"[GUIDELINE_PIPELINE] PMC idconv no full-text host pmid={pmid}: "
            f"{r0.get('errmsg', 'unknown')}"
        )
        return None
    pmcid = r0.get("pmcid")
    if not pmcid or not isinstance(pmcid, str):
        return None
    s = pmcid.strip()
    return s if s.upper().startswith("PMC") else f"PMC{s}"


def _query_core_classification(system: str, search_keywords: Optional[str]) -> str:
    """Quoted canonical name — stable for classification systems (Bosniak, LI-RADS, …)."""
    tail = f" {search_keywords}" if search_keywords else ""
    return f'"{system}"{tail}'.strip()


def topic_line_for_pathway_or_other_search(
    system: str,
    search_keywords: Optional[str],
    context: str,
    *,
    max_chars: int = MAX_TOPIC_SEARCH_CHARS,
) -> str:
    """
    Unquoted topic line for uk_pathway/other web search — avoids mandatory exact system string
    (e.g. wrong or non-verbatim NICE NG numbers). Prefer search_keywords; else system + short context.
    """
    sys_st = system.strip()
    ctx = (context or "").strip()
    if search_keywords and search_keywords.strip():
        base = search_keywords.strip()
    elif ctx:
        c = " ".join(ctx.split())
        if len(c) > max_chars:
            c = c[:max_chars].rsplit(" ", 1)[0]
        base = f"{sys_st} {c}".strip()
    else:
        base = sys_st
    base = " ".join(base.split())
    if len(base) > max_chars:
        base = base[:max_chars].rsplit(" ", 1)[0]
    return base or sys_st


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


def _best_authoritative_from_multiple(
    search_results: "List[Any]",
) -> "Optional[Tuple[str, str]]":
    """
    Collect all authoritative hits across a list of search_data objects (from a parallel gather),
    deduplicate by URL, rank by recency (then length as tie-break), and return the best —
    merging the top two when present.

    Exceptions in the results list (return_exceptions=True) are logged and skipped.
    source_type="society guideline"/"journal publication" rescues hits where is_authoritative
    was conservatively set to False by the Firecrawl extractor.
    """
    # Log any search failures so degraded results are visible in pipeline logs.
    errors = [r for r in search_results if isinstance(r, BaseException)]
    if errors:
        error_types = ", ".join(sorted({type(e).__name__ for e in errors}))
        print(
            f"[GUIDELINE_PIPELINE] _best_authoritative_from_multiple: "
            f"{len(errors)}/{len(search_results)} searches failed ({error_types})"
        )

    hits: List[Tuple[int, int, str, str]] = []
    seen_urls: set = set()
    position: int = 0
    for sd in search_results:
        if sd is None or isinstance(sd, BaseException):
            continue
        for doc in sd.web or []:
            j = getattr(doc, "json", None)
            if not isinstance(j, dict):
                continue
            summary = (j.get("criteria_summary") or "").strip()
            is_auth = bool(j.get("is_authoritative"))
            source_type_val = (j.get("source_type") or "").lower().strip()
            # Rescue: Firecrawl extractor can be overly conservative; accept docs the schema
            # correctly identified as a society guideline or journal publication even when
            # is_authoritative came back False (e.g. sparse PDF metadata, unusual source URL).
            is_rescued = not is_auth and source_type_val in ("society guideline", "journal publication")
            if not ((is_auth or is_rescued) and summary):
                continue
            url = _doc_url(doc)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            url_lower = url.lower()
            if any(p in url_lower for p in _DISQUALIFYING_URL_PATHS):
                print(
                    f"[GUIDELINE_PIPELINE] _best_authoritative_from_multiple SKIP non-protocol URL: {url!r}"
                )
                continue
            if is_rescued:
                print(
                    f"[GUIDELINE_PIPELINE] _best_authoritative_from_multiple source_type RESCUE "
                    f"source_type={source_type_val!r} url={url!r}"
                )
            sc = _recency_score(url, summary)
            hits.append((sc, position, summary, url))
            position += 1
    if not hits:
        return None
    # Primary sort: recency (higher = newer). Secondary: content length (longer = richer) so a
    # thin 2024 update notice doesn't lead over a comprehensive same-year guideline document.
    # Tertiary: discovery order (stable tie-break).
    hits.sort(key=lambda x: (-x[0], -len(x[2]), x[1]))
    _, _, top_text, top_url = hits[0]
    if len(hits) >= 2:
        _, _, second_text, _ = hits[1]
        combined = f"{top_text}\n\nAdditional version criteria:\n{second_text}"
        if len(combined) > MERGED_CRITERIA_MAX_CHARS:
            combined = combined[: MERGED_CRITERIA_MAX_CHARS - 1].rstrip() + "…"
        print(
            f"[GUIDELINE_PIPELINE] _best_authoritative_from_multiple merged 2 hits "
            f"recency_scores=({hits[0][0]}, {hits[1][0]}) combined_chars={len(combined)} "
            f"primary_url={top_url!r}"
        )
        return (combined, top_url)
    return (top_text, top_url)


def _scrape_options(system: str) -> "ScrapeOptions":
    """Default scrape options for HTML web searches — PDF parsing disabled to avoid credit cost."""
    from firecrawl.v2.types import ScrapeOptions

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


def _pdf_scrape_options(system: str) -> "ScrapeOptions":
    """Scrape options for PDF-targeted searches — PDF parsing enabled (no parsers restriction)."""
    from firecrawl.v2.types import ScrapeOptions

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
        # parsers intentionally omitted → Firecrawl default parsers apply, enabling PDF text extraction
    )


async def _maybe_enrich_nice_landing_hit(
    client: Any,
    guideline: ApplicableGuideline,
    hit: Tuple[str, str],
    scrape_opts: "ScrapeOptions",
    *,
    timeout_ms: int,
) -> Tuple[str, str]:
    """If hit is a thin NICE guidance landing page, use Firecrawl map to discover
    recommendation subpages dynamically, then scrape the top candidates concurrently
    and return the richest authoritative result."""
    content, url = hit
    normalized = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    if not _NICE_GUIDANCE_LANDING_RE.match(normalized):
        return hit

    # Discover recommendation subpages via map; fall back to hard-coded candidates.
    chapter_urls: list[str] = []
    try:
        t0 = time.perf_counter()
        map_result = await client.map(
            normalized,
            search="recommendations",
            limit=_NICE_MAP_LIMIT,
            timeout=_NICE_MAP_TIMEOUT_SEC,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        chapter_urls = [link.url for link in (map_result.links or []) if getattr(link, "url", None)]
        print(
            f"[GUIDELINE_PIPELINE] NICE map found {len(chapter_urls)} candidate(s) "
            f"for {normalized!r} elapsed_ms={elapsed_ms:.0f}"
        )
    except Exception as exc:
        print(
            f"[GUIDELINE_PIPELINE] NICE map failed for {normalized!r}: "
            f"{type(exc).__name__}: {exc} — falling back to hard-coded candidates"
        )

    if not chapter_urls:
        chapter_urls = [
            f"{normalized}/chapter/recommendations",
            f"{normalized}/chapter/Recommendations",
            f"{normalized}/chapter/1-Recommendations",
        ]

    base_len = len((content or "").strip())

    async def _scrape_chapter(chapter_url: str) -> "Tuple[str, str] | None":
        try:
            print(f"[GUIDELINE_PIPELINE] NICE chapter enrichment try {chapter_url!r}")
            t0 = time.perf_counter()
            doc = await client.scrape(
                chapter_url,
                formats=scrape_opts.formats,
                only_main_content=scrape_opts.only_main_content,
                max_age=scrape_opts.max_age,
                proxy=scrape_opts.proxy,
                parsers=scrape_opts.parsers,
                timeout=timeout_ms,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            j = getattr(doc, "json", None)
            if not isinstance(j, dict):
                print(
                    f"[GUIDELINE_PIPELINE] NICE chapter enrichment no json "
                    f"elapsed_ms={elapsed_ms:.0f}"
                )
                return None
            summary = (j.get("criteria_summary") or "").strip()
            if not (j.get("is_authoritative") and summary):
                return None
            print(
                f"[GUIDELINE_PIPELINE] NICE chapter enrichment hit "
                f"criteria_chars={len(summary)} url={chapter_url!r} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return (summary, chapter_url)
        except Exception as exc:
            print(
                f"[GUIDELINE_PIPELINE] NICE chapter enrichment skip {chapter_url!r}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    # Scrape top N candidates concurrently and pick the longest authoritative result.
    candidates = chapter_urls[:_NICE_MAX_CHAPTER_SCRAPES]
    results = await asyncio.gather(*[_scrape_chapter(u) for u in candidates])
    best: "Tuple[str, str] | None" = None
    for r in results:
        if r is None:
            continue
        summary, chapter_url = r
        if len(summary) > base_len and (best is None or len(summary) > len(best[0])):
            best = r

    if best:
        print(
            f"[GUIDELINE_PIPELINE] NICE chapter enrichment REPLACE "
            f"criteria_chars={len(best[0])} url={best[1]!r}"
        )
        return best
    return hit


async def _maybe_enrich_pubmed_pmc_hit(
    client: Any,
    guideline: ApplicableGuideline,
    hit: Tuple[str, str],
    scrape_opts: "ScrapeOptions",
    *,
    timeout_ms: int,
) -> Tuple[str, str]:
    """If hit URL is PubMed and the article exists in PMC, scrape PMC HTML for fuller guideline text."""
    content, url = hit
    if _is_pmc_article_url(url):
        return hit
    pmid = _pubmed_pmid_from_url(url)
    if not pmid:
        return hit
    pmcid = await _fetch_pmcid_for_pmid(pmid)
    if not pmcid:
        return hit
    pmc_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    base_len = len((content or "").strip())
    try:
        print(
            f"[GUIDELINE_PIPELINE] PubMed→PMC enrichment scrape {pmc_url!r} "
            f"(pmid={pmid} prior_chars={base_len})"
        )
        t0 = time.perf_counter()
        doc = await client.scrape(
            pmc_url,
            formats=scrape_opts.formats,
            only_main_content=scrape_opts.only_main_content,
            max_age=scrape_opts.max_age,
            proxy=scrape_opts.proxy,
            parsers=scrape_opts.parsers,
            timeout=timeout_ms,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        j = getattr(doc, "json", None)
        if not isinstance(j, dict):
            print(
                f"[GUIDELINE_PIPELINE] PubMed→PMC enrichment no json "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return hit
        summary = (j.get("criteria_summary") or "").strip()
        if not (j.get("is_authoritative") and summary):
            print(
                f"[GUIDELINE_PIPELINE] PubMed→PMC enrichment not authoritative or empty "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return hit
        if len(summary) >= base_len:
            print(
                f"[GUIDELINE_PIPELINE] PubMed→PMC enrichment REPLACE "
                f"criteria_chars={len(summary)} url={pmc_url!r} "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            return (summary, pmc_url)
    except Exception as exc:
        print(
            f"[GUIDELINE_PIPELINE] PubMed→PMC enrichment skip {pmc_url!r}: "
            f"{type(exc).__name__}: {exc}"
        )
    return hit


async def _enrich_fetched_hit(
    client: Any,
    guideline: ApplicableGuideline,
    hit: Tuple[str, str],
    scrape_opts: "ScrapeOptions",
    *,
    timeout_ms: int,
) -> Tuple[str, str]:
    """NICE chapter depth, then PubMed→PMC full text when available."""
    hit = await _maybe_enrich_nice_landing_hit(
        client, guideline, hit, scrape_opts, timeout_ms=timeout_ms
    )
    hit = await _maybe_enrich_pubmed_pmc_hit(
        client, guideline, hit, scrape_opts, timeout_ms=timeout_ms
    )
    return hit


def _web_result_count(search_data: Any) -> int:
    return len(search_data.web or [])


def _log_fetch_hit(hit: Tuple[str, str], _fetch_t0: float, label: str) -> None:
    _ms = (time.perf_counter() - _fetch_t0) * 1000.0
    print(
        f"[GUIDELINE_PIPELINE] fetch_guideline HIT authoritative ({label}) "
        f"criteria_chars={len(hit[0])} url={hit[1]!r} total_elapsed_ms={_ms:.0f}"
    )


async def fetch_guideline(guideline: ApplicableGuideline) -> Optional[Tuple[str, str]]:
    t = guideline.type
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

    scrape_opts = _scrape_options(guideline.system)
    pdf_scrape_opts = _pdf_scrape_options(guideline.system)
    _fetch_t0 = time.perf_counter()

    core: Optional[str] = None
    topic: Optional[str] = None
    if t == "classification":
        core = _query_core_classification(guideline.system, guideline.search_keywords)
        print(
            f"[GUIDELINE_PIPELINE] fetch_guideline START system={guideline.system!r} "
            f"type={t!r} query_core={core[:120]!r}{'…' if len(core) > 120 else ''}"
        )
    else:
        topic = topic_line_for_pathway_or_other_search(
            guideline.system,
            guideline.search_keywords,
            guideline.context,
        )
        print(
            f"[GUIDELINE_PIPELINE] fetch_guideline START system={guideline.system!r} "
            f"type={t!r} topic_line={topic[:120]!r}{'…' if len(topic) > 120 else ''}"
        )

    async def run_search(
        query: str,
        *,
        categories: Optional[List[str]] = None,
        location: Optional[str] = None,
        label: str = "",
        timeout_ms: int = SEARCH_TIMEOUT_MS,
        result_limit: int = SEARCH_LIMIT_NARROW,
        scrape_opts_override: "Optional[Any]" = None,
    ) -> Any:
        effective_scrape_opts = scrape_opts_override if scrape_opts_override is not None else scrape_opts
        kw: dict = {
            "limit": result_limit,
            "scrape_options": effective_scrape_opts,
            "timeout": timeout_ms,
        }
        if categories:
            kw["categories"] = categories
        if location:
            kw["location"] = location
        qpv = query[:100]
        qdots = "…" if len(query) > 100 else ""
        pdf_flag = " [pdf_scrape_opts]" if scrape_opts_override is not None else ""
        print(
            f"[GUIDELINE_PIPELINE]   Firecrawl.search [{label}]{pdf_flag} "
            f"categories={categories!r} location={location!r} limit={result_limit} "
            f"query_len={len(query)} query_preview={qpv!r}{qdots}"
        )
        t0 = time.perf_counter()
        # Client-side socket timeout independent of the server-side timeout param (which
        # instructs Firecrawl but does not cancel a stalled HTTP connection). Without this
        # a hanging PDF search blocks asyncio.gather until the outer 50s cap kills the branch.
        client_timeout_sec = (timeout_ms / 1000) + 5.0
        try:
            sd = await asyncio.wait_for(client.search(query, **kw), timeout=client_timeout_sec)
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE]   Firecrawl.search [{label}] → CLIENT TIMEOUT "
                f"elapsed_ms={elapsed_ms:.0f}"
            )
            raise
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        n = _web_result_count(sd)
        print(
            f"[GUIDELINE_PIPELINE]   Firecrawl.search [{label}] → web_results={n} "
            f"elapsed_ms={elapsed_ms:.0f}"
        )
        _log_web_results_perf(sd, label)
        return sd

    hit: Optional[Tuple[str, str]] = None

    # ── classification ───────────────────────────────────────────────────────
    if t == "classification":
        assert core is not None
        q_rp = QUERY_TEMPLATES["classification"].format(core=core)
        q_fb = QUERY_FALLBACKS["classification"].format(core=core)
        print(f"[GUIDELINE_PIPELINE] classification: firing 3 searches in parallel")
        gathered = await asyncio.gather(
            run_search(
                q_rp,
                label="classification web",
                timeout_ms=SEARCH_TIMEOUT_RADIOPAEDIA_MS,
            ),
            run_search(
                q_rp,
                categories=["research"],
                label="classification research",
                timeout_ms=SEARCH_TIMEOUT_RADIOPAEDIA_MS,
            ),
            run_search(
                q_fb,
                label="classification fallback",
                result_limit=SEARCH_LIMIT_BROAD,
            ),
            return_exceptions=True,
        )
        hit = _best_authoritative_from_multiple(list(gathered))
        if hit:
            hit = await _enrich_fetched_hit(
                client, guideline, hit, scrape_opts, timeout_ms=SEARCH_TIMEOUT_MS
            )
            _log_fetch_hit(hit, _fetch_t0, "classification [parallel]")
        else:
            _ms = (time.perf_counter() - _fetch_t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE] fetch_guideline MISS (no authoritative JSON after all attempts) "
                f"total_elapsed_ms={_ms:.0f}"
            )
        return hit

    # ── uk_pathway ───────────────────────────────────────────────────────────
    assert topic is not None
    if t == "uk_pathway":
        loc = "United Kingdom"
        q_primary = UK_PATHWAY_PRIMARY_QUERY.format(topic=topic)
        q_fb = UK_PATHWAY_FALLBACK_QUERY.format(topic=topic)
        q_pdf = PDF_GUIDELINE_QUERY.format(topic=topic)
        q_pdf_cat = PDF_CATEGORY_QUERY.format(topic=topic)
        print(f"[GUIDELINE_PIPELINE] uk_pathway: firing 5 searches in parallel")
        gathered = await asyncio.gather(
            run_search(q_primary, location=loc, label="uk_pathway primary"),
            run_search(
                q_primary,
                location=loc,
                categories=["research"],
                label="uk_pathway research",
            ),
            run_search(
                q_fb,
                location=loc,
                label="uk_pathway fallback",
                result_limit=SEARCH_LIMIT_BROAD,
            ),
            run_search(
                q_pdf,
                label="uk_pathway pdf filetype",
                result_limit=SEARCH_LIMIT_NARROW,
                scrape_opts_override=pdf_scrape_opts,
            ),
            run_search(
                q_pdf_cat,
                categories=["pdf"],
                label="uk_pathway pdf category",
                result_limit=SEARCH_LIMIT_NARROW,
                scrape_opts_override=pdf_scrape_opts,
            ),
            return_exceptions=True,
        )
        hit = _best_authoritative_from_multiple(list(gathered))
        if hit:
            hit = await _enrich_fetched_hit(
                client, guideline, hit, scrape_opts, timeout_ms=SEARCH_TIMEOUT_MS
            )
            _log_fetch_hit(hit, _fetch_t0, "uk_pathway [parallel]")
            return hit
        _ms = (time.perf_counter() - _fetch_t0) * 1000.0
        print(
            f"[GUIDELINE_PIPELINE] fetch_guideline MISS (no authoritative JSON after all attempts) "
            f"total_elapsed_ms={_ms:.0f}"
        )
        return None

    # ── other ────────────────────────────────────────────────────────────────
    q_o = OTHER_PRIMARY_QUERY.format(topic=topic)
    q_of = OTHER_FALLBACK_QUERY.format(topic=topic)
    q_pdf = PDF_GUIDELINE_QUERY.format(topic=topic)
    q_pdf_cat = PDF_CATEGORY_QUERY.format(topic=topic)
    print(f"[GUIDELINE_PIPELINE] other: firing 5 searches in parallel")
    gathered = await asyncio.gather(
        run_search(q_o, label="other primary"),
        run_search(q_o, categories=["research"], label="other research"),
        run_search(
            q_of,
            label="other fallback",
            result_limit=SEARCH_LIMIT_BROAD,
        ),
        run_search(
            q_pdf,
            label="other pdf filetype",
            result_limit=SEARCH_LIMIT_NARROW,
            scrape_opts_override=pdf_scrape_opts,
        ),
        run_search(
            q_pdf_cat,
            categories=["pdf"],
            label="other pdf category",
            result_limit=SEARCH_LIMIT_NARROW,
            scrape_opts_override=pdf_scrape_opts,
        ),
        return_exceptions=True,
    )
    hit = _best_authoritative_from_multiple(list(gathered))
    if hit:
        hit = await _enrich_fetched_hit(
            client, guideline, hit, scrape_opts, timeout_ms=SEARCH_TIMEOUT_MS
        )
        _log_fetch_hit(hit, _fetch_t0, "other [parallel]")
        return hit
    _ms = (time.perf_counter() - _fetch_t0) * 1000.0
    print(
        f"[GUIDELINE_PIPELINE] fetch_guideline MISS (no authoritative JSON after all attempts) "
        f"total_elapsed_ms={_ms:.0f}"
    )
    return None


async def _fetch_guideline_via_tavily(
    guideline: ApplicableGuideline,
) -> Optional[Tuple[str, str]]:
    """
    Tavily-based fetch path for ensure_guideline_cached.
    Uses Tavily Search (advanced depth) to discover the authoritative URL, then Tavily Extract
    to pull the full content. Returns (content, source_url) or None on failure.
    """
    import os as _os
    tavily_key = _os.getenv("TAVILY_API_KEY", "")
    if not tavily_key:
        print("[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: TAVILY_API_KEY not set, skipping")
        return None

    try:
        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(tavily_key)
    except ImportError:
        print("[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: tavily not installed, skipping")
        return None

    # Build a targeted search query from the guideline
    kw = " ".join(guideline.search_keywords[:4]) if guideline.search_keywords else ""
    query = f"{guideline.system} {kw}".strip()
    if guideline.type == "classification":
        query = f"UK {query} classification criteria thresholds management"
    else:
        query = f"UK {query} guideline recommendations pathway"

    _t0 = time.perf_counter()
    try:
        # Stage 1: Tavily Search to discover authoritative URL
        search_resp = await asyncio.wait_for(
            client.search(
                query=query,
                search_depth="advanced",
                max_results=3,
                chunks_per_source=3,
                include_domains=[
                    "nice.org.uk", "rcr.ac.uk", "bsr.org.uk", "sign.ac.uk",
                    "brit-thoracic.org.uk", "eshre.eu", "esc.int", "acr.org",
                    "rsna.org", "gov.uk", "nhs.uk",
                ],
            ),
            timeout=18.0,
        )
        results = search_resp.get("results", [])
        if not results:
            print(f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: no search results for {guideline.system!r}")
            return None

        # Pick the top URL
        top_url = results[0].get("url", "")
        # Use inline content if available and substantial
        inline_content = results[0].get("content", "")
        if top_url and inline_content and len(inline_content) > 400:
            _ms = (time.perf_counter() - _t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: inline hit "
                f"url={top_url!r} chars={len(inline_content)} elapsed_ms={_ms:.0f}"
            )
            return (inline_content, top_url)

        # Stage 2: Tavily Extract for full content
        if top_url:
            extract_resp = await asyncio.wait_for(
                client.extract(urls=[top_url]),
                timeout=18.0,
            )
            ext_results = extract_resp.get("results", [])
            if ext_results:
                raw_content = ext_results[0].get("raw_content", "") or ""
                if len(raw_content) > 400:
                    _ms = (time.perf_counter() - _t0) * 1000.0
                    print(
                        f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: extract hit "
                        f"url={top_url!r} chars={len(raw_content)} elapsed_ms={_ms:.0f}"
                    )
                    return (raw_content[:8000], top_url)

        print(f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: no usable content for {guideline.system!r}")
        return None

    except asyncio.TimeoutError:
        _ms = (time.perf_counter() - _t0) * 1000.0
        print(f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: TIMEOUT elapsed_ms={_ms:.0f}")
        return None
    except Exception as exc:
        _ms = (time.perf_counter() - _t0) * 1000.0
        print(
            f"[GUIDELINE_PIPELINE] _fetch_guideline_via_tavily: EXCEPTION "
            f"{type(exc).__name__}: {exc!s} elapsed_ms={_ms:.0f}"
        )
        return None


async def ensure_guideline_cached(
    guideline: ApplicableGuideline,
    db: Session,
) -> GuidelineResolution:
    """
    Fetch and cache a guideline for audit context injection.

    Cache hierarchy (guideline_cache table dropped — now uses in-process session cache):
      1. Module-level in-memory cache (_GUIDELINE_SESSION_CACHE) — avoids re-fetching within
         the same server process. TTL mirrors the old DB success expiry.
      2. Tavily Search + Extract — primary fetch path (cheap, no Firecrawl credit burn).
      3. Firecrawl — fallback if Tavily returns no usable content.
    """
    print(f"[GUIDELINE_PIPELINE] ensure_guideline_cached ENTER system={guideline.system!r}")
    if len(guideline.system) > MAX_GUIDELINE_SYSTEM_LEN:
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached SKIP system too long "
            f"len={len(guideline.system)}"
        )
        return GuidelineResolution(None, None, False)

    # ── In-process session cache (replaces guideline_cache DB table) ──────────
    _cache_key = guideline.system.lower().strip()
    _cached = _GUIDELINE_SESSION_CACHE.get(_cache_key)
    if _cached is not None:
        content, source_url, expires_ts = _cached
        if time.time() < expires_ts:
            if content:
                print(
                    f"[GUIDELINE_PIPELINE] ensure_guideline_cached SESSION HIT "
                    f"content_chars={len(content)} source_url={source_url!r}"
                )
                return GuidelineResolution(content, source_url, True)
            # Cached miss — skip within TTL window
            print(
                f"[GUIDELINE_PIPELINE] ensure_guideline_cached SESSION MISS SKIP "
                f"system={guideline.system!r}"
            )
            return GuidelineResolution(None, None, False)
        # Expired entry — remove and re-fetch
        del _GUIDELINE_SESSION_CACHE[_cache_key]
    # ──────────────────────────────────────────────────────────────────────────

    print(
        f"[GUIDELINE_PIPELINE] ensure_guideline_cached FETCH wait_timeout={FETCH_TIMEOUT_SECONDS}s"
    )
    _ensure_fetch_t0 = time.perf_counter()
    _fetch_error_kind: Optional[str] = None

    # Primary path: Tavily → Firecrawl fallback
    result = None
    _tavily_result = await _fetch_guideline_via_tavily(guideline)
    if _tavily_result is not None:
        _fetch_ms = (time.perf_counter() - _ensure_fetch_t0) * 1000.0
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached Tavily fetch OK "
            f"elapsed_ms={_fetch_ms:.0f}"
        )
        result = _tavily_result
    else:
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached Tavily miss → falling back to Firecrawl"
        )
        try:
            result = await asyncio.wait_for(
                fetch_guideline(guideline),
                timeout=FETCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            _fetch_ms = (time.perf_counter() - _ensure_fetch_t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE] ensure_guideline_cached TIMEOUT after {FETCH_TIMEOUT_SECONDS}s: {exc!r} "
                f"elapsed_ms={_fetch_ms:.0f}"
            )
            logger.debug("guideline fetch failed for %r: %s", guideline.system, exc)
            result = None
            _fetch_error_kind = "timeout"
        except Exception as exc:
            _fetch_ms = (time.perf_counter() - _ensure_fetch_t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE] ensure_guideline_cached EXCEPTION: "
                f"{type(exc).__name__}: {exc!s} elapsed_ms={_fetch_ms:.0f}"
            )
            logger.debug("guideline fetch failed for %r: %s", guideline.system, exc)
            result = None
            _fetch_error_kind = "exception"
        else:
            _fetch_ms = (time.perf_counter() - _ensure_fetch_t0) * 1000.0
            print(
                f"[GUIDELINE_PIPELINE] ensure_guideline_cached Firecrawl fetch_guideline finished "
                f"elapsed_ms={_fetch_ms:.0f} ok={result is not None}"
            )

    if result:
        content, source_url = result
        success_days = _success_expiry_days(guideline.type)
        _GUIDELINE_SESSION_CACHE[_cache_key] = (
            content,
            source_url,
            time.time() + success_days * 86400,
        )
        cc = (content or "").strip()
        print(
            f"[GUIDELINE_PIPELINE] ensure_guideline_cached CACHE STORED "
            f"content_chars={len(cc)} ttl_days={success_days} source_url={source_url!r}"
        )
        return GuidelineResolution(cc, source_url or None, bool(cc))

    # Cache the miss with a short TTL to avoid hammering APIs on every audit
    _miss_ttl = (
        EXPIRY_UNAVAILABLE_HOURS_TRANSIENT * 3600
        if _fetch_error_kind
        else EXPIRY_UNAVAILABLE_DAYS_GENUINE_MISS * 86400
    )
    _GUIDELINE_SESSION_CACHE[_cache_key] = (None, None, time.time() + _miss_ttl)
    unavailable_reason = f"search_{_fetch_error_kind}" if _fetch_error_kind else "no_authoritative_result"
    print(
        f"[GUIDELINE_PIPELINE] ensure_guideline_cached MISS stored "
        f"reason={unavailable_reason!r} system={guideline.system!r}"
    )
    return GuidelineResolution(None, None, False)
