"""Intervals for bake-off numbers. Every bake-off reports a 95 % interval (rev 2 §5).

Proportions use the Wilson score interval (sane at 0/n and n/n, unlike the normal
approximation). Latency p95 uses a seeded percentile bootstrap so reruns print the
same interval for the same data.

Calibration (D-03): Brier score, expected calibration error over equal-width bins and
the reliability table behind it. A choice question enters as top-label pairs (p = the
confidence of the chosen option, y = it was right) for ECE and the table, and as full
distributions for the multiclass Brier; a noul enters as (p(true), label). Intervals
come from a seeded bootstrap that resamples whole cases when items share a case.
"""
from __future__ import annotations

import random
from math import sqrt
from typing import Any, Callable, Hashable, Mapping, Optional, Sequence, TypeVar

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    # Exact endpoints at 0/n and n/n (float error otherwise prints 0.9999... as the bound).
    return (0.0 if k == 0 else max(0.0, centre - half), 1.0 if k == n else min(1.0, centre + half))


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    p: Optional[float] = k / n if n else None
    return {"k": k, "n": n, "p": p, "ci95": [round(lo, 4), round(hi, 4)]}


def fmt_rate(r: dict[str, Any]) -> str:
    if not r["n"]:
        return f"n/a ({r['k']}/{r['n']})"
    lo, hi = r["ci95"]
    return f"{r['p']:.3f} [{lo:.2f}, {hi:.2f}] ({r['k']}/{r['n']})"


def quantile(values: list[int], q: float) -> int:
    """Nearest-rank on the sorted values; same convention as triage_summary._p."""
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


def bootstrap_quantile_ci(values: list[int], q: float, n_boot: int = 2000, seed: int = 0) -> tuple[int, int]:
    if not values:
        return (0, 0)
    rng = random.Random(seed)
    stats = sorted(quantile([rng.choice(values) for _ in values], q) for _ in range(n_boot))
    return (stats[int(0.025 * (n_boot - 1))], stats[int(0.975 * (n_boot - 1))])


# --- calibration (D-03) -----------------------------------------------------------

T = TypeVar("T")


def brier(p: Sequence[float], y: Sequence[int]) -> Optional[float]:
    """Binary Brier score: mean squared gap between the probability and the 0/1 outcome."""
    if not p:
        return None
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(p)


def brier_multiclass(probs: Sequence[Mapping[str, float]], labels: Sequence[str]) -> Optional[float]:
    """Sum over classes of (p_k - [k is the label])^2, averaged; 0 is perfect, 2 is worst.
    A class missing from a distribution counts as probability 0."""
    if not probs:
        return None
    total = 0.0
    for dist, label in zip(probs, labels):
        total += sum((v - (1.0 if k == label else 0.0)) ** 2 for k, v in dist.items())
        if label not in dist:
            total += 1.0
    return total / len(probs)


def _bin(p: float, n_bins: int) -> int:
    return min(n_bins - 1, int(round(p * n_bins, 9)))


def reliability_table(p: Sequence[float], y: Sequence[int], n_bins: int = 10) -> list[dict[str, Any]]:
    """Equal-width bins on [0, 1]; the last bin is closed so p = 1.0 lands in it."""
    groups: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for pi, yi in zip(p, y):
        groups[_bin(pi, n_bins)].append((pi, yi))
    table = []
    for i, g in enumerate(groups):
        table.append({
            "lo": round(i / n_bins, 10),
            "hi": round((i + 1) / n_bins, 10),
            "n": len(g),
            "mean_p": sum(pi for pi, _ in g) / len(g) if g else None,
            "freq": sum(yi for _, yi in g) / len(g) if g else None,
        })
    return table


def ece(p: Sequence[float], y: Sequence[int], n_bins: int = 10) -> Optional[float]:
    """Expected calibration error: bin-weighted |mean probability - observed frequency|."""
    if not p:
        return None
    n = len(p)
    return sum(b["n"] / n * abs(b["mean_p"] - b["freq"]) for b in reliability_table(p, y, n_bins) if b["n"])


def fmt_reliability(table: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"     [{b['lo']:.1f}, {b['hi']:.1f}] n={b['n']:<4} mean_p={b['mean_p']:.3f} freq={b['freq']:.3f}"
        for b in table if b["n"]
    )


def _resample_indices(n: int, groups: Optional[Sequence[Hashable]], rng: random.Random) -> list[int]:
    if groups is None:
        return [rng.randrange(n) for _ in range(n)]
    members: dict[Hashable, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    keys = list(members)
    return [i for _ in keys for i in members[rng.choice(keys)]]


def _pct(stats: list[float], n_boot: int) -> tuple[float, float]:
    stats.sort()
    return (stats[int(0.025 * (n_boot - 1))], stats[int(0.975 * (n_boot - 1))])


def bootstrap_stat_ci(
    items: Sequence[T],
    stat: Callable[[list[T]], float],
    groups: Optional[Sequence[Hashable]] = None,
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile interval for any statistic of a list of items; with groups, whole groups
    (cases) are resampled so correlated items (a case's sections) are not counted as independent."""
    if not items:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        idx = _resample_indices(len(items), groups, rng)
        stats.append(stat([items[i] for i in idx]))
    return _pct(stats, n_boot)


def paired_bootstrap_diff_ci(
    a: Sequence[T],
    b: Sequence[T],
    stat: Callable[[list[T]], float],
    groups: Optional[Sequence[Hashable]] = None,
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """stat(a) - stat(b) with a percentile interval; a and b are aligned item by item and
    resampled with the same indices, so the case mix cancels out of the difference."""
    if not a:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        idx = _resample_indices(len(a), groups, rng)
        diffs.append(stat([a[i] for i in idx]) - stat([b[i] for i in idx]))
    lo, hi = _pct(diffs, n_boot)
    return (stat(list(a)) - stat(list(b)), lo, hi)
