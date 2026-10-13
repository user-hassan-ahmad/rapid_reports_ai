"""The findings-triggered rows lab's pure scoring (the runners call Jev / Qwen and are run by the controller)."""
from rapid_reports_ai.scripts import triggered_rows_lab as lab

SET = {"slug": "s", "examples": ["a", "b", "c"], "truth": {"habits": [
    {"id": "h1", "paragraph": "Upper", "condition": "c1", "reports": [1, 3]},
    {"id": "h2", "paragraph": "Upper", "condition": "c2", "reports": [2]},
    {"id": "h3", "paragraph": "Lower", "condition": "c3", "reports": [1, 2]}]}}


def test_score_propose_counts_matches_singles_and_quotes():
    payload = {"habits": [{}, {}, {}], "raw_quotes": 8, "verified_quotes": 6}
    row = lab.score_propose(SET, payload, {"0": "h1", "1": "h2", "2": None})
    assert row == {"slug": "s", "proposed": 3, "tp": 1, "fp": 2, "single_proposed": 1, "real": 2, "found": 1,
                   "raw_quotes": 8, "verified_quotes": 6}
    s = lab.summarise_propose([row, {**row, "slug": "t", "tp": 2, "fp": 1, "found": 2}])
    assert (s["precision"], s["recall"], s["quotes_verified"], s["single_proposed"]) == (0.5, 0.75, 0.75, 2)


def test_score_trigger_rows_and_tables():
    tset = {"slug": "t", "dictations": [
        {"id": "d1", "category": "met", "met": ["c1"], "answered": {"c1": "no"}},
        {"id": "d2", "category": "negated", "met": []},
        {"id": "d3", "category": "hedged", "met": []}]}
    payload = {"habits": [{"condition": "c1", "region": "Upper", "mode": "ask"}],
               "scores": {"d1": {"c1": 0.9}, "d2": {"c1": 0.6}, "d3": {"c1": 0.2}},
               "stated": {"d1": {"c1": [0.1, 0.95]}, "d2": {"c1": [0.0, 0.0]}, "d3": {"c1": [0.0, 0.0]}}}
    rows = lab.score_trigger(tset, payload)
    assert [(r["category"], r["truth"], r["score"]) for r in rows] == [("met", True, 0.9), ("negated", False, 0.6),
                                                                       ("hedged", False, 0.2)]
    table = lab.trigger_table(rows, thresholds=(0.5, 0.7))
    assert table["negated"] == {"n": 1, 0.5: 0.0, 0.7: 1.0} and table["all"]["n"] == 3
    assert lab.answered_table(rows, 0.8) == {"n": 1, "correct": 1, "false_fold": 0, "missed": 0}
    assert lab.band_table(rows, 0.35, 0.5) == {"n": 3, "in_band": 0, "in_band_met": 0, "rate": 0.0}
    banded = [{**rows[0], "score": 0.4}, rows[1], rows[2]]
    assert lab.band_table(banded, 0.35, 0.5) == {"n": 3, "in_band": 1, "in_band_met": 1, "rate": 0.333}
    prf = lab.prf_table(rows, 0.5)
    assert prf["met"] == {"n": 1, "tp": 1, "fp": 0, "fn": 0, "p": 1.0, "r": 1.0}
    assert prf["negated"] == {"n": 1, "tp": 0, "fp": 1, "fn": 0, "p": 0.0, "r": None}
    assert prf["all"]["p"] == 0.5 and prf["all"]["r"] == 1.0


def test_cap_pressure_ranks_template_rows_first_within_the_caps():
    assert lab.cap_pressure(["A"], ["A", "A", "B"]) == {"template_rows": 1, "template_capped": 0, "generic_pushed": 1}
    assert lab.cap_pressure(["A", "B", "C", "D", "E"], ["A"]) == {"template_rows": 4, "template_capped": 1,
                                                                   "generic_pushed": 1}
    assert lab.cap_pressure([], ["A"]) == {"template_rows": 0, "template_capped": 0, "generic_pushed": 0}


def test_session_caps_uses_met_ask_habits_only():
    tset = {"slug": "t", "dictations": [{"id": "d1", "category": "met", "met": ["c1"], "generic": ["Upper", "Upper"]}]}
    payload = {"habits": [{"condition": "c1", "region": "Upper", "mode": "ask"},
                          {"condition": "c2", "region": "Upper", "mode": "state"}],
               "scores": {"d1": {"c1": 0.9, "c2": 0.9}}, "stated": {}}
    assert lab.session_caps(tset, payload, 0.5) == [{"id": "d1", "template_rows": 1, "template_capped": 0,
                                                    "generic_pushed": 1}]


def test_md_table():
    assert lab.md_table(["a", "b"], [[1, 2]]) == "| a | b |\n|---|---|\n| 1 | 2 |"


def test_report_writes_every_table_from_the_root(tmp_path):
    import json
    (tmp_path / "sets").mkdir()
    (tmp_path / "sets" / "t.json").write_text(json.dumps({"slug": "t", "scan_type": "CT", "sheet": "", "dictations": [
        {"id": "d1", "category": "met", "met": ["c1"], "answered": {"c1": "no"}, "generic": ["Upper"]}]}))
    out = tmp_path / "runs" / "trigger" / "sets" / "run1-B"
    out.mkdir(parents=True)
    (out / "t.json").write_text(json.dumps({"habits": [{"condition": "c1", "region": "Upper", "mode": "ask"}],
                                            "scores": {"d1": {"c1": 0.9}}, "stated": {"d1": {"c1": [0.1, 0.9]}}}))
    text = lab.report(tmp_path, "trigger", "sets", 1, "B")
    for head in ("precision / recall by variant", "Trigger accuracy by category", "Silent band", "Already answered",
                 "Rows per session against the caps"):
        assert head in text, head
    assert (tmp_path / "REPORT_trigger_sets.md").read_text() == text
    assert lab.DEFAULT_ROOT.parts[-3:] == ("rr-template-conversion-private", "synthetic", "triggered_rows")


def test_propose_report_gives_precision_recall_and_verified_quotes(tmp_path):
    import json
    (tmp_path / "propose").mkdir()
    (tmp_path / "propose" / "s.json").write_text(json.dumps(SET))
    for sub, data in (("runs/propose/sets/run1", {"habits": [{}, {}], "raw_quotes": 4, "verified_quotes": 3}),
                      ("labels/propose/run1", {"0": "h1", "1": None})):
        (tmp_path / sub).mkdir(parents=True)
        (tmp_path / sub / "s.json").write_text(json.dumps(data))
    text = lab.report(tmp_path, "propose", "sets", 1, "B")
    assert "precision" in text and "recall" in text and "quotes_verified" in text and "0.75" in text
