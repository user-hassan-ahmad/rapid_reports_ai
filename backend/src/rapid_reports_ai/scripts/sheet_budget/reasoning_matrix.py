"""Reasoning on/off matrix — analyser x generator.

Reasoning is 93-95% of every Qwen generation, and `reasoning_effort` is binary
for this model on Groq (`none` | `default`; low/medium/high are GPT-OSS-only).
A probe on 2026-08-12 measured 750 output tokens / 3.0s with reasoning default
against 38 tokens / 0.2s with it off, so this is the largest available lever.

Reasoning can be disabled independently at each stage, so this runs the 2x2
rather than a single both-off comparison: the analyser's latency hides behind
dictation, so if the generator's reasoning is the expensive one and the
analyser's is the useful one, that asymmetry is the result we want.

Also captures `finish_reason` and per-call token usage, absent from the
sheet-budget runner. That is the diagnostic for ledger item L-05, the
unexplained 12% intermittent truncation: `finish_reason == "length"` would
confirm a cap, anything else rules it out.

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.reasoning_matrix
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.reasoning_matrix --no-judge
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.reasoning_matrix --cell off_off
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

MODEL = "qwen/qwen3.8-27b"  # default; override with --model (e.g. qwen-3.8-27b on Cerebras)

# The 2x2. `None` means leave the provider default (reasoning on).
CELLS = [
    {"id": "on_on",   "analyser": None,   "generator": None,   "label": "control"},
    {"id": "on_off",  "analyser": None,   "generator": "none", "label": "generator reasoning off"},
    {"id": "off_on",  "analyser": "none", "generator": None,   "label": "analyser reasoning off"},
    {"id": "off_off", "analyser": "none", "generator": "none", "label": "both off"},
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
    new_run_id,
)
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

from . import gate, judge, report as report_mod  # noqa: E402


# ── Instrumentation ──────────────────────────────────────────────────────────
# The production call sites do not surface usage or finish_reason, and threading
# them through would change signatures used by live routes. Wrapping the shared
# agent runner keeps the experiment's observability entirely inside this module.

_CAPTURED: list[dict] = []
_REASONING: dict[str, str | None] = {"analyser": None, "generator": None}
_MAX_TOKENS: dict[str, int | None] = {"override": None}
_DIRECTIVES: dict[str, list[str]] = {"names": []}
_STAGE: dict[str, str] = {"current": "?"}
_ORIG_RUNNER = eu._run_agent_with_model


async def _instrumented(**kw):
    """Inject reasoning_effort for the active stage and record what came back."""
    stage = _STAGE["current"]
    effort = _REASONING.get(stage)
    if effort is not None and kw.get("model_name") == MODEL:
        settings = dict(kw.get("model_settings") or {})
        extra = dict(settings.get("extra_body") or {})
        extra["reasoning_effort"] = effort
        settings["extra_body"] = extra
        kw["model_settings"] = settings
    if _MAX_TOKENS["override"] and kw.get("model_name") == MODEL:
        # Qwen 3.8 on Cerebras reasons past the 16k production cap; a `length`
        # finish with empty content makes pydantic-ai retry, so usage() sums
        # 2-3 attempts and the surviving sheet can be cut mid-sentence.
        settings = dict(kw.get("model_settings") or {})
        settings["max_tokens"] = _MAX_TOKENS["override"]
        kw["model_settings"] = settings

    t0 = time.time()
    result = await _ORIG_RUNNER(**kw)
    rec: dict[str, Any] = {"stage": stage, "model": kw.get("model_name"),
                           "latency_s": round(time.time() - t0, 2)}
    try:
        u = result.usage()
        rec["input_tokens"] = getattr(u, "input_tokens", None)
        rec["output_tokens"] = getattr(u, "output_tokens", None)
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
    """The stage's main call - the description sub-call is far smaller."""
    rows = [c for c in _CAPTURED if c["stage"] == stage and c.get("output_tokens")]
    return max(rows, key=lambda c: c["output_tokens"]) if rows else {}


