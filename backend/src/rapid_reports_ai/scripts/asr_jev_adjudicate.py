"""Can Jev choose correctly where the live stream and a second engine disagree on a critical word?

    PYTHONPATH=src python -m rapid_reports_ai.scripts.asr_jev_adjudicate <dir with bakeoff.json, bakeoff2.json>

Result 2026-09-29 (4 captured sessions, 34 decidable disagreements): Jev right 31/34. Every
correct switch to the second engine at ≥ 0.97 (subsegmental, defects, Tarlov); the wrong ones
≤ 0.64 (visualized; "No" → "lumbar"). Switch only at ≥ 0.90 and never when a number, side or
negation would be lost: 100 % on this data (tuned on it; confirm with more sessions)."""
import asyncio, difflib, json, os, sys
from dotenv import load_dotenv; load_dotenv(".env")
from rapid_reports_ai.scripts.asr_bakeoff import normalise, _critical
from rapid_reports_ai.dictation_triage import JEV_MODEL
from rapid_reports_ai.jev_client import jev_post

S = sys.argv[1]
SCAN = {"13-25": "CT chest, abdomen and pelvis with IV contrast", "14-01": "CT chest, abdomen and pelvis with IV contrast",
        "15-20": "CT pulmonary angiogram", "15-23": "MRI lumbar spine without contrast"}
FORMAT = {"slash", "colon", "new", "paragraph", "comma", "full", "stop"}  # Deepgram owns commands
data = {**json.load(open(f"{S}/bakeoff.json")), **json.load(open(f"{S}/bakeoff2.json"))}

def disagreements(live, other):
    sm = difflib.SequenceMatcher(None, live, other, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        a, b = live[i1:i2], other[j1:j2]
        if not any(_critical(w) and w not in FORMAT for w in a + b):
            continue
        if set(a + b) <= FORMAT:
            continue
        yield i1, i2, a, b

async def ask(scan, left, a, b, right):
    sa = " ".join(left + a + right); sb = " ".join(left + b + right)
    body = {"model": JEV_MODEL, "state": {"scan_type": scan, "dictation": " ".join(left + ["[?]"] + right)},
            "questions": {"pick": {"type": "choice",
                                   "instructions": "Which version of this dictated passage is what the radiologist said, "
                                                   "judged by clinical sense for this scan and by the surrounding words?",
                                   "criteria": {"a": sa, "b": sb}}}}
    r = await jev_post(body, os.environ["OPENROUTER_API_KEY"], 10, None)
    ans = r.json()["answers"]["pick"]
    return ans.get("choice") or ans.get("answer"), ans.get("confidence")

async def main():
    tally = {}
    for sess, v in data.items():
        key = next(k for k in SCAN if k in sess); scan = SCAN[key]
        ref = normalise(v["reference"]); live = normalise(v["engines"]["live (deepgram stream)"]["text"])
        for name in ("deepgram-batch", "gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-v3-turbo (groq)"):
            other = normalise(v["engines"][name]["text"])
            for i1, i2, a, b in disagreements(live, other):
                left, right = live[max(0, i1 - 10):i1], live[i2:i2 + 10]
                ref_str = " ".join(ref)
                a_ok = " ".join(left[-4:] + a + right[:4]) in ref_str
                b_ok = " ".join(left[-4:] + b + right[:4]) in ref_str
                if a_ok == b_ok:
                    continue  # neither or both match the script: not a decidable case
                pick, conf = await ask(scan, left, a, b, right)
                right_pick = (pick == "a" and a_ok) or (pick == "b" and b_ok)
                t = tally.setdefault(name, [0, 0, 0])
                t[0] += 1; t[1] += right_pick; t[2] += (not a_ok and pick == "b" and b_ok)
                print(f"  {name:24s} {key}  live {' '.join(a)!r:22s} other {' '.join(b)!r:22s} → Jev {pick} ({conf:.2f}) "
                      f"{'✓' if right_pick else '✗'} (script says {'live' if a_ok else 'other'})")
    print("\nper engine: decidable disagreements / Jev right / live errors Jev fixed")
    for n, (tot, ok, fixed) in tally.items():
        print(f"  {n:24s} {tot} / {ok} / {fixed}")

asyncio.run(main())
