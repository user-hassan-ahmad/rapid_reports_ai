"""Alignment (spec §5.2): pure code, ambiguity kept."""
from rapid_reports_ai.review_engine.alignment import align, level_of, numbers, section_models, side_of

REPORT = ("FINDINGS:\nThe liver is normal. A 14 mm cyst is present in the left kidney. No free fluid.\n"
          "Right leg:\nNo deep vein thrombosis.\n\nIMPRESSION:\nLeft renal cyst.")
DICT = "- Liver normal\n- 14 mm left renal cyst\n- No DVT right leg\n- Spleen enlarged 15 cm"


def test_helpers():
    assert side_of("left and right kidneys") == "bilateral" and side_of("Left kidney") == "left" and side_of("x") is None
    assert level_of("Disc bulge at l4/5.") == "L4/5" and level_of("segment 7 lesion") == "SEGMENT 7"
    assert numbers("A 1.4 cm lesion and 12 mm node, 5x4 mm, at L4") == {"14mm", "12mm", "5", "4mm"}
    assert [s.role for s in section_models(["FINDINGS", "IMPRESSION", "TECHNIQUE", "Clinical history"])] == \
        ["findings", "impression", "technique", "history"]


def test_lines_and_clauses_with_offsets():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"])
    assert [l.text for l in al.lines][:2] == ["Liver normal", "14 mm left renal cyst"]
    assert al.lines[1].side == "left" and al.lines[2].negative
    c = next(c for c in al.clauses if "14 mm" in c.text)
    assert c.section == "FINDINGS" and REPORT[c.start:c.end] == c.text


def test_pairs_many_to_many_and_unmatched():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"])
    paired = [al.clause(p.clause_id).text for p in al.pairs if p.line_id == "d1"]
    assert any("14 mm" in t for t in paired) and any(t.startswith("Left renal cyst") for t in paired)
    assert "d3" in al.unmatched_lines
    assert all(0 < p.score <= 1 for p in al.pairs)


def test_subheading_side():
    al = align("FINDINGS:\nLeft side:\nThe kidney is normal. A 14 mm renal cyst.\n", "- 14 mm renal cyst", "", ["FINDINGS"])
    c = next(c for c in al.clauses if c.text.startswith("A 14 mm"))
    assert c.side is None and c.subheading_side == "left"


def test_level_mismatch_never_pairs():
    al = align("FINDINGS:\nDisc bulge at L4/5. Normal disc at L3/4.\n", "- Disc bulge L3/4", "", ["FINDINGS"])
    assert all(al.clause(p.clause_id).level != "L4/5" for p in al.pairs if p.line_id == "d0")


def test_history_lines_are_a_second_source_not_targets():
    al = align(REPORT, DICT, "Known left renal cyst", ["FINDINGS", "IMPRESSION"])
    assert al.history and al.history[0].id == "h0" and al.history[0].background
    assert all(p.line_id.startswith("d") for p in al.pairs)


def test_background_flag_by_index():
    al = align(REPORT, DICT, "", ["FINDINGS", "IMPRESSION"], background={0})
    assert al.lines[0].background and not al.lines[1].background


def test_no_sections_falls_back_to_whole_report():
    al = align("A 5 mm nodule.", "- 5 mm nodule", "", [])
    assert al.clauses and al.pairs
