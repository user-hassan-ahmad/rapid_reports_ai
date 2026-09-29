"""Sheet-encoding A/B — does a YAML-encoded sheet change generator cost or quality?

Tests the L-26 prediction on the sheet-encoding axis. L-26 showed generator
reasoning is driven by the clinical task, not input size (removing 89% of the
user prompt moved reasoning -14% / +19%). If that holds, re-encoding the sheet
as YAML should cut sheet tokens but leave generator reasoning — 94% of its
output — unmoved. If reasoning *does* drop with quality parity, the encoding
migration earns its cost. Either way the answer comes from runs, not priors.

Design — the ONLY delta is the sheet encoding:
  - One fresh analyser call (params untouched, reasoning default) produces the
    markdown sheet. Both arms share it. "Full analyse and generate", one delta.
  - The sheet is transcoded markdown -> YAML *deterministically* (no model), so
    arm content is identical by construction and verified by a word-bag check.
  - Arms interleaved A,B,A,B,... so time-of-day API load cannot favour one arm.
  - Reasoning length is stochastic (L-05), so single runs are noise: default
    3 reps per arm.
  - The judge sees the SAME markdown sheet for both arms: content is identical,
    and holding judge inputs constant isolates the generator as the only moving
    part. The YAML sheet is what the *generator* saw in arm B.

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.sheet_encoding_ab
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.sheet_encoding_ab --reps 3
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.sheet_encoding_ab --transcode-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parents[3]
CASES_PATH = BACKEND_ROOT / "test_cases" / "analyser_suite.json"
OUTPUT_ROOT = BACKEND_ROOT / "test_output"
STORED_SHEET_RUNS = OUTPUT_ROOT / "REASONING_CAPFIX" / "runs.json"
MODEL = "qwen/qwen3.8-27b"
DEFAULT_CASE = "ct_tap_acute_abdomen_gda_bleed"


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
from rapid_reports_ai.quick_report_api import _run_one_generator  # noqa: E402
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

from . import gate, judge  # noqa: E402


# ── Instrumentation (capture-only) ───────────────────────────────────────────
# Same wrapping pattern as reasoning_matrix, minus the injection: model params
# stay exactly as production sets them. We only record usage + finish_reason.

_CAPTURED: list[dict] = []
_STAGE: dict[str, str] = {"current": "?"}
_ORIG_RUNNER = eu._run_agent_with_model


async def _instrumented(**kw):
    t0 = time.time()
    result = await _ORIG_RUNNER(**kw)
    rec: dict[str, Any] = {"stage": _STAGE["current"], "model": kw.get("model_name"),
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
    rows = [c for c in _CAPTURED if c["stage"] == stage and c.get("output_tokens")]
    return max(rows, key=lambda c: c["output_tokens"]) if rows else {}


# ── Markdown -> YAML transcoder (deterministic, no model) ────────────────────

_KEYED = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")


def _clean(text: str) -> str:
    return text.replace("**", "").strip()


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _parse_bullets(lines: list[str]) -> list[dict]:
    """Bullet lines -> [{text, children}] tree by indentation (2 spaces/level)."""
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(-1, root)]
    for raw in lines:
        m = re.match(r"^(\s*)-\s+(.*)$", raw)
        if not m:
            # Non-bullet prose inside a section: attach to the last node's text.
            if raw.strip() and stack[-1][1]:
                stack[-1][1][-1]["text"] += " " + raw.strip()
            continue
        indent, text = len(m.group(1)), m.group(2)
        node = {"text": text, "children": []}
        while stack and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((indent, node["children"]))
    return root


def _node_to_obj(node: dict):
    m = _KEYED.match(node["text"])
    if node["children"]:
        children = _children_to_obj(node["children"])
        if m:
            key, val = _key(m.group(1)), _clean(m.group(2))
            # A key with both an inline value and children keeps both.
            return {key: ([val] + children if isinstance(children, list) else
                          {"_": val, **children}) if val else children}
        return {_key(node["text"]) or "items": children}
    if m:
        return {_key(m.group(1)): _clean(m.group(2))}
    return _clean(node["text"])


def _children_to_obj(children: list[dict]):
    objs = [_node_to_obj(c) for c in children]
    # Merge into a mapping when every child is a single-key dict with unique
    # keys — compact and duplicate-safe; otherwise stay a list.
    if all(isinstance(o, dict) and len(o) == 1 for o in objs):
        keys = [next(iter(o)) for o in objs]
        if len(keys) == len(set(keys)):
            merged: dict = {}
            for o in objs:
                merged.update(o)
            return merged
    return objs


def transcode_to_yaml(sheet_md: str) -> str:
    lines = sheet_md.split("\n")
    doc: dict = {}
    section: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if section is not None:
            doc[section] = _children_to_obj(_parse_bullets(buf)) if buf else None
        buf = []

    for line in lines:
        h1 = re.match(r"^#\s+(.*)$", line)
        h2 = re.match(r"^##\s+(.*)$", line)
        if h1:
            doc["title"] = _clean(h1.group(1))
        elif h2:
            flush()
            section = _key(h2.group(1))
        elif section is not None:
            buf.append(line)
    flush()
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          width=4096, default_flow_style=False)


_WORD = re.compile(r"[a-z0-9.]+")


def verify_content(sheet_md: str, sheet_yaml: str) -> dict:
    """Word-bag comparison: the transcode must not lose content."""
    def bag(text: str) -> dict[str, int]:
        text = text.replace("**", " ").replace("_", " ").lower()
        out: dict[str, int] = {}
        for w in _WORD.findall(text):
            out[w] = out.get(w, 0) + 1
        return out

    md, ym = bag(sheet_md), bag(sheet_yaml)
    missing = {w: n - ym.get(w, 0) for w, n in md.items() if ym.get(w, 0) < n}
    total = sum(md.values())
    lost = sum(missing.values())
    return {"total_words": total, "lost_words": lost,
            "loss_pct": round(100 * lost / max(total, 1), 2),
            "missing_sample": dict(list(missing.items())[:10])}


# ── Experiment ───────────────────────────────────────────────────────────────

async def _with_backoff(coro_factory, *, what: str, attempts: int = 3):
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


async def run_generator(case: dict, sheet_for_generator: str, arm: str,
                        rep: int, tm: TemplateManager) -> dict[str, Any]:
    label = f"{arm}#{rep}/{case['name']}"
    _CAPTURED.clear()
    _STAGE["current"] = "generator"
    candidate = await _with_backoff(
        lambda: _run_one_generator(
            tm=tm,
            template_config={
                "generation_mode": "skill_sheet_guided",
                "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + sheet_for_generator,
                "scan_type": case["scan_type"],
            },
            user_inputs={
                "FINDINGS": case["findings"],
                "CLINICAL_HISTORY": case["clinical_history"],
            },
            model_name=MODEL,
            run_id=f"encab-{arm}-{rep}-{new_run_id()}",
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            skill_sheet_markdown=sheet_for_generator,
        ),
        what=f"{label} generator",
    )
    usage = _biggest("generator")
    report_text = candidate.get("content") or ""
    print(f"  [{label}] report {len(report_text):,} ch  "
          f"{(candidate.get('latency_ms') or 0)/1000:.1f}s  "
          f"in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
          f"finish={usage.get('finish_reason')}")
    return {
        "arm": arm,
        "rep": rep,
        "case": case["name"],
        "generator_latency_ms": candidate.get("latency_ms"),
        "generator_usage": usage,
        "generator_finish_reason": usage.get("finish_reason"),
        "generator_error": candidate.get("error"),
        "report": report_text,
        "report_chars": len(report_text),
        "gate": gate.run_gate(report_text),
    }


def _mean(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def summarise(runs: list[dict]) -> dict:
    out: dict = {}
    for arm in ("markdown", "yaml"):
        rows = [r for r in runs if r["arm"] == arm and not r.get("generator_error")]
        judged = [r for r in rows if r.get("judge")]
        dims: dict[str, float | None] = {}
        if judged:
            for d in judged[0]["judge"]:
                dims[d] = _mean([r["judge"][d]["score"] for r in judged])
        out[arm] = {
            "n": len(rows),
            "gen_latency_s": _mean([(r["generator_latency_ms"] or 0) / 1000 for r in rows]),
            "input_tokens": _mean([r["generator_usage"].get("input_tokens") for r in rows]),
            "output_tokens": _mean([r["generator_usage"].get("output_tokens") for r in rows]),
            "report_chars": _mean([r["report_chars"] for r in rows]),
            "gate_pass": sum(1 for r in rows if r["gate"].get("passed")),
            "finish": [r.get("generator_finish_reason") for r in rows],
            "judge_dims": dims,
            "judge_mean": _mean([s for s in dims.values() if s is not None]) if dims else None,
        }
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sheet-encoding A/B (markdown vs YAML)")
    p.add_argument("--case", default=DEFAULT_CASE)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--transcode-only", action="store_true",
                   help="No API calls: transcode the stored REASONING_CAPFIX "
                        "sheet for --case, print verification, exit.")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    cases = json.loads(CASES_PATH.read_text())
    case = next((c for c in cases if c["name"] == args.case), None)
    if case is None:
        print(f"unknown case {args.case!r}; have {[c['name'] for c in cases]}")
        return 1

    if args.transcode_only:
        stored = json.loads(STORED_SHEET_RUNS.read_text())
        row = next(r for r in stored
                   if r["case"] == args.case and r["cell"] == "on_on")
        sheet_md = row["skill_sheet"]
        sheet_yaml = transcode_to_yaml(sheet_md)
        check = verify_content(sheet_md, sheet_yaml)
        print(f"markdown: {len(sheet_md):,} ch (~{len(sheet_md)//4:,} tok)")
        print(f"yaml:     {len(sheet_yaml):,} ch (~{len(sheet_yaml)//4:,} tok)  "
              f"delta {100*(len(sheet_yaml)-len(sheet_md))/len(sheet_md):+.1f}%")
        print(f"content check: {check}")
        print("\n--- YAML (first 60 lines) ---")
        print("\n".join(sheet_yaml.split("\n")[:60]))
        return 0

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = OUTPUT_ROOT / f"ENCODING_AB_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"case: {case['name']}  reps/arm: {args.reps}  out: {out_dir}\n")

    # One shared analyser call — the full pipeline's first stage, params untouched.
    _CAPTURED.clear()
    _STAGE["current"] = "analyser"
    t0 = time.time()
    sheet_result = await _with_backoff(
        lambda: generate_ephemeral_skill_sheet(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            api_key="",  # groq path resolves GROQ_API_KEY itself
            model_override=MODEL,
        ),
        what="analyser",
    )
    sheet_md = sheet_result["skill_sheet"]
    analyser_usage = _biggest("analyser")
    print(f"analyser: {len(sheet_md):,} ch in {time.time()-t0:.1f}s  "
          f"out={analyser_usage.get('output_tokens')} tok\n")

    sheet_yaml = transcode_to_yaml(sheet_md)
    check = verify_content(sheet_md, sheet_yaml)
    print(f"markdown sheet: {len(sheet_md):,} ch (~{len(sheet_md)//4:,} tok)")
    print(f"yaml sheet:     {len(sheet_yaml):,} ch (~{len(sheet_yaml)//4:,} tok)  "
          f"delta {100*(len(sheet_yaml)-len(sheet_md))/len(sheet_md):+.1f}%")
    print(f"content check:  {check}\n")
    if check["loss_pct"] > 1.0:
        print("✗ transcode lost >1% of content — aborting rather than test a broken arm")
        return 1
    (out_dir / "sheet.md").write_text(sheet_md)
    (out_dir / "sheet.yaml").write_text(sheet_yaml)

    tm = TemplateManager()
    runs: list[dict] = []
    for rep in range(1, args.reps + 1):
        for arm, sheet in (("markdown", sheet_md), ("yaml", sheet_yaml)):
            try:
                runs.append(await run_generator(case, sheet, arm, rep, tm))
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {arm}#{rep} failed: {exc}")
                runs.append({"arm": arm, "rep": rep, "case": case["name"],
                             "generator_error": str(exc)})

    if not args.no_judge:
        inputs = judge.format_inputs(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            findings=case["findings"],
        )
        for run in runs:
            if run.get("generator_error") or not run.get("gate", {}).get("passed"):
                continue
            # Judge context uses the markdown sheet for BOTH arms: content is
            # identical, and constant judge inputs isolate the generator delta.
            run["judge"] = await asyncio.to_thread(
                judge.score_case, inputs=inputs,
                skill_sheet=sheet_md, report=run["report"],
            )
            mean = sum(v["score"] for v in run["judge"].values()) / len(run["judge"])
            print(f"  judged {run['arm']}#{run['rep']}  mean {mean:.2f}")

    summary = summarise(runs)
    result = {
        "case": case["name"],
        "model": MODEL,
        "analyser": {"sheet_chars": len(sheet_md),
                     "latency_ms": sheet_result.get("latency_ms"),
                     "usage": analyser_usage},
        "transcode": {"yaml_chars": len(sheet_yaml), "check": check},
        "summary": summary,
        "runs": runs,
    }
    (out_dir / "runs.json").write_text(json.dumps(result, indent=2))

    print("\n════ SUMMARY ════")
    for arm, s in summary.items():
        print(f"\n  {arm}  (n={s['n']}, gate {s['gate_pass']}/{s['n']})")
        print(f"    gen latency   {s['gen_latency_s']}s")
        print(f"    input tokens  {s['input_tokens']}")
        print(f"    output tokens {s['output_tokens']}   finish={s['finish']}")
        print(f"    report chars  {s['report_chars']}")
        print(f"    judge         {s['judge_dims']}  mean={s['judge_mean']}")
    print(f"\n✅ → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
