from __future__ import annotations

import pytest

from rapid_reports_ai.scripts.bakeoff_stats import bootstrap_quantile_ci, fmt_rate, quantile, rate, wilson


def test_wilson_known_values():
    lo, hi = wilson(47, 48)
    assert lo == pytest.approx(0.891, abs=1e-3) and hi == pytest.approx(0.9963, abs=1e-3)
    assert wilson(0, 10)[0] == 0.0 and wilson(0, 10)[1] == pytest.approx(0.2775, abs=1e-3)
    assert wilson(10, 10)[1] == 1.0 and wilson(10, 10)[0] == pytest.approx(0.7225, abs=1e-3)
    assert wilson(0, 0) == (0.0, 1.0)


def test_rate_and_format():
    r = rate(45, 49)
    assert r["k"] == 45 and r["n"] == 49 and r["p"] == pytest.approx(45 / 49)
    assert r["ci95"] == [pytest.approx(0.8081, abs=1e-4), pytest.approx(0.9678, abs=1e-4)]
    assert fmt_rate(r) == "0.918 [0.81, 0.97] (45/49)"
    assert rate(0, 0)["p"] is None and fmt_rate(rate(0, 0)) == "n/a (0/0)"


def test_quantile_matches_nearest_rank():
    assert quantile([], 0.95) == 0
    assert quantile([100, 200, 300, 400], 0.5) == 300
    assert quantile(list(range(1, 101)), 0.95) == 95


def test_bootstrap_ci_is_ordered_and_deterministic():
    vals = [300] * 95 + [900] * 5
    lo, hi = bootstrap_quantile_ci(vals, 0.95)
    assert 300 <= lo <= hi <= 900
    assert bootstrap_quantile_ci(vals, 0.95) == (lo, hi)  # seeded
    assert bootstrap_quantile_ci([250] * 20, 0.95) == (250, 250)
    assert bootstrap_quantile_ci([], 0.95) == (0, 0)
