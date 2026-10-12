"""Garbled-phrase lab: current semantic prompt vs + garbled_phrase kind; 2 runs each."""
import asyncio, json, sys
import rapid_reports_ai.dictation_semantic as S
items = json.load(open(sys.argv[1]))
NEW_KIND = ("- garbled_phrase: words that read as a speech-to-text error and change or obscure what a finding says: "
            "a word that makes no sense in its position, a term broken into sound-alike words, a sound-alike word "
            "that is not a real finding or structure here, or a prefix or negation left attached to the wrong word "
            "(for example to a number). Quote only the garbled words. Not unusual but valid terminology, named signs, "
            "classifications, abbreviations or a deliberate fragment.\n")
BASE = S.SEMANTIC_SYSTEM_PROMPT
NEW = BASE.replace("- unit_anomaly:", NEW_KIND + "- unit_anomaly:").replace(
    "Do NOT report: incomplete or truncated sentences", "Do NOT report: spelling or wording slips that leave the meaning clear, incomplete or truncated sentences")
async def run(prompt):
    S.SEMANTIC_SYSTEM_PROMPT = prompt
    async def one(it):
        return await S.check_semantic("CT", "", it["dictation"])
    return await asyncio.gather(*(one(it) for it in items))
def score(res):
    caught = flagged_clean = 0; wrong_kind = 0
    for it, flags in zip(items, res):
        if it["garble"]:
            hit = [f for f in flags if it["garble"].lower() in f.excerpt.lower() or f.excerpt.lower() in it["dictation"].lower() and any(w in f.excerpt.lower() for w in it["garble"].lower().split())]
            caught += bool(hit)
        else:
            flagged_clean += bool(flags)
            if flags: print("     clean flagged:", it["dictation"][:60], [(f.kind, f.excerpt) for f in flags])
    return caught, flagged_clean
async def main():
    for name, p in (("current", BASE), ("garbled", NEW)):
        for r in range(2):
            res = await run(p)
            c, f = score(res)
            print(f"{name} run{r+1}: garbles caught {c}/13, clean flagged {f}/12")
            if name == "garbled" and r == 0:
                for it, flags in zip(items, res):
                    if it["garble"] and not any(it["garble"].split()[0].lower() in fl.excerpt.lower() for fl in flags):
                        print("     missed:", it["garble"], [(fl.kind, fl.excerpt) for fl in flags])
asyncio.run(main())
