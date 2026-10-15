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


def test_said_is_only_the_radiologists_units_and_taps():
    c = next(c for c in GOLDEN if c["name"] == "rows_assumed_conclusion_removed")
    st = findings_block(_units(c), c["groups"], GateRecord.model_validate(c["gate"]), removed=[])
    said = st.said()
    assert "Liver 18 cm." in said and "No focal lesion." in said and "No appendicitis." in said
    assert "Portal vein patent." not in said and "Spleen normal." not in said   # assumed normals never override
    assert "Hepatomegaly." not in said                                         # nor does the conclusion


def test_applied_recommendations_reach_the_block_and_plain():
    c = next(c for c in GOLDEN if c["name"] == "rows_assumed_conclusion_removed")
    recs = [{"key": "k1", "text": "Solid nodule 6-8 mm: CT at 3 months (BTS 2015)."}, {"key": "k2", "text": "  "}]
    st = findings_block(_units(c), c["groups"], GateRecord.model_validate({**c["gate"], "recommendations": recs}))
    assert "Recommendations (selected by the radiologist): Solid nodule 6-8 mm: CT at 3 months (BTS 2015)." in st.block
    assert "Solid nodule 6-8 mm: CT at 3 months (BTS 2015)." in st.plain()     # its numbers count as stated
    assert "Recommendations (selected" not in st.plain()
    plain = findings_block(_units(c), c["groups"], GateRecord.model_validate(c["gate"]))
    assert findings_block(_units(c), c["groups"], GateRecord.model_validate({**c["gate"], "recommendations": recs[1:]})).block == plain.block


def test_an_applied_line_counts_as_stated_for_the_number_check_and_the_post_gen_check():
    """backend-1b 2026-10-15: report.py passes Statements.all_texts() to undictated_numbers, and plain() feeds the
    removed guard and the post-generation check, so a selected line is treated as the radiologist's statement: its
    guideline numbers are never flagged as undictated, and the omission check may restore it if the writer drops it
    (intended)."""
    from rapid_reports_ai.template_number_check import undictated_numbers
    c = next(c for c in GOLDEN if c["name"] == "rows_assumed_conclusion_removed")
    line = "Solid nodule 6-8 mm: CT in 3 months (BTS 2015)."
    st = findings_block(_units(c), c["groups"], GateRecord.model_validate({**c["gate"], "recommendations": [{"text": line}]}))
    assert line in st.all_texts() and line in st.plain()
    report = "Impression: follow-up CT in 3 months."
    flagged = lambda texts: [n for n in undictated_numbers(report, texts, "") if "3" in n["text"]]   # noqa: E731
    without = findings_block(_units(c), c["groups"], GateRecord.model_validate(c["gate"]))
    assert flagged(without.all_texts())            # control: with no applied line the 3 is undictated
    assert not flagged(st.all_texts())             # the applied line supplies it
