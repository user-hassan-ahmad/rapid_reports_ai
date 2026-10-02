"""Scoring (spec §6, §7): per-arm metrics, paired gains/losses against A, McNemar, and calibration helpers.

    .venv/bin/python -m rapid_reports_ai.scripts.jev_tool_lab.score \
        --items test_cases/jev_tool_lab/s1_pilot.json --results $LAB_OUT/results_*.jsonl"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .arms import ArmResult
from .scenarios import S1Item


def balanced_accuracy(pairs: Sequence[Tuple[bool, bool]]) -> float:
    """pairs of (label, predicted) for the gradable decision."""
    pos = [p for lab, p in pairs if lab]
    neg = [p for lab, p in pairs if not lab]
    tpr = sum(pos) / len(pos) if pos else 0.0
    tnr = sum(1 for p in neg if not p) / len(neg) if neg else 0.0
    return (tpr + tnr) / 2


def percentile(xs: Sequence[float], q: float) -> Optional[float]:
    """Nearest-rank percentile."""
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def brier(probs: Sequence[float], labels: Sequence[bool]) -> float:
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in zip(probs, labels)) / len(probs)


def ece(probs: Sequence[float], labels: Sequence[bool], bins: int = 5) -> float:
    total, n = 0.0, len(probs)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(1 for i in idx if labels[i]) / len(idx)
            total += len(idx) / n * abs(acc - conf)
    return total


def auc(probs: Sequence[float], labels: Sequence[bool]) -> float:
    pos = [p for p, y in zip(probs, labels) if y]
    neg = [p for p, y in zip(probs, labels) if not y]
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant counts b (gains) and c (losses)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def _correct(r: ArmResult, items: Dict[str, S1Item]) -> Optional[bool]:
    if r.decision is None:
        return None
    return r.decision.gradable == items[r.item_id].gradable


def paired(arm_rows: List[ArmResult], a_rows: List[ArmResult], items: Dict[str, S1Item], run: int) -> Dict[str, int]:
    a = {r.item_id: _correct(r, items) for r in a_rows if r.run == run}
    gains = losses = 0
    for r in arm_rows:
        if r.run != run or r.item_id not in a:
            continue
        mine, base = _correct(r, items), a[r.item_id]
        if mine and base is False:
            gains += 1
        elif base and mine is False:
            losses += 1
    return {"gains": gains, "losses": losses}


def summarise(rows: List[ArmResult], items: Dict[str, S1Item]) -> Dict[str, dict]:
    by_arm: Dict[str, List[ArmResult]] = defaultdict(list)
    for r in rows:
        by_arm[r.arm].append(r)
    out: Dict[str, dict] = {}
    for arm, rs in sorted(by_arm.items()):
        ok = [r for r in rs if r.decision is not None]
        pairs = [(items[r.item_id].gradable, r.decision.gradable) for r in ok]
        flag = [p for lab, p in pairs if not lab]          # flag class = not gradable
        clear = [p for lab, p in pairs if lab]
        lat = [r.latency_s for r in ok]
        runs = sorted({r.run for r in rs})
        s = {"n": len(rs), "errors": len(rs) - len(ok),
             "bal_acc": round(balanced_accuracy(pairs), 3) if pairs else None,
             "flag_recall": round(sum(1 for p in flag if not p) / len(flag), 3) if flag else None,
             "false_alarm": round(sum(1 for p in clear if not p) / len(clear), 3) if clear else None,
             "p50_latency_s": percentile(lat, 0.5), "p90_latency_s": percentile(lat, 0.9),
             "mean_qwen_in": round(statistics.mean(r.qwen_in for r in ok), 1) if ok else None,
             "mean_qwen_out": round(statistics.mean(r.qwen_out for r in ok), 1) if ok else None,
             "mean_jev_calls": round(statistics.mean(r.jev_calls for r in ok), 2) if ok else None,
             "mean_requests": round(statistics.mean(r.requests for r in ok), 2) if ok else None,
             "mean_tokens": round(statistics.mean(r.qwen_in + r.qwen_out for r in ok), 1) if ok else None}
        if len(runs) >= 2:
            first = {r.item_id: r.decision.gradable for r in ok if r.run == runs[0]}
            second = {r.item_id: r.decision.gradable for r in ok if r.run == runs[1]}
            both = [i for i in first if i in second]
            s["stability"] = round(sum(first[i] == second[i] for i in both) / len(both), 3) if both else None
        if arm != "A" and "A" in by_arm:
            s["vs_A"] = {}
            for run in runs:
                g = paired(rs, by_arm["A"], items, run)
                s["vs_A"][f"run{run}"] = {**g, "mcnemar_p": round(mcnemar_exact(g["gains"], g["losses"]), 4)}
        if arm == "B":
            asked = sum(len((r.plan or {}).get("questions", [])) for r in rs)
            bad_q = sum(1 for r in rs for e in r.invalid if not e.startswith("rule:"))
            s["invalid_share"] = bad_q / asked if asked else None
            s["rule_invalid_share"] = round(sum(any(e.startswith("rule:") for e in r.invalid) for r in rs) / len(rs), 3)
            s["fallback_share"] = round(sum(r.fallback for r in rs) / len(rs), 3)
        if arm == "C" and "Cb" in by_arm:          # Jev's share of C's lift: C against its own blank-evidence control
            s["vs_Cb"] = {f"run{run}": paired(rs, by_arm["Cb"], items, run) for run in runs}
        if arm in ("C", "D"):
            decided = [r for r in ok if r.rule_outcome in ("yes", "no")]
            over = [r for r in decided if r.decision.gradable != (r.rule_outcome == "yes")]
            s["overrule_share"] = round(len(over) / len(decided), 3) if decided else None
            s["overrule_right_share"] = (round(sum(1 for r in over if _correct(r, items)) / len(over), 3)
                                         if over else None)
        if arm == "D":
            asked = sum(len((r.plan or {}).get("questions", [])) for r in rs)
            linted = sum(len({e.split(":")[0] for e in r.lint if not e.startswith("rule:")}) for r in rs)
            s["lint_share"] = round(linted / asked, 3) if asked else None
        out[arm] = s
    base = out.get("A")
    if base and base["p90_latency_s"] and base["mean_tokens"]:   # the §7.1 cost bars, read straight off the summary
        for arm, s in out.items():
            if arm != "A" and s["p90_latency_s"] is not None and s["mean_tokens"] is not None:
                s["p90_latency_vs_A"] = round(s["p90_latency_s"] / base["p90_latency_s"], 3)
                s["tokens_vs_A"] = round(s["mean_tokens"] / base["mean_tokens"], 3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--results", nargs="+", required=True)
    args = ap.parse_args()
    items = {x["id"]: S1Item(**x) for x in json.loads(Path(args.items).read_text())}
    rows = [ArmResult.model_validate_json(line) for p in args.results
            for line in Path(p).read_text().splitlines() if line.strip()]
    summary = summarise(rows, items)
    print(json.dumps(summary, indent=2))
    dest = Path(args.results[0]).parent / f"summary_{os.getpid()}.json"
    dest.write_text(json.dumps(summary, indent=2))
    print(dest)


if __name__ == "__main__":
    main()
