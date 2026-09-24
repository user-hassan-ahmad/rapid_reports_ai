"""Score both coverage candidates on tests/fixtures/coverage_cases.jsonl.

Usage (from backend/, keys loaded):
    PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.coverage_bakeoff', run_name='__main__')"
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any, Optional

from rapid_reports_ai.scripts.bakeoff_baselines import baseline_coverage
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate
from rapid_reports_ai.scripts.triage_summary import BUCKETS, _p

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "coverage_cases.jsonl"
OUT_DIR = Path(__file__).resolve().parents[4] / "docs" / "model-migration"


@dataclass(frozen=True)
class Row:
    id: str
    candidate: str
    checklist: list[str]
    expected: list[str]
    scores: Optional[dict[str, float]]
    latency_ms: int
    cost_usd: Optional[float]
    hard: bool
    rule: str
    error: Optional[str]


def _exact(row: Row, threshold: float = 0.5) -> bool:
    got = {s for s in row.checklist if (row.scores or {}).get(s, 0.0) >= threshold}
    return got == set(row.expected)


def code_row(case: dict) -> Row:
    return Row(case["id"], "code", case["checklist"], case["expected_covered"],
               baseline_coverage(case["scratchpad"], case["checklist"]), 0, None, case["hard"], case["rule"], None)


def score(rows: list[Row], threshold: float = 0.5) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    by_cand: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_cand[r.candidate].append(r)
    for cand, rs in by_cand.items():
        ok = [r for r in rs if r.error is None and r.scores is not None]
        tp = fp = fn = 0
        for r in ok:
            exp = set(r.expected)
            for s in r.checklist:
                got = r.scores.get(s, 0.0) >= threshold
                if got and s in exp:
                    tp += 1
                elif got:
                    fp += 1
                elif s in exp:
                    fn += 1
        by_rule: dict[str, dict[str, float]] = {}
        for rule in sorted({r.rule for r in ok}):
            rr = [r for r in ok if r.rule == rule]
            by_rule[rule] = {"n": len(rr), "exact": sum(_exact(r, threshold) for r in rr) / len(rr)}
        hard = [r for r in ok if r.hard]
        lat = [r.latency_ms for r in ok]
        buckets: dict[str, dict[str, float]] = {}
        per_section = [(r.scores[s], s in set(r.expected)) for r in ok for s in r.checklist if r.candidate == "jev"]
        if per_section:
            for name, lo, hi in BUCKETS:
                # bucket by distance from 0.5 mapped to a confidence in [0.5, 1]: conf = 0.5 + |p - 0.5|
                items = [(p, e) for p, e in per_section if lo <= 0.5 + abs(p - 0.5) < hi]
                buckets[name] = {
                    "n": len(items),
                    "accuracy": (sum((p >= threshold) == e for p, e in items) / len(items)) if items else 0.0,
                }
        exact_k = sum(_exact(r, threshold) for r in ok)
        out[cand] = {
            "n": len(rs),
            "errors": len(rs) - len(ok),
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "exact_set_accuracy": (exact_k / len(ok)) if ok else 0.0,
            "precision_rate": rate(tp, tp + fp),
            "recall_rate": rate(tp, tp + fn),
            "exact_rate": rate(exact_k, len(ok)),
            "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
            "by_rule": by_rule,
            "hard": {"n": len(hard), "exact": (sum(_exact(r, threshold) for r in hard) / len(hard)) if hard else 0.0},
            "latency_p50_ms": int(median(lat)) if lat else 0,
            "latency_p95_ms": _p(lat, 0.95),
            "cost_usd": round(sum(r.cost_usd or 0.0 for r in rs), 8),
            "buckets": buckets,
        }
    return out


def fmt(s: dict[str, dict[str, Any]]) -> str:
    lines = []
    for cand, m in s.items():
        lines.append(
            f"== {cand}: n={m['n']} errors={m['errors']} p50={m['latency_p50_ms']}ms "
            f"p95={m['latency_p95_ms']}ms {m['latency_p95_ci_ms']} cost=${m['cost_usd']:.5f}"
        )
        lines.append(f"   P={fmt_rate(m['precision_rate'])}  R={fmt_rate(m['recall_rate'])}")
        lines.append(f"   exact={fmt_rate(m['exact_rate'])}")
        lines.append(f"   hard: n={m['hard']['n']} exact={m['hard']['exact']:.3f}")
        for rule, v in m["by_rule"].items():
            lines.append(f"   {rule:<30} n={v['n']:<3} exact={v['exact']:.2f}")
        for b, v in m["buckets"].items():
            lines.append(f"   conf {b:<8} n={v['n']:<4} accuracy={v['accuracy']:.3f}")
    return "\n".join(lines)


async def main() -> int:
    from rapid_reports_ai.canvas_routes import qwen_coverage
    from rapid_reports_ai.section_coverage import get_jev_coverage

    missing = [k for k in ("OPENROUTER_API_KEY", "CEREBRAS_API_KEY") if not os.environ.get(k)]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 2
    cases = [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]
    sem = asyncio.Semaphore(4)

    async def run(case: dict) -> list[Row]:
        rows = []
        async with sem:
            rows.append(code_row(case))
            for cand in ("jev", "qwen"):
                try:
                    if cand == "jev":
                        d = await get_jev_coverage().classify(case["scratchpad"], case["checklist"], case["scan_type"])
                    else:
                        d = await qwen_coverage(case["scratchpad"], case["checklist"], case["scan_type"])
                    rows.append(Row(case["id"], cand, case["checklist"], case["expected_covered"], d.scores,
                                    d.latency_ms, d.cost_usd, case["hard"], case["rule"], None))
                except Exception as e:
                    rows.append(Row(case["id"], cand, case["checklist"], case["expected_covered"], None, 0, None,
                                    case["hard"], case["rule"], type(e).__name__))
        return rows

    nested = await asyncio.gather(*(run(c) for c in cases))
    rows = [r for rs in nested for r in rs]
    s = score(rows)
    print(fmt(s))
    print("\n-- non-exact cases --")
    for r in rows:
        if r.error is None and not _exact(r):
            got = [x for x in r.checklist if r.scores.get(x, 0) >= 0.5]
            print(f"   {r.candidate:<4} {r.id:<6} {r.rule:<28} expected={r.expected} got={got}")
    errors = [r for r in rows if r.error]
    if errors:
        print("\n-- errors --")
        for r in errors:
            print(f"   {r.candidate:<4} {r.id:<6} {r.error}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"coverage-bakeoff-{date.today().isoformat()}.json"
    out.write_text(json.dumps({"summary": s, "rows": [r.__dict__ for r in rows]}, indent=1))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
