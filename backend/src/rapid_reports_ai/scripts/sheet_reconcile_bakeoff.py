"""X-06 extension bake-off: does a dictated finding affect each skill-sheet item?

Jev (one noul per item, one call per case) vs Qwen 3.8 reasoning off vs a lexical baseline, on the
hand-labelled items in test_cases/sheet_reconcile_labelled.json. Results: docs/superpowers/research/
2026-09-29-sheet-reconciliation-bakeoff.md.

Usage: python -m rapid_reports_ai.scripts.sheet_reconcile_bakeoff <labelled.json> <results_out.json>
"""
import asyncio, json, re, time, io, contextlib, sys, os
import httpx
from typing import List
from pydantic import BaseModel
from dotenv import load_dotenv; load_dotenv()
from rapid_reports_ai.enhancement_utils import _run_agent_with_model
cases=json.load(open(sys.argv[1]))
KEY=os.environ["OPENROUTER_API_KEY"]
Q = ("Is this statement from a report template affected by the dictated findings? Affected means a dictated finding "
     "contradicts it, or acts on the structure it describes (displaces, compresses, obstructs, drains into, extends to, "
     "involves it, or is a finding of the same kind in that structure), so it cannot be written as it stands. "
     "Statement: ")
def state(c): return f"SCAN TYPE: {c['scan_type']}\nDICTATED FINDINGS:\n{c['findings']}"
async def jev(client, c):
    qs={f"i{k}":{"type":"noul","instructions":Q+it["text"]} for k,it in enumerate(c["items"])}
    t=time.time()
    r=await client.post("https://openrouter.ai/api/v1/systemone", headers={"Authorization":f"Bearer {KEY}"},
        json={"model":"typesafe/jev-1.13","state":state(c),"questions":qs}, timeout=60)
    r.raise_for_status(); d=r.json(); dt=time.time()-t
    ans=d.get("answers") or d.get("results") or d
    out=[]
    for k in range(len(c["items"])):
        a=ans[f"i{k}"]; out.append(float(a["noul"] if isinstance(a,dict) else a))
    return out, dt
class Affected(BaseModel):
    affected: List[int]
async def qwen(c):
    lines="\n".join(f"{k}. {it['text']}" for k,it in enumerate(c["items"]))
    t=time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        r=await _run_agent_with_model(model_name="qwen-3.8-27b", output_type=Affected,
            system_prompt="You compare report-template statements against a radiologist's dictated findings. "+Q.replace("Statement: ","")+" Return the numbers of every affected statement.",
            user_prompt=f"{state(c)}\n\nSTATEMENTS:\n{lines}", api_key="",
            model_settings={"temperature":0.1,"max_tokens":1500,"reasoning_effort":"none"})
    return set(r.output.affected), time.time()-t
STOP=set("the a an of in or and to with no without is are be as for on at by from this that any other normal normally unremarkable identified suggest acute visualised visible clear intact patent size calibre contour configuration abnormality abnormal evidence finding findings level levels either both within".split())
def lexical(c):
    pos=[l.lower() for l in re.split(r"\n|(?<=\.)\s|/", c["findings"]) if l.strip() and not re.match(r"\s*-?\s*(no|nil)\b", l.strip().lower())]
    ptxt=" ".join(pos); out=set()
    for k,it in enumerate(c["items"]):
        words=[w for w in re.findall(r"[a-z]{4,}", it["text"].lower()) if w not in STOP]
        if any(re.search(r"\b"+w[:6], ptxt) for w in words): out.add(k)
    return out
async def main():
    res=[]
    async with httpx.AsyncClient() as client:
        for c in cases:
            (jv,jt),(qw,qt)=await asyncio.gather(jev(client,c), qwen(c))
            res.append({"name":c["name"],"jev":jv,"jev_s":jt,"qwen":sorted(qw),"qwen_s":qt,"lex":sorted(lexical(c)),
                        "labels":[it["label"] for it in c["items"]],"types":[it["type"] for it in c["items"]],"texts":[it["text"] for it in c["items"]]})
            print(f"{c['name'][:40]:40} jev {jt:.2f}s  qwen {qt:.2f}s", flush=True)
    json.dump(res, open(sys.argv[2],"w"), indent=1)
asyncio.run(main())
