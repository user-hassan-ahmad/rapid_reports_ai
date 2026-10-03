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
