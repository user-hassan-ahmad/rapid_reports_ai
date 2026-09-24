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

from dataclasses import dataclass
from math import ceil
from statistics import median
from typing import Any

from rapid_reports_ai.dictation_triage import TriageDecision
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, quantile, rate
from rapid_reports_ai.section_coverage import CoverageDecision
from rapid_reports_ai.utterance_boundary import BoundaryDecision
from rapid_reports_ai.utterance_bundle import BundleDecision, BundleState

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
