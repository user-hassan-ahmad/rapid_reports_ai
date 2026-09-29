import asyncio, json, io, contextlib, sys
from typing import List
from pydantic import BaseModel
from dotenv import load_dotenv; load_dotenv()
from rapid_reports_ai.enhancement_utils import _run_agent_with_model
S=sys.argv[1]; data=json.load(open(f"{S}/prune/items.json"))
class Split(BaseModel):
    negatives: List[List[str]]
SYS=("Rewrite each radiology negative statement as a list of single-claim negative sentences, one claim each, keeping the wording "
     "and any shared qualifier (such as 'to suggest ...' or 'in the ...') attached to every claim it applies to. A statement that "
     "already makes one claim is returned as a one-item list. Return one list per input statement, in order.")
async def one(c):
    negs=[i["text"] for i in c["items"] if i["type"]=="_negative_to_split"]
    with contextlib.redirect_stdout(io.StringIO()):
        r=await _run_agent_with_model(model_name="qwen-3.8-27b", output_type=Split, system_prompt=SYS,
            user_prompt="\n".join(f"{k+1}. {n}" for k,n in enumerate(negs)), api_key="",
            model_settings={"temperature":0,"max_tokens":3000,"reasoning_effort":"none"})
    assert len(r.output.negatives)==len(negs), (c["name"], len(r.output.negatives), len(negs))
    items=[i for i in c["items"] if i["type"]!="_negative_to_split"]
    for parent,cl in zip(negs, r.output.negatives):
        for x in cl: items.append({"type":"negative_clause","text":x,"parent":parent})
    c["items"]=items
async def main():
    await asyncio.gather(*(one(c) for c in data))
    json.dump(data, open(f"{S}/prune/items.json","w"), indent=1)
    for c in data: print(c["name"][:40], len(c["items"]))
asyncio.run(main())
