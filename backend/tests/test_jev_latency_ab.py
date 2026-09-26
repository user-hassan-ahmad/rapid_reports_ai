from __future__ import annotations

from rapid_reports_ai.scripts.jev_latency_ab import summarise_arms


def test_summarise_arms():
    s = summarise_arms({"fresh": [500] * 18 + [900] * 2, "shared": [300] * 20, "empty": []})
    assert s["fresh"]["n"] == 20 and s["fresh"]["p50"] == 500 and s["fresh"]["p95"] == 900
    assert s["shared"] == {"n": 20, "p50": 300, "p50_ci": [300, 300], "p95": 300, "p95_ci": [300, 300]}
    lo, hi = s["fresh"]["p95_ci"]
    assert 500 <= lo <= hi <= 900
    assert s["empty"]["n"] == 0
