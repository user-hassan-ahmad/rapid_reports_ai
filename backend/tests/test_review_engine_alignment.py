"""Alignment (spec §5.2): pure code, ambiguity kept."""
from rapid_reports_ai.review_engine.alignment import align, level_of, levels_of, numbers, section_models, side_of

REPORT = ("FINDINGS:\nThe liver is normal. A 14 mm cyst is present in the left kidney. No free fluid.\n"
          "Right leg:\nNo deep vein thrombosis.\n\nIMPRESSION:\nLeft renal cyst.")
DICT = "- Liver normal\n- 14 mm left renal cyst\n- No DVT right leg\n- Spleen enlarged 15 cm"


def test_helpers():
    assert side_of("left and right kidneys") == "bilateral" and side_of("Left kidney") == "left" and side_of("x") is None
    assert level_of("Disc bulge at l4/5.") == "L4/5" and level_of("segment 7 lesion") == "SEGMENT 7"
    assert numbers("A 1.4 cm lesion and 12 mm node, 5x4 mm, at L4") == {"14mm", "12mm", "5mm", "4mm"}
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


# ── review fixes (synthetic probes) ──────────────────────────────────────────

def _al(report, dictation, sections=("FINDINGS",)):
    return align(report, dictation, "", list(sections))


def _best(al, lid):
    ps = sorted([p for p in al.pairs if p.line_id == lid], key=lambda p: -p.score)
    return [(al.clause(p.clause_id).text, p.how) for p in ps]


def test_levels_canonical_and_all_returned():
    for t in ["L4/5", "L4-L5", "L4-5", "L4/L5", "l4 / 5"]:
        assert level_of(t) == "L4/5", t
    assert level_of("L5-S1") == "L5/S1" and level_of("C7/T1") == "C7/T1" and level_of("fracture of T7.") == "T7"
    assert levels_of("Disc bulges at L3/4 and L4/5.") == ["L3/4", "L4/5"]
    assert levels_of("A 9 mm nodule in the right lower lobe.") == ["RLL"] and levels_of("RLL nodule") == ["RLL"]


def test_mri_sequences_and_tnm_are_not_levels():
    assert levels_of("T1 hypointense T2 hyperintense right frontal lesion") == []
    assert level_of("T2 weighted images") is None and level_of("high T2 signal") is None
    assert level_of("on FLAIR and T2") is None
    assert level_of("T3 N1 M0") is None and level_of("staged T2N0") is None
    assert level_of("abnormal signal in the T7 vertebral body") == "T7"


def test_numbers_units_levels_dates():
    assert numbers("5 x 4 cm") == {"50mm", "40mm"} and numbers("5x4 mm") == {"5mm", "4mm"}
    assert numbers("L4/5") == set() and numbers("12/03/2024") == set()
    assert numbers("4cm") == numbers("40mm") == {"40mm"}


def test_sides_abbreviations_and_false_friends():
    assert side_of("Rt kidney") == "right" and side_of("Lt kidney") == "left"
    assert side_of("R adrenal mass") == "right" and side_of("L kidney") == "left"
    assert side_of("RLL nodule") == "right" and side_of("LUL mass") == "left"
    assert side_of("liver and spleen are both in size") is None
    assert side_of("drain left in situ") is None and side_of("both kidneys") == "bilateral"


def test_level_variants_pair_and_multilevel_clause():
    al = _al("FINDINGS:\nAt L4-L5 there is a broad-based disc bulge. At L5/S1 there is a left paracentral protrusion.\n",
             "- L4/5 disc bulge\n- L5-S1 left paracentral protrusion")
    assert _best(al, "d0")[0][0].startswith("At L4-L5") and _best(al, "d1")[0][0].startswith("At L5/S1")
    al = _al("FINDINGS:\nDisc bulges at L3/4 and L4/5 without canal stenosis.\n", "- L4/5 disc bulge")
    assert al.clauses[0].levels == ["L3/4", "L4/5"] and al.clauses[0].level == "L3/4" and _best(al, "d0")


def test_mri_sequence_lines_pair():
    al = _al("FINDINGS:\nThere is a T2 hyperintense lesion in the right frontal lobe with no restricted diffusion.\n",
             "- T1 hypointense T2 hyperintense right frontal lesion")
    assert _best(al, "d0") and al.clauses[0].levels == []


def test_level_conflict_pair_dictation_is_truth():
    al = _al("FINDINGS:\nThere is a wedge fracture of T7.\n", "- T9 wedge fracture")
    assert [(p.line_id, p.how) for p in al.pairs] == [("d0", "level_conflict")]
    # a line that already pairs at its own level raises no conflicts with other levels
    al = _al("FINDINGS:\nDisc bulge at L4/5. Disc bulge at L3/4.\n", "- Disc bulge L3/4")
    assert [p.how for p in al.pairs if al.clause(p.clause_id).level == "L4/5"] == []


