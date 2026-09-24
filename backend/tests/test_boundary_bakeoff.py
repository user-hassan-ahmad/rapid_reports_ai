from __future__ import annotations

from rapid_reports_ai.scripts.boundary_bakeoff import expected_standalone, score_boundary


def _row(i, expected, raw, code, standalone, lat=300, err=None):
    return {"id": f"r{i}", "expected_boundary": expected, "raw": raw, "resolved": raw, "code": code,
            "standalone": standalone, "confidence": 0.9, "latency_ms": lat, "cost_usd": 1e-5, "error": err,
            "hard": False}


def test_expected_standalone():
    assert expected_standalone({"expected_boundary": "complete"}) is True
    assert expected_standalone({"expected_boundary": "continues"}) is False
    assert expected_standalone({"expected_boundary": "command"}) is None


def test_score_boundary():
    rows = [
        _row(1, "complete", "complete", "complete", 0.8),
        _row(2, "continues", "complete", "continues", 0.7),   # jev wrong, code right, standalone wrong
        _row(3, "command", "command", "command", 0.1),        # standalone not scored
        _row(4, "complete", None, "continues", None, lat=0, err="TriageError"),
    ]
    s = score_boundary(rows)
    assert s["n"] == 4 and s["errors"] == 1
    assert (s["jev_raw"]["k"], s["jev_raw"]["n"]) == (2, 3)
    assert (s["code"]["k"], s["code"]["n"]) == (3, 4)          # code has no error rows
    assert (s["standalone_jev"]["k"], s["standalone_jev"]["n"]) == (1, 2)
    assert (s["standalone_code"]["k"], s["standalone_code"]["n"]) == (2, 3)
    assert (s["by_class"]["continues"]["code"]["k"], s["by_class"]["continues"]["jev_raw"]["k"]) == (1, 0)
    assert s["latency_p95_ms"] == 300
