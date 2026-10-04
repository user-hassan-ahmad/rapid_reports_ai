"""Binding correction 12 (spec §9, 2026-10-04): only code-built edits are pre-applied, and the one-click guard
fixes from the adversarial re-review of 431c96c (t10 probes A–H). Synthetic text only."""
import pytest

from rapid_reports_ai.report_review import quick_section_names
from rapid_reports_ai.review_engine import verifier as V
from rapid_reports_ai.review_engine.items import Edit


def R(body, imp="Normal."):
    return f"FINDINGS:\n{body}\nIMPRESSION:\n{imp}"


def G(report, edit, kind="partial", d="", h="", **kw):
    kw.setdefault("sections", quick_section_names(report))
    return V.guard_failures(report, edit, kind, d, h, **kw)


def PA(report, edit, kind, d="", code_built=True, line_text=None):
    return V.preapply_failures(report, edit, kind, d, code_built=code_built, line_text=line_text,
                               sections=quick_section_names(report))


def rem(find):
    return Edit(mode="remove", find=find)


def rep(find, replace, mode="replace"):
    return Edit(mode=mode, find=find, replace=replace)


# ── insert_from_line ────────────────────────────────────────────────────────
def test_insert_from_line_tidies_only_and_anchors_on_last_sentence():
    rpt = R("Liver normal. Spleen normal.")
    e = V.insert_from_line(rpt, "-  small   left renal cyst", "FINDINGS", sections=quick_section_names(rpt))
    assert e == Edit(mode="insert", after="Spleen normal.", replace="Small left renal cyst.", section="FINDINGS")
    assert V.apply_edit(rpt, e, quick_section_names(rpt)) == R("Liver normal. Spleen normal. Small left renal cyst.")


def test_insert_from_line_keeps_words_and_existing_stop():
    rpt = R("Liver normal.")
    e = V.insert_from_line(rpt, "2. 5 mm nodule?", "FINDINGS")
    assert e.replace == "5 mm nodule?"


def test_insert_from_line_empty_body_anchor_none():
    rpt = "FINDINGS:\n\nIMPRESSION:\nNormal."
    e = V.insert_from_line(rpt, "small effusion", "FINDINGS", sections=quick_section_names(rpt))
    assert e is not None and e.after is None and e.replace == "Small effusion."


def test_insert_from_line_refuses_unsafe():
    assert V.insert_from_line(R("Liver normal."), "", "FINDINGS") is None
    assert V.insert_from_line("IMPRESSION:\nNormal.", "small effusion", "FINDINGS") is None
    rpt = R("Liver normal. No effusion")                    # last sentence has no end: not a sentence end
    assert V.insert_from_line(rpt, "small effusion", "FINDINGS") is None
    rpt = R("Liver normal.", imp="Liver normal.")           # anchor not unique
    assert V.insert_from_line(rpt, "small effusion", "FINDINGS") is None


# ── pre-apply: removal ──────────────────────────────────────────────────────
def test_preapply_removal_code_built_negative_ok():
    rpt = R("Small left effusion. No pneumothorax. Liver normal.")
    assert PA(rpt, rem("No pneumothorax."), "contradicted", d="Small left pneumothorax.") == []
    rpt = R("Liver normal. The appendix is not dilated.")
    assert PA(rpt, rem("The appendix is not dilated."), "contradicted", d="Dilated appendix 9 mm.") == []
    rpt = R("Liver normal. There is no hydronephrosis.")
    assert PA(rpt, rem("There is no hydronephrosis."), "contradicted", d="Mild left hydronephrosis.") == []


def test_preapply_removal_requires_code_built():
    rpt = R("Small left effusion. No pneumothorax. Liver normal.")
    assert PA(rpt, rem("No pneumothorax."), "contradicted", d="Small pneumothorax.", code_built=False)


def test_preapply_removal_requires_remove_mode_or_pure_list_item_drop():
    # t11 3d: _negative_fix's pure-deletion replace (one list item dropped) is now eligible like a remove;
    # any other replace is not
    rpt = R("No effusion, pneumothorax, or consolidation. Liver normal.")
    e = rep("No effusion, pneumothorax, or consolidation.", "No effusion or consolidation.")
    assert PA(rpt, e, "contradicted", d="Small pneumothorax.") == []
    e = rep("No effusion, pneumothorax, or consolidation.", "No effusion or consolidation is seen.")
    assert PA(rpt, e, "contradicted", d="Small pneumothorax.")


