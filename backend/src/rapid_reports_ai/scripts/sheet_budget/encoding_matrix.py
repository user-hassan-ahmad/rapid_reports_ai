"""Encoding experiment — can stated directives replace analyser reasoning?

Narrow by design. Everything already decided is dropped:
  - generator reasoning stays ON (L-09/L-12: removing it costs output_adherence
    4.80 -> 4.00 and normal_fill 5.00 -> 4.40, and the radiologist preferred the
    reasoning-on prose);
  - sheet-budget tiers are settled (L-01/L-02);
  - the generator output cap is fixed (L-10).

One live question remains: L-17 measured three specifiable differences between
reasoning-on and reasoning-off sheets — sweep exhaustiveness, general vs
case-keyed suppression rules, and the defeasibility clause on normal-fill. If
those are stated outright, does a reasoning-OFF analyser close the gap?

Two cells, tested against baselines already collected:
  enc_a   analyser OFF + integrity directives          generator unchanged
  enc_ag  analyser OFF + integrity directives          generator + floor rule

Baselines for comparison (no re-run needed):
  off_on  analyser OFF, no directives   -> test_output/REASONING_CAPFIX
  on_on   analyser ON,  no directives   -> test_output/REASONING_CAPFIX

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.encoding_matrix
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.encoding_matrix --no-judge
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
MODEL = "qwen/qwen3.6-27b"

# Injected into the generator's user prompt. A floor on inclusion, not a
# constraint on judgement: the generator keeps discretion over placement and
# emphasis, and over whether an item earns an impression line. What it loses is
# discretion over whether a dictated finding appears at all — which is what was
# silently exercised when the adrenal nodule was planned and then dropped (L-16).
GENERATOR_FLOOR_RULE = """

## Inclusion floor — mandatory

No dictated finding may be silently dropped. Every finding present in the dictation must appear
somewhere in the report. If a dictated finding maps to no station in the sweep order, place it in a
terminal sentence covering incidental and secondary observations rather than omitting it.

