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

from ...guideline_prefetch import DOMAIN_FILTER_PATHWAY, _normalize_tavily_results
from .types import Chunk, Publication, Source

logger = logging.getLogger(__name__)

EXTRACT_FOCUS = "categories, criteria, thresholds, required features, management recommendations"
TOP_URLS = 2
SEARCH_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 30.0

# Tier 1: publishers and issuing societies. Tier 2: PubMed Central full text. Tier 3: everything else.
TIER1 = {*DOMAIN_FILTER_PATHWAY, "pubs.rsna.org", "rsna.org", "acr.org", "www.acr.org", "ajronline.org",
         "www.ajronline.org", "bir.org.uk", "esur.org", "www.esur.org", "eje.bioscientifica.com",
         "academic.oup.com", "uicc.org", "www.uicc.org", "thorax.bmj.com", "britishthyroidassociation.org",
         "www.britishthyroidassociation.org", "link.springer.com", "esmo.org", "www.esmo.org"}
TIER2 = {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov"}


def _clean(s: str) -> str:
    return " ".join(re.sub(r"[·•|]+", " ", s).split())


def first_pass_queries(name: str, version: str, pub: Publication, branch: str) -> list[str]:
    ident = _clean(f"{name} {version}")
    q1 = f'"{pub.title}" {pub.year}'.strip() if pub.title else f"{ident} classification"
    q2 = _clean(f"{ident} {branch} criteria recommendations")
    return [q1, q2]


def branch_query(name: str, version: str, branch: str) -> str:
    return _clean(f"{name} {version} {branch} recommendations")


def tier(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    if host in TIER1 or any(host.endswith("." + d) for d in TIER1):
        return 1
    if host in TIER2:
        return 2
    return 3


def rank(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda r: (tier(r.get("url", "")), -float(r.get("score") or 0.0)))


async def _search(query: str) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    from tavily import AsyncTavilyClient
    try:
        resp = await asyncio.wait_for(AsyncTavilyClient(key).search(query=query, search_depth="basic", max_results=5),
                                      SEARCH_TIMEOUT_S)
        return _normalize_tavily_results(resp)
    except Exception as e:
        logger.warning("[copilot.search] %s: %s q=%r", type(e).__name__, str(e)[:160], query[:80])
        return []


async def _extract(urls: list[str]) -> dict[str, str]:
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key or not urls:
        return {}
    from tavily import AsyncTavilyClient
    try:
        resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(
            urls=urls, query=EXTRACT_FOCUS, chunks_per_source=5, extract_depth="advanced"), EXTRACT_TIMEOUT_S)
    except Exception as e:
        logger.warning("[copilot.extract] %s: %s", type(e).__name__, str(e)[:160])
        return {}
    return {r.get("url", ""): (r.get("raw_content") or "").strip() for r in resp.get("results", []) if r.get("url")}


async def gather(queries: list[str], branch: str) -> tuple[list[Chunk], list[Source]]:
    """Search every query in parallel, rank by source tier, extract the top URLs (focus query). A URL whose extract
    fails keeps its search content, so one blocked page never empties the pass."""
    found: dict[str, dict] = {}
    for results in await asyncio.gather(*(_search(q) for q in queries)):
        for r in results:
            found.setdefault(r["url"], r)
    top = rank(list(found.values()))[:TOP_URLS]
    if not top:
        return [], []
    extracted = await _extract([r["url"] for r in top])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks, sources = [], []
    for r in top:
        text = extracted.get(r["url"]) or r.get("content") or ""
        if text.strip():
            chunks.append(Chunk(url=r["url"], text=text, branch=branch))
            sources.append(Source(url=r["url"], title=r.get("title", ""), tier=tier(r["url"]), fetched_at=now))
    return chunks, sources
