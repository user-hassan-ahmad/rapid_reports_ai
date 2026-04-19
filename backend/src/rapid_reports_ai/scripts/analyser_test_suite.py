"""Analyser test suite — fan a test case across all analyser variants in
parallel and produce structured comparison output.

For each test case in ``backend/test_cases/analyser_suite.json``:
  1. Generate a skill sheet against each of the active analyser variants
     (GLM + Haiku, with Sonnet optional for heavier comparisons) — in parallel.
  2. For each resulting skill sheet, run the dual-model generator
     (GLM + Sonnet) against it — also in parallel.
  3. Persist all skill sheets and reports to a timestamped output folder
     plus a summary markdown and metrics CSV for side-by-side comparison.

Usage:
    poetry run python -m rapid_reports_ai.scripts.analyser_test_suite
    poetry run python -m rapid_reports_ai.scripts.analyser_test_suite --case ct_head_cerebellar_haemorrhage
    poetry run python -m rapid_reports_ai.scripts.analyser_test_suite --variants zai-glm-4.7 claude-haiku-4-5-20251001

Outputs:
    backend/test_output/<timestamp>/
        case_<name>.json      full structured data per case
        summary.md            human-readable side-by-side comparison
        metrics.csv           latency / length / clause-count metrics
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repository roots
SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent  # rapid_reports_ai/
SRC_ROOT = PACKAGE_ROOT.parent  # src/
BACKEND_ROOT = SRC_ROOT.parent  # backend/
TEST_CASES_PATH = BACKEND_ROOT / "test_cases" / "analyser_suite.json"
TEST_OUTPUT_ROOT = BACKEND_ROOT / "test_output"


def _load_dotenv_into_env() -> None:
    """Manually parse backend/.env into os.environ — robust against shell
    invocation and not-installed dotenv.

    Uses set-if-empty semantics rather than setdefault: if the parent shell
    exported a key as an empty string (a common cause of "API key not
    configured" failures), we still load the .env value. Existing non-empty
    values from the shell take precedence (so explicit overrides work)."""
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'\"")
        if not os.environ.get(k):
            os.environ[k] = v


_load_dotenv_into_env()

# Imports must come after .env load so module-level env reads work.
from rapid_reports_ai.quick_report_analyser import (  # noqa: E402
    generate_ephemeral_skill_sheet,
    new_run_id,
)
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.quick_report_api import _run_one_generator  # noqa: E402
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Variants tested. Each one invokes a different analyser model + prompt combo.
# Adding a variant: append the model identifier (must be registered in
# MODEL_PROVIDERS in enhancement_utils.py).
# ─────────────────────────────────────────────────────────────────────────────

# Default analyser variants — the two production paths. Sonnet is kept available
# via `--variants` for reference-quality comparison runs but is not default.
ANALYSER_VARIANTS: list[str] = [
    "zai-glm-4.7",                  # Cerebras GLM — FAST production path
    "claude-haiku-4-5-20251001",    # Anthropic Haiku 4.5 — BEST production path
]

# Default generator — single GLM, matching production. Sonnet generator was
# dropped; available via `--generators` flag for side-by-side comparison.
GENERATOR_MODELS: list[str] = [
    "zai-glm-4.7",
]


# ─────────────────────────────────────────────────────────────────────────────
# Per-case execution
# ─────────────────────────────────────────────────────────────────────────────

async def _run_one_variant(
    case: dict[str, str],
    analyser_model: str,
    cerebras_api_key: str,
) -> dict[str, Any]:
    """Run one analyser variant + dual-model generator chain for one case.

    Returns a dict with the analyser result and both candidate reports, or
    an error record if any stage failed.
    """
    variant_t0 = time.time()
    print(f"  [{case['name']} / {analyser_model}] starting...")

    # --- Step 1: analyser ---------------------------------------------------
    try:
        sheet_result = await generate_ephemeral_skill_sheet(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            api_key=cerebras_api_key,
            model_override=analyser_model,
        )
    except Exception as e:
        print(f"  ⚠ [{case['name']} / {analyser_model}] analyser failed: {e}")
        return {
            "analyser_model": analyser_model,
            "stage": "analyser",
            "error": str(e),
            "total_latency_ms": int((time.time() - variant_t0) * 1000),
        }

    skill_sheet_md = sheet_result["skill_sheet"]
    print(
        f"  ✓ [{case['name']} / {analyser_model}] analyser done "
        f"({sheet_result['latency_ms']/1000:.1f}s, {len(skill_sheet_md):,} chars)"
    )

    # --- Step 2: dual-model generator --------------------------------------
    tm = TemplateManager()
    template_config = {
        "generation_mode": "skill_sheet_guided",
        "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + skill_sheet_md,
        "scan_type": case["scan_type"],
    }
    user_inputs = {
        "FINDINGS": case["findings"],
        "CLINICAL_HISTORY": case["clinical_history"],
    }
    run_id_base = f"test-{case['name']}-{analyser_model[:10].replace('/', '-')}-{new_run_id()}"

    candidate_tasks = [
        _run_one_generator(
            tm=tm,
            template_config=template_config,
            user_inputs=user_inputs,
            model_name=gen_model,
            run_id=f"{run_id_base}-{gen_model[:8].replace('/', '-')}",
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            skill_sheet_markdown=skill_sheet_md,
        )
        for gen_model in GENERATOR_MODELS
    ]
    candidates = await asyncio.gather(*candidate_tasks, return_exceptions=True)

    # Normalise exceptions to candidate-error records so the JSON shape is
    # uniform whether a generator succeeds or fails.
    norm_candidates: list[dict[str, Any]] = []
    for gm, c in zip(GENERATOR_MODELS, candidates):
        if isinstance(c, Exception):
            norm_candidates.append({
                "model": gm,
                "content": "",
                "error": str(c),
                "latency_ms": None,
            })
        else:
            norm_candidates.append(c)

    total_latency_ms = int((time.time() - variant_t0) * 1000)
    print(
        f"  ✓ [{case['name']} / {analyser_model}] complete "
        f"(total {total_latency_ms/1000:.1f}s)"
    )

    return {
        "analyser_model": analyser_model,
        "analyser_latency_ms": sheet_result["latency_ms"],
        "analyser_prompt_version": sheet_result.get("prompt_version"),
        "analyser_prompt_chars": sheet_result.get("prompt_chars"),
        "skill_sheet": skill_sheet_md,
        "skill_sheet_chars": len(skill_sheet_md),
        "candidate_reports": norm_candidates,
        "total_latency_ms": total_latency_ms,
    }


async def run_case(case: dict[str, str], variants: list[str]) -> dict[str, Any]:
    """Fan a single case across every variant in parallel and gather results."""
    print(f"\n{'='*80}\nCASE: {case['name']}  ({case['scan_type']})\n{'='*80}")
    cerebras_key = os.environ.get("CEREBRAS_API_KEY", "")

    variant_tasks = [
        _run_one_variant(case, v, cerebras_key) for v in variants
    ]
    variant_results = await asyncio.gather(*variant_tasks, return_exceptions=True)

    norm_variants: list[dict[str, Any]] = []
    for v, r in zip(variants, variant_results):
        if isinstance(r, Exception):
            norm_variants.append({
                "analyser_model": v,
                "stage": "outer",
                "error": str(r),
            })
        else:
            norm_variants.append(r)

    return {
        "case_name": case["name"],
        "scan_type": case["scan_type"],
        "clinical_history": case["clinical_history"],
        "findings": case["findings"],
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "variants": norm_variants,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Output writers
# ─────────────────────────────────────────────────────────────────────────────

def _write_case_json(case_result: dict[str, Any], output_dir: Path) -> None:
    path = output_dir / f"case_{case_result['case_name']}.json"
    path.write_text(json.dumps(case_result, indent=2))


def _write_summary_markdown(all_results: list[dict[str, Any]], output_dir: Path) -> None:
    """Write a concise side-by-side summary across cases × variants."""
    lines: list[str] = []
    lines.append(f"# Analyser Test Suite — {output_dir.name}")
    lines.append("")
    lines.append(f"**Cases run:** {len(all_results)}")
    lines.append(f"**Variants:** {', '.join(ANALYSER_VARIANTS)}")
    lines.append(f"**Generator models per sheet:** {', '.join(GENERATOR_MODELS)}")
    # Prompt versions — one row per variant, pinned at the top so regressions
    # can be traced to specific prompt edits from the suite output alone.
    pv_seen: dict[str, str] = {}
    for case in all_results:
        for v in case.get("variants", []):
            pv = v.get("analyser_prompt_version")
            m = v.get("analyser_model")
            if pv and m and m not in pv_seen:
                pv_seen[m] = pv
    if pv_seen:
        lines.append("**Analyser prompt versions:** " + "; ".join(
            f"{m}={pv}" for m, pv in pv_seen.items()
        ))
    lines.append("")

    # Latency table
    lines.append("## Analyser latency (s)")
    lines.append("")
    header = "| Case | " + " | ".join(ANALYSER_VARIANTS) + " |"
    sep = "|---|" + "|".join(["---"] * len(ANALYSER_VARIANTS)) + "|"
    lines.append(header)
    lines.append(sep)
    for case in all_results:
        row = [case["case_name"]]
        v_by_model = {v["analyser_model"]: v for v in case["variants"]}
        for variant in ANALYSER_VARIANTS:
            v = v_by_model.get(variant)
            if v and "analyser_latency_ms" in v:
                row.append(f"{v['analyser_latency_ms']/1000:.1f}")
            elif v and "error" in v:
                row.append("ERR")
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Sheet length table
    lines.append("## Skill sheet length (chars)")
    lines.append("")
    lines.append(header)
    lines.append(sep)
    for case in all_results:
        row = [case["case_name"]]
        v_by_model = {v["analyser_model"]: v for v in case["variants"]}
        for variant in ANALYSER_VARIANTS:
            v = v_by_model.get(variant)
            if v and "skill_sheet_chars" in v:
                row.append(f"{v['skill_sheet_chars']:,}")
            elif v and "error" in v:
                row.append("ERR")
            else:
                row.append("—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Generator latency tables (per generator model, separate tables)
    for gen_model in GENERATOR_MODELS:
        lines.append(f"## Generator latency for {gen_model} (s) — by analyser variant")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for case in all_results:
            row = [case["case_name"]]
            v_by_model = {v["analyser_model"]: v for v in case["variants"]}
            for variant in ANALYSER_VARIANTS:
                v = v_by_model.get(variant)
                if not v or "candidate_reports" not in v:
                    row.append("—")
                    continue
                cand = next(
                    (c for c in v["candidate_reports"] if c.get("model") == gen_model),
                    None,
                )
                if cand and cand.get("latency_ms") is not None:
                    row.append(f"{cand['latency_ms']/1000:.1f}")
                else:
                    row.append("ERR")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("## Per-case JSON files")
    lines.append("")
    for case in all_results:
        lines.append(f"- `case_{case['case_name']}.json`")
    lines.append("")

    (output_dir / "summary.md").write_text("\n".join(lines))


def _write_metrics_csv(all_results: list[dict[str, Any]], output_dir: Path) -> None:
    """Tabular metrics for downstream programmatic analysis."""
    rows: list[dict[str, Any]] = []
    for case in all_results:
        for variant in case["variants"]:
            base = {
                "case_name": case["case_name"],
                "scan_type": case["scan_type"],
                "analyser_model": variant.get("analyser_model"),
                "analyser_prompt_version": variant.get("analyser_prompt_version"),
                "analyser_latency_ms": variant.get("analyser_latency_ms"),
                "skill_sheet_chars": variant.get("skill_sheet_chars"),
                "total_latency_ms": variant.get("total_latency_ms"),
                "analyser_error": variant.get("error") if "skill_sheet" not in variant else None,
            }
            for cand in variant.get("candidate_reports") or []:
                rows.append({
                    **base,
                    "generator_model": cand.get("model"),
                    "generator_latency_ms": cand.get("latency_ms"),
                    "generator_content_chars": len(cand.get("content") or ""),
                    "generator_error": cand.get("error"),
                })
            if not variant.get("candidate_reports"):
                rows.append({
                    **base,
                    "generator_model": None,
                    "generator_latency_ms": None,
                    "generator_content_chars": None,
                    "generator_error": None,
                })

    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with (output_dir / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyser test suite")
    p.add_argument(
        "--case",
        action="append",
        default=None,
        help="Filter to specific case name(s). Repeatable. Default: all.",
    )
    p.add_argument(
        "--variants",
        nargs="+",
        default=None,
        help=f"Filter to specific analyser variant(s). Default: {ANALYSER_VARIANTS}.",
    )
    p.add_argument(
        "--generators",
        nargs="+",
        default=None,
        help=f"Generator model(s) per sheet. Default: {GENERATOR_MODELS}. "
             "Add 'claude-sonnet-4-6' for side-by-side comparison runs.",
    )
    p.add_argument(
        "--cases-file",
        default=str(TEST_CASES_PATH),
        help=f"Path to test cases JSON file. Default: {TEST_CASES_PATH.name}. "
             "Use 'test_cases/quick_eval.json' for a 3-case basket.",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory. Default: backend/test_output/<timestamp>/",
    )
    return p.parse_args()


async def main() -> int:
    args = _parse_args()

    cases = json.loads(Path(args.cases_file).read_text())
    if args.case:
        wanted = set(args.case)
        cases = [c for c in cases if c["name"] in wanted]
        if not cases:
            print(f"ERROR: no cases matched filter {sorted(wanted)}", file=sys.stderr)
            return 2

    variants = args.variants or ANALYSER_VARIANTS
    # Override the module-level default with the CLI selection so downstream
    # output writers (summary.md, metrics.csv) use the active generator set.
    if args.generators:
        GENERATOR_MODELS[:] = args.generators

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else (TEST_OUTPUT_ROOT / timestamp)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Analyser test suite")
    print(f"  cases:    {[c['name'] for c in cases]}")
    print(f"  variants: {variants}")
    print(f"  output:   {output_dir}")

    all_results: list[dict[str, Any]] = []
    for case in cases:
        case_t0 = time.time()
        result = await run_case(case, variants)
        case_total_s = time.time() - case_t0
        print(f"\n→ Case {case['name']} done in {case_total_s:.1f}s wall time")
        _write_case_json(result, output_dir)
        all_results.append(result)

    _write_summary_markdown(all_results, output_dir)
    _write_metrics_csv(all_results, output_dir)

    print(f"\n✅ Wrote {len(all_results)} case file(s), summary.md, and metrics.csv")
    print(f"   → {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
