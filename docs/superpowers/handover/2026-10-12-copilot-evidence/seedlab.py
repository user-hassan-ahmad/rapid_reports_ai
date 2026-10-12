"""Seed fetch lab (Task 12): full resolve + synchronous fill per seed into the LOCAL dev registry; records entries,
chunks, latencies and Jev scores for a hand read. Curated sources for systems whose criteria live in ACR PDFs."""
import asyncio, json, os, sys, time, logging
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv; load_dotenv('/Users/hassan/Code/rapid_reports_ai/backend/.env')
assert 'localhost' in os.environ['DATABASE_URL']
logging.basicConfig(level=logging.WARNING)
logging.getLogger("rapid_reports_ai.hybrid_stack.copilot.fetch").setLevel(logging.DEBUG)
from rapid_reports_ai.database import SessionLocal
from rapid_reports_ai.hybrid_stack.copilot import fetch as F, search as S, registry as R
from rapid_reports_ai.hybrid_stack.copilot.types import Card
from seeds import SEEDS
D = os.path.dirname(__file__) + "/"
CURATED = {"O-RADS US": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC11392681"],
           "LI-RADS CT/MRI": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC6368120", "https://pmc.ncbi.nlm.nih.gov/articles/PMC9476877"]}
_real_search = S._search
CURRENT = {"name": ""}
async def _search(q):
    out = await _real_search(q)
    for u in CURATED.get(CURRENT["name"], []):
        out = [{"url": u, "title": CURRENT["name"], "score": 0.99, "content": f"{CURRENT['name']} curated source", "domain": "pmc.ncbi.nlm.nih.gov", "snippet": ""}] + out
    return out
S._search = _search
F._spawn_fill = lambda *a, **k: None
async def one(name, ver, pub, branches):
    CURRENT["name"] = name
    card = Card(key=R.make_key(name, ver), name=name, version=ver, finding_id="lab", branch=branches[0], skeleton=branches, publication=pub)
    rec = {"seed": name, "key": card.key}
    with SessionLocal() as db:
        t0 = time.perf_counter(); e = await F.resolve_guideline(db, card); rec["first_ms"] = int((time.perf_counter()-t0)*1000)
    t0 = time.perf_counter()
    await F._fill(card, F.to_fill(branches, e.content) if e else branches[1:]); rec["fill_ms"] = int((time.perf_counter()-t0)*1000)
    with SessionLocal() as db:
        row = R.by_key(db, card.key)
        rec["entry"] = R.entry(row).model_dump() if row else None
        rec["chunks"] = row.chunks if row else []
    json.dump(rec, open(D + f"seed_{card.key.replace('@','_').replace('/','-')}_{os.getpid()}.json", "w"), indent=1, default=str)
    st = {b["name"]: (b["state"], len(b["outputs"]), bool(b["rule"])) for b in (rec["entry"] or {}).get("content", {}).get("branches", [])}
    print(f"{name:28} first={rec['first_ms']}ms fill={rec['fill_ms']}ms {st}", flush=True)
    return rec
async def main():
    with SessionLocal() as db:   # fresh registry for the lab keys
        for n, v, *_ in SEEDS:
            row = R.by_key(db, R.make_key(n, v))
            if row: db.delete(row)
        db.commit()
    for s in SEEDS:
        try: await one(*s)
        except Exception as e: print("FAIL", s[0], type(e).__name__, e)
asyncio.run(main())
