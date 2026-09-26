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


# --- calibration (D-03) -----------------------------------------------------------

from rapid_reports_ai.scripts.bakeoff_stats import (  # noqa: E402
    bootstrap_stat_ci,
    brier,
    brier_multiclass,
    ece,
    fmt_reliability,
    paired_bootstrap_diff_ci,
    reliability_table,
)

P = [0.05, 0.15, 0.95, 1.0, 0.92]
Y = [0, 0, 1, 1, 0]


def test_brier_binary():
    assert brier([0.9, 0.2], [1, 0]) == pytest.approx((0.01 + 0.04) / 2)
    assert brier([1.0, 0.0], [1, 0]) == 0.0
    assert brier([], []) is None


def test_brier_multiclass_counts_missing_classes_as_zero():
    probs = [{"a": 0.7, "b": 0.3}, {"a": 0.4, "b": 0.5, "c": 0.1}]
    assert brier_multiclass(probs, ["a", "b"]) == pytest.approx((0.18 + 0.42) / 2)
    assert brier_multiclass([{"a": 1.0}], ["b"]) == pytest.approx(2.0)  # label absent from the map
    assert brier_multiclass([], []) is None


def test_reliability_table_bins():
    t = reliability_table(P, Y)
    assert len(t) == 10 and t[0]["lo"] == 0.0 and t[9]["hi"] == 1.0
    assert (t[0]["n"], t[0]["mean_p"], t[0]["freq"]) == (1, pytest.approx(0.05), 0.0)
    assert (t[1]["n"], t[1]["freq"]) == (1, 0.0)
    assert t[9]["n"] == 3  # 1.0 lands in the last bin, which is closed
    assert t[9]["mean_p"] == pytest.approx((0.95 + 1.0 + 0.92) / 3) and t[9]["freq"] == pytest.approx(2 / 3)
    assert t[5] == {"lo": 0.5, "hi": 0.6, "n": 0, "mean_p": None, "freq": None}
    assert sum(b["n"] for b in t) == 5
    assert reliability_table([0.1, 0.3], [0, 1])[1]["n"] == 1  # float edge: 0.1 is bin 1, not bin 0


def test_ece():
    # (1/5)|0.05-0| + (1/5)|0.15-0| + (3/5)|0.95667-0.66667|
    assert ece(P, Y) == pytest.approx(0.01 + 0.03 + 0.6 * ((0.95 + 1.0 + 0.92) / 3 - 2 / 3))
    assert ece([0.8] * 10, [1] * 8 + [0] * 2) == pytest.approx(0.0)
    assert ece([], []) is None


def test_bootstrap_stat_ci():
    items = list(zip(P, Y))
    stat = lambda xs: brier([p for p, _ in xs], [y for _, y in xs])
    lo, hi = bootstrap_stat_ci(items, stat)
    assert 0.0 <= lo <= stat(items) <= hi
    assert bootstrap_stat_ci(items, stat) == (lo, hi)  # seeded
    assert bootstrap_stat_ci([(0.5, 1)] * 6, stat) == (0.25, 0.25)
    # grouped: whole groups are resampled together
    g_lo, g_hi = bootstrap_stat_ci(items, stat, groups=["a", "a", "b", "b", "b"])
    assert g_lo <= g_hi


def test_paired_bootstrap_diff():
    items = list(zip(P, Y))
    stat = lambda xs: brier([p for p, _ in xs], [y for _, y in xs])
    assert paired_bootstrap_diff_ci(items, items, stat) == (0.0, 0.0, 0.0)
    hedged = [(0.5, y) for y in Y]            # 0.25 on every item
    sharp = [(float(y), y) for y in Y]         # 0.0 on every item
    assert paired_bootstrap_diff_ci(hedged, sharp, stat) == (0.25, 0.25, 0.25)
    mixed = [(0.5, y) for y in Y[:3]] + [(float(y), y) for y in Y[3:]]  # worse on 3 of 5, never better
    d, lo, hi = paired_bootstrap_diff_ci(mixed, sharp, stat)
    assert d == pytest.approx(0.15) and 0 < lo <= d <= hi


def test_fmt_reliability_skips_empty_bins():
    s = fmt_reliability(reliability_table(P, Y))
    assert s.count("\n") == 2 and "[0.9, 1.0] n=3" in s and "mean_p=0.957 freq=0.667" in s