@pytest.mark.parametrize("body,find", [
    ("Liver normal. No effusion but a 4 mm nodule is seen.", "No effusion but a 4 mm nodule is seen."),     # D4
    ("Liver normal. No effusion, small 4 mm nodule seen.", "No effusion, small 4 mm nodule seen."),         # D3
    ("Liver normal. No effusion. small 4 mm nodule.", "No effusion. small 4 mm nodule."),                   # D6/H13
    ("Liver normal. No effusion… Small 4 mm nodule.", "No effusion… Small 4 mm nodule."),                   # D7
    ("Liver normal. No effusion? Small 4 mm nodule.", "No effusion? Small 4 mm nodule."),                   # D8
    ("Liver normal. No effusion: small 4 mm nodule.", "No effusion: small 4 mm nodule."),                   # D9
    ("Liver normal. No effusion but there is a 4 mm nodule.", "No effusion but there is a 4 mm nodule."),   # H2
    ("Liver normal. Small left effusion, no pneumothorax.", "Small left effusion, no pneumothorax."),       # H5
    ("Liver normal. No effusion — small 4 mm nodule.", "No effusion — small 4 mm nodule."),                 # H12
    ("Liver normal. No effusion. 4 mm nodule.", "No effusion. 4 mm nodule."),                               # H14
    ("Liver normal. No effusion. (4 mm nodule.)", "No effusion. (4 mm nodule.)"),                           # H15
    ("Liver normal. Small 4 mm nodule in the right lower lobe.", "Small 4 mm nodule in the right lower lobe."),  # H4
    ("Simple cyst without enhancement. Liver normal.", " without enhancement"),                             # A13
    ("Liver normal. Nil free fluid.", "Nil"),                                                               # A12
    ("Liver normal. Unremarkable spleen.", "Unremarkable spleen."),                 # unremarkable is not a negator
])
def test_preapply_removal_negative_only(body, find):
    assert PA(R(body), rem(find), "contradicted")


@pytest.mark.parametrize("body,find,d", [
    ("Liver normal. No PE.", "No PE.", "No PE."),                                                   # E1
    ("Liver normal. No free fluid.", "No free fluid.", "Nil free fluid."),                          # E2
    ("Liver normal. No pneumothorax.", "No pneumothorax.", "No PTX."),                              # E3
    ("Liver normal. No collection.", "No collection.", "Free of collections."),                     # E4
    ("Liver normal. No effusion.", "No effusion.", "Neither effusion nor pneumothorax."),           # E7
    ("Liver normal. Nil ascites.", "Nil ascites.", "Nil ascites."),                                 # H17
])
def test_preapply_removal_never_dictated(body, find, d):
    assert PA(R(body), rem(find), "contradicted", d=d)
    assert "remove_dictated" in G(R(body), rem(find), "contradicted", d=d)


@pytest.mark.parametrize("report,find", [
    ("FINDINGS:\nLiver normal.\n\nIMPRESSION:\n1. No free fluid.", "No free fluid."),                        # F21
    ("FINDINGS:\n\nCHEST:\nNo pneumothorax.\n\nABDOMEN:\nLiver normal.\n\nIMPRESSION:\nNormal.", "No pneumothorax."),  # F9
])
def test_preapply_removal_never_empties_a_section(report, find):
    assert PA(report, rem(find), "contradicted")


def test_preapply_removal_list_items_of_negative_sentence():
    rpt = R("Liver normal. No effusion, pneumothorax or consolidation.")
    assert PA(rpt, rem(", pneumothorax"), "contradicted", d="Small pneumothorax.") == []
    rpt = R("No pleural effusion, pericardial effusion or ascites. Liver normal.")             # C1: two items
    assert PA(rpt, rem(", pericardial effusion or ascites"), "contradicted", d="Moderate ascites.")


# ── pre-apply: insert ───────────────────────────────────────────────────────
def test_preapply_insert_code_built_ok():
    rpt = R("Liver normal. Spleen normal.")
    line = "5 mm left renal cyst"
    e = V.insert_from_line(rpt, line, "FINDINGS")
    assert PA(rpt, e, "absent", d=f"Liver normal.\n{line}", line_text=line) == []


