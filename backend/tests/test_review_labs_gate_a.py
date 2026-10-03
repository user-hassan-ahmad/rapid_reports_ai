import os

import pytest

from rapid_reports_ai.scripts.review_labs import gate_a as GA


def test_gate_a_card_hides_engine_and_peer_read():
    src = {"n": 7, "kind": "partial", "id8": "abcd1234", "scan": "CT", "detector_line": "Line X",
           "report_sentence": "Sentence Y", "dictation_full": "Line X", "report_full": "Sentence Y",
           "class": "suppress", "issue": "v3 issue"}
    peer = {"n": 7, "verdict": "minor", "reason": "peer reason"}
    card = GA.label_card(src, peer)
    shown = " ".join(b["text"] for b in card["blocks"])
    hidden = " ".join(b["text"] for b in card["hidden"])
    assert card["id"] == "c7" and "Line X" in shown
    assert "suppress" not in shown and "peer reason" not in shown
    assert "suppress" in hidden and "peer reason" in hidden


def test_gate_a_card_ids_constant():
    assert len(GA.LABEL_SET) == 27 and len(set(GA.LABEL_SET)) == 27


def test_gate_a_items_map_kinds_and_ids():
    cards = [{"n": 1, "kind": "contradiction", "id8": "r1", "detector_line": "No X."}]
    compare = [{"id8": "r1", "jev_pool_unsampled": [{"kind": "omission", "text": "Y seen"}]}]
    cases = {"r1": {"id": "r1-full", "scan": "CT", "dictation": "d", "history": "", "report": "No X."}}
    items = GA.build_items(cards, compare, cases)
    assert [i["id"] for i in items] == ["c1", "u-r1-0"]
    assert items[0]["candidate"] == {"lane": "accuracy", "kind": "contradicted", "detector": "jev.contradiction",
                                     "anchor": "No X.", "line": None, "evidence": {}}
    assert items[1]["candidate"]["kind"] == "absent" and items[1]["candidate"]["line"] == "Y seen"


def _row(i, run, cls, id8, **kw):
    return {"item_id": i, "id8": id8, "run": run, "cls": cls, **kw}


def test_gate_a_score_core():
    rows = [
        _row("c1", 1, "action", "r1", verified={"code": True}),
        _row("c1", 2, "action", "r1"),
        _row("c2", 1, "suppress", "r1", verified={"code": False}),
        _row("c2", 2, "minor", "r1", error="boom"),
        _row("c3", 1, "action", "r2", verified={"code": True, "unconfirmed": True}),
        _row("c3", 2, "action", "r2"),
    ]
    labels = {"rules": "text", "c1": {"verdict": "action", "material": True},
              "c2": {"verdict": "action"}, "c3": {"verdict": "suppress"}, "c4": {"at": 123}}
    read = {"c5": {"at": 1}}
    m = GA.score(labels, read, rows)
    assert {"recall", "material", "precision", "noise"} <= set(m["pass"])
    assert m["errors"] == 1 and m["n_labelled"] == 3
    assert m["fix_rejected_by_guards"] == 1 and m["unconfirmed"] == 1
    assert m["disagreements"] == ["c2", "c3"]
    assert m["class_change_share"] == pytest.approx(1 / 3)


def test_gate_a_synthetic_items():
    data = [{"id": "s-1", "category": "x", "label": "action", "scan": "CT", "dictation": "d", "history": "",
             "report": "r", "candidate": {"lane": "coverage", "kind": "partial", "detector": "synthetic",
                                          "line": "L", "anchor": None, "evidence": {}}}]
    items, labels = GA.build_synthetic_items(data)
    assert items == [{"id": "s-1", "id8": "s-1", "case": {"scan": "CT", "dictation": "d", "history": "", "report": "r"},
                      "candidate": data[0]["candidate"]}]
    assert labels == {"s-1": {"verdict": "action"}}
