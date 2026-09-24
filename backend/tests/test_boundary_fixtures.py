import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "boundary_cases.jsonl"
REQUIRED = {
    "id", "scan_type", "buffered", "chunk", "scratchpad_tail",
    "expected_boundary", "expected_asr_risk", "hard", "note",
}


def load():
    return [json.loads(l) for l in FIXTURES.read_text().splitlines() if l.strip()]


def test_well_formed():
    for c in load():
        assert REQUIRED <= set(c), c.get("id")
        assert c["expected_boundary"] in {"complete", "continues", "command"}, c["id"]
        assert isinstance(c["expected_asr_risk"], bool) and isinstance(c["hard"], bool)
        assert c["chunk"].strip()
        if "expected_placement" in c:
            assert c["expected_placement"] in {"extend_previous_line", "new_line", "new_paragraph"}, c["id"]
            assert c["expected_boundary"] == "complete", c["id"]


def test_ids_unique_and_ten_per_class():
    cases = load()
    assert len({c["id"] for c in cases}) == len(cases)
    counts = Counter(c["expected_boundary"] for c in cases)
    for k in ("complete", "continues", "command"):
        assert counts[k] >= 10, k
