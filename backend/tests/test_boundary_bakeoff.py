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


def test_boundary_calibration():
    from rapid_reports_ai.scripts.boundary_bakeoff import boundary_calibration

    def row(cid, exp, jev_probs, lp_probs, st=0.8, asr=0.2, err=None):
        return {"id": cid, "expected_boundary": exp, "expected_asr_risk": False, "error": None,
                "probabilities": jev_probs, "standalone": st, "asr_risk": asr,
                "qwen_lp": None if err else {"boundary": {"probabilities": lp_probs}, "standalone": {"noul": st},
                                             "asr_risk": {"noul": asr}},
                "qwen_lp_error": err}

    p = {"complete": 0.8, "continues": 0.1, "command": 0.1}
    rows = [row("a", "complete", p, p), row("b", "command", p, p), row("c", "continues", p, p, err="X")]
    blocks = {s["question"]: s for s, _ in boundary_calibration(rows)}
    assert blocks["boundary"]["candidates"]["jev"]["n"] == 2
    assert blocks["standalone"]["candidates"]["qwen-lp"]["n"] == 1  # commands carry no standalone label
    assert blocks["asr_risk"]["candidates"]["jev"]["n"] == 2