async def run_one(case: dict, cell: dict, tm: TemplateManager) -> dict[str, Any]:
    _CAPTURED.clear()
    _REASONING["analyser"] = cell["analyser"]
    _REASONING["generator"] = cell["generator"]
    label = f"{cell['id']}/{case['name']}"

    _STAGE["current"] = "analyser"
    t0 = time.time()
    sheet_result = await generate_ephemeral_skill_sheet(
        scan_type=case["scan_type"], clinical_history=case["clinical_history"],
        api_key="", model_override=MODEL,
        directives=tuple(_DIRECTIVES["names"]) if _DIRECTIVES["names"] else None,
    )
    sheet = sheet_result["skill_sheet"]
    a_usage = _biggest("analyser")
    print(f"  [{label}] sheet {len(sheet):,}ch  {sheet_result['latency_ms']/1000:.1f}s  "
          f"out={a_usage.get('output_tokens')}  finish={a_usage.get('finish_reason')}")

    _STAGE["current"] = "generator"
    gen_t0 = time.time()
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
        gen_error = None
    except Exception as exc:  # noqa: BLE001
        report_text, gen_error = "", str(exc)
    gen_ms = int((time.time() - gen_t0) * 1000)
    g_usage = _biggest("generator")
    print(f"  [{label}] report {len(report_text):,}ch  {gen_ms/1000:.1f}s  "
          f"out={g_usage.get('output_tokens')}  finish={g_usage.get('finish_reason')}")

    return {
        "cell": cell["id"], "cell_label": cell["label"], "case": case["name"],
        "analyser_reasoning": cell["analyser"] or "default",
        "generator_reasoning": cell["generator"] or "default",
        "sheet_chars": len(sheet), "report_chars": len(report_text),
        "analyser_latency_ms": sheet_result["latency_ms"], "generator_latency_ms": gen_ms,
        "analyser_usage": a_usage, "generator_usage": g_usage,
        "analyser_finish_reason": a_usage.get("finish_reason"),
        "generator_finish_reason": g_usage.get("finish_reason"),
        "generator_error": gen_error,
        "gate": gate.run_gate(report_text),
        "report": report_text, "skill_sheet": sheet,
        "total_wall_s": round(time.time() - t0, 1),
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qwen reasoning on/off matrix")
    p.add_argument("--cell", action="append", default=None,
                   help="Filter to cell id(s): on_on, on_off, off_on, off_off. Repeatable.")
    p.add_argument("--case", action="append", default=None, help="Filter to case name(s).")
    p.add_argument("--cases-file", default=None, help="Case corpus JSON (default test_cases/analyser_suite.json).")
    p.add_argument("--no-judge", action="store_true", help="Skip the paid v2.2 judge.")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--model", default=None,
                   help="Model id for both stages (must be in MODEL_PROVIDERS). Default qwen/qwen3.8-27b on Groq.")
    p.add_argument("--runs", type=int, default=1, help="Repeat each cell x case N times.")
    p.add_argument("--effort", default=None,
                   help="reasoning_effort for every stage marked 'on' (Cerebras: low/medium/high; default = provider default).")
    p.add_argument("--directive", action="append", default=None,
                   help="Named analyser directive(s) from quick_report_analyser.DIRECTIVES, e.g. prune_v1. Repeatable.")
    p.add_argument("--max-tokens", type=int, default=None,
                   help="Override max_tokens on both stages for --model (Cerebras accepts up to 131072).")
    return p.parse_args()


async def main() -> int:
    global MODEL
    args = _parse_args()
    if args.model:
        MODEL = args.model
    _MAX_TOKENS["override"] = args.max_tokens
    _DIRECTIVES["names"] = list(args.directive or [])
    cells = [dict(c) for c in CELLS if not args.cell or c["id"] in set(args.cell)]
    if args.effort:
        for c in cells:
            for stage in ("analyser", "generator"):
                if c[stage] is None:
                    c[stage] = args.effort
            c["id"] = f"{c['id']}@{args.effort}"
    cases = json.loads(Path(args.cases_file).read_text() if args.cases_file else CASES_PATH.read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_ROOT / f"reasoning_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"model: {MODEL} ({eu._get_model_provider(MODEL)})\ncells: {[c['id'] for c in cells]}\n"
          f"cases: {len(cases)}\nruns:  {args.runs}\nmax_tokens: {args.max_tokens or 'production default'}\nout:   {out_dir}\n")

    tm = TemplateManager()
    runs: list[dict] = []
    for cell in cells:
        print(f"--- {cell['id']}  ({cell['label']}) ---")
        for case in cases:
            for i in range(args.runs):
                try:
                    r = await run_one(case, cell, tm)
                    r["run_index"] = i
                    r["model"] = MODEL
                    r["max_tokens_override"] = args.max_tokens
                    r["effort"] = args.effort
                    r["directives"] = list(args.directive or [])
                    runs.append(r)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ✗ {cell['id']}/{case['name']} run {i}: {exc}")
                    runs.append({"cell": cell["id"], "case": case["name"], "run_index": i,
                                 "model": MODEL, "error": str(exc)})
        print()

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
                skill_sheet=run["skill_sheet"], report=run["report"],
            )
            mean = sum(v["score"] for v in run["judge"].values()) / len(run["judge"])
            print(f"  judged {run['cell']}/{run['case']}  mean {mean:.2f}")

    (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))
    # Reuse the sheet-budget emitters by mapping cell -> tier and sheet -> tokens.
    for r in runs:
        r["tier"] = r.get("cell")
        if "sheet_chars" in r:
            r["sheet_tokens_est"] = r["sheet_chars"] // 4
    report_mod.write_curve_csv(runs, out_dir / "matrix.csv")
    print(f"\n✅ {len(runs)} runs → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