def test_subheading_lines_without_periods():
    al = _al("FINDINGS:\nLeft knee:\nSmall joint effusion\nRight knee:\nACL tear\n\nIMPRESSION:\nRight ACL tear.",
             "- Left knee small effusion\n- Right ACL tear", ("FINDINGS", "IMPRESSION"))
    f = [(c.text, c.side, c.subheading_side) for c in al.clauses if c.section == "FINDINGS"]
    assert f == [("Small joint effusion", None, "left"), ("ACL tear", None, "right")]


def test_subheading_side_not_clause_side_and_both_resets():
    rep = "FINDINGS:\nLeft knee:\nSmall joint effusion. The ACL is intact.\nRight knee:\nThe ACL is torn. No effusion.\n"
    al = _al(rep, "- Left knee small effusion")
    assert [(c.text, c.side, c.subheading_side) for c in al.clauses] == [
        ("Small joint effusion.", None, "left"), ("The ACL is intact.", None, "left"),
        ("The ACL is torn.", None, "right"), ("No effusion.", None, "right")]
    assert _best(al, "d0")[0][0] == "Small joint effusion."
    al = _al("FINDINGS:\nRight knee: Medial meniscal tear.\nBoth knees: Mild osteoarthritis.\nOther findings:\nBone islands.\n",
             "- x")
    assert [(c.text, c.subheading_side) for c in al.clauses] == [
        ("Medial meniscal tear.", "right"), ("Mild osteoarthritis.", "bilateral"), ("Bone islands.", None)]


def test_list_markers_and_digit_sentences():
    rep = ("FINDINGS:\nThe liver is normal. 14 mm cyst in the left kidney.\n\n"
           "IMPRESSION:\n1. 9 mm right lower lobe nodule; CT follow-up suggested.\n2) Simple left renal cyst.")
    al = _al(rep, "- Left kidney cyst 14 mm", ("FINDINGS", "IMPRESSION"))
    assert [c.text for c in al.clauses] == ["The liver is normal.", "14 mm cyst in the left kidney.",
                                            "9 mm right lower lobe nodule;", "CT follow-up suggested.",
                                            "Simple left renal cyst."]
    assert all(rep[c.start:c.end] == c.text for c in al.clauses)


def test_generic_words_do_not_pair():
    al = _al("FINDINGS:\nThe liver and spleen are normal in size. The pancreas is normal.\n",
             "- Liver normal\n- Spleen normal size\n- Gallbladder normal")
    assert "d2" in al.unmatched_lines
    assert [t for t, _ in _best(al, "d0")] == ["The liver and spleen are normal in size."]


def test_negative_lists_split_on_or_and_offsets():
    rep = "FINDINGS:\nNo free fluid, lymphadenopathy or bony lesion. No hydronephrosis or renal calculi.\n"
    al = _al(rep, "- No free fluid\n- No lymphadenopathy\n- No bony lesion\n- No renal calculi")
    assert [c.text for c in al.clauses] == ["No free fluid", "No lymphadenopathy", "No bony lesion",
                                            "No hydronephrosis", "No renal calculi"]
    assert all(c.negative for c in al.clauses)
    first = al.clauses[0]
    assert rep[first.start:first.end] == "No free fluid" and first.sentence_start == first.start
    second = al.clauses[1]     # synthetic item: offsets fall back to the sentence
    assert (second.start, second.end) == (second.sentence_start, second.sentence_end)
    assert rep[second.sentence_start:second.sentence_end].startswith("No free fluid, lymph")
    for i in range(4):
        assert _best(al, f"d{i}")[0][1] in ("exact", "lexical")
    one = _al("FINDINGS:\nNo pericolic or paracolic fluid collection.\n", "- x")
    assert [c.text for c in one.clauses] == ["No pericolic or paracolic fluid collection."]


def test_negative_extended():
    al = _al("FINDINGS:\nThe gallbladder is not seen. The adrenals are unremarkable.\n",
             "- Appendix absent\n- Right no effusion")
    assert all(c.negative for c in al.clauses) and all(l.negative for l in al.lines)


def test_side_numbers_pairs():
    al = _al("FINDINGS:\nA 4 cm mass in the right adrenal gland.\n", "- R adrenal mass 4cm\n- Rt adrenal mass 40mm")
    assert [l.side for l in al.lines] == ["right", "right"] and len(al.pairs) == 2


def test_empty_inputs():
    assert _al("", "").clauses == [] and _al("   ", "- Liver normal").unmatched_lines == ["d0"]
