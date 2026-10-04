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


# ── Gate B1 peer-read fixes (synthetic text, patterns only) ───────────────────

def _pairs(al):
    return sorted((p.line_id, al.clause(p.clause_id).text) for p in al.pairs)


def test_dash_level_ranges_are_canonical():
    for t, lv in [("L4–L5", "L4/5"), ("L4—L5", "L4/5"), ("L4 – L5", "L4/5"), ("C5–C6", "C5/6"),
                  ("T11–T12", "T11/12"), ("T12–L1", "T12/L1"), ("L5‐S1", "L5/S1")]:
        assert levels_of(f"Disc bulge at {t}.") == [lv], t
    al = _al("FINDINGS:\nAt L4–L5 there is a broad disc bulge. At L5–S1 there is a small disc protrusion.\n",
             "- L4-L5 broad disc bulge\n- L5-S1 small disc protrusion")
    assert all(p.how != "level_conflict" for p in al.pairs)
    assert _pairs(al) == [("d0", "At L4–L5 there is a broad disc bulge."),
                          ("d1", "At L5–S1 there is a small disc protrusion.")]


def test_best_match_pruning_keeps_only_near_best():
    from rapid_reports_ai.review_engine.alignment import BEST_MARGIN
    assert BEST_MARGIN == 0.15
    rep = ("FINDINGS:\nSmall right pleural effusion. Right basal atelectasis adjacent to the pleural effusion "
           "with volume loss.\n")
    al = _al(rep, "- Small right pleural effusion\n- Right basal atelectasis with volume loss")
    assert _pairs(al) == [("d0", "Small right pleural effusion."),
                          ("d1", "Right basal atelectasis adjacent to the pleural effusion with volume loss.")]


def test_merge_and_split_still_many_to_many():
    al = _al("FINDINGS:\nThe cruciate and collateral ligaments are intact.\n",
             "- Cruciate ligaments intact\n- Collateral ligaments intact")
    assert [l for l, _ in _pairs(al)] == ["d0", "d1"]
    al = _al("FINDINGS:\nA 14 mm cyst in the left kidney.\n\nIMPRESSION:\nSimple left renal cyst.",
             "- 14 mm simple left renal cyst", ("FINDINGS", "IMPRESSION"))
    assert len(_pairs(al)) == 2                       # a finding and its impression restatement


def test_siblings_by_side_never_pair():
    rep = "FINDINGS:\nLeft knee:\nSmall joint effusion. The ACL is intact.\nRight knee:\nSmall joint effusion. The ACL is torn.\n"
    al = _al(rep, "- Left small joint effusion\n- Right small joint effusion\n- Right ACL torn")
    sides = {(p.line_id, al.clause(p.clause_id).subheading_side) for p in al.pairs}
    assert sides == {("d0", "left"), ("d1", "right"), ("d2", "right")}
    al = _al("FINDINGS:\nA 5 mm left renal calculus. A 5 mm right renal calculus.\n",
             "- 5 mm left renal calculus\n- 5 mm right renal calculus")
    assert _pairs(al) == [("d0", "A 5 mm left renal calculus."), ("d1", "A 5 mm right renal calculus.")]
    al = _al("FINDINGS:\nBilateral renal calculi.\n", "- Left renal calculus\n- Right renal calculus")
    assert [l for l, _ in _pairs(al)] == ["d0", "d1"]          # bilateral is neutral


def test_siblings_by_level_never_pair_and_conflict_only_without_own_level():
    rep = "FINDINGS:\nAt L4/5 there is a mild disc bulge. At L5/S1 there is a mild disc bulge.\n"
    al = _al(rep, "- L4/5 mild disc bulge\n- L5/S1 mild disc bulge")
    assert _pairs(al) == [("d0", "At L4/5 there is a mild disc bulge."), ("d1", "At L5/S1 there is a mild disc bulge.")]
    # the line's own level exists in the report (with other words): no conflict pairs to other levels
    rep = "FINDINGS:\nAt L4/5 the disc is normal. At L5/S1 there is a disc protrusion.\n"
    al = _al(rep, "- L4/5 disc protrusion")
    assert all(p.how != "level_conflict" for p in al.pairs)


