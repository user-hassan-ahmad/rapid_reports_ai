import json
from pathlib import Path

import pytest

from rapid_reports_ai.hybrid_stack.gate_model import GateRecord, findings_hash
from rapid_reports_ai.hybrid_stack.units import StackUnit

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "stack_golden.json").read_text())["cases"]


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["name"])
def test_findings_hash_matches_the_browser(case):
    units = [StackUnit.model_validate(u) for u in case["units"]]
    assert findings_hash(units) == case["expected"]["hash"]


def test_gate_record_keeps_unknown_fields_and_defaults():
    g = GateRecord.model_validate({"conclusion_text": "C.", "removed": ["No effusion."], "units_hash": "k",
                                   "future_field": 1})
    assert g.removed == ["No effusion."] and g.items == [] and g.assumed == {} and g.findings_hash is None
    assert g.model_extra == {"future_field": 1}
