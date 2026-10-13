"""Arm A diagnosis: per seed, the current first pass — URLs, tiers, extract success, chars, and Jev coverage per branch."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv('/Users/hassan/Code/rapid_reports_ai/backend/.env')
from rapid_reports_ai.hybrid_stack.copilot import search as S, jev as J
from seeds import SEEDS
D = os.path.dirname(__file__) + "/"
async def one(name, ver, pub, branches):
    # use the case branch = first skeleton branch, as the first pass would
    b = branches[0]
    qs = S.first_pass_queries(name, ver, pub, b)
    found = {}
    for q in qs:
        for r in await S._search(q):
            found.setdefault(S._canon(r["url"]) if hasattr(S, "_canon") else r["url"], r)
    ranked = S.rank(S._above_floor(list(found.values())) if hasattr(S, "_above_floor") else list(found.values()))
    top = ranked[:S.TOP_URLS]
    ext = await S._extract([r["url"] for r in top], f"{b}: {S.EXTRACT_FOCUS}")
    chunks = []
    rows = []
    for r in ranked[:6]:
        e = ext.get(r["url"]) if r in top else None
        rows.append({"url": r["url"], "tier": S.tier(r["url"]), "score": round(float(r.get("score") or 0), 2),
                     "picked": r in top, "extracted_chars": len(e or ""), "search_chars": len(r.get("content") or "")})
        if r in top:
            chunks.append(f"[{r['url']}]\n{e or r.get('content') or ''}")
    text = "\n\n".join(chunks)
    cov = await J.coverage(text, [f"{name} {ver}: {x}".strip() for x in branches])
    return {"seed": name, "queries": qs, "candidates": rows, "coverage": {k: round(v, 2) for k, v in cov.items()}, "text": text}
async def main(tag):
    out = [await one(*s) for s in SEEDS]
    json.dump(out, open(D + f"{tag}_{os.getpid()}.json", "w"), indent=1)
    for o in out:
        print(f"\n## {o['seed']}  queries={o['queries']}")
        for c in o["candidates"]: print(f"   {'*' if c['picked'] else ' '} t{c['tier']} s{c['score']} ext={c['extracted_chars']:6} srch={c['search_chars']:5} {c['url'][:95]}")
        print("   coverage:", o["coverage"])
asyncio.run(main(sys.argv[1]))
