"""Section-list probe: the prod sections call as the stack's group vocabulary, per lab case.
Arms: prompt (prod | v2 additions) x reasoning (none | medium), called directly (the canvas
helper forces reasoning off). Prints each list for a hand read plus simple counts.

    PYTHONPATH=src .venv/bin/python -m rapid_reports_ai.scripts.hybrid_stack_lab.sections_probe
"""
import asyncio, json, os, re, time
from pathlib import Path
import httpx
from dotenv import load_dotenv; load_dotenv(".env")
from rapid_reports_ai.canvas_routes import SECTIONS_SYSTEM_PROMPT, SECTIONS_USER_PROMPT_TEMPLATE
from rapid_reports_ai.scripts.hybrid_stack_lab.lab import SECTIONS_ADDITIONS

HERE = Path(__file__).parent
SCHEMA = {"type": "object", "properties": {"sections": {"type": "array", "items": {"type": "string"}}},
          "required": ["sections"], "additionalProperties": False}


def prompt(case, arm):
    base = SECTIONS_USER_PROMPT_TEMPLATE.format(scan_type=case["scan_type"], clinical_history=case["clinical_history"])
    return base if arm == "prod" else base.replace("## OUTPUT RULES", SECTIONS_ADDITIONS + "## OUTPUT RULES")


async def call(c, sem, case, arm, effort, fmt="schema"):
    async with sem:
        t0 = time.perf_counter()
        r = await c.post("https://api.cerebras.ai/v1/chat/completions",
                         headers={"Authorization": f"Bearer {os.environ['CEREBRAS_API_KEY']}"}, json={
            "model": "qwen-3.8-27b", "temperature": 0.1, "max_tokens": 6000 if effort != "none" else 1000,
            "reasoning_effort": effort,
            "messages": [{"role": "system", "content": SECTIONS_SYSTEM_PROMPT}, {"role": "user", "content": prompt(case, arm)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "s", "schema": SCHEMA}} if fmt == "schema"
            else {"type": "json_object"}})
        dt = time.perf_counter() - t0
        try:
            secs = json.loads(r.json()["choices"][0]["message"]["content"])["sections"]
        except Exception as e:
            secs = [f"ERROR {r.status_code} {type(e).__name__}"]
        return case["id"], arm, f"{effort}/{fmt}", secs, dt


async def main():
    cases = json.loads((HERE / "cases.json").read_text())["cases"]
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=120) as c:
        arms = [tuple(x.split(":")) for x in os.environ.get("PROBE_ARMS", "prod:none:schema,v2:none:schema,prod:medium:schema,v2:medium:schema").split(",")]
        res = await asyncio.gather(*(call(c, sem, k, a, e, f) for k in cases for a, e, f in arms))
    out = Path(os.environ.get("LAB_OUT", ".")) / f"sections_probe_{os.getpid()}.json"
    out.write_text(json.dumps(res, indent=2))
    male = re.compile(r"prostat|seminal", re.I)
    for cid, arm, eff, secs, dt in res:
        dup = len(secs) - len({s.upper() for s in secs})
        sexed = "MALE" if any(male.search(s) for s in secs) else ""
        print(f"{cid[:28]:28} {arm:4} {eff:14} {dt:5.1f}s n={len(secs):2} dup={dup} {sexed:4} | {' · '.join(secs)}")
    print("\nsaved", out)

asyncio.run(main())
