"""Unfinished-sentence lab (2026-10-12): two Jev wordings, 2 runs. Each sentence is asked inside a mixed dictation
block (as the scratchpad asks it); reports the score spread per class and the best threshold."""
import asyncio, json, os, random, sys
from dotenv import load_dotenv
from rapid_reports_ai.jev_client import JEV_MODEL, jev_post

WORDINGS = {
 "A": ("SENTENCE stops before its statement is complete: it ends on a word that needs more after it (a verb, "
       "preposition, conjunction or article), a measurement or comparison is left without its value, or it runs "
       "straight into another statement or heading with the first left unfinished. A short deliberate fragment that "
       "states a complete finding, a sweeping remark or a heading on its own is not unfinished. SENTENCE: {s}"),
 "B": ("The radiologist stopped SENTENCE before finishing what it says, or it runs into another statement with the "
       "first left incomplete. A short complete fragment or a heading is finished. SENTENCE: {s}"),
}

async def ask(block, wording):
    qs = {f"u{i}": {"type": "noul", "instructions": WORDINGS[wording].format(s=s)} for i, s in enumerate(block)}
    r = await jev_post({"model": JEV_MODEL, "state": "DICTATION:\n" + "\n".join(block), "questions": qs},
                       os.environ.get("OPENROUTER_API_KEY", ""), 8.0)
    r.raise_for_status()
    a = r.json().get("answers") or {}
    return [float((a.get(f"u{i}") or {}).get("noul") or 0.0) for i in range(len(block))]

async def main(path):
    fx = json.load(open(path))
    items = [(s, True) for s in fx["unfinished"]] + [(s, False) for s in fx["finished"]]
    random.Random(7).shuffle(items)
    blocks = [items[i:i + 10] for i in range(0, len(items), 10)]
    for w in WORDINGS:
        for run in (1, 2):
            scores = await asyncio.gather(*(ask([s for s, _ in b], w) for b in blocks))
            res = [(s, u, sc) for b, bs in zip(blocks, scores) for (s, u), sc in zip(b, bs)]
            un = sorted(sc for _, u, sc in res if u); fi = sorted(sc for _, u, sc in res if not u)
            best = max((t / 20 for t in range(1, 20)), key=lambda t: sum(x >= t for x in un) + sum(x < t for x in fi))
            print(f"{w} run{run}: unfinished min {un[0]:.2f} median {un[len(un)//2]:.2f} | finished max {fi[-1]:.2f} | "
                  f"best t={best:.2f}: caught {sum(x >= best for x in un)}/{len(un)}, false {sum(x >= best for x in fi)}/{len(fi)}")
            for s, u, sc in sorted(res, key=lambda x: -x[2]):
                if (u and sc < best) or (not u and sc >= 0.3):
                    print(f"     {'MISS' if u else 'FALSE'} {sc:.2f} {s}")

if __name__ == "__main__":
    load_dotenv(sys.argv[2] if len(sys.argv) > 2 else ".env", override=True)
    asyncio.run(main(sys.argv[1]))
