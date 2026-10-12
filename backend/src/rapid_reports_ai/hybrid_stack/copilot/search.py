"""Targeted search for one guideline (spec §5.3). Queries are built only from the guideline's identity, publication
and branch names, never from dictated words: the guideline's own vocabulary finds it best, the results serve every
later case, and no patient text reaches the search API."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from ...guideline_prefetch import DOMAIN_FILTER_PATHWAY, _GEO_BLOCK_SIGNATURES, _normalize_tavily_results
from .types import Chunk, Publication, Source

logger = logging.getLogger(__name__)

EXTRACT_FOCUS = "categories, criteria, thresholds, required features, management recommendations"
TOP_URLS = 2
MIN_SCORE = 0.3            # a relevance floor below top results; if nothing clears it, use what search gave us
SEARCH_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 55.0    # Tavily's advanced extract is slow on long guideline pages

# Tier 1: publishers and issuing societies. Tier 2: PubMed Central / Europe PMC full text. Tier 3: everything else.
# www.* variants are covered by the bare domain's suffix match (_match_domain), so they aren't listed twice.
TIER1 = {*DOMAIN_FILTER_PATHWAY, "rsna.org", "acr.org", "ajronline.org", "bir.org.uk", "esur.org",
         "eje.bioscientifica.com", "academic.oup.com", "uicc.org", "thorax.bmj.com",
         "britishthyroidassociation.org", "link.springer.com", "esmo.org", "jacr.org",
         "clinicalradiologyonline.net", "springeropen.com", "ersjournals.com", "esgar.org", "myesr.org",
         "thyroid.org"}
TIER2 = {"ncbi.nlm.nih.gov", "europepmc.org"}


def _clean(s: str) -> str:
    return " ".join(re.sub(r"[·•|]+", " ", s).split())


def first_pass_queries(name: str, version: str, pub: Publication, branch: str) -> list[str]:
    ident = _clean(f"{name} {version}")
    title = pub.title.replace('"', "")
    q1 = f'"{title}" {pub.year}'.strip() if title else f"{ident} classification"
    q2 = _clean(f"{ident} {branch} criteria recommendations")
    return [q1, q2]


def branch_query(name: str, version: str, branch: str) -> str:
    return _clean(f"{name} {version} {branch} recommendations")


def _match_domain(host: str, domains: set[str]) -> bool:
    return host in domains or any(host.endswith("." + d) for d in domains)


def tier(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    if _match_domain(host, TIER1):
        return 1
    if _match_domain(host, TIER2):
        return 2
    return 3


def rank(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda r: (tier(r.get("url", "")), -float(r.get("score") or 0.0)))


def _above_floor(results: list[dict]) -> list[dict]:
    """Keep only results that clear MIN_SCORE; a query that returns nothing relevant still needs *something* to
    rank, so an empty pass after the floor falls back to the unfiltered list rather than dropping everything."""
    kept = [r for r in results if float(r.get("score") or 0.0) >= MIN_SCORE]
    return kept or results


def _canon(url: str) -> str:
    """A dedupe key that treats the same document under different URL spellings as one: lower-cased host, no
    scheme, no fragment, no trailing slash, and NCBI's old www.ncbi.nlm.nih.gov/pmc/ path folded onto the
    pmc.ncbi.nlm.nih.gov host Tavily usually returns."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    path = p.path.rstrip("/")
    if host == "www.ncbi.nlm.nih.gov" and path.startswith("/pmc/articles/"):
        host = "pmc.ncbi.nlm.nih.gov"
        path = path[len("/pmc"):]
    return f"{host}{path}"


def _blocked(text: str) -> bool:
    """A page that answered 200 but served an access-restriction message instead of content (spec reuses the
    prefetch pipeline's geo-block signatures)."""
    probe = text[:600].lower()
    return any(sig in probe for sig in _GEO_BLOCK_SIGNATURES)


async def _search(query: str) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    try:
        from tavily import AsyncTavilyClient
        resp = await asyncio.wait_for(AsyncTavilyClient(key).search(query=query, search_depth="basic", max_results=5),
                                      SEARCH_TIMEOUT_S)
        return _normalize_tavily_results(resp)
    except Exception as e:
        logger.warning("[copilot.search] %s: %s q=%r", type(e).__name__, str(e)[:160], query[:80])
        return []


async def _extract(urls: list[str], query: str = EXTRACT_FOCUS) -> dict[str, str]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key or not urls:
        return {}
    try:
        from tavily import AsyncTavilyClient
        resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(
            urls=urls, query=query, chunks_per_source=5, extract_depth="advanced", timeout=EXTRACT_TIMEOUT_S),
            EXTRACT_TIMEOUT_S + 5)
    except Exception as e:
        logger.warning("[copilot.extract] %s: %s", type(e).__name__, str(e)[:160])
        return {}
    out: dict[str, str] = {}
    for r in resp.get("results", []):
        url = r.get("url", "")
        content = (r.get("raw_content") or "").strip()
        if url and content and not _blocked(content):
            out[url] = content
    return out


async def gather(queries: list[str], branch: str, focus: str = "", exclude: set[str] | None = None,
                  ) -> tuple[list[Chunk], list[Source]]:
    """Search every query in parallel, dedupe by canonical URL, drop any URL already in the registry (`exclude`),
    keep only results above the relevance floor, rank by source tier, extract the top URLs with a branch-focused
    query. A URL whose extract comes back blocked or empty keeps its search content, so one blocked page never
    empties the pass."""
    exclude = exclude or set()
    found: dict[str, dict] = {}
    for results in await asyncio.gather(*(_search(q) for q in queries)):
        for r in results:
            if r["url"] in exclude:
                continue
            found.setdefault(_canon(r["url"]), r)
    top = rank(_above_floor(list(found.values())))[:TOP_URLS]
    if not top:
        return [], []
    extract_query = f"{focus}: {EXTRACT_FOCUS}" if focus else EXTRACT_FOCUS
    extracted = await _extract([r["url"] for r in top], extract_query)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks, sources = [], []
    for r in top:
        text = extracted.get(r["url"]) or r.get("content") or ""
        if text.strip():
            chunks.append(Chunk(url=r["url"], text=text, branch=branch))
            sources.append(Source(url=r["url"], title=r.get("title", ""), tier=tier(r["url"]), fetched_at=now))
    return chunks, sources
