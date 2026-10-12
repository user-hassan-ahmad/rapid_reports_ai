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
TOP_URLS = 4
PAGE_MAX = 16000            # per page cap on a full-page extract; 4 x 16k fits Jev's 6 x 12k windows
MIN_EXTRACT_CHARS = 1500    # a picked page's extract shorter than this reads as failed/paywalled/landing
MIN_SCORE = 0.3            # a relevance floor below top results; if nothing clears it, use what search gave us
SEARCH_TIMEOUT_S = 15.0
EXTRACT_TIMEOUT_S = 55.0    # Tavily's advanced extract is slow on long guideline pages

# Tier 1: publishers and issuing societies. Tier 2: PubMed Central / Europe PMC full text. Tier 3: everything else.
# Tier 4: abstract-only / landing pages (_ABSTRACT) demoted below everything else bar the relevance floor cut.
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
    is_abstract = bool(_ABSTRACT.search(url.lower()))
    if _match_domain(host, TIER2) and not is_abstract:   # PMC / Europe PMC full text; pubmed shares this domain
        return 2                                          # but is caught by is_abstract before it gets here
    if is_abstract:
        return 4
    if _match_domain(host, TIER1):
        return 1
    return 3


def _normalize_phrase(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def _name_phrases(name: str) -> list[str]:
    """The guideline's full name as the phrase(s) an on-topic page must contain: the whole normalised name, plus
    (when it has 3+ tokens, e.g. "BTA U classification") just its first two tokens, since a page naming the short
    form ("BTA U") is still on topic."""
    toks = _normalize_phrase(name).split()
    if not toks:
        return []
    phrases = [" ".join(toks)]
    if len(toks) >= 3:
        phrases.append(" ".join(toks[:2]))
    return phrases


def on_topic(result: dict, name: str) -> bool:
    """Whether a search result is about the named guideline at all, judged on what search already gave us (title +
    the first 1500 chars of its snippet + the URL) rather than another network round trip."""
    phrases = _name_phrases(name)
    if not phrases:
        return True
    haystack = _normalize_phrase(
        f"{result.get('title', '')} {(result.get('content') or '')[:1500]} {result.get('url', '')}")
    return any(p in haystack for p in phrases)


def rank(results: list[dict], name: str = "") -> list[dict]:
    """Sort by tier, then on-topic, then score. When `name` is given, a result that fails the on-topic check never
    ranks better than tier 3 and, within a tier, always sorts behind an on-topic one regardless of score — an
    off-topic tier-1 page (demoted to 3) falls behind an on-topic tier-3 page even if its own score is higher.
    `name=""` makes every result "on topic" so neither effect fires and score alone breaks ties, as before."""
    def key(r: dict) -> tuple[int, int, float]:
        t = tier(r.get("url", ""))
        topic_ok = not name or on_topic(r, name)
        if name and not topic_ok:
            t = max(t, 3)
        return (t, 0 if topic_ok else 1, -float(r.get("score") or 0.0))
    return sorted(results, key=key)


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


async def _extract(urls: list[str]) -> dict[str, str]:
    """Full pages, not snippets: no `query` / `chunks_per_source` — a focused extract was only returning ~2.5-3.5k
    chars (5 snippets) per page, too little for the tables these guidelines live in. Each page is capped at
    PAGE_MAX chars rather than left to Tavily's own limit."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key or not urls:
        return {}
    try:
        from tavily import AsyncTavilyClient
        resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(
            urls=urls, extract_depth="advanced", timeout=EXTRACT_TIMEOUT_S), EXTRACT_TIMEOUT_S + 5)
    except Exception as e:
        logger.warning("[copilot.extract] %s: %s", type(e).__name__, str(e)[:160])
        return {}
    out: dict[str, str] = {}
    for r in resp.get("results", []):
        url = r.get("url", "")
        content = (r.get("raw_content") or "").strip()
        if url and content and not _blocked(content):
            out[url] = content[:PAGE_MAX]
    return out


async def gather(queries: list[str], branch: str, focus: str = "", exclude: set[str] | None = None,
                  name: str = "") -> tuple[list[Chunk], list[Source]]:
    """Search every query in parallel, dedupe by canonical URL, drop any URL already in the registry (`exclude`),
    keep only results above the relevance floor, rank by source tier (an off-topic result demoted to no better
    than tier 3 when `name` is given; `name=""` skips the on-topic check entirely), extract the top URLs as full
    pages. Any picked page whose extract comes back under MIN_EXTRACT_CHARS (failed/paywalled/landing) is swapped,
    in one extra extract round, for the next ranked candidate not yet tried; a page that didn't make the cut keeps
    its own search snippet when its replacement yields no text either. `focus` is kept for callers — full pages
    are read now, so it no longer steers the extract."""
    exclude = exclude or set()
    found: dict[str, dict] = {}
    for results in await asyncio.gather(*(_search(q) for q in queries)):
        for r in results:
            if r["url"] in exclude:
                continue
            found.setdefault(_canon(r["url"]), r)
    ranked = rank(_above_floor(list(found.values())), name)
    top = ranked[:TOP_URLS]
    if not top:
        return [], []
    extracted = await _extract([r["url"] for r in top])
    short = [r for r in top if len(extracted.get(r["url"], "")) < MIN_EXTRACT_CHARS]
    if short:
        tried = {r["url"] for r in top}
        replacements = [r for r in ranked if r["url"] not in tried][:len(short)]
        replaced = set()
        if replacements:
            refill = await _extract([r["url"] for r in replacements])
            for old, new in zip(short, replacements):
                new_text = refill.get(new["url"]) or ""
                if new_text.strip():   # the replacement yielded text; otherwise `old` keeps its spot and snippet
                    top[top.index(old)] = new
                    extracted[new["url"]] = new_text
                    replaced.add(old["url"])
        for r in short:   # any short page not successfully replaced falls back to its own search snippet, not the
            if r["url"] not in replaced:   # too-short extract text it came back with
                extracted.pop(r["url"], None)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks, sources = [], []
    for r in top:
        text = extracted.get(r["url"]) or r.get("content") or ""
        if text.strip():
            chunks.append(Chunk(url=r["url"], text=text, branch=branch))
            sources.append(Source(url=r["url"], title=r.get("title", ""), tier=tier(r["url"]), fetched_at=now))
    return chunks, sources