def test_side_header_blocks_without_colon():
    from rapid_reports_ai.review_engine.alignment import report_clauses
    rep = "FINDINGS:\nMRI knee left\nThe ACL is intact. Small joint effusion.\nRIGHT KNEE\nThe ACL is torn.\n\nIMPRESSION:\nACL tear."
    cl = report_clauses(rep, ["FINDINGS", "IMPRESSION"])
    assert [(c.text, c.subheading_side) for c in cl] == [
        ("The ACL is intact.", "left"), ("Small joint effusion.", "left"), ("The ACL is torn.", "right"),
        ("ACL tear.", None)]
    assert all(rep[c.start:c.end] == c.text for c in cl)
    al = _al(rep, "MRI knee left\n- ACL intact\n- Small joint effusion\nRight leg\n- ACL torn",
             ("FINDINGS", "IMPRESSION"))
    assert [(l.id, l.side, l.block_side) for l in al.lines] == [
        ("d1", None, "left"), ("d2", None, "left"), ("d4", None, "right")]
    assert ("d1", "The ACL is torn.") not in _pairs(al) and ("d4", "The ACL is intact.") not in _pairs(al)
    assert ("d4", "The ACL is torn.") in _pairs(al)
    # a finding line naming a side is not a header
    al = _al("FINDINGS:\nSmall effusion.\n", "- Left knee small effusion")
    assert [l.id for l in al.lines] == ["d0"]


def test_stems_fold_morphology_without_altering_text():
    from rapid_reports_ai.review_engine.alignment import stems
    assert stems("dilated") == stems("dilatation") == stems("dilation")
    assert stems("lesions") == stems("lesion") and stems("viscera") == stems("visceral")
    assert stems("ventricle") == stems("ventricular") and stems("bases") == stems("base")
    assert stems("aorta") == stems("aortic") and stems("processes") == stems("process")
    al = _al("FINDINGS:\nThe lateral ventricles are mildly dilated. No pelvic visceral abnormality.\n",
             "- Mild dilatation of the lateral ventricle\n- Pelvic viscera unremarkable")
    assert _pairs(al) == [("d0", "The lateral ventricles are mildly dilated."), ("d1", "No pelvic visceral abnormality.")]
    assert al.clauses[0].text == "The lateral ventricles are mildly dilated."


def test_single_shared_word_does_not_pair():
    al = _al("FINDINGS:\nThe patellofemoral joint is normal.\n", "- Mild suprapatellar joint effusion")
    assert al.pairs == []
    al = _al("FINDINGS:\nA cyst in the liver.\n", "- Renal cortical cyst")
    assert al.pairs == []
    al = _al("FINDINGS:\nThe liver contains a 12 mm cyst.\n", "- 12 mm renal cyst")
    assert len(al.pairs) == 1                                        # one stem plus a shared number
    al = _al("FINDINGS:\nAt L4/5 there is a protrusion.\n", "- L4/5 protrusion contacting nerve root")
    assert len(al.pairs) == 1                                        # one stem plus a shared level
    al = _al("FINDINGS:\nThe common carotid artery is patent. The previous graft is patent.\n",
             "- Vertebral artery occluded\n- Previous stent in situ")
    assert al.pairs == []                                            # umbrella words are generic


def test_grouped_normal_summary_carries_member_lines():
    from rapid_reports_ai.review_engine.alignment import GROUP_TERMS
    assert "solid organs" in GROUP_TERMS
    rep = "FINDINGS:\nThe solid abdominal organs are unremarkable. The bowel is normal.\n"
    al = _al(rep, "- Liver normal\n- Spleen normal\n- Pancreas unremarkable\n- Colon unremarkable\n"
                  "- Gallbladder contains a stone\n- Liver lesion 12 mm")
    assert _pairs(al) == [("d0", "The solid abdominal organs are unremarkable."),
                          ("d1", "The solid abdominal organs are unremarkable."),
                          ("d2", "The solid abdominal organs are unremarkable."),
                          ("d3", "The bowel is normal.")]
    rep = "FINDINGS:\nThe liver is normal. The remaining solid organs are unremarkable.\n"
    al = _al(rep, "- Liver normal\n- Spleen normal")
    assert _pairs(al) == [("d0", "The liver is normal."), ("d1", "The remaining solid organs are unremarkable.")]


def test_negative_list_keeps_head_noun():
    al = _al("FINDINGS:\nNo rib, hip or pelvic fractures. No suspicious calvarial or skull base lesion.\n"
             "No hydronephrosis or renal stones.\n", "- x")
    assert [c.text for c in al.clauses] == ["No rib fractures", "No hip fractures", "No pelvic fractures",
                                            "No suspicious calvarial lesion", "No skull base lesion",
                                            "No hydronephrosis", "No renal stones"]