@pytest.mark.parametrize("edit,line,d", [
    # B5: model text, an undictated negative and finding
    (Edit(mode="insert", replace="Small left effusion. No pneumothorax. Rib fracture.", section="FINDINGS"),
     "small left effusion", "small left effusion"),
    # H20: the number comes from history, not the line
    (Edit(mode="insert", replace="Known 3 cm left renal mass.", section="FINDINGS"), "left renal mass", "left renal mass"),
    # B6/B7/E14: mid-sentence anchors
    (Edit(mode="insert", after="Liver", replace="Small effusion.", section="FINDINGS"), "small effusion", "small effusion"),
    # F1: heading in text
    (Edit(mode="insert", replace="Small effusion.\nIMPRESSION:\nEffusion.", section="FINDINGS"),
     "small effusion", "small effusion"),
    # IMPRESSION is not FINDINGS
    (Edit(mode="insert", replace="Small effusion.", section="IMPRESSION"), "small effusion", "small effusion"),
])
def test_preapply_insert_refused(edit, line, d):
    rpt = R("Liver normal. Spleen normal.")
    assert PA(rpt, edit, "absent", d=d, line_text=line)


def test_preapply_insert_needs_line_and_dictated_line():
    rpt = R("Liver normal.")
    e = V.insert_from_line(rpt, "small effusion", "FINDINGS")
    assert PA(rpt, e, "absent", d="small effusion", line_text=None)
    assert PA(rpt, e, "absent", d="liver normal", line_text="small effusion")    # line is not in the dictation


# ── pre-apply: positive correction ──────────────────────────────────────────
def test_preapply_positive_correction_side_ok():
    rpt = R("There is a 4 mm nodule in the right lower lobe. Liver normal.")
    line = "4 mm nodule in the left lower lobe"
    e = rep("There is a 4 mm nodule in the right lower lobe.", "There is a 4 mm nodule in the left lower lobe.")
    # t11: positive corrections are deferred to Gate F (spec §9), never pre-applied
    assert PA(rpt, e, "contradicted", d=line, code_built=False, line_text=line) == ["correction_one_click"]


def test_preapply_positive_correction_number_ok():
    rpt = R("Liver normal. There is a 4 mm nodule in the right lower lobe.")
    line = "6 mm nodule right lower lobe"
    e = rep("4 mm nodule", "6 mm nodule")
    assert PA(rpt, e, "contradicted", d=line, line_text=line) == ["correction_one_click"]     # t11: deferred


@pytest.mark.parametrize("find,replace,line", [
    # H7: the new side is in some other dictated line, not the line about this sentence
    ("right lower lobe apex", "left lower lobe apex", "Left kidney normal."),
    # more than side/number/hedge changes
    ("There is a 4 mm nodule in the right lower lobe.", "There is a 6 mm mass in the right lower lobe.",
     "6 mm mass right lower lobe"),
    # unit change is not a number change
    ("4 mm nodule", "4 cm nodule", "4 cm nodule right lower lobe"),
    # new token not in line
    ("4 mm nodule", "5 mm nodule", "6 mm nodule right lower lobe"),
])
def test_preapply_positive_correction_refused(find, replace, line):
    rpt = R("There is a 4 mm nodule in the right lower lobe apex. Liver normal.")
    assert PA(rpt, rep(find, replace), "contradicted", d=line, line_text=line)


def test_preapply_positive_correction_needs_line_and_positive_find():
    rpt = R("No effusion. Liver normal.")
    assert PA(rpt, rep("No effusion.", "Effusion."), "contradicted", d="Effusion.", line_text="Effusion.")
    rpt = R("There is a 4 mm nodule in the right lower lobe. Liver normal.")
    assert PA(rpt, rep("right", "left"), "contradicted", d="left lower lobe nodule", line_text=None)


def test_preapply_anything_else_ineligible():
    rpt = R("Small effusion. Liver normal.")
    assert PA(rpt, rep("Small effusion.", "Small left effusion.", "upgrade"), "partial", d="small left effusion",
              line_text="small left effusion") == ["not_preapply_eligible"]


# ── one-click guard fixes (Part B) ──────────────────────────────────────────
@pytest.mark.parametrize("find,replace,body", [
    ("Nil free fluid.", "Free fluid.", "Nil free fluid. Liver normal."),                                 # A1
    ("Free of collections.", "Collections present.", "Free of collections. Liver normal."),             # A2
    ("Neither effusion nor pneumothorax.", "Effusion and pneumothorax.",
     "Neither effusion nor pneumothorax. Liver normal."),                                               # A3
    ("No free fluid.", "No doubt, free fluid is present.", "No free fluid. Liver normal."),             # A5
])
def test_negator_flip_fails_outside_removal(find, replace, body):
    assert "drops_negation" in G(R(body), rep(find, replace, "upgrade"))


