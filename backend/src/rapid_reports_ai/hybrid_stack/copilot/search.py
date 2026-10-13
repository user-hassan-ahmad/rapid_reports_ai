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
from . import jev as J
from .types import Chunk, Publication, Source

logger = logging.getLogger(__name__)

EXTRACT_FOCUS = "categories, criteria, thresholds, required features, management recommendations"
TOP_URLS = 4
PAGE_MAX = J.STATE_MAX - 200   # one page = one Jev window: the "[url]\n" header still fits, so 4 first-pass pages
                               # plus 2 retry pages fill the WINDOW_CAP windows and none is dropped
MIN_EXTRACT_CHARS = 1500    # a picked page's extract shorter than this reads as failed/paywalled/landing
MIN_SCORE = 0.3            # a relevance floor below top results; if nothing clears it, use what search gave us
SEARCH_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 55.0    # Tavily's advanced extract is slow on long guideline pages
REFILL_TIMEOUT_S = 25.0     # the refill round is a second chance, not a second full wait

# Tier 1: publishers and issuing societies. Tier 2: PubMed Central / Europe PMC full text. Tier 3: everything else.
# Tier 4: abstract-only / landing pages (_ABSTRACT), ranked below every other tier; only a result Jev's relevance
# gate finds is not about the guideline ranks lower (rank).
# www.* variants are covered by the bare domain's suffix match (_match_domain), so they aren't listed twice.
TIER1 = {*DOMAIN_FILTER_PATHWAY, "rsna.org", "acr.org", "ajronline.org", "bir.org.uk", "esur.org",
         "eje.bioscientifica.com", "academic.oup.com", "uicc.org", "thorax.bmj.com",
         "ese-hormones.org", "british-thyroid-association.org", "link.springer.com", "esmo.org", "jacr.org",
         "clinicalradiologyonline.net", "springeropen.com", "ersjournals.com", "esgar.org", "myesr.org",
         "thyroid.org"}
TIER2 = {"ncbi.nlm.nih.gov", "europepmc.org"}

# Abstract/landing pages: PubMed's own abstract page (as opposed to PMC full text, which shares its ncbi.nlm.nih.gov
# domain), DOI "abstract" views, institutional profile pages, and ResearchGate. These rank last regardless of tier.
_ABSTRACT = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov|/doi/abs/|/abstract\b|scholars\.|researchgate\.net")


def _clean(s: str) -> str:
    return " ".join(re.sub(r"[·•|]+", " ", s).split())


# The privacy backstop (spec §2.18): a guideline name comes from a model that read the case, so a measurement
# ("2 cm", "45 years") or a side/demographic word in it never reaches the search API. Removal only.
_MEASURE = re.compile(r"\b\d+[- ]?years?[- ]old\b|\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m|ml|kg|years?|yrs?|yo|months?|weeks?)\b",
                      re.I)
_CASEY_WORDS = {"left", "right", "bilateral", "male", "female", "man", "woman", "year-old", "pregnant", "smoker",
                "mr", "mrs", "ms", "he", "she"}
NAME_MAX_WORDS = 8


def _scrub(text: str) -> list[str]:
    """The words of `text` with measurement tokens and side/demographic words dropped; other digits (a year, a
    version) stay."""
    cleaned = _MEASURE.sub(" ", text or "")
    return [w for w in cleaned.split() if w.lower().strip(".,;:()") not in _CASEY_WORDS]


def safe_identity(name: str, version: str) -> tuple[str, str]:
    """(name, version) safe to search: measurement tokens and side/demographic words dropped from the name, the
    name capped at NAME_MAX_WORDS words, the version kept intact. Every query builder goes through this."""
    words = _scrub(name)
    out = " ".join(words[:NAME_MAX_WORDS])
    if out != " ".join((name or "").split()):
        logger.info("[copilot.search] identity scrubbed for search (%d -> %d words)", len((name or "").split()),
                    len(words[:NAME_MAX_WORDS]))
    return out, version


def first_pass_queries(name: str, version: str, pub: Publication, branch: str) -> list[str]:
    name, version = safe_identity(name, version)
    ident = _clean(f"{name} {version}")
    # The title comes from the same model that read the case: scrubbed like the name, but not capped (titles run long).
    title = " ".join(_scrub(pub.title.replace('"', "")))
    q1 = f'"{title}" {pub.year}'.strip() if title else f"{ident} classification"
    q2 = _clean(f"{ident} {branch} criteria recommendations")
    return [q1, q2]


def branch_query(name: str, version: str, branch: str) -> str:
    name, version = safe_identity(name, version)
    return _clean(f"{name} {version} {branch} recommendations")


def _match_domain(host: str, domains: set[str]) -> bool:
    return host in domains or any(host.endswith("." + d) for d in domains)


