"""Arms A (raw sheet, medium) / B (reconciled sheet, medium) / C (reconciled sheet, reasoning off)."""
import asyncio, json, re, time, io, contextlib, sys, os, statistics as st
from typing import List, Literal
import httpx
from pydantic import BaseModel
from dotenv import load_dotenv; load_dotenv()
import rapid_reports_ai.enhancement_utils as eu
import rapid_reports_ai.template_manager as tmod
from rapid_reports_ai.template_manager import TemplateManager
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE
from rapid_reports_ai.scripts.sheet_budget import gate, judge
S=sys.argv[1]; REPS=int(sys.argv[2]) if len(sys.argv)>2 else 2
cases=json.load(open(f"{S}/recon/labelled.json")); PRED={r["name"]:r for r in json.load(open(f"{S}/recon/results.json"))}
KEY=os.environ["OPENROUTER_API_KEY"]; GEN_MODEL=eu.MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"]

# ---------- reconciled sheet ----------
HEADER = ("## Reconciliation with this case's dictated findings\n"
  "The items below were checked against this case's dictated findings before generation.\n"
  "- A mandatory negative marked RESCOPE has a dictated finding of its class, or one acting on its region: state the "
  "positive finding and cover only the unaffected remainder; never state the negative as written.\n"
  "- Lines listed under **Affected normal lines** must not be asserted as normal: describe that structure as the "
  "dictated findings require, or state it contingently.\n"
  "- Normal-study lines removed from the Normal-study path are not to be reinstated.\n")
def reconcile(c):
    p=PRED[c["name"]]; sheet=c["sheet"]
    flag={k: p["jev"][k]>=0.5 for k in range(len(c["items"]))}; both={k: flag[k] and k in p["qwen"] for k in flag}
    mn=[k for k,it in enumerate(c["items"]) if it["type"]=="mandatory_negative"]
    for k in mn:
        if flag[k]:
            t=c["items"][k]["text"]; sheet=sheet.replace(f'"{t}"', f'"{t}" — RESCOPE: a dictated finding acts on this', 1)
    nl=[k for k,it in enumerate(c["items"]) if it["type"]=="normal_line"]
    keep=[c["items"][k]["text"] for k in nl if not flag[k]]
    affected=[c["items"][k]["text"] for k in nl if flag[k] and not both[k]]
    m=re.search(r'- \*\*Normal-study path:\*\*.*?(?=\n- \*\*|\n## |\n\n)', sheet, re.S)
    if m:
        new=f'- **Normal-study path:** "{" ".join(keep)}"'
        if affected: new+="\n- **Affected normal lines (do not assert as normal):** " + " ".join(f'"{a}"' for a in affected)
        sheet=sheet[:m.start()]+new+sheet[m.end():]
    title_end=sheet.find("\n", sheet.find("# Skill Sheet"))
    return sheet[:title_end+1]+"\n"+HEADER+"\n"+sheet[title_end+1:], sum(flag.values()), sum(both[k] for k in nl)

# ---------- generator with effort injection (same mechanism as reasoning_matrix) ----------
_EFFORT={"v":None}; _CAP=[]
_ORIG=eu._run_agent_with_model
async def _instr(**kw):
    if kw.get("model_name")==GEN_MODEL and kw.get("output_type") is str and _EFFORT["v"]:
        s=dict(kw.get("model_settings") or {}); e=dict(s.get("extra_body") or {}); e["reasoning_effort"]=_EFFORT["v"]; s["extra_body"]=e; kw["model_settings"]=s
    t=time.time(); r=await _ORIG(**kw)
    if kw.get("model_name")==GEN_MODEL and kw.get("output_type") is str:
        try: u=r.usage(); _CAP.append((time.time()-t, u.output_tokens))
        except Exception: _CAP.append((time.time()-t, None))
    return r
eu._run_agent_with_model=_instr; tmod._run_agent_with_model=_instr
GEN_LOCK=asyncio.Lock()
async def generate(c, sheet, effort):
    async with GEN_LOCK:   # serial: the effort switch is global
        _EFFORT["v"]=effort; _CAP.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            g=await TemplateManager().generate_report_from_config(
                template_config={"generation_mode":"skill_sheet_guided","skill_sheet":QUICK_REPORT_HARDENING_PREAMBLE+sheet,"scan_type":c["scan_type"]},
                user_inputs={"FINDINGS":c["findings"],"CLINICAL_HISTORY":c["clinical_history"]})
        lat,tok=_CAP[-1] if _CAP else (None,None)
    return g["report_content"], lat, tok