def test_signature_lines_are_not_clauses():
    rep = "FINDINGS:\nSmall effusion.\n\nIMPRESSION:\nSmall effusion.\nGMC 1234567\nReported by: Dr A Example\n"
    al = _al(rep, "- Small effusion", ("FINDINGS", "IMPRESSION"))
    assert [c.text for c in al.clauses] == ["Small effusion.", "Small effusion."]


def test_dictated_conclusion_heading_is_not_a_line():
    al = _al("FINDINGS:\nSmall effusion.\n", "- Small effusion\nConclusion:\n- Effusion")
    assert [l.id for l in al.lines] == ["d0", "d2"]


def test_stems_latin_plurals():
    from rapid_reports_ai.review_engine.alignment import stems
    assert stems("calculus") == stems("calculi") and stems("meniscus") == stems("menisci")


def test_level_blocks_from_a_leading_level():
    rep = ("FINDINGS:\nAt L4/5 there is a disc bulge. Moderate canal stenosis is present.\n\n"
           "At L5/S1 there is a disc bulge. Mild canal stenosis is present.\n\n"
           "The conus ends at T12/L1. Vertebral body heights are normal.\n")
    dic = "- At L4/5 there is a disc bulge\n- Moderate canal stenosis\n- At L5/S1 there is a disc bulge\n- Mild canal stenosis"
    al = _al(rep, dic)
    assert [(l.id, l.block_levels) for l in al.lines] == [("d0", []), ("d1", ["L4/5"]), ("d2", []), ("d3", ["L5/S1"])]
    assert [c.block_levels for c in al.clauses] == [[], ["L4/5"], [], ["L5/S1"], [], []]   # a mid-sentence level opens no block
    assert _pairs(al) == [("d0", "At L4/5 there is a disc bulge."), ("d1", "Moderate canal stenosis is present."),
                          ("d2", "At L5/S1 there is a disc bulge."), ("d3", "Mild canal stenosis is present.")]
    assert all(p.how != "level_conflict" for p in al.pairs)                # inherited levels never raise conflicts


def test_pair_kept_when_near_best_for_either_end():
    # the clause merges three lines; the shortest scores lowest for the clause but the clause is that line's best
    rep = "FINDINGS:\nModerate canal stenosis secondary to a broad disc bulge, facet hypertrophy and ligamentum flavum thickening.\n"
    al = _al(rep, "- Moderate canal stenosis\n- Broad disc bulge\n- Ligamentum flavum thickening with facet hypertrophy")
    assert [l for l, _ in _pairs(al)] == ["d0", "d1", "d2"]


def test_function_words_and_umbrella_words_do_not_pair():
    al = _al("FINDINGS:\nThere are two renal calculi which show posterior shadowing.\n",
             "- There are two small liver cysts which show no enhancement")
    assert al.pairs == []
    al = _al("FINDINGS:\nRight upper lobe pulmonary nodule.\n", "- Right lower lobe pulmonary consolidation")
    assert al.pairs == []
    al = _al("FINDINGS:\nThe prevertebral soft tissues are unremarkable.\n", "- Soft tissue swelling over the elbow")
    assert al.pairs == []


def test_synonyms_abbreviations_and_spellings_pair():
    from rapid_reports_ai.review_engine.alignment import stems
    assert stems("oedema") == stems("edema") and stems("haemorrhage") == stems("hemorrhage")
    assert stems("artefact") == stems("artifact") and stems("visualised") == stems("visualized")
    for rep, d in [("No mediastinal lymphadenopathy.", "- No enlarged mediastinal lymph nodes"),
                   ("The anterior cruciate ligament is intact.", "- ACL intact"),
                   ("The distal superficial femoral artery is patent.", "- Distal SFA patent throughout"),
                   ("Significant motion artefact limits assessment.", "- Significant motion artifact")]:
        assert len(_al(f"FINDINGS:\n{rep}\n", d).pairs) == 1, rep


def test_grouped_line_naming_the_group_pairs_each_group_clause():
    rep = "FINDINGS:\nNo upper abdominal visceral abnormality. The pelvic viscera are unremarkable.\n"
    al = _al(rep, "- Unremarkable abdominopelvic viscera and bowel")
    assert [c for _, c in _pairs(al)] == ["No upper abdominal visceral abnormality.", "The pelvic viscera are unremarkable."]
