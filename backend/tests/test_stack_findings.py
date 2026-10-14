import json
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.findings import findings_block, findings_text
from rapid_reports_ai.hybrid_stack.gate_model import GateRecord
from rapid_reports_ai.hybrid_stack.units import StackUnit

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "stack_golden.json").read_text())["cases"]


def _units(c):
    return [StackUnit.model_validate(u) for u in c["units"]]


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["name"])
def test_text_matches_the_browser(case):
    assert findings_text(_units(case), case["groups"]) == case["expected"]["text"]


@pytest.mark.parametrize("case", [c for c in GOLDEN if c["gate"]], ids=lambda c: c["name"])
def test_block_matches_the_browser(case):
    gate = GateRecord.model_validate(case["gate"])
    assert findings_block(_units(case), case["groups"], gate).block == case["expected"]["block"]


def test_plain_has_no_labels_or_removed():
    c = next(c for c in GOLDEN if c["name"] == "rows_assumed_conclusion_removed")
    st = findings_block(_units(c), c["groups"], GateRecord.model_validate(c["gate"]))
    plain = st.plain()
    for label in ("Answered by the radiologist:", "Assumed normal (confirmed", "Conclusion (confirmed",
                  "DO NOT ASSERT", "Confirmed normal (not dictated"):
        assert label not in plain
    for r in c["gate"]["removed"]:
        assert r not in plain
    assert c["gate"]["conclusion_text"].strip() in plain
    assert "Normal study apart from" not in plain          # the units' draft conclusion: the gate's wins
    assert not any(line.split(":")[0] in c["groups"] for line in plain.splitlines() if ":" in line)
    assert "Not enlarged." not in plain                     # a skipped row states nothing


def test_block_and_plain_use_the_reconciled_removed_list():
    units = [StackUnit.model_validate({"id": 1, "text": "No ascites.", "group": "Peritoneum"})]
    gate = GateRecord.model_validate({"removed": ["No ascites."]})
    st = findings_block(units, ["Peritoneum"], gate, removed=[])
    assert "DO NOT ASSERT" not in st.block and st.plain() == "No ascites."