# ---------- measures ----------
class Issue(BaseModel):
    kind: Literal["contradiction","unsupported_normal"]
    quote: str
class Check(BaseModel):
    issues: List[Issue]
VSYS=("You are a consultant radiologist checking a finished report against the radiologist's dictated findings. Report two kinds of issue only, quoting the report exactly:\n"
 "contradiction: the report denies, or states as absent, something the dictated findings report as present (including a finding of the same kind in the same structure).\n"
 "unsupported_normal: the report asserts a structure is normal when a dictated finding would be expected to act on it (displace, compress, obstruct, drain into, extend to, involve it) and the dictation does not say it is normal.\n"
 "Return an empty list if there are none.")
async def verify(c, rep):
    with contextlib.redirect_stdout(io.StringIO()):
        r=await _ORIG(model_name="gpt-oss-120b", output_type=Check, system_prompt=VSYS,
            user_prompt=f"SCAN TYPE: {c['scan_type']}\n\nDICTATED FINDINGS:\n{c['findings']}\n\nREPORT:\n{rep}", api_key="",
            model_settings={"temperature":0.1,"max_tokens":8000,"reasoning_effort":"medium"})
    return sum(i.kind=="contradiction" for i in r.output.issues), sum(i.kind=="unsupported_normal" for i in r.output.issues)
def finding_units(c):
    return [u.strip(" -•") for u in re.split(r"\n+|(?<=\.)\s+(?=[A-Z])", c["findings"]) if len(u.strip(" -•"))>8]
async def retention(client, c, rep):
    units=finding_units(c)
    qs={f"f{k}":{"type":"noul","instructions":"The report conveys this dictated finding (same meaning; wording may differ): "+u} for k,u in enumerate(units)}
    r=await client.post("https://openrouter.ai/api/v1/systemone", headers={"Authorization":f"Bearer {KEY}"},
        json={"model":"typesafe/jev-1.13","state":rep,"questions":qs}, timeout=60)
    r.raise_for_status(); a=r.json().get("answers") or r.json()
    sc=[float(a[f"f{k}"]["noul"]) for k in range(len(units))]
    return sum(s<0.5 for s in sc), len(units)
JSEM=asyncio.Semaphore(4)
async def judge_mean(c, rep):
    async with JSEM:
        d=await asyncio.to_thread(judge.score_case, inputs=judge.format_inputs(scan_type=c["scan_type"],clinical_history=c["clinical_history"],findings=c["findings"]),
                                  skill_sheet=c["sheet"], report=rep)
    return st.mean(v["score"] for v in d.values()), {k:v["score"] for k,v in d.items()}

ARMS=[("A","raw","medium"),("B","reconciled","medium"),("C","reconciled","none")]
async def main():
    runs=json.load(open(f"{S}/recon/arms_runs.json")) if os.path.exists(f"{S}/recon/arms_runs.json") else []
    done={r["case"] for r in runs}
    async with httpx.AsyncClient() as client:
        for c in cases:
            if c["name"] in done: continue
            rsheet,nflag,nremoved=reconcile(c)
            for arm,kind,eff in ARMS:
                for i in range(REPS):
                    try:
                        rep,lat,tok=await generate(c, c["sheet"] if kind=="raw" else rsheet, None if eff=="medium" else eff)
                    except Exception as e:
                        runs.append({"case":c["name"],"arm":arm,"rep":i,"error":f"{type(e).__name__}: {str(e)[:200]}"}); print("ERR",arm,c["name"],e,flush=True); continue
                    g=gate.run_gate(rep)
                    (con,uns),(drop,nunits)=await asyncio.gather(verify(c,rep), retention(client,c,rep)); jm,jd=None,None
                    runs.append({"case":c["name"],"arm":arm,"rep":i,"report":rep,"gen_s":lat,"gen_tokens":tok,"gate_passed":g["passed"],"gate_failures":g["failures"],
                                 "contradictions":con,"unsupported_normals":uns,"dropped_findings":drop,"finding_units":nunits,"judge_mean":jm,"judge":jd,
                                 "reconciled_flags":nflag,"removed_normals":nremoved})
                    print(f"{arm} {c['name'][:30]:30} r{i} gen {lat or 0:5.1f}s tok {tok} gate {'ok' if g['passed'] else g['failures']} con {con} uns {uns} drop {drop}/{nunits}", flush=True)
            json.dump(runs, open(f"{S}/recon/arms_runs.json","w"), indent=1)
asyncio.run(main())