Whether a finding additionally earns a line in the IMPRESSION — and whether that line carries a
recommendation — remains your judgement under the descriptor propagation rule. Placement, emphasis
and impression-worthiness are yours to decide. Inclusion is not.
"""

CELLS = [
    {"id": "enc_a",  "integrity": True, "floor": False, "label": "analyser directives"},
    {"id": "enc_ag", "integrity": True, "floor": True,  "label": "analyser directives + generator floor"},
]


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

from rapid_reports_ai import enhancement_utils as eu  # noqa: E402
from rapid_reports_ai import template_manager as tmod  # noqa: E402
from rapid_reports_ai.quick_report_analyser import (  # noqa: E402
    generate_ephemeral_skill_sheet,
)
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

from . import gate, judge, report as report_mod  # noqa: E402

_CAPTURED: list[dict] = []
_STATE: dict[str, Any] = {"stage": "?", "floor": False}
_ORIG = eu._run_agent_with_model


async def _instrumented(**kw):
    """Force analyser reasoning off, append the generator floor rule, record usage."""
    stage = _STATE["stage"]
    if kw.get("model_name") == MODEL:
        settings = dict(kw.get("model_settings") or {})
        extra = dict(settings.get("extra_body") or {})
        if stage == "analyser":
            extra["reasoning_effort"] = "none"   # generator keeps reasoning on
            settings["extra_body"] = extra
            kw["model_settings"] = settings
        elif stage == "generator" and _STATE["floor"]:
            kw["user_prompt"] = (kw.get("user_prompt") or "") + GENERATOR_FLOOR_RULE

    t0 = time.time()
    result = await _ORIG(**kw)
    rec: dict[str, Any] = {"stage": stage, "latency_s": round(time.time() - t0, 2)}
    try:
        u = result.usage()
        rec["output_tokens"] = getattr(u, "output_tokens", None)
        rec["input_tokens"] = getattr(u, "input_tokens", None)
    except Exception:  # noqa: BLE001
        pass
    try:
        rec["finish_reason"] = result.all_messages()[-1].finish_reason
    except Exception:  # noqa: BLE001
        rec["finish_reason"] = None
    _CAPTURED.append(rec)
    return result


eu._run_agent_with_model = _instrumented
tmod._run_agent_with_model = _instrumented


def _biggest(stage: str) -> dict:
    rows = [c for c in _CAPTURED if c["stage"] == stage and c.get("output_tokens")]
    return max(rows, key=lambda c: c["output_tokens"]) if rows else {}


async def run_one(case: dict, cell: dict, tm: TemplateManager) -> dict[str, Any]:
    _CAPTURED.clear()
    _STATE["floor"] = cell["floor"]
    label = f"{cell['id']}/{case['name']}"

    _STATE["stage"] = "analyser"
    t0 = time.time()
    sheet_result = await generate_ephemeral_skill_sheet(
        scan_type=case["scan_type"], clinical_history=case["clinical_history"],
        api_key="", model_override=MODEL, integrity=cell["integrity"],
    )
    sheet = sheet_result["skill_sheet"]
    a = _biggest("analyser")
    print(f"  [{label}] sheet {len(sheet):,}ch {sheet_result['latency_ms']/1000:.1f}s "
          f"out={a.get('output_tokens')} finish={a.get('finish_reason')}")

    _STATE["stage"] = "generator"
    g0 = time.time()
    try:
        res = await tm.generate_report_from_config(
            template_config={
                "generation_mode": "skill_sheet_guided",
                "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + sheet,
                "scan_type": case["scan_type"],
            },
            user_inputs={"FINDINGS": case["findings"],
                         "CLINICAL_HISTORY": case["clinical_history"]},
            model_override=MODEL,
        )
        report_text = res.get("report_content", "") or ""
        err = None
    except Exception as exc:  # noqa: BLE001
        report_text, err = "", str(exc)
    gen_ms = int((time.time() - g0) * 1000)
    g = _biggest("generator")
    print(f"  [{label}] report {len(report_text):,}ch {gen_ms/1000:.1f}s "
          f"out={g.get('output_tokens')} finish={g.get('finish_reason')}")

    return {
        "cell": cell["id"], "cell_label": cell["label"], "case": case["name"],
        "integrity": cell["integrity"], "floor": cell["floor"],
        "sheet_chars": len(sheet), "report_chars": len(report_text),
        "analyser_latency_ms": sheet_result["latency_ms"], "generator_latency_ms": gen_ms,
        "analyser_usage": a, "generator_usage": g,
        "generator_finish_reason": g.get("finish_reason"),
        "generator_error": err,
        "gate": gate.run_gate(report_text),
        "report": report_text, "skill_sheet": sheet,
        "total_wall_s": round(time.time() - t0, 1),
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qwen directive-encoding experiment")
    p.add_argument("--cell", action="append", default=None)
    p.add_argument("--case", action="append", default=None)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--output-dir", default=None)
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    cells = [c for c in CELLS if not args.cell or c["id"] in set(args.cell)]
    cases = json.loads(CASES_PATH.read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_ROOT / f"encoding_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"cells: {[c['id'] for c in cells]}\ncases: {len(cases)}\nout:   {out_dir}\n")

    tm = TemplateManager()
    runs: list[dict] = []
    for cell in cells:
        print(f"--- {cell['id']}  ({cell['label']}) ---")
        for case in cases:
            try:
                runs.append(await run_one(case, cell, tm))
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {cell['id']}/{case['name']}: {exc}")
                runs.append({"cell": cell["id"], "case": case["name"], "error": str(exc)})
        print()

    if not args.no_judge:
        by_name = {c["name"]: c for c in cases}
        for run in runs:
            if run.get("error") or not run.get("gate", {}).get("passed"):
                continue
            c = by_name[run["case"]]
            run["judge"] = await asyncio.to_thread(
                judge.score_case,
                inputs=judge.format_inputs(scan_type=c["scan_type"],
                                           clinical_history=c["clinical_history"],
                                           findings=c["findings"]),
                skill_sheet=run["skill_sheet"], report=run["report"])
            mean = sum(v["score"] for v in run["judge"].values()) / len(run["judge"])
            print(f"  judged {run['cell']}/{run['case']}  mean {mean:.2f}")

    (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))
    for r in runs:
        r["tier"] = r.get("cell")
        if "sheet_chars" in r:
            r["sheet_tokens_est"] = r["sheet_chars"] // 4
    report_mod.write_curve_csv(runs, out_dir / "matrix.csv")
    print(f"\n✅ {len(runs)} runs → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