def test_negative_rescoped_fails():                                                                    # A4
    f = G(R("No pneumothorax. Liver normal."),
          rep("No pneumothorax.", "No interval change in the left pneumothorax."), d="left lung")
    assert {"drops_negation", "drops_negative_item"} & set(f)


def test_removal_kind_flip():
    # A8: a flip that adds words is not a removal
    f = G(R("No PE. Liver normal."), rep("No PE.", "Large PE."), "contradicted", d="Liver normal.", target="No PE.")
    assert "removal_adds_content" in f
    # A7: a removal-kind flip by deletion stays one-click (test_contradicted_list_item_drop_is_exempt_from_
    # drops_negation sanctions it), but is never pre-applied: a removal is pre-applied only as mode "remove"
    rpt, e = R("No free fluid. Liver normal."), rep("No free fluid.", "Free fluid.")
    assert PA(rpt, e, "contradicted", d="Liver normal.")


@pytest.mark.parametrize("find,replace,d", [
    ("No effusion.", "Large right effusion.", "right kidney cyst"),                                    # B3
    ("No effusion.", "No effusion. Large pneumothorax.", ""),                                          # B4
    ("No effusion.", "No right effusion.", "Right kidney normal. Left effusion."),                     # H18
])
def test_removal_replace_only_deletes(find, replace, d):
    assert "removal_adds_content" in G(R(f"{find} Liver normal."), rep(find, replace), "contradicted", d=d)


def test_removal_replace_deleting_words_ok():
    rpt = R("No effusion, pneumothorax, or consolidation. Liver normal.")
    e = rep("No effusion, pneumothorax, or consolidation.", "No effusion or consolidation.")
    assert G(rpt, e, "contradicted", d="Small pneumothorax.", target="No pneumothorax") == []


@pytest.mark.parametrize("body,after", [
    ("There is no free fluid. Liver normal.", "There is no"),                                          # B6
    ("The spleen is not enlarged. Liver normal.", "The spleen is"),                                    # B7
    ("The left kidney has a 2 cm cyst. Liver normal.", "The left kidney"),                             # E14
])
def test_insert_mid_sentence_fails(body, after):
    e = Edit(mode="insert", after=after, replace="Small effusion.", section="FINDINGS")
    assert "anchor_mid_sentence" in G(R(body), e, "absent", d="small effusion")


def test_insert_after_sentence_or_label_ok():
    e = Edit(mode="insert", after="Liver normal.", replace="Small 5 mm left renal cyst.", section="FINDINGS")
    assert G(R("Liver normal. Spleen normal."), e, "absent", d="5 mm left renal cyst") == []
    rpt = "FINDINGS:\n\nCHEST:\nLungs clear.\n\nIMPRESSION:\nNormal."
    e = Edit(mode="insert", after="CHEST:", replace="Small left effusion.", section="FINDINGS")
    assert "anchor_mid_sentence" not in G(rpt, e, "absent", d="small left effusion")


@pytest.mark.parametrize("report,edit,kind", [
    (R("Liver normal."), Edit(mode="insert", replace="Small effusion.\nIMPRESSION:\nEffusion.", section="FINDINGS"),
     "absent"),                                                                                         # F1
    (R("Liver normal. Small effusion."), rep("Small effusion.", "Small left effusion.\n\nIMPRESSION:\nEffusion.",
                                             "upgrade"), "partial"),                                    # H9
    (R("Liver normal. Small effusion."), rep("Small effusion.", "Small left effusion. IMPRESSION: Effusion.",
                                             "upgrade"), "partial"),
    (R("Liver normal. No effusion."), rem("No effusion.\nIMPRESSION:\nNormal."), "contradicted"),        # F2
    (R("Liver normal. No effusion."), rep("No effusion.\nIMPRESSION:\nNormal.", "Normal."), "contradicted"),  # F3
    (R("Liver normal. No effusion."), rep("No effusion.\nIMPRESSION:\nNormal.", "Unremarkable study."),
     "contradicted"),                                                                                   # H8
])
def test_structure(report, edit, kind):
    assert "structure" in G(report, edit, kind, d="small left effusion", target="No effusion.")