def tier(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    is_abstract = bool(_ABSTRACT.search(url.lower()))
    if _match_domain(host, TIER2) and not is_abstract:   # PMC / Europe PMC full text; pubmed shares this domain
        return 2                                          # but is caught by is_abstract before it gets here
    if is_abstract:
        return 4
    if _match_domain(host, TIER1):
        return 1
    return 3


def rank(results: list[dict], relevance: dict[str, float] | None = None) -> list[dict]:
    """Sort by tier, then score. With Jev's relevance scores (url -> score), a result scored below J.RELEVANT_MIN is
    not about this guideline and ranks last, after tier 4; without them (no name, or Jev failed) tier and score alone
    decide."""
    def key(r: dict) -> tuple[int, int, float]:
        off = relevance is not None and relevance.get(r.get("url", ""), 1.0) < J.RELEVANT_MIN
        return (int(off), tier(r.get("url", "")), -float(r.get("score") or 0.0))
    return sorted(results, key=key)


async def _relevance(results: list[dict], name: str, version: str, title: str) -> dict[str, float] | None:
    """Jev's relevance gate over every candidate, url -> score; None (no reordering) when there is no name or Jev
    fails."""
    if not name.strip() or not results:
        return None
    try:
        got = await J.relevance(results, name, version, title)
    except Exception as e:
        logger.warning("[copilot.search] relevance gate failed (%s): tier and score order only", type(e).__name__)
        return None
    return {r["url"]: v for r, v in zip(results, got)}


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


async def _extract(urls: list[str], timeout: float = EXTRACT_TIMEOUT_S) -> dict[str, str] | None:
    """Full pages, not snippets: no `query` / `chunks_per_source` — a focused extract was only returning ~2.5-3.5k
    chars (5 snippets) per page, too little for the tables these guidelines live in. Each page is capped at
    PAGE_MAX chars rather than left to Tavily's own limit. None when the call failed or timed out; {} when there
    was nothing to extract or nothing came back."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key or not urls:
        return {}
    try:
        from tavily import AsyncTavilyClient
        resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(
            urls=urls, extract_depth="advanced", timeout=timeout), timeout + 5)
    except Exception as e:
        logger.warning("[copilot.extract] %s: %s", type(e).__name__, str(e)[:160])
        return None
    out: dict[str, str] = {}
    for r in resp.get("results", []):
        url = r.get("url", "")
        content = (r.get("raw_content") or "").strip()
        if url and content and not _blocked(content):
            out[url] = content[:PAGE_MAX]
    return out


async def gather(queries: list[str], branch: str, focus: str = "", exclude: set[str] | None = None,
                  name: str = "", version: str = "", title: str = "", top: int | None = None
                  ) -> tuple[list[Chunk], list[Source]]:
    """Search every query in parallel, dedupe by canonical URL, drop any URL already in the registry (`exclude`),
    keep only results above the relevance floor, rank by source tier with Jev's relevance gate (a result not about
    `name` `version` (`title`) ranks last; `name=""` skips the gate), extract the top URLs (`top`, default TOP_URLS) as full pages.

    A picked page whose extract comes back under MIN_EXTRACT_CHARS (failed/paywalled/landing) is offered, in one
    refill round, the next ranked candidate not yet tried: the replacement is taken only if its extract reaches
    MIN_EXTRACT_CHARS or is longer than the short one. An unreplaced short page keeps whichever is longer, its
    extract or its search snippet. No refill when the first extract call itself failed (Tavily down). `focus` is
    kept for callers — full pages are read now, so it no longer steers the extract."""
    exclude = exclude or set()
    found: dict[str, dict] = {}
    for results in await asyncio.gather(*(_search(q) for q in queries)):
        for r in results:
            if r["url"] in exclude:
                continue
            found.setdefault(_canon(r["url"]), r)
    cands = _above_floor(list(found.values()))
    ranked = rank(cands, await _relevance(cands, name, version, title))
    top = ranked[:TOP_URLS if top is None else top]
    if not top:
        return [], []
    first = await _extract([r["url"] for r in top])
    extracted = dict(first or {})
    short = [r for r in top if len(extracted.get(r["url"], "")) < MIN_EXTRACT_CHARS]
    if short and first is not None:
        tried = {r["url"] for r in top}
        replacements = [r for r in ranked if r["url"] not in tried][:len(short)]
        replaced = set()
        if replacements:
            refill = await _extract([r["url"] for r in replacements], timeout=REFILL_TIMEOUT_S) or {}
            for old, new in zip(short, replacements):
                old_text = extracted.get(old["url"], "")
                new_text = refill.get(new["url"]) or ""
                if new_text.strip() and (len(new_text) >= MIN_EXTRACT_CHARS or len(new_text) > len(old_text)):
                    top[top.index(old)] = new
                    extracted[new["url"]] = new_text
                    replaced.add(old["url"])
        short = [r for r in short if r["url"] not in replaced]
    for r in short:   # an unreplaced short page keeps the longer of its extract and its search snippet
        if len(r.get("content") or "") >= len(extracted.get(r["url"], "")):
            extracted.pop(r["url"], None)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks, sources = [], []
    for r in top:
        text = extracted.get(r["url"]) or r.get("content") or ""
        if text.strip():
            chunks.append(Chunk(url=r["url"], text=text, branch=branch))
            sources.append(Source(url=r["url"], title=r.get("title", ""), tier=tier(r["url"]), fetched_at=now))
    return chunks, sources
