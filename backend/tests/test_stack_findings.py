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


# ── filled_value_quotes: what Generate may write back for a value the writer dropped (P3 2026-10-15) ──
# SYNTHETIC units; the gate's quote is a comma-split clause of a dictated sentence.

def _vunit(i, text, group, parts=None):
    return StackUnit(id=i, text=text, group=group, parts=parts)


def _vgate(*chips, removed=()):
    return GateRecord.model_validate({"values": [dict(c) for c in chips], "removed": list(removed)})


def test_a_filled_values_write_back_is_its_whole_dictated_sentence_not_the_clause():
    from rapid_reports_ai.hybrid_stack.findings import filled_value_quotes
    units = [_vunit(1, "Aortic root measuring 3.4 cm at the sinuses, ascending aorta 3.0 cm.", "Aorta"),
             _vunit(2, "Kidneys: right 11 cm, left 10.5 cm.", "Kidneys")]
    gate = _vgate({"item": "Aortic root", "state": "filled", "value": "3.4 cm", "quote": "measuring 3.4 cm at the sinuses"},
                  {"item": "Right kidney", "state": "picked", "value": "11 cm", "quote": "right 11 cm"})
    out = filled_value_quotes(units, gate)
    assert out["Aortic root"]["sentence"] == "Aortic root measuring 3.4 cm at the sinuses, ascending aorta 3.0 cm."
    assert out["Aortic root"]["region"] == "Aorta"
    assert out["Right kidney"]["sentence"] == "Kidneys: right 11 cm, left 10.5 cm."
    assert out["Right kidney"]["region"] == "Kidneys"


def test_a_quote_no_dictated_unit_holds_is_dropped_and_a_chip_without_a_quote_has_no_entry():
    from rapid_reports_ai.hybrid_stack.findings import filled_value_quotes
    units = [_vunit(1, "LVEF 55%.", "Left ventricle")]
    gate = _vgate({"item": "RVEF", "state": "filled", "value": "50%", "quote": "RVEF 50%"},   # not dictated
                  {"item": "LV mass", "state": "filled", "value": None, "quote": None, "kept": True},
                  {"item": "LVEF", "state": "filled", "value": "55%", "quote": "LVEF 55%"})
    assert set(filled_value_quotes(units, gate)) == {"LVEF"}


def test_a_sentence_holding_removed_text_is_never_written_back():
    from rapid_reports_ai.hybrid_stack.findings import filled_value_quotes
    units = [_vunit(1, "Spleen 11 cm, small accessory spleen.", "Spleen")]
    gate = _vgate({"item": "Spleen length", "state": "filled", "value": "11 cm", "quote": "Spleen 11 cm"})
    assert "Spleen length" in filled_value_quotes(units, gate)
    assert filled_value_quotes(units, gate, removed=["small accessory spleen"]) == {}


def test_the_region_comes_from_the_part_holding_the_quote_before_a_part_inside_it():
    from rapid_reports_ai.hybrid_stack.findings import filled_value_quotes
    from rapid_reports_ai.hybrid_stack.units import PartOut
    unit = _vunit(1, "Spleen, spleen 11 cm in length.", "Other",
                  parts=[PartOut(text="Spleen", group="Other"), PartOut(text="spleen 11 cm in length.", group="Spleen")])
    gate = _vgate({"item": "Spleen length", "state": "filled", "value": "11 cm", "quote": "spleen 11 cm"})
    out = filled_value_quotes([unit], gate)
    assert out["Spleen length"]["region"] == "Spleen"            # not "Other", whose text sits inside the quote
    assert out["Spleen length"]["sentence"] == "spleen 11 cm in length."


def test_said_regions_run_parallel_to_said_parts():
    # SYNTHETIC: a placed unit carries its region; unplaced and fixed-group units and taps without a region carry ""
    units = [StackUnit.model_validate({"id": i, "text": t, "group": g, "structure": None, "attach_to": None,
                                       "parts": None, "covers": [], "abnormal": False, "pinned": False,
                                       "heading": False})
             for i, (t, g) in enumerate([("Cyst 2 cm.", "Right kidney"), ("Breathing artefact.", "General"),
                                         ("Loose sentence 3 mm.", None)], 1)]
    gate = GateRecord.model_validate({"items": [
        {"id": "a", "region": "Liver", "sentences": ["Segment 6 cyst 1 cm."], "answered_by": "tap"},
        {"id": "b", "region": "", "sentences": ["No collection."], "answered_by": "tap"}]})
    st = findings_block(units, ["Right kidney", "Liver", "General"], gate)
    assert list(zip(st.said_regions, st.said_parts)) == [
        ("Right kidney", "Cyst 2 cm."), ("", "Breathing artefact."), ("", "Loose sentence 3 mm."),
        ("Liver", "Segment 6 cyst 1 cm."), ("", "No collection.")]