@pytest.mark.parametrize("body,find", [
    ("Liver normal. No effusion. small 4 mm nodule.", "No effusion. small 4 mm nodule."),               # D6
    ("Liver normal. No effusion… Small 4 mm nodule.", "No effusion… Small 4 mm nodule."),               # D7
    ("Liver normal. No effusion? Small 4 mm nodule.", "No effusion? Small 4 mm nodule."),               # D8
    ("Liver normal. No effusion. 4 mm nodule.", "No effusion. 4 mm nodule."),                           # H14
    ("Liver normal. No effusion. (4 mm nodule.)", "No effusion. (4 mm nodule.)"),                       # H15
    ("Liver normal. No effusion — small 4 mm nodule.", "No effusion — small 4 mm nodule."),             # H12
    ("Liver normal. No effusion but there is a 4 mm nodule.", "No effusion but there is a 4 mm nodule."),  # H2
    ("Liver normal. No effusion: small 4 mm nodule.", "No effusion: small 4 mm nodule."),               # D9
])
def test_removal_takes_no_positive_neighbour(body, find):
    assert G(R(body), rem(find), "contradicted", target="No effusion")
    assert G(R(body), rem(find), "removed")                                                              # H3


def test_splitter_digit_and_paren_starts():
    assert len(V._sentences("No effusion. 4 mm nodule. (Old fracture.)")) == 3
    assert len(V._sentences("No effusion… Small nodule? Yes.")) == 3


def test_dictated_mixed_polarity_sentence_protected():                                                 # H5
    rpt = R("Liver normal. Small left effusion, no pneumothorax.")
    f = G(rpt, rem("Small left effusion, no pneumothorax."), "contradicted",
          d="Small left effusion. Small pneumothorax.", target="no pneumothorax")
    assert f


def test_dictated_acronym_list_item_protected():                                                       # E8 / H19
    rpt = R("No PE, effusion or nodule. Liver normal.")
    f = G(rpt, rep("No PE, effusion or nodule.", "No effusion or nodule."), "contradicted",
          d="Lungs clear, no PE.", target="No PE")
    assert "remove_dictated" in f
    rpt = R("No PE or effusion. Liver normal.")
    assert "remove_dictated" in G(rpt, rep("No PE or effusion.", "No effusion."), "removed", d="no PE")


@pytest.mark.parametrize("report,edit,target", [
    (R("No pleural effusion, pericardial effusion or ascites. Liver normal."),
     rem(", pericardial effusion or ascites"), "No ascites"),                                            # C1
    (R("No pleural effusion, pericardial effusion or ascites. Liver normal."),
     rep("No pleural effusion, pericardial effusion or ascites.", "No pleural effusion."), "No ascites"),  # C2
    (R("No pleural effusion, pericardial effusion or ascites."),
     rep("pleural effusion, pericardial effusion or ascites", "pleural effusion"), None),               # C7
])
def test_lost_negatives_counts_items(report, edit, target):
    kind = "removed" if target is None else "contradicted"
    assert "drops_negative_item" in G(report, edit, kind, target=target)


@pytest.mark.parametrize("find,replace,d", [
    # H7: side flipped on a dictated sentence
    ("right lower lobe apex", "left lower lobe apex",
     "There is a 4 mm nodule in the right lower lobe apex, unchanged. Left kidney normal."),
    # number changed on a dictated sentence
    ("4 mm nodule", "5 mm nodule", "There is a 4 mm nodule in the right lower lobe apex, unchanged. 5 mm cyst."),
])
def test_alters_dictated(find, replace, d):
    rpt = R("There is a 4 mm nodule in the right lower lobe apex, unchanged. Liver normal.")
    assert "alters_dictated" in G(rpt, rep(find, replace), "contradicted", d=d)


def test_alters_dictated_spanning_replace():                                                           # H6
    rpt = R("No effusion. There is a 4 mm nodule in the right lower lobe apex. Liver normal.")
    e = rep("No effusion. There is a 4 mm nodule in the right lower lobe apex.",
            "There is a 4 mm nodule in the lower lobe apex.")
    f = G(rpt, e, "contradicted", d="4 mm nodule right lower lobe apex. Small effusion.", target="No effusion.")
    assert "alters_dictated" in f


def test_correction_towards_dictation_not_alters_dictated():
    rpt = R("Small 4 mm nodule in the right lower lobe apex posteriorly. Liver normal.")
    e = rep("right lower lobe", "left lower lobe")
    assert "alters_dictated" not in G(rpt, e, "contradicted",
                                      d="Small 4 mm nodule in the left lower lobe apex posteriorly.")


def test_dictated_shorthand_positive_protected():                                                      # E9
    rpt = R("Left 2 cm SOL in liver. Spleen normal.")
    f = G(rpt, rep("Left 2 cm SOL in liver.", "Liver SOL."), "contradicted", d="L liver SOL 2 cm.")
    assert "remove_dictated" in f


