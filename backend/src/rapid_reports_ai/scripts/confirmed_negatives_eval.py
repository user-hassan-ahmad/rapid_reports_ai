"""Confirmed-branch negatives: calibration dump and A/B runner (ledger L-45).

    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm A --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 3
    poetry run python -m rapid_reports_ai.scripts.confirmed_negatives_eval --arm B --runs 1 --calibrate

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
    conf = dec.get("confirmed_negatives", [])
    findings = _findings_block(report)
    stated = [c["text"] for c in conf if c["outcome"] == "stated"]
    return {
        "case": case["name"], "kind": case.get("kind", "silent"), "arm": arm,
        "analyser_ms": sheet["latency_ms"], "brief_ms": res.get("brief_reconcile_ms"),
        "wall_s": round(time.time() - t0, 1),
        "stated": stated, "stated_in_findings": [s for s in stated if s.lower().rstrip(".") in findings],
        "offered": [o["sentence"] for o in res.get("brief_options") or [] if o["kind"] == "confirmed_negative"],
        "do_not_assert": [c["text"] for c in conf if c["outcome"] == "do_not_assert"],
        "carried": (dec.get("impression_plan") or {}).get("carry_negatives", []),
        "unmatched": dec.get("confirmed_negatives_unmatched", 0),
        "routes": conf, "gate": gate.run_gate(report),
        "report": report, "sheet": sheet["skill_sheet"], "brief": res.get("brief_text"),
    }


async def calibrate(case: dict) -> list[dict]:
    """Jev `present` score for every differential of a B sheet, for hand labelling."""
    sheet = await generate_ephemeral_skill_sheet(scan_type=case["scan_type"], clinical_history=case["clinical_history"],
                                                 api_key="", directives=ARMS["B"])
    diffs = qb.differential_lines(qb.parse_sheet(sheet["skill_sheet"]))
    state = f"SCAN TYPE: {case['scan_type']}\nDICTATED FINDINGS:\n{case['findings']}"
    ans = await qb._jev(state, {f"d{k}": {"type": "noul", "instructions": qb.Q_PRESENT + t} for k, t in enumerate(diffs)})
    return [{"case": case["name"], "branch": t[:90], "present": round(float(ans[f"d{k}"]["noul"]), 3), "label": ""}
            for k, t in enumerate(diffs)]


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arm", choices=ARMS, required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--cases-file", default=str(BACKEND / "test_cases" / "silent_staging.json"))
    p.add_argument("--case", action="append")
    p.add_argument("--calibrate", action="store_true")
    a = p.parse_args()
    cases = [c for c in json.loads(Path(a.cases_file).read_text()) if not a.case or c["name"] in a.case]
    out_dir = BACKEND / "test_output" / "confirmed_negatives"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    if a.calibrate:
        rows = [r for c in cases for r in await calibrate(c)]
        path = out_dir / f"{stamp}_calibration_{Path(a.cases_file).stem}.json"
        path.write_text(json.dumps(rows, indent=1))
        for r in rows:
            print(f"{r['present']:.2f}  {r['case']:<30} {r['branch']}")
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
                  f"unmatched={r['unmatched']} gate={'ok' if r['gate']['passed'] else r['gate']['failures']} "
                  f"analyser={r['analyser_ms']/1000:.1f}s", flush=True)
    path = out_dir / f"{stamp}_arm{a.arm}_{Path(a.cases_file).stem}.json"
    path.write_text(json.dumps(rows, indent=1, default=str))
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
