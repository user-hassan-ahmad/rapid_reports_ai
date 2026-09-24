"""The fixture file is data the bake-off and the lab depend on; keep it well-formed."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from rapid_reports_ai.dictation_triage import TRIAGE_ACTIONS

FIXTURES = Path(__file__).parent / "fixtures" / "triage_utterances.jsonl"
REQUIRED = {
    "id", "committed", "active", "utterance", "scan_type",
    "expected_action", "expected_is_correction", "expected_needs_committed_edit", "hard", "note",
}


def load_cases() -> list[dict]:
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


def test_every_line_is_well_formed():
    cases = load_cases()
    assert cases, "fixture file is empty"
    for c in cases:
        assert REQUIRED <= set(c), f"{c.get('id')} missing {REQUIRED - set(c)}"
        assert c["expected_action"] in TRIAGE_ACTIONS, c["id"]
        assert isinstance(c["expected_is_correction"], bool)
        assert isinstance(c["expected_needs_committed_edit"], bool)
        assert isinstance(c["hard"], bool)
        assert c["utterance"].strip()


def test_ids_unique():
    ids = [c["id"] for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_at_least_eight_cases_per_action():
    counts = Counter(c["expected_action"] for c in load_cases())
    for action in TRIAGE_ACTIONS:
        assert counts[action] >= 8, f"{action}: {counts[action]}"