def test_insert_from_line_after_closing_label():
    rpt = "FINDINGS:\nLungs clear.\n\nABDOMEN:\n\nIMPRESSION:\nNormal."
    e = V.insert_from_line(rpt, "small ascites", "FINDINGS", sections=quick_section_names(rpt))
    assert e is not None and e.after == "ABDOMEN:"


# ── t11 adversarial re-review of ddcb88a: regression tests ──────────────────
def PAI(report, line, d, line_context=None):
    """Pre-apply of code's own insert of `line` (the worst case: the edit is exactly insert_from_line's)."""
    names = quick_section_names(report)
    e = V.insert_from_line(report, line, "FINDINGS", sections=names)
    assert e is not None, "insert_from_line refused: test would not exercise preapply_failures"
    return V.preapply_failures(report, e, "absent", d, code_built=True, line_text=line, sections=names,
                               line_context=line_context)


def R2(body, imp="1. Normal."):
    return f"FINDINGS:\n{body}\n\nIMPRESSION:\n{imp}"


# 1. positive corrections are deferred (spec §9: measured in Gate F first): never pre-applied
@pytest.mark.parametrize("body,find,replace,d", [
    ("Hepatic lesion segment 6. Malignancy is unlikely.", "is unlikely", "is likely",
     "Malignancy unlikely, likely benign haemangioma."),                                                  # C1
    ("Fracture of the left distal radius.", "radius.", "radius unlikely.",
     "Fracture left distal radius, scaphoid fracture unlikely"),                                          # C2
    ("Nodule in segment 7 measures 8 mm.", "7 measures", "12 measures", "Segment 7 nodule now 12 mm."),   # C3
    ("Lesion measures 12 x 8 mm.", "12 x", "9 x", "Lesion 12 x 9 mm."),                                   # C4
    ("Disc protrusion at L4/5 with left foraminal narrowing.", "L4/5", "L5/5",
     "L5/S1 disc protrusion with left foraminal narrowing."),                                             # C6
    ("Right kidney normal; left renal calculus.", "Right kidney", "Left kidney", "Left renal calculus."),  # C8
    ("Left renal cyst and a 6 mm right renal calculus.", "Left renal cyst", "Right renal cyst",
     "Right renal calculus 6 mm."),                                                                        # C9
    ("Definite left adrenal metastasis 15 mm.", "Definite", "Probable", "Probable left adrenal adenoma 15 mm."),  # C14
    ("Malignancy is likely.", "likely", "unlikely", "Malignancy unlikely."),                              # C17
    ("Bilateral pleural effusions, larger on the left.", "Bilateral", "Left",
     "Left pleural effusion larger than right."),                                                          # C24
    ("Bilateral L5 pars defects with grade 1 anterolisthesis.", "Bilateral", "Right", "Right L5 pars defect."),  # C25
])
def test_t11_positive_correction_never_preapplied(body, find, replace, d):
    assert PA(R2(body), rep(find, replace), "contradicted", d=d, line_text=d) == ["correction_one_click"]


def test_t11_numbered_list_marker_correction_never_preapplied():                                     # C11
    rpt = R2("Lungs otherwise clear.", imp="1. Right lower lobe nodule 6 mm.\n2. No effusion.")
    d = "Right lower lobe nodule 8 mm."
    assert PA(rpt, rep("1. Right", "8. Right"), "contradicted", d=d, line_text=d)


# 2a. the line is one whole dictated line, never a fragment or a span across lines
@pytest.mark.parametrize("line,d", [
    ("left renal mass", "No evidence of left renal mass. Liver normal."),                                # I1
    ("left adrenal nodule", "Previously seen left adrenal nodule has resolved."),                          # I2
    ("effusion. Right rib", "Small effusion. Right rib fracture."),                                       # I3
])
def test_t11_insert_line_must_be_whole_dictated_line(line, d):
    assert PAI(R2("Liver normal. Spleen normal."), line, d)


# 2b. one sentence only
def test_t11_insert_refuses_multi_sentence_line():                                                    # I14
    d = "Small effusion. No pneumothorax."
    assert PAI(R2("Liver normal."), d, d)


