"""Intervals for bake-off numbers. Every bake-off reports a 95 % interval (rev 2 §5).

Proportions use the Wilson score interval (sane at 0/n and n/n, unlike the normal
approximation). Latency p95 uses a seeded percentile bootstrap so reruns print the
same interval for the same data.
"""
from __future__ import annotations

import random
from math import sqrt
from typing import Any, Optional

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
