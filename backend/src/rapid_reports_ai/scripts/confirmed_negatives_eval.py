"""Finding-linked negatives: coverage check and A/B runner (ledger L-45).

    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm A --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --coverage

A = production directives; B = production + finding_negatives. Serial, to stay inside
provider rate limits. Results go to test_output/confirmed_negatives/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[3]
load_dotenv(BACKEND / ".env")

from rapid_reports_ai import quick_report_brief as qb  # noqa: E402
from rapid_reports_ai.quick_report_analyser import PRODUCTION_DIRECTIVES, generate_ephemeral_skill_sheet  # noqa: E402
from rapid_reports_ai.quick_report_generator import generate_quick_report  # noqa: E402
from rapid_reports_ai.scripts.sheet_budget import gate  # noqa: E402

ARMS = {"A": PRODUCTION_DIRECTIVES, "B": PRODUCTION_DIRECTIVES + ("finding_negatives",)}


def _findings_block(report: str) -> str:
    m = re.search(r"FINDINGS:(.*?)(?:\n[A-Z ]+:|\Z)", report, re.S)
    return (m.group(1) if m else "").lower()


async def run_case(case: dict, arm: str) -> dict:
    t0 = time.time()
    sheet = await generate_ephemeral_skill_sheet(scan_type=case["scan_type"], clinical_history=case["clinical_history"],
                                                 api_key="", directives=ARMS[arm])
    res = await generate_quick_report(skill_sheet=sheet["skill_sheet"], scan_type=case["scan_type"],
                                      findings=case["findings"], clinical_history=case["clinical_history"])
    report, dec = res["report_content"], res.get("brief_decisions") or {}
    conf = dec.get("finding_negatives", [])
    findings = _findings_block(report)
    stated = [c["text"] for c in conf if c["outcome"] == "stated"]
    return {
        "case": case["name"], "kind": case.get("kind", "silent"), "arm": arm,
        "analyser_ms": sheet["latency_ms"], "brief_ms": res.get("brief_reconcile_ms"),
        "wall_s": round(time.time() - t0, 1),
        "stated": stated, "stated_in_findings": [s for s in stated if s.lower().rstrip(".") in findings],
        "offered": [o["sentence"] for o in res.get("brief_options") or [] if o["kind"] == "finding_negative"],
        "do_not_assert": [c["text"] for c in conf if c["outcome"] == "do_not_assert"],
        "carried": (dec.get("impression_plan") or {}).get("carry_negatives", []),
        "routes": conf, "gate": gate.run_gate(report),
        "report": report, "sheet": sheet["skill_sheet"], "brief": res.get("brief_text"),
    }


async def coverage(case: dict) -> dict:
    """R3 gate: does a key of a B sheet match the dictated finding, and how strongly?"""
    sheet = await generate_ephemeral_skill_sheet(scan_type=case["scan_type"], clinical_history=case["clinical_history"],
                                                 api_key="", directives=ARMS["B"])
    s = sheet["skill_sheet"]
    b = qb._bullet(qb._section(qb.parse_sheet(s), "Companion Matrix"), "If present")
    cands = qb.parse_if_present(b.lines) if b else []
    keys = qb.distinct_keys(cands)
    state = f"SCAN TYPE: {case['scan_type']}\nDICTATED FINDINGS:\n{case['findings']}"
    ans = await qb._jev(state, {f"f{i}": {"type": "noul", "instructions": qb.Q_FINDING + k} for i, k in enumerate(keys)}) if keys else {}
    scores = {k: round(float(ans[f"f{i}"]["noul"]), 3) for i, k in enumerate(keys)}
    top = max(scores, key=scores.get) if scores else None
    return {"case": case["name"], "kind": case.get("kind", "silent"), "findings": case["findings"],
            "keys": scores, "top_key": top, "top_score": scores.get(top, 0.0) if top else 0.0,
            "negatives": [{"key": c.key, "text": c.text, "tag": c.tag} for c in cands],
            "block": "\n".join(b.lines) if b else None, "analyser_ms": sheet["latency_ms"]}


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=ARMS, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--cases-file", default=str(BACKEND / "test_cases" / "silent_staging.json"))
    p.add_argument("--case", action="append")
    p.add_argument("--coverage", action="store_true")
    a = p.parse_args()
    cases = [c for c in json.loads(Path(a.cases_file).read_text()) if not a.case or c["name"] in a.case]
    out_dir = BACKEND / "test_output" / "confirmed_negatives"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if a.coverage:
        rows = []
        for c in cases:
            r = await coverage(c)
            rows.append(r)
            print(f"{r['kind']:<8} {r['top_score']:.2f}  {c['name']:<32} top={r['top_key']!r}  keys={len(r['keys'])} "
                  f"negs={len(r['negatives'])}", flush=True)
        path = out_dir / f"{stamp}_coverage_{Path(a.cases_file).stem}.json"
        path.write_text(json.dumps(rows, indent=1))
        print(path)
        return
    rows = []
    for run in range(a.runs):
        for c in cases:
            r = await run_case(c, a.arm)
            r["run"] = run
            rows.append(r)
            print(f"[{a.arm} r{run}] {c['name']:<30} stated={len(r['stated'])} in_findings={len(r['stated_in_findings'])} "
                  f"offered={len(r['offered'])} dna={len(r['do_not_assert'])} carried={len(r['carried'])} "
                  f"gate={'ok' if r['gate']['passed'] else r['gate']['failures']} "
                  f"analyser={r['analyser_ms']/1000:.1f}s", flush=True)
    path = out_dir / f"{stamp}_arm{a.arm}_{Path(a.cases_file).stem}.json"
    path.write_text(json.dumps(rows, indent=1, default=str))
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