# 2c. block context and sub-headed FINDINGS
def test_t11_insert_refuses_line_under_dictated_level_block():                                        # I24
    d = "At L4/5 broad disc bulge.\nRight foraminal narrowing.\nL5/S1 normal."
    rpt = R2("L4/5: broad disc bulge. L5/S1: normal disc.")
    assert PAI(rpt, "Right foraminal narrowing.", d)
    rpt = R2("Broad disc bulge at L4/5. Normal disc at L5/S1.")                    # no inline labels in the report
    assert PAI(rpt, "Right foraminal narrowing.", d)
    assert PAI(rpt, "Right foraminal narrowing.", "Right foraminal narrowing.", line_context={"block_levels": ["L4/5"]})


def test_t11_insert_refuses_line_under_dictated_side_header():                                        # I25
    d = "LEFT KIDNEY:\nSimple cyst 2 cm.\nRIGHT KIDNEY:\nNormal."
    rpt = R2("The left kidney is normal in size. The right kidney is normal.")
    assert PAI(rpt, "Simple cyst 2 cm.", d)
    assert PAI(rpt, "Simple cyst 2 cm.", "Simple cyst 2 cm.", line_context={"block_side": "left"})


def test_t11_insert_line_context_stated_by_line_ok():
    rpt = R2("Liver normal. Spleen normal.")
    line = "Left simple renal cyst 2 cm."
    assert PAI(rpt, line, line, line_context={"block_side": "left", "block_levels": []}) == []


def test_t11_insert_refuses_sub_headed_findings():                                                    # I6
    d = "Small left pleural effusion."
    rpt = "FINDINGS:\nCHEST:\nLungs clear.\nABDOMEN:\nLiver normal. Spleen normal.\n\nIMPRESSION:\n1. Normal."
    assert PAI(rpt, d, d)


# 2d. duplicate / contradiction anywhere in FINDINGS
def test_t11_insert_refuses_conflict_with_findings():                                                 # I7
    d = "Small left pleural effusion."
    assert PAI(R2("Small right pleural effusion. Liver normal."), d, d)


def test_t11_insert_refuses_duplicate_in_other_paragraph():                                           # I13b
    d = "Left renal cyst."
    rpt = "FINDINGS:\nLeft renal cyst.\n\nLiver normal.\n\nIMPRESSION:\n1. Normal."
    assert PAI(rpt, d, d)


# 2e. non-finding lines
@pytest.mark.parametrize("line", [
    "History: fall, ?hip fracture.",                                                                      # I4
    "Recommend follow-up CT in 3 months.",                                                                # I5
    "Comparison: CT 12/03/2025.",                                                                         # I11
    "Discussed with Dr Smith at 14:30.",                                                                  # I12
    "Liver: 2 cm cyst.",                                                                                  # I17
    "liver: 2 cm cyst.",
    "Correlate clinically.",
    "Unchanged from the previous study.",
])
def test_t11_insert_refuses_non_finding_lines(line):
    assert PAI(R2("Spleen normal."), line, line)


# 2f. tidy only capitalises an all-lower-case first word
def test_t11_tidy_keeps_mixed_case_first_word():                                                      # I10
    rpt = R2("Liver normal.")
    assert V.insert_from_line(rpt, "eGFR 45, pT2 tumour.", "FINDINGS").replace == "eGFR 45, pT2 tumour."
    assert V.insert_from_line(rpt, "small left effusion", "FINDINGS").replace == "Small left effusion."


def test_t11_insert_legit_still_preapplied():                                                         # I18
    d = "Small left effusion"
    assert PAI(R2("Liver normal. Spleen normal."), d, d) == []
    assert PAI(R2("Liver normal. Spleen normal."), d, f"Liver normal.\n- {d}.") == []


# 3a. removals only inside FINDINGS / IMPRESSION (TECHNIQUE etc. never); a side-specific negative beside a
# dictated positive on the other side is not contradicted by it
@pytest.mark.parametrize("report,find,d", [
    ("TECHNIQUE:\nAxial CT. Without contrast.\n\nFINDINGS:\nRight pleural effusion. Heart normal.\n\nIMPRESSION:\n"
     "1. Effusion.", "Without contrast.", "Right pleural effusion."),                                      # X16b
    (R2("Large right effusion. Liver normal.", imp="1. Large right effusion.\n2. No effusion on the left."),
     "No effusion on the left.", "Large right effusion."),                                                # X17
    (R2("Large right effusion. No effusion on the left. Liver normal."), "No effusion on the left.",
     "Large right effusion."),
])
def test_t11_removal_section_and_side(report, find, d):
    assert PA(report, rem(find), "contradicted", d=d)


