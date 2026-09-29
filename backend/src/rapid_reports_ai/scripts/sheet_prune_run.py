import asyncio, json, os, sys, time, io, contextlib
from typing import List, Literal
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv; load_dotenv()
from rapid_reports_ai.enhancement_utils import _run_agent_with_model
S=sys.argv[1]; data=json.load(open(f"{S}/prune/labelled.json")); KEY=os.environ["OPENROUTER_API_KEY"]
Q={
 "differential":{
   "present":"A dictated finding shows that this diagnosis or branch is present in this case. Branch: ",
   "settled":"The dictated findings settle this branch as not applicable to this case: a dictated finding establishes a different diagnosis that answers the same clinical question, or a dictated negative rules it out. Silence about it does not settle it. Branch: ",
   "silent":"The dictated findings contain nothing that bears on this branch, either for or against it. Branch: "},
 "style_exemplar":{
   "match":"This example report sentence describes the same kind of finding as one that is dictated in this case. Example: ",
   "absent":"This example report sentence describes a finding or diagnosis that is not present in the dictated findings. Example: "},
 "recommendation":{
   "met":"A dictated finding meets the condition that triggers this recommendation. Recommendation: ",
   "unmet":"The condition for this recommendation is not met by the dictated findings, or it belongs to a diagnosis the findings rule out. Recommendation: "},
 "suppression_rule":{
   "applies":"This rule applies to this report: its IF condition is met by the dictated findings, or it is a general writing rule that applies to any report. Rule: "},
 "measurement":{
   "applies":"The finding this measurement convention is for is present in the dictated findings. Convention: "},
 "negative_clause":{
   "contra":"The dictated findings report this as present, or report a finding of the same kind in the same place, so stating this negative would contradict the dictation. Negative: ",
   "expected":"A dictated finding would normally be expected to cause what this negative denies, so it cannot be stated as absent just because the dictation is silent. Negative: "},
}
def state(c): return f"SCAN TYPE: {c['scan_type']}\nDICTATED FINDINGS:\n{c['findings']}"
async def jev(client, c):
    qs={}
    for k,it in enumerate(c["items"]):
        if it["type"]=="impression_variant_choice":
            v=json.loads(it["text"])
            qs[f"i{k}_choice"]={"type":"choice","instructions":"Which impression exemplar best matches the shape of this case's findings (severity, number of findings, complications)?",
                                "criteria":{f"v{j}":x[:400] for j,x in enumerate(v)}}
        else:
            for qn,qt in Q[it["type"]].items(): qs[f"i{k}_{qn}"]={"type":"noul","instructions":qt+it["text"]}
    t=time.time()
    r=await client.post("https://openrouter.ai/api/v1/systemone", headers={"Authorization":f"Bearer {KEY}"},
        json={"model":"typesafe/jev-1.13","state":state(c),"questions":qs}, timeout=120)
    if r.status_code!=200: raise RuntimeError(r.text[:300])
    a=r.json().get("answers") or r.json(); dt=time.time()-t
    for k,it in enumerate(c["items"]):
        if it["type"]=="impression_variant_choice":
            it["jev"]={"choice":a[f"i{k}_choice"]["choice"],"confidence":a[f"i{k}_choice"].get("confidence")}
        else:
            it["jev"]={qn: float(a[f"i{k}_{qn}"]["noul"]) for qn in Q[it["type"]]}
    return len(qs), dt
class Act(BaseModel):
    index: int
    action: Literal["keep","prune","present","contradicted","expected","v0","v1","v2"]
class Acts(BaseModel):
    actions: List[Act]
QSYS=("You prepare a radiology skill sheet for one case by checking each item against the dictated findings. Silence never settles "
 "anything. For each numbered item return one action:\n"
 "differential: 'present' if a dictated finding shows it; 'prune' only if a dictated finding establishes a different diagnosis answering the same question or a dictated negative rules it out; else 'keep'.\n"
 "style_exemplar: 'keep' if it describes the same kind of finding as one dictated, else 'prune'.\n"
 "recommendation: 'keep' if a dictated finding meets its trigger, 'prune' if its condition is unmet or it belongs to a ruled-out diagnosis.\n"
 "suppression_rule: 'keep' if its condition is met or it is a general writing rule, else 'prune'.\n"
 "measurement: 'keep' if its finding is dictated, else 'prune'.\n"
 "negative_clause: 'contradicted' if the dictation reports it or a finding of the same kind in the same place; 'expected' if a dictated finding would normally cause it; else 'keep'.\n"
 "impression_variant_choice: 'v0', 'v1' or 'v2' for the exemplar that best matches the shape of this case.")
async def qwen(c):
    lines=[]
    for k,it in enumerate(c["items"]):
        t=it["text"] if it["type"]!="impression_variant_choice" else " | ".join(f"v{j}: {x[:200]}" for j,x in enumerate(json.loads(it["text"])))
        lines.append(f"{k}. [{it['type']}] {t}")
    t=time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        r=await _run_agent_with_model(model_name="qwen-3.8-27b", output_type=Acts, system_prompt=QSYS,
            user_prompt=state(c)+"\n\nITEMS:\n"+"\n".join(lines), api_key="",
            model_settings={"temperature":0,"max_tokens":6000,"reasoning_effort":"none"})
    m={a.index:a.action for a in r.output.actions}
    for k,it in enumerate(c["items"]): it["qwen"]=m.get(k)
    return time.time()-t
async def main():
    async with httpx.AsyncClient() as client:
        for c in data:
            (nq,jt),qt=await asyncio.gather(jev(client,c), qwen(c))
            print(f"{c['name'][:40]:40} jev {nq} questions in {jt:.2f}s | qwen {qt:.2f}s", flush=True)
    json.dump(data, open(f"{S}/prune/results.json","w"), indent=1)
asyncio.run(main())
