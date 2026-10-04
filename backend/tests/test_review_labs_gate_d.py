import os

import pytest

from rapid_reports_ai.scripts.review_labs import gate_d as GD


def test_reconstruct_edits():
    qc = {"flags": [{"kind": "contradiction", "text": "No free fluid", "score": 0.8},
                    {"kind": "contradiction", "text": "Liver enlarged", "score": 0.7},
                    {"kind": "omission", "text": "Small left pleural effusion", "score": 0.1}],
          "kept_dictated_negative": [], "clauses_removed": 1, "edits_applied": 1}
    content = "FINDINGS:\nThe liver is normal. There is a small left pleural effusion.\nIMPRESSION:\nEffusion."
    final = content.replace(" There is a small left pleural effusion.", "")
    edits = GD.reconstruct(qc, content, final)
    rem = [e for e in edits if e["type"] == "removal"]
    ins = [e for e in edits if e["type"] == "insertion"]
    assert [e["text"] for e in rem] == ["No free fluid"]          # the positive contradiction is never auto-removed
    assert ins[0]["located"] == "There is a small left pleural effusion."
    assert ins[0]["kept_by_user"] is False


REPORT = ("FINDINGS:\nThe liver is normal. There is no free fluid. The spleen is normal.\nIMPRESSION:\nNormal.")
NEW = ("FINDINGS:\nThe liver is normal. The spleen is normal. There is a small left pleural effusion.\nIMPRESSION:\nNormal.")
TEL = {"flags": [{"kind": "contradiction", "text": "no free fluid", "score": 0.8},
                 {"kind": "omission", "text": "Small left pleural effusion", "score": 0.1}],
       "kept_dictated_negative": [], "clauses_removed": 1, "edits_applied": 1}


def test_replay_edits_exact_location():
    edits = GD.replay_edits(TEL, REPORT, NEW)
    rem = [e for e in edits if e["type"] == "removal"]
    ins = [e for e in edits if e["type"] == "insertion"]
    assert [e["text"] for e in rem] == ["no free fluid"]
    assert ins[0]["located"] == "There is a small left pleural effusion."
    assert all(e["original"] == REPORT for e in edits)


def test_replay_edits_nothing_applied():
    assert GD.replay_edits({"flags": [{"kind": "omission", "text": "x", "score": 0.1}]}, REPORT, REPORT) == []


def test_replay_edits_skips_unremoved_flag():
    # the flagged clause is still in the new report: not an applied removal
    tel = {"flags": [{"kind": "contradiction", "text": "no free fluid", "score": 0.8}], "kept_dictated_negative": []}
    assert GD.replay_edits(tel, REPORT, REPORT.replace("liver", "kidney")) == []


def test_pre_edit_both_row_kinds():
    live_ins = {"type": "insertion", "content": NEW, "located": "There is a small left pleural effusion.", "text": "x"}
    assert "pleural" not in GD.pre_edit(live_ins)
    live_rem = {"type": "removal", "content": REPORT.replace(" There is no free fluid.", ""), "text": "no free fluid"}
    assert "no free fluid." in GD.pre_edit(live_rem)
    for t in ("insertion", "removal"):
        assert GD.pre_edit({"type": t, "content": NEW, "original": REPORT, "text": "t", "located": "t"}) == REPORT


def test_cmd_replay_with_fake_check(monkeypatch, tmp_path):
    import json
    from rapid_reports_ai import report_review
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    calls = []

    async def fake(report, findings, scan_type, options, **kw):
        calls.append((findings, scan_type, options))
        return (NEW if report == REPORT else report), [], dict(TEL)

    monkeypatch.setattr(report_review, "run_quality_check", fake)
    src = tmp_path / "src.json"
    rows = [{"id": f"{i}abcdef0123", "input_data": {"variables": {"FINDINGS": "d", "SCAN_TYPE": "CT", "CLINICAL_HISTORY": "h"}},
             "report_content": REPORT if i == 1 else "A. B.", "final_report_content": None} for i in (1, 2)]
    src.write_text(json.dumps(rows))
    GD.main(["replay", "--source", str(src), "--only", "1abcdef0"])
    out = json.loads((tmp_path / "gate_d" / "edits_replay.json").read_text())
    assert len(calls) == 1 and calls[0][2] == []
    assert {e["type"] for e in out} == {"removal", "insertion"}
    e = out[0]
    assert e["created_at"] == "replay" and e["report_type"] == "replay" and e["final"] is None
    assert e["content"] == NEW and e["original"] == REPORT and e["scan"] == "CT" and e["history"] == "h"
    assert e["key"].startswith("1abcdef0-")


def test_latest_edits_prefers_replay(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("RR_LAB_OUT", str(tmp_path))
    d = tmp_path / "gate_d"
    d.mkdir()
    (d / "edits_since_2026-10-01.json").write_text(json.dumps([{"key": "a"}]))
    assert GD._latest_edits() == [{"key": "a"}] and GD._source_label() == "pull since 2026-10-01"
    (d / "edits_replay.json").write_text(json.dumps([{"key": "r"}]))
    assert GD._latest_edits() == [{"key": "r"}] and GD._source_label() == "replay"
