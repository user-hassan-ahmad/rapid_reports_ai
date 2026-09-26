"""Pure summary of triage records. Shared by the bake-off (fixture labels) and the
shadow report (derived labels) so both print the same shape."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any, Optional

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS
from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, rate

BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.5", 0.0, 0.5),
    ("0.5-0.8", 0.5, 0.8),
    ("0.8-0.95", 0.8, 0.95),
    (">=0.95", 0.95, 1.01),
)


@dataclass(frozen=True)
class Record:
    id: str
    candidate: str
    expected_action: str
    action: Optional[str]
    confidence: Optional[float]
    latency_ms: int
    cost_usd: Optional[float]
    hard: bool
    error: Optional[str]
    is_correction: Optional[float]
    expected_is_correction: Optional[bool]
    needs_committed_edit: Optional[float]
    expected_needs_committed_edit: Optional[bool]
    probabilities: Optional[dict[str, float]] = None  # the full action distribution, when stated


def _p(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[idx]


def _acc(records: list[Record]) -> float:
    return sum(r.action == r.expected_action for r in records) / len(records) if records else 0.0


def _aux(records: list[Record], value_attr: str, expected_attr: str) -> Optional[float]:
    pairs = [(getattr(r, value_attr), getattr(r, expected_attr)) for r in records]
    pairs = [(v, e) for v, e in pairs if v is not None and e is not None]
    if not pairs:
        return None
    return sum((v >= 0.5) == e for v, e in pairs) / len(pairs)


def _candidate_summary(records: list[Record]) -> dict[str, Any]:
    ok = [r for r in records if r.error is None and r.action is not None]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in ok:
        confusion[r.expected_action][r.action] += 1
    per_action = {}
    for a in TRIAGE_ACTIONS:
        tp = confusion[a][a]
        fn = sum(confusion[a].values()) - tp
        fp = sum(confusion[x][a] for x in TRIAGE_ACTIONS if x != a)
        per_action[a] = {
            "n": tp + fn,
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
        }
    lat = [r.latency_ms for r in ok]
    hard = [r for r in ok if r.hard]
    correct = sum(r.action == r.expected_action for r in ok)
    out: dict[str, Any] = {
        "n": len(records),
        "errors": len(records) - len(ok),
        "accuracy": _acc(ok),
        "accuracy_rate": rate(correct, len(ok)),
        "per_action": per_action,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "latency_p50_ms": int(median(lat)) if lat else 0,
        "latency_p95_ms": _p(lat, 0.95),
        "latency_p95_ci_ms": list(bootstrap_quantile_ci(lat, 0.95)),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in records), 8),
        "hard": {
            "n": len(hard),
            "accuracy": _acc(hard),
            "rate": rate(sum(r.action == r.expected_action for r in hard), len(hard)),
        },
        "is_correction_accuracy": _aux(ok, "is_correction", "expected_is_correction"),
        "needs_committed_edit_accuracy": _aux(ok, "needs_committed_edit", "expected_needs_committed_edit"),
    }
    with_conf = [r for r in ok if r.confidence is not None]
    if with_conf:
        buckets = {}
        for name, lo, hi in BUCKETS:
            rs = [r for r in with_conf if lo <= r.confidence < hi]
            buckets[name] = {"n": len(rs), "accuracy": _acc(rs), "coverage": len(rs) / len(with_conf)}
        out["confidence_buckets"] = buckets
    return out


def summarise(records: list[Record]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by[r.candidate].append(r)
    return {c: _candidate_summary(rs) for c, rs in by.items()}


def format_summary(summary: dict[str, dict[str, Any]]) -> str:
    lines = []
    for cand, s in summary.items():
        lines.append(
            f"== {cand}: n={s['n']} errors={s['errors']} accuracy={fmt_rate(s['accuracy_rate'])} "
            f"p50={s['latency_p50_ms']}ms p95={s['latency_p95_ms']}ms {s['latency_p95_ci_ms']} "
            f"cost=${s['cost_usd']:.5f}"
        )
        lines.append(
            f"   hard: accuracy={fmt_rate(s['hard']['rate'])}   "
            f"is_correction@0.5={s['is_correction_accuracy']}  "
            f"needs_committed_edit@0.5={s['needs_committed_edit_accuracy']}"
        )
        for a, m in s["per_action"].items():
            lines.append(f"   {a:<28} n={m['n']:<3} recall={m['recall']} precision={m['precision']}")
        if "confidence_buckets" in s:
            for b, m in s["confidence_buckets"].items():
                lines.append(f"   conf {b:<8} n={m['n']:<3} accuracy={m['accuracy']:.3f} coverage={m['coverage']:.2f}")
    return "\n".join(lines)
