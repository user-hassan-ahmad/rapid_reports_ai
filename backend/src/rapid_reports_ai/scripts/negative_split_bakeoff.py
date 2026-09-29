"""Clause splitting by selection: code proposes split points and shared wording, Jev chooses, code rebuilds."""
import asyncio, json, os, re, sys, time, io, contextlib
from typing import List
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv; load_dotenv()
from rapid_reports_ai.enhancement_utils import _run_agent_with_model
S=sys.argv[1]; items=json.load(open(f"{S}/prune/split_items.json")); KEY=os.environ["OPENROUTER_API_KEY"]
exec(open(f"{S}/prune/gold_split.py").read())
SEP=re.compile(r",\s+or\s+|,\s+and\s+|,\s+|\s+or\s+|\s+and\s+")
def candidates(t):
    return [(m.start(), m.end(), m.group(0)) for m in SEP.finditer(t)]
async def post(client, qs):
    r=await client.post("https://openrouter.ai/api/v1/systemone", headers={"Authorization":f"Bearer {KEY}"},
        json={"model":"typesafe/jev-1.13","state":"Radiology report template negatives are being split into single-claim statements.","questions":qs}, timeout=120)
    r.raise_for_status(); return r.json().get("answers") or r.json()
async def jev_split_all(client):
    # call 1: every candidate separator of every item
    qs={}
    for i,it in enumerate(items):
        t=it["text"]
        for j,(a,b,sep) in enumerate(candidates(t)):
            marked=t[:a]+" ⟦"+sep.strip()+"⟧ "+t[b:]
            qs[f"s{i}_{j}"]={"type":"noul","instructions":("In this sentence the separator inside ⟦ ⟧ joins two separate findings or locations "
               "being denied, rather than joining words inside one name or inside a closing qualifier such as 'to suggest …'. Sentence: ")+marked}
    t0=time.time(); a1=await post(client, qs); t1=time.time()-t0
    # call 2: shared opening and closing words, given the chosen splits
    qs2={}; plans={}
    for i,it in enumerate(items):
        t=it["text"]; cands=candidates(t)
        cuts=[(a,b) for j,(a,b,_) in enumerate(cands) if float(a1[f"s{i}_{j}"]["noul"])>=0.5]
        segs=[]; prev=0
        for a,b in cuts: segs.append(t[prev:a]); prev=b
        segs.append(t[prev:]); plans[i]=segs
        if len(segs)<2: continue
        fw=segs[0].split(); lw=segs[-1].split()
        pre=[" ".join(fw[:k]) for k in range(1,len(fw))]           # never the whole first item
        suf=[""]+[" ".join(lw[k:]) for k in range(1,len(lw))]       # never the whole last item
        qs2[f"p{i}"]={"type":"choice","instructions":"Which opening words are shared by every item in this list? Sentence: "+t,
                      "criteria":{f"o{k}":p for k,p in enumerate(pre)}}
        qs2[f"x{i}"]={"type":"choice","instructions":"Which closing words, if any, apply to every item in this list? Sentence: "+t,
                      "criteria":{f"o{k}":(x if x else "(none: nothing after the last item applies to the others)") for k,x in enumerate(suf)}}
        plans[i]=(segs,pre,suf)
    t0=time.time(); a2=await post(client, qs2) if qs2 else {}; t2=time.time()-t0
    out={}
    for i,it in enumerate(items):
        p=plans[i]
        if isinstance(p,list): out[i]=[it["text"]]; continue
        segs,pre,suf=p
        P=pre[int(a2[f"p{i}"]["choice"][1:])]; X=suf[int(a2[f"x{i}"]["choice"][1:])]
        clauses=[]
        for k,sg in enumerate(segs):
            core=sg
            if k==0 and core.startswith(P): core=core[len(P):].strip()
            if k==len(segs)-1 and X and core.endswith(X): core=core[:-len(X)].strip()
            clauses.append(" ".join(w for w in (P,core,X) if w))
        out[i]=clauses
    return out, len(qs), len(qs2), t1, t2
class Split(BaseModel):
    negatives: List[List[str]]
async def qwen_split():
    SYS=("Rewrite each radiology negative statement as a list of single-claim sentences, one claim each, keeping the wording and any "
         "shared qualifier attached to every claim it applies to. A statement that already makes one claim is returned as a one-item list. "
         "Return one list per input statement, in order.")
    t0=time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        r=await _run_agent_with_model(model_name="qwen-3.8-27b", output_type=Split, system_prompt=SYS,
            user_prompt="\n".join(f"{k+1}. {x['text']}" for k,x in enumerate(items)), api_key="",
            model_settings={"temperature":0,"max_tokens":8000,"reasoning_effort":"none"})
    return {i:c for i,c in enumerate(r.output.negatives)}, time.time()-t0
norm=lambda s: re.sub(r"\s+"," ",s.strip().rstrip(".").lower())
def correct(i, clauses): return any(sorted(map(norm,clauses))==sorted(map(norm,g)) for g in G[i])
def extractive(i, clauses):
    src=set(re.findall(r"[\w*'-]+", items[i]["text"].lower()))
    return all(set(re.findall(r"[\w*'-]+", c.lower()))<=src for c in clauses)
async def main():
    async with httpx.AsyncClient() as client:
        (jv,n1,n2,t1,t2),(qw,tq)=await asyncio.gather(jev_split_all(client), qwen_split())
    jc=[i for i in range(len(items)) if correct(i,jv[i])]; qc=[i for i in range(len(items)) if correct(i,qw.get(i,[]))]
    print(f"Jev selection: {len(jc)}/{len(items)} exactly right | call 1: {n1} split-point questions {t1:.2f}s, call 2: {n2} choice questions {t2:.2f}s")
    print(f"Qwen rewrite:  {len(qc)}/{len(items)} exactly right | {tq:.2f}s | reworded (words not in source): {sum(not extractive(i,qw.get(i,[])) for i in range(len(items)))}")
    print("Jev selection reworded: 0 by construction")
    print("\nJev errors:")
    for i in range(len(items)):
        if i not in jc: print(f"  {i:2} {items[i]['text'][:75]}\n       -> {jv[i]}")
    print("\nQwen errors:")
    for i in range(len(items)):
        if i not in qc: print(f"  {i:2} {items[i]['text'][:75]}\n       -> {qw.get(i)}")
    json.dump({"jev":jv,"qwen":qw}, open(f"{S}/prune/split_results.json","w"), indent=1)
asyncio.run(main())
