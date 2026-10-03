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
