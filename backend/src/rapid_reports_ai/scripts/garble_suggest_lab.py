"""Garble suggestion + blocking lab (2026-10-12): the shipped semantic prompt, 2 runs over the garble fixture.
Per garble: caught; suggestion right / empty / WRONG (a wrong suggestion is the failure that matters); blocking
matches the label (None = either). Clean dictations: any flag is a false positive."""
import asyncio, json, sys
from dotenv import load_dotenv
import rapid_reports_ai.dictation_semantic as S

def norm(s): return " ".join(s.lower().replace("-", " ").split())

async def main(path, runs=2):
    items = json.load(open(path))
    for r in range(runs):
        res = await asyncio.gather(*(S.check_semantic("CT", "", it["dictation"]) for it in items))
        caught = right = empty = wrong = bok = bbad = fp = 0
        for it, flags in zip(items, res):
            if not it["garble"]:
                if flags:
                    fp += 1
                    print("   clean flagged:", it["dictation"][:60], [(f.kind, f.excerpt, f.blocking) for f in flags])
                continue
            hit = next((f for f in flags if f.kind == "garbled_phrase" and any(w in norm(f.excerpt) for w in norm(it["garble"]).split())), None)
            if not hit:
                print("   missed:", it["garble"], [(f.kind, f.excerpt) for f in flags]); continue
            caught += 1
            # The suggestion replaces the quote: score the phrase it produces.
            s = norm(hit.suggestion)
            fixed = norm(it["garble"]).replace(norm(hit.excerpt), s) if s else ""
            if not s: empty += 1; tag = "empty" + (" (ok)" if "" in it["suggestion_ok"] else "")
            elif any(o and norm(o) in fixed for o in it["suggestion_ok"]): right += 1; tag = "right"
            else: wrong += 1; tag = "WRONG"
            if it["blocking"] is None or hit.blocking == it["blocking"]: bok += 1
            else: bbad += 1; tag += f" blocking={hit.blocking}"
            print(f"   {it['garble']!r:30} -> {hit.excerpt!r} suggestion={hit.suggestion!r} [{tag}]")
        print(f"run{r+1}: caught {caught}/13 · suggestion right {right}, empty {empty}, WRONG {wrong} · "
              f"blocking ok {bok}, wrong {bbad} · clean flagged {fp}/12")

if __name__ == "__main__":
    load_dotenv(sys.argv[2] if len(sys.argv) > 2 else ".env", override=True)
    asyncio.run(main(sys.argv[1]))
