from __future__ import annotations

import json

import pytest

from rapid_reports_ai.scripts.lab_session_summary import format_report, load_sessions, report, summarise


def _dec(i, route, latency=250, polish=None):
    return {
        "id": f"d{i}", "seq": i, "at": i, "route": route, "reason": "r", "qset": "2026-09-26.2",
        "action": None, "confidence": None, "probabilities": None, "is_correction": None, "standalone": None,
        "latency_ms": latency, "roundtrip_ms": None,
        "polish_called": route == "polish" if polish is None else polish,
        "polish_ms": 900 if route == "polish" else None,
        "utterance_len": 12, "utterance_hash": "deadbeef", "applied_len": 12,
        "closes_line": False, "line_closed_by": None, "error": None,
    }


def _out(i, kind, route):
    return {"decision_id": f"d{i}", "kind": kind, "route": route, "ms_since": 1500, "at": 0}


def _session(decisions, outcomes):
    return {"schema": "rr-lab-session/1", "started_at": 0, "exported_at": 1, "scan_type": "CT chest",
            "qsets": ["2026-09-26.2"], "decisions": decisions, "outcomes": outcomes}


S1 = _session(
    [_dec(1, "fast_append", 240), _dec(2, "fast_append", 260), _dec(3, "polish", 300), _dec(4, "command", 250),
     _dec(5, "skip", None)],
    [_out(1, "undo", "fast_append"), _out(1, "undo", "fast_append"), _out(3, "edit", "polish")],
)
S2 = _session([_dec(1, "polish", 320), _dec(2, "fast_append", 230)], [_out(2, "redictate", "fast_append")])


def test_polish_calls_against_the_polish_everything_baseline():
    s = summarise(S1["decisions"], S1["outcomes"])
    assert s["utterances"] == 5
    assert s["polish_calls"]["k"] == 1 and s["polish_calls"]["n"] == 5
    assert s["polish_calls"]["p"] == pytest.approx(0.2)
    assert s["polish_calls"]["ci95"][0] < 0.2 < s["polish_calls"]["ci95"][1]
    assert s["reduction_vs_baseline"] == pytest.approx(0.8)


def test_outcomes_counted_once_per_decision_by_route():
    s = summarise(S1["decisions"], S1["outcomes"])
    fa = s["routes"]["fast_append"]
    assert fa["n"] == 2 and fa["undo"]["k"] == 1 and fa["edit"]["k"] == 0 and fa["any"]["k"] == 1
    assert s["routes"]["polish"]["edit"]["k"] == 1
    assert s["routes"]["command"]["any"]["k"] == 0


def test_bundle_latency_only_over_decisions_that_asked_jev():
    s = summarise(S1["decisions"], S1["outcomes"])
    assert s["bundle_ms"]["n"] == 4
    assert s["bundle_ms"]["p50"] in (250, 260)
    lo, hi = s["bundle_ms"]["p50_ci95"]
    assert lo <= s["bundle_ms"]["p50"] <= hi


def test_report_per_session_and_overall_with_a_session_clustered_interval():
    r = report([("a.json", S1), ("b.json", S2)])
    assert [x["file"] for x in r["sessions"]] == ["a.json", "b.json"]
    o = r["overall"]
    assert o["utterances"] == 7 and o["polish_calls"]["k"] == 2
    lo, hi = o["polish_per_utterance_session_ci95"]
    assert 0.0 <= lo <= 2 / 7 <= hi <= 1.0
    text = format_report(r)
    assert "polish calls / utterance" in text and "fast_append" in text


def test_load_sessions_reads_files_and_directories_and_rejects_other_json(tmp_path):
    (tmp_path / "s1.json").write_text(json.dumps(S1))
    (tmp_path / "other.json").write_text(json.dumps({"schema": "something-else"}))
    sub = tmp_path / "more"
    sub.mkdir()
    (sub / "s2.json").write_text(json.dumps(S2))
    loaded = load_sessions([str(tmp_path / "s1.json"), str(sub)])
    assert [name for name, _ in loaded] == ["s1.json", "s2.json"]
    with pytest.raises(ValueError):
        load_sessions([str(tmp_path / "other.json")])


def test_overall_keeps_outcomes_with_their_own_session():
    """Decision ids are unique per session only; pooled outcomes must not cross over."""
    o = report([("a.json", S1), ("b.json", S2)])["overall"]
    fa, po = o["routes"]["fast_append"], o["routes"]["polish"]
    assert (fa["n"], fa["undo"]["k"], fa["redictate"]["k"]) == (3, 1, 1)
    assert (po["n"], po["undo"]["k"], po["edit"]["k"]) == (2, 0, 1)


def test_one_session_has_no_session_clustered_interval():
    """Resampling one cluster always returns it: [p, p] would look precise and is not."""
    r = report([("a.json", S1)])
    assert r["overall"]["polish_per_utterance_session_ci95"] is None
    assert "needs ≥ 2 sessions" in format_report(r)
