"""Arm B: demote abstract pages, + body query, extract top 4 full pages (cap 20k each), society domains fixed."""
import asyncio, json, os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv('/Users/hassan/Code/rapid_reports_ai/backend/.env')
from rapid_reports_ai.hybrid_stack.copilot import search as S, jev as J
from seeds import SEEDS
D = os.path.dirname(__file__) + "/"
TOP, PAGE_MAX = 4, 16000
BODY_DOMAINS = {"american college of radiology": "acr.org", "european society of endocrinology": "ese-hormones.org", "british thyroid association": "british-thyroid-association.org", "fleischner society": "rsna.org", "society of abdominal radiology": "rsna.org"}
EXTRA_T1 = {"ese-hormones.org", "british-thyroid-association.org"}
ABSTRACT = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov|/doi/abs/|/abstract\b|scholars\.|researchgate\.net")
def tier(url):
    if ABSTRACT.search(url): return 4
    host = (url.split("/")[2] if "//" in url else url).lower()
    if any(host == d or host.endswith("." + d) for d in EXTRA_T1): return 1
    return S.tier(url)
def _n(x): return " ".join(re.sub(r"[^a-z0-9]+"," ",(x or "").lower()).split())
def on_topic(r, name):
    head = _n(r.get("title","") + " " + (r.get("content") or "")[:1500] + " " + r["url"])
    toks = [t for t in _n(name).split() if len(t) > 2] or _n(name).split()
    return toks[0] in head
def rank(rs, name): return sorted(rs, key=lambda r: (tier(r["url"]) if on_topic(r, name) else max(3, tier(r["url"])), -float(r.get("score") or 0)))
async def search_dom(q, domain):
    from tavily import AsyncTavilyClient
    try:
        resp = await asyncio.wait_for(AsyncTavilyClient(os.environ.get("TAVILY_API_KEY","")).search(query=q, search_depth="basic", max_results=5, include_domains=[domain]), 15)
        return S._normalize_tavily_results(resp)
    except Exception as e: print("dom search fail", e); return []
async def extract_full(urls):
    key = os.environ.get("TAVILY_API_KEY", "")
    from tavily import AsyncTavilyClient
    resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(urls=urls, extract_depth="advanced"), 60)
    return {r.get("url", ""): (r.get("raw_content") or "").strip()[:PAGE_MAX] for r in resp.get("results", [])}
async def one(name, ver, pub, branches):
    b = branches[0]
    qs = S.first_pass_queries(name, ver, pub, b) + [f"{name} {ver} {pub.body} summary table".replace("  ", " ").strip()]
    found = {}
    results = [await S._search(q) for q in qs]
    dom = BODY_DOMAINS.get(_n(pub.body))
    if dom:
        qd = f"{name} {ver} pdf".replace("  "," ").strip(); qs = qs + [f"{qd} @{dom}"]
        results.append(await search_dom(qd, dom))
    for rs in results:
        for r in rs:
            found.setdefault(S._canon(r["url"]), r)
    ranked = rank(S._above_floor(list(found.values())), name)
    top = ranked[:TOP]
    try: ext = await extract_full([r["url"] for r in top])
    except Exception as e: print("extract fail", e); ext = {}
    rows, chunks = [], []
    for r in ranked[:8]:
        e = ext.get(r["url"]) if r in top else None
        rows.append({"url": r["url"], "tier": tier(r["url"]) if on_topic(r, name) else max(3, tier(r["url"])), "score": round(float(r.get("score") or 0), 2), "picked": r in top,
                     "extracted_chars": len(e or "")})
        if r in top: chunks.append(f"[{r['url']}]\n{e or r.get('content') or ''}")
    text = "\n\n".join(chunks)
    cov = await J.coverage(text, [f"{name} {ver}: {x}".strip() for x in branches])
    return {"seed": name, "queries": qs, "candidates": rows, "coverage": {k: round(v, 2) for k, v in cov.items()}, "chars": len(text), "text": text}
async def main(tag):
    out = [await one(*s) for s in SEEDS]
    json.dump(out, open(D + f"{tag}_{os.getpid()}.json", "w"), indent=1)
    for o in out:
        print(f"\n## {o['seed']}  chars={o['chars']}")
        for c in o["candidates"]: print(f"   {'*' if c['picked'] else ' '} t{c['tier']} s{c['score']} ext={c['extracted_chars']:6} {c['url'][:95]}")
        print("   coverage:", o["coverage"])
asyncio.run(main(sys.argv[1]))
