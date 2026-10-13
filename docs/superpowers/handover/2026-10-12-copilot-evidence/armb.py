"""Arm B: demote abstract pages, + body query, extract top 4 full pages (cap 20k each), society domains fixed."""
import asyncio, json, os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv('/Users/hassan/Code/rapid_reports_ai/backend/.env')
from rapid_reports_ai.hybrid_stack.copilot import search as S, jev as J
from seeds import SEEDS
D = os.path.dirname(__file__) + "/"
TOP, PAGE_MAX = 4, 20000
EXTRA_T1 = {"ese-hormones.org", "british-thyroid-association.org"}
ABSTRACT = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov|/doi/abs/|/abstract\b|scholars\.|researchgate\.net")
def tier(url):
    if ABSTRACT.search(url): return 4
    host = (url.split("/")[2] if "//" in url else url).lower()
    if any(host == d or host.endswith("." + d) for d in EXTRA_T1): return 1
    return S.tier(url)
def rank(rs): return sorted(rs, key=lambda r: (tier(r["url"]), -float(r.get("score") or 0)))
async def extract_full(urls):
    key = os.environ.get("TAVILY_API_KEY", "")
    from tavily import AsyncTavilyClient
    resp = await asyncio.wait_for(AsyncTavilyClient(key).extract(urls=urls, extract_depth="advanced"), 60)
    return {r.get("url", ""): (r.get("raw_content") or "").strip()[:PAGE_MAX] for r in resp.get("results", [])}
async def one(name, ver, pub, branches):
    b = branches[0]
    qs = S.first_pass_queries(name, ver, pub, b) + [f"{name} {ver} {pub.body} summary table".replace("  ", " ").strip()]
    found = {}
    for q in qs:
        for r in await S._search(q):
            found.setdefault(S._canon(r["url"]), r)
    ranked = rank(S._above_floor(list(found.values())))
    top = ranked[:TOP]
    try: ext = await extract_full([r["url"] for r in top])
    except Exception as e: print("extract fail", e); ext = {}
    rows, chunks = [], []
    for r in ranked[:8]:
        e = ext.get(r["url"]) if r in top else None
        rows.append({"url": r["url"], "tier": tier(r["url"]), "score": round(float(r.get("score") or 0), 2), "picked": r in top,
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
