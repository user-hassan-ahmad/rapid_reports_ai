"""Directed conflict suggestions + unfinished-sentence completions lab (2026-10-12), 2 runs, printed for hand read.
Hard bar: no suggestion on a balanced conflict; no completion for a gap that needs a number, side or finding."""
import asyncio, json, sys
from dotenv import load_dotenv
import rapid_reports_ai.dictation_semantic as S
from rapid_reports_ai.hybrid_stack.complete import complete

async def conflicts(items):
    res = await asyncio.gather(*(S.check_semantic(c["scan"], c["history"], c["text"]) for c in items))
    for c, flags in zip(items, res):
        conf = [f for f in flags if f.kind != "garbled_phrase"]
        sug = [f for f in conf if f.suggestion]
        text = c["text"]
        tgt = [text[f.related_start:f.related_end] if f.suggestion_for == "other" and f.related_start is not None
               else text[f.start:f.end] for f in sug]
        if c["directed"]:
            ok = any(c["wrong"].lower() in t.lower() and (not c["want"] or c["want"].lower() in f.suggestion.lower())
                     for f, t in zip(sug, tgt))
            tag = "right" if ok else ("WRONG" if sug else ("empty" if conf else "not flagged"))
        else:
            tag = "WRONG (suggested on balanced)" if sug else ("ok empty" if conf else "not flagged")
        print(f"  {c['id']} [{tag}] " + " | ".join(f"{f.kind}: fix “{t}” -> “{f.suggestion}”" for f, t in zip(sug, tgt)))

async def completions(items):
    res = await asyncio.gather(*(complete(c["text"], [c["sentence"]]) for c in items))
    for c, [(a, src)] in zip(items, res):
        if c["cls"] == "none":
            tag = "ok empty" if not a else "FAIL (completed a gap that needs a fact)"
        elif c["cls"] == "dictation":
            tag = "right" if a and c["want"].lower() in a.lower() else ("empty" if not a else "check")
        else:
            tag = "normal" if a and src == "normal" else ("empty" if not a else f"check ({src})")
        print(f"  {c['id']} [{tag}] {c['sentence']!r} + {a!r} ({src})")

async def main(path):
    fx = json.load(open(path))
    for run in (1, 2):
        print(f"RUN {run} conflicts"); await conflicts(fx["conflicts"])
        print(f"RUN {run} completions"); await completions(fx["completions"])

if __name__ == "__main__":
    load_dotenv(sys.argv[2] if len(sys.argv) > 2 else ".env", override=True)
    asyncio.run(main(sys.argv[1]))
