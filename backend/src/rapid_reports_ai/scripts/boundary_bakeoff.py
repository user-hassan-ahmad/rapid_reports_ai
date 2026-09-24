"""Score Jev's boundary + ASR-risk decisions on tests/fixtures/boundary_cases.jsonl,
next to the plain-code baseline (scripts/bakeoff_baselines.py), with 95 % intervals.

Usage (from backend/):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.boundary_bakeoff', run_name='__main__')"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Callable, Optional

from rapid_reports_ai.scripts.bakeoff_baselines import baseline_boundary
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate
from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p
from rapid_reports_ai.utterance_boundary import get_jev_boundary, resolve, resolve_placement

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "boundary_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"
CLASSES = ("complete", "continues", "command")


def expected_standalone(row: dict) -> Optional[bool]:
    """Standalone has no label of its own: a finished statement should read as one, an
    unfinished one should not. Commands are not statements and are not scored."""
    return {"complete": True, "continues": False}.get(row["expected_boundary"])


def _hits(rows: list[dict], pred: Callable[[dict], bool]) -> dict[str, Any]:
    return rate(sum(1 for r in rows if pred(r)), len(rows))


def score_boundary(rows: list[dict]) -> dict[str, Any]:
    ok = [r for r in rows if r["error"] is None]
    lat = [r["latency_ms"] for r in ok]
    st_ok = [r for r in ok if expected_standalone(r) is not None]
    st_all = [r for r in rows if expected_standalone(r) is not None]
    return {
        "n": len(rows),
        "errors": len(rows) - len(ok),
        "jev_raw": _hits(ok, lambda r: r["raw"] == r["expected_boundary"]),
        "jev_resolved": _hits(ok, lambda r: r["resolved"] == r["expected_boundary"]),
        "code": _hits(rows, lambda r: r["code"] == r["expected_boundary"]),
        "by_class": {
            k: {
                "jev_raw": _hits([r for r in ok if r["expected_boundary"] == k], lambda r: r["raw"] == k),
                "code": _hits([r for r in rows if r["expected_boundary"] == k], lambda r: r["code"] == k),
            }
            for k in CLASSES
        },
        "standalone_jev": _hits(st_ok, lambda r: (r["standalone"] >= 0.5) == expected_standalone(r)),
        "standalone_code": _hits(st_all, lambda r: (r["code"] == "complete") == expected_standalone(r)),
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": _p(lat, 0.95),
        "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in rows), 8),
    }


async def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(c):
        base = {**c, "code": baseline_boundary(c["buffered"], c["chunk"])}
        async with sem:
            try:
                d = await get_jev_boundary().classify(
                    c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"], c.get("silence_s", 0.0)
                )
                return {**base, "raw": d.boundary, "resolved": resolve(d), "confidence": d.confidence,
                        "asr_risk": d.asr_risk, "standalone": d.standalone, "latency_ms": d.latency_ms,
                        "cost_usd": d.cost_usd, "error": None, "placement_raw": d.placement,
                        "placement": resolve_placement(d), "placement_confidence": d.placement_confidence}
            except Exception as e:
                return {**base, "raw": None, "resolved": "complete", "confidence": None, "asr_risk": None,
                        "standalone": None, "latency_ms": 0, "cost_usd": None, "error": type(e).__name__}

    rows = await asyncio.gather(*(run(c) for c in cases))
    ok = [r for r in rows if r["error"] is None]
    s = score_boundary(rows)
    print(f"== boundary: n={s['n']} errors={s['errors']} p50={s['latency_p50_ms']}ms "
          f"p95={s['latency_p95_ms']}ms {s['latency_p95_ci_ms']} cost=${s['cost_usd']:.5f}")
    print(f"   jev raw        {fmt_rate(s['jev_raw'])}")
    print(f"   jev resolved   {fmt_rate(s['jev_resolved'])}")
    print(f"   code           {fmt_rate(s['code'])}")
    for k, v in s["by_class"].items():
        print(f"   {k:<10} jev_raw={fmt_rate(v['jev_raw'])}  code={fmt_rate(v['code'])}")
    print(f"   standalone@0.5 jev={fmt_rate(s['standalone_jev'])}  code={fmt_rate(s['standalone_code'])}")
    hard = [r for r in ok if r["hard"]]
    print(f"   hard       n={len(hard):<3} resolved_acc="
          f"{sum(r['resolved'] == r['expected_boundary'] for r in hard) / max(1, len(hard)):.2f}")
    asr = [r for r in ok if r["asr_risk"] is not None]
    print(f"   asr_risk@0.5 acc={sum((r['asr_risk'] >= 0.5) == r['expected_asr_risk'] for r in asr) / max(1, len(asr)):.3f}")
    for name, lo, hi in BUCKETS:
        rs = [r for r in ok if lo <= r["confidence"] < hi]
        if rs:
            print(f"   conf {name:<8} n={len(rs):<3} raw_acc={sum(r['raw'] == r['expected_boundary'] for r in rs) / len(rs):.3f}")
    print("\n-- jev misses --")
    for r in ok:
        if r["resolved"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} raw={r['raw']:<9} "
                  f"conf={r['confidence']:.2f} resolved={r['resolved']:<9} '{r['buffered']} | {r['chunk']}'")
    print("\n-- code misses --")
    for r in rows:
        if r["code"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} code={r['code']:<9} '{r['buffered']} | {r['chunk']}'")
    pl = [r for r in ok if r.get("expected_placement")]
    if pl:
        print(f"\n-- placement (n={len(pl)}) resolved_acc="
              f"{sum(r['placement'] == r['expected_placement'] for r in pl) / len(pl):.3f} raw_acc="
              f"{sum(r['placement_raw'] == r['expected_placement'] for r in pl) / len(pl):.3f}")
    print("\n-- asr risk --")
    for r in asr:
        if (r["asr_risk"] >= 0.5) != r["expected_asr_risk"] or r["expected_asr_risk"]:
            print(f"   {r['id']:<7} expected={r['expected_asr_risk']!s:<5} asr={r['asr_risk']:.2f} '{r['buffered']} | {r['chunk']}'")
    print(f"\nasr cases: {dict(Counter(r['expected_asr_risk'] for r in asr))}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"boundary-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "rows": rows}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
