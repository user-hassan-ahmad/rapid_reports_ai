"""Per-question calibration, Jev against each other candidate (D-03).

A question's rows are aligned across candidates (the same cases, in the same order;
the caller drops a case any candidate failed on). A choice row is (distribution,
label); a noul row is (p(true), 0/1 label). Hard-label candidates enter through
hard_choice / hard_noul, so a candidate that states no probability is scored as one
that is always certain.

Differences are other − Jev with a paired bootstrap interval (cases resampled when
`groups` is given): positive means Jev's score is lower, i.e. better.
Verdict, fixed before the run (plan Task 8): Jev better only if the Brier interval
excludes 0 in Jev's favour and ECE does not favour the other candidate with an
interval excluding 0.
"""
from __future__ import annotations

from typing import Any, Hashable, Literal, Mapping, Optional, Sequence

from rapid_reports_ai.scripts.bakeoff_stats import (
    bootstrap_stat_ci,
    brier,
    brier_multiclass,
    ece,
    fmt_rate,
    fmt_reliability,
    paired_bootstrap_diff_ci,
    rate,
    reliability_table,
)

Kind = Literal["choice", "noul"]


def hard_choice(choice: str) -> dict[str, float]:
    return {choice: 1.0}


def hard_noul(value: float | bool) -> float:
    return 1.0 if float(value) >= 0.5 else 0.0


def _top(dist: Mapping[str, float]) -> tuple[str, float]:
    best = max(dist, key=lambda k: dist[k])
    return best, dist[best]


def _pairs(kind: Kind, rows: list[tuple[Any, Any]]) -> list[tuple[float, int]]:
    """(stated probability, outcome) for ECE and the table: top label for a choice."""
    if kind == "choice":
        return [(_top(d)[1], int(_top(d)[0] == label)) for d, label in rows]
    return [(float(p), int(y)) for p, y in rows]


def _brier_rows(kind: Kind, rows: list[tuple[Any, Any]]) -> float:
    if kind == "choice":
        return brier_multiclass([d for d, _ in rows], [l for _, l in rows])
    return brier([float(p) for p, _ in rows], [int(y) for _, y in rows])


def _ece_rows(kind: Kind, rows: list[tuple[Any, Any]]) -> float:
    pr = _pairs(kind, rows)
    return ece([p for p, _ in pr], [y for _, y in pr])


def _correct(kind: Kind, rows: list[tuple[Any, Any]]) -> int:
    if kind == "choice":
        return sum(_top(d)[0] == label for d, label in rows)
    return sum((float(p) >= 0.5) == bool(y) for p, y in rows)


def verdict(diff: Mapping[str, Sequence[float]]) -> str:
    b_lo, b_hi = diff["brier_diff_ci"]
    e_lo, e_hi = diff["ece_diff_ci"]
    if b_lo > 0:
        return "mixed" if e_hi < 0 else "jev better"
    if b_hi < 0:
        return "other better"
    return "not shown"


def calibration_block(
    question: str,
    kind: Kind,
    by_candidate: dict[str, tuple[Sequence[Any], Sequence[Any]]],
    groups: Optional[Sequence[Hashable]] = None,
    ref: str = "jev",
) -> tuple[dict[str, Any], str]:
    rows = {c: list(zip(values, labels)) for c, (values, labels) in by_candidate.items()}
    sizes = {len(r) for r in rows.values()}
    if len(sizes) != 1:
        raise ValueError(f"candidates not aligned for {question}: {({c: len(r) for c, r in rows.items()})}")

    b_stat = lambda xs: _brier_rows(kind, xs)
    e_stat = lambda xs: _ece_rows(kind, xs)
    out: dict[str, Any] = {"question": question, "kind": kind, "candidates": {}, "vs_jev": {}}
    for cand, r in rows.items():
        pr = _pairs(kind, r)
        out["candidates"][cand] = {
            "n": len(r),
            "accuracy": rate(_correct(kind, r), len(r)),
            "brier": b_stat(r) if r else None,
            "brier_ci": list(bootstrap_stat_ci(r, b_stat, groups)),
            "ece": e_stat(r) if r else None,
            "ece_ci": list(bootstrap_stat_ci(r, e_stat, groups)),
            "reliability": reliability_table([p for p, _ in pr], [y for _, y in pr]),
        }
    if ref in rows and rows[ref]:
        for cand, r in rows.items():
            if cand == ref:
                continue
            bd, blo, bhi = paired_bootstrap_diff_ci(r, rows[ref], b_stat, groups)
            ed, elo, ehi = paired_bootstrap_diff_ci(r, rows[ref], e_stat, groups)
            d = {"brier_diff": bd, "brier_diff_ci": [blo, bhi], "ece_diff": ed, "ece_diff_ci": [elo, ehi]}
            d["verdict"] = verdict(d)
            out["vs_jev"][cand] = d

    lines = [f"-- calibration: {question} ({kind}{', ' + str(len(set(groups))) + ' cases' if groups else ''})"]
    for cand, m in out["candidates"].items():
        lines.append(
            f"   {cand:<8} n={m['n']:<4} acc={fmt_rate(m['accuracy'])}  "
            f"Brier={m['brier']:.4f} [{m['brier_ci'][0]:.4f}, {m['brier_ci'][1]:.4f}]  "
            f"ECE={m['ece']:.4f} [{m['ece_ci'][0]:.4f}, {m['ece_ci'][1]:.4f}]"
        )
        lines.append(fmt_reliability(m["reliability"]))
    for cand, d in out["vs_jev"].items():
        lines.append(
            f"   {cand} − jev: Brier {d['brier_diff']:+.4f} [{d['brier_diff_ci'][0]:+.4f}, {d['brier_diff_ci'][1]:+.4f}]  "
            f"ECE {d['ece_diff']:+.4f} [{d['ece_diff_ci'][0]:+.4f}, {d['ece_diff_ci'][1]:+.4f}]  → {d['verdict']}"
        )
    return out, "\n".join(lines)
