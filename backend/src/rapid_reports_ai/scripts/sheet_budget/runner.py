"""Sheet-budget experiment runner.

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner --tier T1 --tier T2
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner --no-judge

Everything is serialised. Groq's OTPM ceiling (32,000 observed) kills
concurrent Qwen calls; the 2026-08-12 bake-off lost 4 of 20 cells that way,
and the same cells passed cleanly when re-run serially.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parents[3]
CASES_PATH = BACKEND_ROOT / "test_cases" / "analyser_suite.json"
OUTPUT_ROOT = BACKEND_ROOT / "test_output"

ANALYSER_MODEL = "qwen/qwen3.6-27b"
GENERATOR_MODEL = "qwen/qwen3.6-27b"

# NOT WIRED: spec section 4 asks for a fixed seed. GroqModelSettings exposes
# `seed`, but neither generate_ephemeral_skill_sheet nor
# generate_report_from_config threads model settings from the caller, so
# wiring it means changing two production signatures for a determinism Groq
# does not guarantee anyway. Recorded rather than silently dropped: if
# run-to-run variance proves to swamp tier differences, thread it then.


def _load_dotenv() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip().strip("'\"")


_load_dotenv()

from rapid_reports_ai.quick_report_analyser import (  # noqa: E402
    generate_ephemeral_skill_sheet,
    new_run_id,
)
from rapid_reports_ai.quick_report_api import _run_one_generator  # noqa: E402
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

from . import compliance, gate, judge, report as report_mod, tiers  # noqa: E402


async def _with_backoff(coro_factory, *, what: str, attempts: int = 3):
    """Retry on Groq 429s. Serialisation is the primary defence; this is the net."""
    last = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "429" not in str(exc) or i == attempts - 1:
                raise
            wait = 20.0 * (i + 1)
            print(f"    429 on {what}; backing off {wait:.0f}s")
            await asyncio.sleep(wait)
    raise last


async def run_one(case: dict, tier: dict, tm: TemplateManager) -> dict[str, Any]:
    directive = tiers.render_directive(tier)
    label = f"{tier['id']}/{case['name']}"
    print(f"  [{label}] analysing...")

    t0 = time.time()
    sheet_result = await _with_backoff(
        lambda: generate_ephemeral_skill_sheet(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            api_key="",  # groq path resolves GROQ_API_KEY itself
            model_override=ANALYSER_MODEL,
            budget_directive=directive,
        ),
        what=f"{label} analyser",
    )
    sheet = sheet_result["skill_sheet"]
    print(
        f"  [{label}] sheet {len(sheet):,} chars "
        f"in {sheet_result['latency_ms']/1000:.1f}s"
    )

    template_config = {
        "generation_mode": "skill_sheet_guided",
        "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + sheet,
        "scan_type": case["scan_type"],
    }
    user_inputs = {
        "FINDINGS": case["findings"],
        "CLINICAL_HISTORY": case["clinical_history"],
    }

    candidate = await _with_backoff(
        lambda: _run_one_generator(
            tm=tm,
            template_config=template_config,
            user_inputs=user_inputs,
            model_name=GENERATOR_MODEL,
            run_id=f"budget-{tier['id']}-{case['name']}-{new_run_id()}",
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            skill_sheet_markdown=sheet,
        ),
        what=f"{label} generator",
    )
    report_text = candidate.get("content") or ""
    print(
        f"  [{label}] report {len(report_text):,} chars "
        f"in {(candidate.get('latency_ms') or 0)/1000:.1f}s"
    )

    return {
        "tier": tier["id"],
        "cuts": tier.get("cuts"),
        "case": case["name"],
        "sheet_chars": len(sheet),
        "sheet_tokens_est": len(sheet) // 4,
        "analyser_latency_ms": sheet_result["latency_ms"],
        "generator_latency_ms": candidate.get("latency_ms"),
        "report": report_text,
        "report_chars": len(report_text),
        "generator_error": candidate.get("error"),
        "compliance": compliance.check(sheet, tier),
        "gate": gate.run_gate(report_text),
        "skill_sheet": sheet,
        "total_wall_s": round(time.time() - t0, 1),
    }


def _report_compliance(tier: dict, runs: list[dict]) -> None:
    """Abort signal: per spec section 8, check compliance after T2, not after
    all 25 runs. A budget the model ignores makes the tiers inseparable and
    the experiment meaningless, so it is worth five minutes to find out."""
    rows = [r for r in runs if r.get("tier") == tier["id"] and "compliance" in r]
    if not rows:
        return
    misses = {
        f: [(r["case"], r["compliance"][f]["got"], r["compliance"][f]["want"])
            for r in rows if not r["compliance"][f]["ok"]]
        for f in tiers.BUDGETED_INTS
    }
    misses = {f: v for f, v in misses.items() if v}
    if misses and tier["id"] != "T1":
        print(f"  ⚠ {tier['id']} COMPLIANCE MISS — the model is not honouring the budget:")
        for f, rows_ in misses.items():
            print(f"      {f}: (case, got, want) = {rows_}")
        print("      If this persists, stop and switch to hard section ablation (spec §8).")
    else:
        print(f"  ✓ {tier['id']} compliant")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qwen sheet-budget experiment")
    p.add_argument("--tier", action="append", default=None,
                   help="Filter to tier id(s). Repeatable. Default: all.")
    p.add_argument("--case", action="append", default=None,
                   help="Filter to case name(s). Repeatable. Default: all.")
    p.add_argument("--no-judge", action="store_true",
                   help="Skip the paid v2.2 judge; gate only.")
    p.add_argument("--output-dir", default=None)
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    all_tiers = tiers.load_tiers()
    tiers.validate_tiers(all_tiers)
    if args.tier:
        all_tiers = [t for t in all_tiers if t["id"] in set(args.tier)]
    cases = json.loads(CASES_PATH.read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_ROOT / f"budget_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"tiers: {[t['id'] for t in all_tiers]}")
    print(f"cases: {[c['name'] for c in cases]}")
    print(f"out:   {out_dir}\n")

    tm = TemplateManager()
    runs: list[dict] = []
    for tier in all_tiers:
        for case in cases:
            try:
                runs.append(await run_one(case, tier, tm))
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {tier['id']}/{case['name']} failed: {exc}")
                runs.append({"tier": tier["id"], "case": case["name"], "error": str(exc)})
        _report_compliance(tier, runs)

    if not args.no_judge:
        by_name = {c["name"]: c for c in cases}
        for run in runs:
            if run.get("error") or not run.get("gate", {}).get("passed"):
                continue
            case = by_name[run["case"]]
            run["judge"] = await asyncio.to_thread(
                judge.score_case,
                inputs=judge.format_inputs(
                    scan_type=case["scan_type"],
                    clinical_history=case["clinical_history"],
                    findings=case["findings"],
                ),
                skill_sheet=run["skill_sheet"],
                report=run["report"],
            )
            mean = sum(v["score"] for v in run["judge"].values()) / len(run["judge"])
            print(f"  judged {run['tier']}/{run['case']}  mean {mean:.2f}")

    (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))
    report_mod.write_curve_csv(runs, out_dir / "curve.csv")
    report_mod.write_artifact_html(runs, out_dir / "curve.html")
    print(f"\n✅ {len(runs)} runs → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
