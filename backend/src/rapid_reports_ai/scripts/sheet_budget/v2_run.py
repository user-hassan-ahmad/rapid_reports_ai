"""Parallel runner for the v2 pipeline. Same corpus, same output shape as the
other runners, so all existing analysis tooling works unchanged.

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.v2_run \
        --case clean_mri_ankle_fragments --output-dir test_output/V2SMOKE
"""
from __future__ import annotations

import argparse, asyncio, json, os, sys, time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]

def _load_dotenv():
    p = BACKEND_ROOT / ".env"
    if not p.exists(): return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip().strip("'\"")

_load_dotenv()

from rapid_reports_ai.report_v2 import (  # noqa: E402
    generate_sheet_v2, generate_report_v2, validate_sheet_v2,
)
from . import gate  # noqa: E402


async def _bo(factory, what, attempts=4):
    import asyncio
    last=None
    for i in range(attempts):
        try:
            return await factory()
        except Exception as exc:  # noqa: BLE001
            last=exc
            if "429" not in str(exc) and "rate" not in str(exc).lower():
                raise
            print(f"    429 on {what}; backing off {25*(i+1)}s")
            await asyncio.sleep(25*(i+1))
    raise last


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases-file", default=str(BACKEND_ROOT / "test_cases/broad_suite.json"))
    ap.add_argument("--case", action="append", default=None)
    ap.add_argument("--model", default=None,
                    help="Override V2_MODEL for both stages (e.g. gemma-4-31b).")
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    cases = json.loads(Path(args.cases_file).read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)

    runs = []
    for c in cases:
        t0 = time.time()
        try:
            s = await _bo(lambda: generate_sheet_v2(c["scan_type"], c["clinical_history"], **({"model":args.model} if args.model else {})), c["name"]+" sheet")
            v = validate_sheet_v2(s["sheet"])
            print(f"  [{c['name']}] sheet {len(s['sheet']):,}ch {s['latency_ms']/1000:.1f}s "
                  f"obligations={v['obligations']} (Q={v['question_tier']}) "
                  f"unassessable={v['unassessable']} stray_prose={len(v['stray_prose'])} ok={v['ok']}")
            r = await _bo(lambda: generate_report_v2(s["sheet"], c["scan_type"],
                                         c["clinical_history"], c["findings"],
                                         **({"model":args.model} if args.model else {})), c["name"]+" report")
            g = gate.run_gate(r["report"])
            print(f"  [{c['name']}] report {len(r['report']):,}ch {r['latency_ms']/1000:.1f}s "
                  f"gate={'pass' if g['passed'] else 'FAIL ' + str(g['failures'])}")
            runs.append({"cell": "v2", "model": args.model or "qwen/qwen3.6-27b", "case": c["name"],
                         "skill_sheet": s["sheet"], "sheet_chars": len(s["sheet"]),
                         "sheet_validation": v,
                         "analyser_latency_ms": s["latency_ms"],
                         "report": r["report"], "report_chars": len(r["report"]),
                         "generator_latency_ms": r["latency_ms"],
                         "gate": g, "total_wall_s": round(time.time() - t0, 1)})
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {c['name']}: {exc}")
            runs.append({"cell": "v2", "model": args.model or "qwen/qwen3.6-27b", "case": c["name"], "error": str(exc)})
    (out / "runs.json").write_text(json.dumps(runs, indent=2))
    print(f"\n✅ {len(runs)} runs → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
