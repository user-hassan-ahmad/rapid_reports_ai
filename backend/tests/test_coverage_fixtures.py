from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "coverage_cases.jsonl"
REQUIRED = {"id", "scan_type", "checklist", "scratchpad", "expected_covered", "rule", "hard", "note"}
RULES = {
    "direct-subject", "direct-location", "direct-modifier", "collective-group", "collective-boundary",
    "specific-overrides-collective", "bare-mention", "adjacent-structure", "parent-not-enumerating",
    "incidental-co-mention", "vague-filler", "abbreviation",
}


def load():
    return [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]


def test_well_formed():
    cases = load()
    assert cases
    for c in cases:
        assert REQUIRED <= set(c), c.get("id")
        assert c["rule"] in RULES, c["id"]
        assert set(c["expected_covered"]) <= set(c["checklist"]), c["id"]
        assert isinstance(c["hard"], bool)


def test_ids_unique():
    ids = [c["id"] for c in load()]
    assert len(ids) == len(set(ids))


def test_every_rule_has_at_least_two_cases():
    counts = Counter(c["rule"] for c in load())
    for r in RULES:
        assert counts[r] >= 2, r