# 3b. dictated negatives (and normal statements about the same organ) protect, shorthand on both sides
@pytest.mark.parametrize("body,find,d,kind", [
    ("Multiple liver lesions, possibly metastases. No bony metastases.", "No bony metastases.",
     "Multiple liver lesions ?mets. No bone mets.", "contradicted"),                                       # X1
    ("Left kidney normal. No hydronephrosis.", "No hydronephrosis.", "Left kidney normal. No hydro.", "removed"),  # X3
    ("Soft tissue swelling. No fracture.", "No fracture.", "No fx.", "contradicted"),                     # X4
    ("Heart normal. No consolidation.", "No consolidation.", "Lungs clear.", "contradicted"),             # X10
    ("Small effusion. No ICH.", "No ICH.", "No acute intracranial haemorrhage.", "contradicted"),         # X15b
    ("Liver normal. No significant lymphadenopathy.", "No significant lymphadenopathy.", "No nodes.",
     "contradicted"),                                                                                      # X25
])
def test_t11_removal_dictated_negative_protected(body, find, d, kind):
    assert PA(R2(body), rem(find), kind, d=d)


# 3c. abnormal findings phrased as negatives
@pytest.mark.parametrize("body,find,d", [
    ("Right testis normal. No flow in the left testis.", "No flow in the left testis.", "Left testicular torsion."),  # X8
    ("Right kidney normal. The left kidney is not seen.", "The left kidney is not seen.", "Left nephrectomy."),  # X9
    ("Liver normal. No enhancement of the left kidney.", "No enhancement of the left kidney.", "Left renal infarct."),
    ("Liver normal. No excretion from the left kidney.", "No excretion from the left kidney.", "Left obstruction."),
])
def test_t11_removal_abnormal_negative_refused(body, find, d):
    assert PA(R2(body), rem(find), "removed", d=d)


# 3d. false-refusal fixes
def test_t11_semantic_contradiction_without_normal_statement_ok():
    rpt = R2("Free gas present. No pneumoperitoneum. Liver normal.")
    assert PA(rpt, rem("No pneumoperitoneum."), "removed", d="Free gas under the diaphragm.") == []
    assert PA(rpt, rem("No pneumoperitoneum."), "removed", d="Free gas under the diaphragm. Liver normal.")


def test_t11_small_bowel_is_not_a_size_word():                                                        # X20
    rpt = R2("Dilated loops. No small bowel obstruction. Liver normal.")
    assert PA(rpt, rem("No small bowel obstruction."), "contradicted",
              d="Dilated small bowel loops with transition point.") == []


def test_t11_negative_fix_list_item_drop_preapplied():
    rpt = R2("No effusion, pneumothorax, or consolidation. Liver normal.")
    sent = "No effusion, pneumothorax, or consolidation."
    s = rpt.index(sent) + sent.index("pneumothorax")
    e = V._negative_fix(rpt, s, s + len("pneumothorax"), "No pneumothorax", quick_section_names(rpt))
    assert e is not None and e.mode == "replace"
    assert PA(rpt, e, "contradicted", d="Small left pneumothorax.") == []
    assert PA(rpt, e, "contradicted", d="Small left pneumothorax.", code_built=False)
    # two items lost, or words added: never
    assert PA(rpt, rep(sent, "No effusion."), "contradicted", d="Small pneumothorax. Consolidation.")
    assert PA(rpt, rep(sent, "No effusion or collapse."), "contradicted", d="Small pneumothorax.")


# ── controller addition: brief-option sentence grounds its own additions insert (one-click only) ─────────────
def test_additions_option_sentence_grounds_its_insert_one_click_only():
    from rapid_reports_ai.review_engine.items import ReviewItem, Span
    rpt = R2("Liver normal. Left renal cyst.")
    sent = "Ultrasound follow-up is suggested."
    e = Edit(mode="insert", after="Left renal cyst.", replace=sent, section="FINDINGS")
    it = ReviewItem(key="k", report_id="r", run_id="u", lane="additions", kind="option", cls="action", edit=e,
                    section="FINDINGS", anchor=Span(start=0, end=1, text="x"), evidence={"sentence": sent})
    src = V._extra_source(it)
    assert sent in src.split("\n")
    assert G(rpt, e, "option", "left renal cyst", extra_source=src, additions=True) == []
    assert "additions_new_content" in G(rpt, e, "option", "left renal cyst", additions=True)
    assert PA(rpt, e, "option", d="left renal cyst", line_text=sent)                    # never pre-applied
