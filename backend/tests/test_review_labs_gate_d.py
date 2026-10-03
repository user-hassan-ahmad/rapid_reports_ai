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
