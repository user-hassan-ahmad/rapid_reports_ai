"""Score Jev's boundary + ASR-risk decisions on tests/fixtures/boundary_cases.jsonl.

Usage (from backend/):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.boundary_bakeoff', run_name='__main__')"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median

from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p
from rapid_reports_ai.utterance_boundary import get_jev_boundary, resolve, resolve_placement

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "boundary_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


async def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("missing OPENROUTER_API_KEY", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(c):
        async with sem:
            try:
                d = await get_jev_boundary().classify(
                    c["scan_type"], c["buffered"], c["chunk"], c["scratchpad_tail"], c.get("silence_s", 0.0)
                )
                return {**c, "raw": d.boundary, "resolved": resolve(d), "confidence": d.confidence,
                        "asr_risk": d.asr_risk, "latency_ms": d.latency_ms, "cost_usd": d.cost_usd, "error": None,
                        "placement_raw": d.placement, "placement": resolve_placement(d),
                        "placement_confidence": d.placement_confidence}
            except Exception as e:
                return {**c, "raw": None, "resolved": "complete", "confidence": None, "asr_risk": None,
                        "latency_ms": 0, "cost_usd": None, "error": type(e).__name__}

    rows = await asyncio.gather(*(run(c) for c in cases))
    ok = [r for r in rows if r["error"] is None]
    by_class = defaultdict(list)
    for r in ok:
        by_class[r["expected_boundary"]].append(r)
    n_ok = max(1, len(ok))
    print(
        f"== jev boundary: n={len(rows)} errors={len(rows) - len(ok)} "
        f"resolved_acc={sum(r['resolved'] == r['expected_boundary'] for r in ok) / n_ok:.3f} "
        f"raw_acc={sum(r['raw'] == r['expected_boundary'] for r in ok) / n_ok:.3f} "
        f"p50={int(median([r['latency_ms'] for r in ok])) if ok else 0}ms "
        f"p95={_p([r['latency_ms'] for r in ok], 0.95)}ms cost=${sum(r['cost_usd'] or 0 for r in rows):.5f}"
    )
    for k, rs in by_class.items():
        print(f"   {k:<10} n={len(rs):<3} resolved_acc={sum(r['resolved'] == k for r in rs) / len(rs):.2f} "
              f"raw_acc={sum(r['raw'] == k for r in rs) / len(rs):.2f}")
    hard = [r for r in ok if r["hard"]]
    print(f"   hard       n={len(hard):<3} resolved_acc="
          f"{sum(r['resolved'] == r['expected_boundary'] for r in hard) / max(1, len(hard)):.2f}")
    asr = [r for r in ok if r["asr_risk"] is not None]
    print(f"   asr_risk@0.5 acc={sum((r['asr_risk'] >= 0.5) == r['expected_asr_risk'] for r in asr) / max(1, len(asr)):.3f}")
    for name, lo, hi in BUCKETS:
        rs = [r for r in ok if lo <= r["confidence"] < hi]
        if rs:
            print(f"   conf {name:<8} n={len(rs):<3} raw_acc={sum(r['raw'] == r['expected_boundary'] for r in rs) / len(rs):.3f}")
    print("\n-- misses --")
    for r in ok:
        if r["resolved"] != r["expected_boundary"]:
            print(f"   {r['id']:<7} expected={r['expected_boundary']:<9} raw={r['raw']:<9} "
                  f"conf={r['confidence']:.2f} resolved={r['resolved']:<9} '{r['buffered']} | {r['chunk']}'")
    pl = [r for r in ok if r.get("expected_placement")]
    if pl:
        print(f"\n-- placement (n={len(pl)}) resolved_acc="
              f"{sum(r['placement'] == r['expected_placement'] for r in pl) / len(pl):.3f} raw_acc="
              f"{sum(r['placement_raw'] == r['expected_placement'] for r in pl) / len(pl):.3f}")
        for r in pl:
            if r["placement"] != r["expected_placement"]:
                print(f"   {r['id']:<7} expected={r['expected_placement']:<21} got={r['placement_raw']:<21} "
                      f"conf={r['placement_confidence']:.2f} tail='{r['scratchpad_tail'][:50]}' | '{r['buffered']} | {r['chunk']}'")
    print("\n-- asr risk --")
    for r in asr:
        if (r["asr_risk"] >= 0.5) != r["expected_asr_risk"] or r["expected_asr_risk"]:
            print(f"   {r['id']:<7} expected={r['expected_asr_risk']!s:<5} asr={r['asr_risk']:.2f} '{r['buffered']} | {r['chunk']}'")
    print(f"\nasr cases: {dict(Counter(r['expected_asr_risk'] for r in asr))}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"boundary-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
