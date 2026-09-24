"""Bundle parity: does asking every per-utterance question in one Jev call change any
answer, and is the one call fast enough? Rev 2 §4 component 1 exit criterion.

Each fixture (triage, boundary, coverage sets) is run ref -> bundle -> ref again. A
question passes when the bundle's net extra misses fit inside the separate call's own
run-to-run noise (min 1, or 2 % of units) and none of them is confident (>= 0.95).
The one call passes when p95 < 500 ms over all bundle calls with zero errors.

Usage (from backend/, keys in .env):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.bundle_parity', run_name='__main__')" [--repeats 2] [--concurrency 1]

Never run by pytest. Writes docs/model-migration/bundle-parity-<date>.json; exits 1 on FAIL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any

from rapid_reports_ai.dictation_triage import TriageDecision, TriageError, TriageState, get_triager
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, quantile, rate
from rapid_reports_ai.section_coverage import CoverageDecision, get_jev_coverage
from rapid_reports_ai.utterance_boundary import BoundaryDecision, get_jev_boundary
from rapid_reports_ai.utterance_bundle import BundleDecision, BundleState, get_jev_bundle

CONFIDENT = 0.95
LATENCY_LIMIT_MS = 500

# Triage and boundary fixtures carry no checklist; the bundle always asks section
# questions, so each scan type gets a realistic one. Coverage fixtures bring their own.
PARITY_CHECKLISTS: dict[str, list[str]] = {
    "CT chest": ["LUNGS", "PLEURA", "MEDIASTINUM", "HEART", "BONES"],
    "CXR": ["LUNGS", "PLEURA", "HEART", "MEDIASTINUM", "BONES"],
    "CT abdomen pelvis": ["LIVER", "GALLBLADDER", "PANCREAS", "SPLEEN", "KIDNEYS", "BOWEL", "LYMPH NODES", "BONES"],
    "US abdomen": ["LIVER", "GALLBLADDER", "BILE DUCTS", "PANCREAS", "SPLEEN", "KIDNEYS"],
    "US renal": ["KIDNEYS", "BLADDER"],
    "CT head": ["BRAIN PARENCHYMA", "VENTRICLES", "EXTRA-AXIAL SPACES", "SKULL"],
    "MRI lumbar spine": ["VERTEBRAL BODIES", "INTERVERTEBRAL DISCS", "SPINAL CANAL", "NERVE ROOTS"],
    "MRCP": ["LIVER", "GALLBLADDER", "BILE DUCTS", "PANCREATIC DUCT"],
}


def triage_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], c["committed"], c["active"], "", c["utterance"], PARITY_CHECKLISTS[c["scan_type"]])


def boundary_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], "", c["scratchpad_tail"], c["buffered"], c["chunk"], PARITY_CHECKLISTS[c["scan_type"]])


def coverage_state(c: dict) -> BundleState:
    return BundleState(c["scan_type"], "", c["scratchpad"], "", "", list(c["checklist"]))


@dataclass(frozen=True)
class Unit:
    question: str
    case_id: str
    ref_ok: bool
    ref2_ok: bool
    bundle_ok: bool
    bundle_conf: float


def _noul_ok(p: float, expected: bool) -> bool:
    return (p >= 0.5) == expected


def _noul_conf(p: float) -> float:
    return 0.5 + abs(p - 0.5)


def triage_units(c: dict, ref: TriageDecision, ref2: TriageDecision, b: BundleDecision) -> list[Unit]:
    bt = b.triage
    units = [Unit("action", c["id"], ref.action == c["expected_action"], ref2.action == c["expected_action"],
                  bt.action == c["expected_action"], bt.confidence or 0.0)]
    for q, exp_key in (("is_correction", "expected_is_correction"), ("needs_committed_edit", "expected_needs_committed_edit")):
        exp = c[exp_key]
        p_ref, p_ref2, p_b = getattr(ref, q), getattr(ref2, q), getattr(bt, q)
        units.append(Unit(q, c["id"], _noul_ok(p_ref, exp), _noul_ok(p_ref2, exp), _noul_ok(p_b, exp), _noul_conf(p_b)))
    return units


def standalone_units(c: dict, ref: BoundaryDecision, ref2: BoundaryDecision, b: BundleDecision) -> list[Unit]:
    exp = {"complete": True, "continues": False}.get(c["expected_boundary"])
    if exp is None:
        return []
    return [Unit("standalone", c["id"], _noul_ok(ref.standalone, exp), _noul_ok(ref2.standalone, exp),
                 _noul_ok(b.standalone, exp), _noul_conf(b.standalone))]


def coverage_units(c: dict, ref: CoverageDecision, ref2: CoverageDecision, b: BundleDecision) -> list[Unit]:
    expected = set(c["expected_covered"])
    return [
        Unit("coverage", f"{c['id']}/{s}", _noul_ok(ref.scores[s], s in expected), _noul_ok(ref2.scores[s], s in expected),
             _noul_ok(b.coverage[s], s in expected), _noul_conf(b.coverage[s]))
        for s in c["checklist"]
    ]


def verdict(units: list[Unit]) -> dict[str, Any]:
    n = len(units)
    bundle_only = sum(u.ref_ok and not u.bundle_ok for u in units)
    ref_only = sum(u.bundle_ok and not u.ref_ok for u in units)
    noise = sum(u.ref_ok != u.ref2_ok for u in units)
    allowed = max(1, noise, ceil(0.02 * n))
    confident_new = sum(u.ref_ok and not u.bundle_ok and u.bundle_conf >= CONFIDENT for u in units)
    return {
        "n": n,
        "ref": rate(sum(u.ref_ok for u in units), n),
        "ref2": rate(sum(u.ref2_ok for u in units), n),
        "bundle": rate(sum(u.bundle_ok for u in units), n),
        "bundle_only_wrong": bundle_only,
        "ref_only_wrong": ref_only,
        "noise_discordant": noise,
        "allowed_net_loss": allowed,
        "confident_new_wrong": confident_new,
        "pass": (bundle_only - ref_only) <= allowed and confident_new == 0,
    }


def latency_gate(latencies: list[int], limit_ms: int = LATENCY_LIMIT_MS) -> dict[str, Any]:
    p95 = quantile(latencies, 0.95)
    return {
        "n": len(latencies),
        "p50": int(median(latencies)) if latencies else 0,
        "p95": p95,
        "p95_ci": list(bootstrap_quantile_ci(latencies, 0.95)),
        "limit_ms": limit_ms,
        "pass": bool(latencies) and p95 < limit_ms,
    }


# --- live runner ------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"
COMMAND_ACTIONS = ("delete_previous_utterance", "formatting_command")


async def _ref_triage(c: dict) -> TriageDecision:
    return await get_triager("jev").classify(TriageState(c["committed"], c["active"], c["utterance"], c["scan_type"]))


async def _ref_boundary(c: dict) -> BoundaryDecision:
    return await get_jev_boundary().classify(c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"], 0.0)


async def _ref_coverage(c: dict) -> CoverageDecision:
    return await get_jev_coverage().classify(c["scratchpad"], c["checklist"], c["scan_type"])


KINDS = {
    "triage": ("triage_utterances.jsonl", triage_state, _ref_triage, triage_units),
    "boundary": ("boundary_cases.jsonl", boundary_state, _ref_boundary, standalone_units),
    "coverage": ("coverage_cases.jsonl", coverage_state, _ref_coverage, coverage_units),
}


async def run_case(kind: str, c: dict, sem: asyncio.Semaphore, repeats: int) -> dict[str, Any]:
    _, to_state, ref_fn, to_units = KINDS[kind]
    state = to_state(c)
    rec: dict[str, Any] = {"kind": kind, "id": c["id"], "error": None, "units": [], "bundle_latencies": []}
    async with sem:
        try:
            ref = await ref_fn(c)
            b = await get_jev_bundle().classify(state)
            ref2 = await ref_fn(c)
            extra = [(await get_jev_bundle().classify(state)).latency_ms for _ in range(repeats - 1)]
        except TriageError as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
            return rec
    rec["units"] = [u.__dict__ for u in to_units(c, ref, ref2, b)]
    rec["bundle_latencies"] = [b.latency_ms, *extra]
    rec["ref_latencies"] = [ref.latency_ms, ref2.latency_ms]
    rec["n_questions"] = b.n_questions
    rec["bundle_cost_usd"] = b.cost_usd
    if kind == "boundary" and c["expected_boundary"] == "command":
        rec["command_action"] = b.triage.action  # informational: commands are not a bundle question yet
    return rec


def summarise(recs: list[dict[str, Any]]) -> dict[str, Any]:
    units = [Unit(**u) for r in recs for u in r["units"]]
    questions = sorted({u.question for u in units})
    per_q = {q: verdict([u for u in units if u.question == q]) for q in questions}
    bundle_lat = [l for r in recs for l in r["bundle_latencies"]]
    small = [l for r in recs if r.get("n_questions", 0) <= 8 for l in r["bundle_latencies"]]
    large = [l for r in recs if r.get("n_questions", 0) > 8 for l in r["bundle_latencies"]]
    ref_lat = {k: latency_gate([l for r in recs if r["kind"] == k for l in r.get("ref_latencies", [])])
               for k in KINDS}
    errors = [r for r in recs if r["error"]]
    cmds = [r for r in recs if "command_action" in r]
    gate = latency_gate(bundle_lat)
    return {
        "questions": per_q,
        "latency": gate,
        "latency_by_size": {"<=8 questions": latency_gate(small), ">8 questions": latency_gate(large)},
        "ref_latency": ref_lat,
        "errors": len(errors),
        "commands_caught_by_action": rate(sum(r["command_action"] in COMMAND_ACTIONS for r in cmds), len(cmds)),
        "bundle_cost_usd": round(sum(r.get("bundle_cost_usd") or 0.0 for r in recs), 8),
        "pass": all(v["pass"] for v in per_q.values()) and gate["pass"] and not errors,
    }


def fmt(s: dict[str, Any]) -> str:
    lines = [f"== bundle parity: {'PASS' if s['pass'] else 'FAIL'}  errors={s['errors']}  cost=${s['bundle_cost_usd']:.5f}"]
    for q, v in s["questions"].items():
        lines.append(
            f"   {q:<22} {'PASS' if v['pass'] else 'FAIL'}  ref={fmt_rate(v['ref'])}  bundle={fmt_rate(v['bundle'])}  "
            f"bundle-only={v['bundle_only_wrong']} ref-only={v['ref_only_wrong']} noise={v['noise_discordant']} "
            f"allowed={v['allowed_net_loss']} confident-new={v['confident_new_wrong']}"
        )
    g = s["latency"]
    lines.append(f"   latency (bundle)       {'PASS' if g['pass'] else 'FAIL'}  n={g['n']} p50={g['p50']}ms "
                 f"p95={g['p95']}ms {g['p95_ci']} limit<{g['limit_ms']}ms")
    for k, v in s["latency_by_size"].items():
        lines.append(f"     {k:<20} n={v['n']} p50={v['p50']}ms p95={v['p95']}ms")
    for k, v in s["ref_latency"].items():
        lines.append(f"   latency (separate {k:<8}) n={v['n']} p50={v['p50']}ms p95={v['p95']}ms")
    lines.append(f"   commands caught by action (info): {fmt_rate(s['commands_caught_by_action'])}")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2, help="bundle calls per fixture (accuracy uses the first)")
    ap.add_argument("--concurrency", type=int, default=1, help="1 = one utterance at a time, as in the app")
    args = ap.parse_args(sys.argv[1:])
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    sem = asyncio.Semaphore(args.concurrency)
    jobs = []
    for kind, (fname, *_rest) in KINDS.items():
        for c in (json.loads(l) for l in (FIXTURES / fname).read_text().splitlines() if l.strip()):
            jobs.append(run_case(kind, c, sem, max(1, args.repeats)))
    recs = await asyncio.gather(*jobs)
    s = summarise(recs)
    print(fmt(s))
    print("\n-- bundle-only misses --")
    for r in recs:
        for u in r["units"]:
            if u["ref_ok"] and not u["bundle_ok"]:
                print(f"   {u['question']:<22} {u['case_id']:<24} bundle_conf={u['bundle_conf']:.2f}")
    for r in recs:
        if r["error"]:
            print(f"   ERROR {r['kind']:<8} {r['id']:<14} {r['error']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"bundle-parity-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "records": recs}, indent=1))
    print(f"\nwrote {out}")
    return 0 if s["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
