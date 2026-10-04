"""Eval harness helpers: output paths in the scratchpad, reuse of earlier outputs, the 2-run cap, the summary."""
import json
import os

import pytest

from rapid_reports_ai.scripts import review_engine_eval as E


def test_out_path_requires_scratch_and_has_pid(monkeypatch, tmp_path):
    monkeypatch.delenv("RR_LAB_OUT", raising=False)
    with pytest.raises(SystemExit):
        E.out_path("eval")
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    p = E.out_path("eval")
    assert p.parent == tmp_path / "review_eval" and str(os.getpid()) in p.name


def test_done_ids_reads_previous_outputs(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps({"report_id": "r1", "run": 1}) + "\n" + json.dumps({"report_id": "r2", "run": 1}) + "\n")
    assert E.done_ids([f], run=1) == {"r1", "r2"} and E.done_ids([f], run=2) == set()


def test_done_ids_skips_failed_rows(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps({"report_id": "r1", "run": 1, "exception": "Boom"}) + "\n")
    assert E.done_ids([f], run=1) == set()


def test_runs_capped():
    assert E.cap_runs(5) == 2 and E.cap_runs(1) == 1


def test_pct():
    assert E.pct([], 50) is None
    assert E.pct([10, 20, 30, 40], 50) == 25 and E.pct([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9.1


def test_item_counts_and_would_pre_apply():
    items = [{"lane": "coverage", "kind": "absent", "cls": "action", "status": "open",
              "evidence": {"would_pre_apply": True}},
             {"lane": "accuracy", "kind": "negative", "cls": "info", "status": "open", "evidence": None}]
    c = E.item_counts(items)
    assert c["lane"] == {"coverage": 1, "accuracy": 1} and c["cls"] == {"action": 1, "info": 1}
    assert c["would_pre_apply"] == 1


def test_edit_preview_insert_and_remove():
    rep = "FINDINGS:\nLiver normal. No ascites.\n"
    ins = E.edit_preview(rep, {"mode": "insert", "after": "Liver normal.", "replace": "Small cyst."})
    assert "Liver normal." in ins["before"] and "Small cyst." in ins["after"]
    rem = E.edit_preview(rep, {"mode": "remove", "find": "No ascites."})
    assert "No ascites." in rem["before"] and "No ascites." not in rem["after"]
