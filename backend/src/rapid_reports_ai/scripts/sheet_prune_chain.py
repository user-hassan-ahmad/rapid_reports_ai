"""Serial chain: a broad sieve question, then gated specific questions on the survivors."""
import asyncio, json, os, re, sys, time
import httpx
from dotenv import load_dotenv; load_dotenv()
S=sys.argv[1]; data=json.load(open(f"{S}/prune/results.json")); KEY=os.environ["OPENROUTER_API_KEY"]
POLICY1_X={"1.1","1.2","1.3","1.13","1.14","1.15","2.4","2.5","2.6","4.4","4.5","4.6"}
STAGE1={
 "differential":("present","A dictated finding shows that this diagnosis or branch is present in this case. Branch: "),
 "negative_clause":("related","A dictated finding relates to what this negative statement is about: the same structure, the same kind of finding, or a consequence of a dictated finding. Negative: "),
}
STAGE2={
 "differential":{
   "alternative":"A dictated finding establishes a different diagnosis that answers the same clinical question this branch addresses. Branch: ",
   "ruled_out":"The dictation explicitly states a negative that rules this branch out. Branch: ",
   "invisible":"This branch cannot be seen on imaging; it needs clinical, laboratory or other tests. Branch: ",
   "sign_dictated_if_present":"If this branch were present on this scan, it would produce a visible imaging sign that the radiologist would have dictated. Branch: "},
 "negative_clause":{
   "contra":"The dictation reports this as present, or reports a finding of the same kind in the same place, so stating this negative would contradict the dictation. Negative: "},
}
STAGE3_NEG=("expected","A dictated finding would normally and predictably cause what this negative denies, not merely make it possible, so it cannot be stated as absent from silence. Negative: ")
def state(c): return f"SCAN TYPE: {c['scan_type']}\nDICTATED FINDINGS:\n{c['findings']}"
async def ask(client, c, qs):
    if not qs: return {}, 0.0
    t=time.time()
    r=await client.post("https://openrouter.ai/api/v1/systemone", headers={"Authorization":f"Bearer {KEY}"},
        json={"model":"typesafe/jev-1.13","state":state(c),"questions":qs}, timeout=120)
    r.raise_for_status(); a=r.json().get("answers") or r.json()
    return {k: float(v["noul"]) for k,v in a.items()}, time.time()-t
async def run_case(client, ci, c):
    idx=[(k,it) for k,it in enumerate(c["items"]) if it["type"] in STAGE1]
    s1,t1=await ask(client,c,{f"i{k}":{"type":"noul","instructions":STAGE1[it["type"]][1]+it["text"]} for k,it in idx})
    for k,it in idx: it["chain"]={STAGE1[it["type"]][0]: s1[f"i{k}"]}
    gated=[(k,it) for k,it in idx if s1[f"i{k}"]<0.5] if True else []
    # differentials: gate on NOT present; negatives: gate on related
    gated=[(k,it) for k,it in idx if (it["type"]=="differential" and s1[f"i{k}"]<0.5) or (it["type"]=="negative_clause" and s1[f"i{k}"]>=0.5)]
    qs={f"i{k}_{qn}":{"type":"noul","instructions":qt+it["text"]} for k,it in gated for qn,qt in STAGE2[it["type"]].items()}
    s2,t2=await ask(client,c,qs)
    for k,it in gated:
        for qn in STAGE2[it["type"]]: it["chain"][qn]=s2[f"i{k}_{qn}"]
    g3=[(k,it) for k,it in gated if it["type"]=="negative_clause" and it["chain"]["contra"]<0.5]
    s3,t3=await ask(client,c,{f"i{k}":{"type":"noul","instructions":STAGE3_NEG[1]+it["text"]} for k,it in g3})
    for k,it in g3: it["chain"]["expected"]=s3[f"i{k}"]
    for k,it in c["items"] and enumerate(c["items"]):
        if it["type"]=="differential": it["policy1_label"]=("X" if f"{ci}.{k}" in POLICY1_X else it["label"])
    return len(idx), len(qs), len(g3), t1+t2+t3, (t1,t2,t3)
async def main():
    async with httpx.AsyncClient() as client:
        for ci,c in enumerate(data):
            n1,n2,n3,tt,ts=await run_case(client,ci,c)
            print(f"{c['name'][:38]:38} stage1 {n1} q, stage2 {n2} q, stage3 {n3} q | {tt:.2f}s total ({' + '.join(f'{x:.2f}' for x in ts)})", flush=True)
    json.dump(data, open(f"{S}/prune/chain_results.json","w"), indent=1)
asyncio.run(main())
