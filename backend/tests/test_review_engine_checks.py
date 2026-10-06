# tests/test_review_engine_checks.py
"""Code checks (spec §6.2 laterality, §6.3 unsupported / misattributed / inconsistent). Certainty is Jev C1n's."""
import pytest

from rapid_reports_ai.review_engine.alignment import align
from rapid_reports_ai.review_engine.checks import hedge_tag, modality, run_checks


def run(report, dictation, scan="CT abdomen", history="", title=None):
    al = align(report, dictation, history, ["FINDINGS", "IMPRESSION"])
    return run_checks(report, dictation, history, scan, al, study_title=title)


def kinds(cs):
    return sorted((c.kind, c.detector) for c in cs)


def test_unsupported_number():
    cs = [c for c in run("FINDINGS:\nThe CBD measures 6 mm.\nIMPRESSION:\nNormal.", "- CBD not dilated")
          if c.kind == "unsupported"]
    assert cs and cs[0].detector == "code.numbers" and cs[0].evidence["numbers"] == ["6mm"]
    assert cs[0].lane == "accuracy" and cs[0].anchor.text == "The CBD measures 6 mm."


def test_number_from_history_or_other_unit_is_supported():
    assert not run("FINDINGS:\nThe CBD measures 6 mm.\n", "- CBD", history="Known 6 mm CBD")
    assert not [c for c in run("FINDINGS:\nA 1.4 cm renal cyst.\n", "- 14 mm renal cyst") if c.kind == "unsupported"]


def test_unsupported_prior_and_date():
    cs = run("FINDINGS:\nThe nodule is stable compared with the prior CT of 03/02/2025.\n", "- Lung nodule")
    assert ("unsupported", "code.prior") in kinds(cs) and ("unsupported", "code.dates") in kinds(cs)


def test_prior_is_fine_when_dictated():
    cs = run("FINDINGS:\nThe nodule is stable compared with the prior CT.\n", "- Lung nodule stable since prior CT")
    assert ("unsupported", "code.prior") not in kinds(cs)


@pytest.mark.parametrize("clause,tag", [
    ("No effusion.", "negated"), ("Appendicitis cannot be excluded.", "possible"), ("Possible small effusion.", "possible"),
    ("Likely a cyst.", "probable"), ("Findings in keeping with cholecystitis.", "probable"), ("Acute appendicitis.", "definite"),
    # lexicon coverage (L-53: this is the dedicated dropped-hedge detector)
    ("May represent a cyst.", "possible"), ("This might be a cyst.", "possible"), ("Possibly a cyst.", "possible"),
    ("Could be a cyst.", "possible"), ("?appendicitis", "possible"), ("Query appendicitis.", "possible"),
    ("Probable cyst.", "probable"), ("Probably a cyst.", "probable"), ("Suggestive of a cyst.", "probable"),
    ("Suspicious for malignancy.", "probable"), ("Favoured to be a cyst.", "probable"),
    ("Consistent with a cyst.", "probable"),          # UK convention: consistent with / in keeping with = probable
    ("The lesion is a cyst.", "definite"), ("The nodes are enlarged.", "definite"),
    ("Appearances diagnostic of a cyst.", "definite"),
    ("Scan of 12 May 2024 shows a cyst.", "definite"),  # a month name is not a hedge
    # lexicon fixes (probe 2026-10-04)
    ("Cannot exclude a small effusion.", "possible"), ("Can't exclude a small effusion.", "possible"),
    ("Fracture not ruled out.", "possible"), ("Fracture cannot be ruled out.", "possible"),
    ("Fracture may not be ruled out.", "possible"),
    ("Features suggest cholecystitis.", "probable"), ("Appearances suggest a cyst.", "probable"),
    ("Nothing to suggest malignancy.", "negated"),
    ("Indeterminate 8 mm nodule.", "definite"), ("Equivocal enhancement.", "definite"),
    # real-world hedges (hybrid certainty rule validation, 2026-10-04)
    ("Thickening, worrisome for malignancy.", "probable"), ("Thickening, concerning for malignancy.", "probable"),
    ("Suspicious primary gallbladder malignancy.", "probable"), ("Suspected appendicitis.", "probable"),
    ("A lucency, which appears to represent a fracture.", "probable"),
    ("Thickening, suggesting chronic inflammation.", "probable"),
    ("A lucency, raising the possibility of a fracture.", "possible"),
    ("Appearances raise the possibility of a fracture.", "possible"),
    ("The gallbladder appears thick-walled.", "definite"),      # "appears" alone describes, it does not hedge
    ("No suspicious lesion.", "negated"),
])
def test_hedge_tag(clause, tag):
    assert hedge_tag(clause) == tag


def test_no_code_overstated_detector():
    # certainty moved to Jev C1n (Accuracy lane, Task 6); hedge_tag stays as an evidence helper only
    for d, r in [("- Possible small left effusion", "Small left pleural effusion."),
                 ("- may represent an undisplaced fracture", "In keeping with an undisplaced fracture.")]:
        assert not [c for c in run(f"FINDINGS:\n{r}\n", d) if c.kind == "overstated"]


def test_misattributed():
    cs = run("FINDINGS:\nThe liver contains a lesion. The spleen measures 12 mm.\n", "- Liver lesion 12 mm\n- Spleen normal")
    mis = [c for c in cs if c.kind == "misattributed"]
    assert mis and mis[0].anchor.text == "The spleen measures 12 mm." and mis[0].evidence["number"] == "12mm"


def test_modality_vocabulary():
    assert modality("CT abdomen pelvis") == "CT" and modality("MRI knee") == "MR" and modality("US thyroid") == "US"
    cs = run("FINDINGS:\nThe lesion shows high T2-weighted signal.\n", "- lesion")
    assert ("inconsistent", "code.modality") in kinds(cs)
    assert ("inconsistent", "code.modality") not in kinds(run("FINDINGS:\nHigh signal lesion.\n", "- high signal lesion"))


def test_size_word():
    assert ("inconsistent", "code.size_word") in kinds(run("FINDINGS:\nA small 45 mm mass.\n", "- 45 mm mass"))
    assert ("inconsistent", "code.size_word") in kinds(run("FINDINGS:\nA large 4 mm nodule.\n", "- 4 mm nodule"))
    assert ("inconsistent", "code.size_word") not in kinds(run("FINDINGS:\nA small 4 mm nodule.\n", "- 4 mm nodule"))


def test_laterality_unbounded_and_bounded():
    rep, d = "FINDINGS:\nA 14 mm renal cyst.\n", "- Left renal cyst 14 mm"
    lat = [c for c in run(rep, d) if c.kind == "laterality"]
    assert lat and lat[0].lane == "coverage" and lat[0].line_id == "d0" and lat[0].evidence == {"side": "left"}
    assert not [c for c in run(rep, d, title="CT Kidney Left") if c.kind == "laterality"]
    rep2 = "FINDINGS:\nLeft side:\nThe kidney is normal. A 14 mm renal cyst.\n"
    assert not [c for c in run(rep2, d) if c.kind == "laterality"]


def test_level_conflict_is_one_differs_item():
    rep = "FINDINGS:\nDisc protrusion at L5/S1.\n"
    al = align(rep, "- L4/5 disc protrusion", "", ["FINDINGS"])
    assert [p.how for p in al.pairs] == ["level_conflict"]
    cs = [c for c in run_checks(rep, "- L4/5 disc protrusion", "", "MRI lumbar spine", al)
          if c.detector == "code.level_conflict"]
    assert len(cs) == 1
    c = cs[0]
    assert c.lane == "coverage" and c.kind == "differs" and c.line_id == "d0"
    assert c.evidence == {"dictated_level": "L4/5", "report_levels": ["L5/S1"]}
    assert c.anchor.text == "Disc protrusion at L5/S1." and c.anchor.start == rep.index("Disc")


def test_no_level_conflict_when_line_pairs_at_its_own_level():
    rep = "FINDINGS:\nDisc bulge at L4/5. Disc bulge at L3/4.\n"
    assert not [c for c in run(rep, "- Disc bulge L3/4", scan="MRI lumbar spine") if c.detector == "code.level_conflict"]


# ── regressions from the 2026-10-04 probes (synthetic text) ─────────────────────

def has(cs, kind, detector):
    return (kind, detector) in kinds(cs)


@pytest.mark.parametrize("report,dictation,history,flag", [
    # src_prior is per-reference: an unrelated "previous" in the source does not license a study comparison
    ("The nodule is stable compared with the prior CT.", "- lung nodule", "Previous MI. Cough.", True),
    ("Liver normal. The nodule is unchanged compared with the prior CT.",
     "- liver normal, previous cholecystectomy\n- lung nodule", "", True),
    ("No change from the previous scan.", "- liver lesion", "", True),
    ("Interval development of ascites.", "- ascites", "", True),
    # "since the" is not a study reference; surgical / medical history is not a study reference
    ("The patient has had pain since the fall.", "- fall", "", False),
    ("Status post previous cholecystectomy.", "- post cholecystectomy", "", False),
    ("Previous MI noted.", "- heart normal", "", False),
    # source prior-study phrases
    ("No change compared with the prior CT.", "- no change from old CT", "", False),
    ("Compared with the prior CT.", "- comparison made with 2023 CT", "", False),
    ("Unchanged since the previous CT.", "- unchanged since last scan", "", False),
    ("The nodule is stable compared with CT in May.", "- lung nodule stable since CT in May", "", False),
    ("Stable compared with the prior study.", "- nodule", "Comparison: previous CT 01/02/2024", False),
])
def test_prior_reference(report, dictation, history, flag):
    assert has(run(f"FINDINGS:\n{report}\n", dictation, history=history), "unsupported", "code.prior") is flag


def test_misattributed_skips_unpaired_clause():
    cs = run("FINDINGS:\nThe common bile duct measures 6 mm.\n", "- CBD 6 mm")
    assert not [c for c in cs if c.kind == "misattributed"]


def test_misattributed_owner_without_anatomy_word():
    cs = run("FINDINGS:\nThe gallbladder contains a stone. The pancreatic duct measures 9 mm.\n",
             "- gallstone 9 mm\n- pancreatic duct normal")
    mis = [c for c in cs if c.kind == "misattributed"]
    assert mis and mis[0].anchor.text == "The pancreatic duct measures 9 mm." and mis[0].line_id == "d0"


@pytest.mark.parametrize("report,dictation,flag", [
    ("A 5 mm polyp in the large bowel.", "- 5 mm large bowel polyp", False),
    ("Small bowel dilated to 40 mm.", "- SBO, small bowel 40 mm", False),
    ("Dilated small bowel loops measuring up to 35 mm.", "- dilated small bowel 35 mm", False),
    ("Large intestine dilated to 70 mm.", "- large intestine 70 mm", False),
    ("Small amount of free fluid adjacent to the 35 mm collection.", "- small free fluid\n- 35 mm collection", False),
    ("Small bilateral effusions and a 45 mm liver lesion.", "- small bilateral effusions\n- 45 mm liver lesion", False),
    ("The left kidney is small, measuring 80 mm.", "- small left kidney 80 mm", False),
    ("A small 30 mm mass.", "- 30 mm mass", True),
    ("Subcentimetre nodes, the largest 10 mm.", "- nodes 10 mm", True),
    ("Massive 5 mm haemorrhage.", "- 5 mm haemorrhage", True),
    ("A large 9 cm aortic aneurysm.", "- 9 cm AAA", False),
])
def test_size_word_regressions(report, dictation, flag):
    assert has(run(f"FINDINGS:\n{report}\n", dictation), "inconsistent", "code.size_word") is flag


@pytest.mark.parametrize("scan,s", [("CTPA", "CT"), ("CTKUB", "CT"), ("CT KUB", "CT"), ("CTA neck", "CT"),
                                    ("CTC", "CT"), ("PET-CT", "CT"), ("MRCP", "MR"), ("MRA", "MR"), ("MRV head", "MR"),
                                    ("USS abdomen", "US"), ("CXR", "XR"), ("XR wrist", "XR"), ("Chest X-ray", "XR")])
def test_modality_abbreviations(scan, s):
    assert modality(scan) == s


@pytest.mark.parametrize("report,dictation,scan,history,flag", [
    ("No Doppler signal within the lesion.", "- avascular lesion", "US testes", "", False),
    ("Normal colour Doppler signal in both testes.", "- normal flow both testes", "US scrotum", "", False),
    ("Normal colour signal in both testes.", "- normal flow", "US scrotum", "", False),
    ("The hypoechoic lesion on the prior ultrasound is seen.", "- lesion seen on prior US", "MRI liver",
     "US showed hypoechoic lesion", False),
    ("A hyperintense liver lesion.", "- liver lesion", "CT abdomen", "", True),
    ("A hypointense liver lesion.", "- liver lesion", "CT abdomen", "", True),
    ("No signal change.", "- normal", "CTPA", "", True),
])
def test_modality_regressions(report, dictation, scan, history, flag):
    cs = run(f"FINDINGS:\n{report}\n", dictation, scan=scan, history=history)
    assert has(cs, "inconsistent", "code.modality") is flag


@pytest.mark.parametrize("report,dictation,history,flag", [
    ("The CBD measures 6 mm.", "- CBD 6 millimetres", "", False),
    ("The CBD measures 6 mm.", "- CBD six mm", "", False),
    ("The CBD measures 6 mm.", "- CBD 6", "", False),
    ("Prostate volume 45 ml.", "- prostate 45 cc", "", False),
    ("Stenosis of 70%.", "- ICA stenosis 70", "", False),
    ("Grade 2 splenic injury.", "- grade II splenic injury", "", False),
    ("Grade II splenic injury.", "- grade 2 splenic injury", "", False),
    ("Grade III splenic injury.", "- grade 2 splenic injury", "", True),
    ("A 1.5 cm cyst.", "- 14 mm cyst", "", True),
    ("The CBD measures 6 mm.", "- CBD 6 cm", "", True),
])
def test_number_regressions(report, dictation, history, flag):
    assert has(run(f"FINDINGS:\n{report}\n", dictation, history=history), "unsupported", "code.numbers") is flag


@pytest.mark.parametrize("report,dictation,flag", [
    ("Reported by Dr Smith, GMC 1234567.", "- liver normal", False),
    ("Dr Jones GMC 7654321", "- liver normal", False),
    ("NMC 12345678.", "- liver normal", False),
    ("Contact ext 4567 for queries.", "- liver normal", False),
    ("Bosniak IIF cyst.", "- renal cyst", False),
    ("Grade II injury.", "- injury", False),
    ("Type IV lesion.", "- lesion", False),
    ("Clavien III complication.", "- complication", False),
    ("Bosniak III cyst.", "- bosniak 2 cyst", True),
    ("No lymphadenopathy (>10 mm).", "- no nodes", False),
    ("No nodes greater than 10 mm short axis.", "- no nodes", False),
    ("Within normal limits (<7 mm).", "- normal", False),
    ("No nodes up to 12 mm.", "- no nodes", False),
    ("Node measures 12 mm.", "- node", True),
    ("Node greater than 12 mm.", "- node", True),
    ("Lesion of 45 Hounsfield units.", "- lesion 45 HU", False),
    ("Lesion of 45 H.U.", "- lesion 45 HU", False),
    ("Lesion of 45 HU.", "- lesion 45 Hounsfield units", False),
    ("Lesion of 50 HU.", "- lesion 45 HU", True),
])
def test_false_positive_sources(report, dictation, flag):
    assert has(run(f"FINDINGS:\n{report}\n", dictation), "unsupported", "code.numbers") is flag


def test_list_dash_marker_is_not_a_number():
    assert not run("IMPRESSION:\n1 - Cholecystitis.\n", "- cholecystitis")


@pytest.mark.parametrize("report,dictation,history,flag", [
    ("Compared with CT dated 03/02/2025.", "- compared with CT 3/2/25", "", False),
    ("Compared with the CT of May 2024.", "- compared with CT 05/2024", "", False),
    ("Compared with the CT of May 2024.", "- compared with CT 12/05/2024", "", False),
    ("Compared with the CT of 2 March 2025.", "- compared with CT 02/03/2025", "", False),
    ("Compared with CT of 04/05/2024.", "- compared with prior", "CT 01/01/2023", True),
    ("Compared with the CT of 12 May 2024.", "- compared with prior CT", "", True),
])
def test_date_regressions(report, dictation, history, flag):
    assert has(run(f"FINDINGS:\n{report}\n", dictation, history=history), "unsupported", "code.dates") is flag


def test_level_conflict_one_item_per_pair():
    rep = "FINDINGS:\nDisc protrusion at L5/S1. Disc protrusion at L3/4.\n"
    cs = [c for c in run(rep, "- L4/5 disc protrusion", scan="MRI lumbar spine") if c.detector == "code.level_conflict"]
    assert sorted(tuple(c.evidence["report_levels"]) for c in cs) == [("L3/4",), ("L5/S1",)]


# ── L-56: alignment is a confidence-gated supporting tool; these checks fire only on confident pairs ──────────

def _weaken(al, score=0.3):
    """The same alignment with every pair demoted to a weak (non-exact, non-number) score."""
    return al.model_copy(update={"pairs": [p.model_copy(update={"score": score}) for p in al.pairs]})


def _gated(report, dictation, scan="CT abdomen", weak=False):
    al = align(report, dictation, "", ["FINDINGS", "IMPRESSION"])
    return run_checks(report, dictation, "", scan, _weaken(al) if weak else al)


@pytest.mark.parametrize("report,dictation,scan,detector", [
    ("FINDINGS:\nThe liver contains a lesion. The spleen measures 12 mm.\n", "- Liver lesion 12 mm\n- Spleen normal",
     "CT abdomen", "code.measurement"),
    ("FINDINGS:\nA 14 mm renal cyst.\n", "- Left renal cyst 14 mm", "CT abdomen", "code.laterality"),
    ("FINDINGS:\nDisc protrusion at L5/S1.\n", "- L4/5 disc protrusion", "MRI lumbar spine", "code.level_conflict"),
])
def test_alignment_consumers_fire_only_on_confident_pairs(report, dictation, scan, detector):
    assert [c for c in _gated(report, dictation, scan) if c.detector == detector]
    assert not [c for c in _gated(report, dictation, scan, weak=True) if c.detector == detector]


def test_misattributed_weak_owner_pair_still_exempts():
    # the owner line weakly paired to the clause is still "paired": a weak pair never creates a flag
    rep, d = "FINDINGS:\nThe spleen measures 12 mm.\n", "- Spleen 12 mm"
    al = align(rep, d, "", ["FINDINGS"])
    assert not [c for c in run_checks(rep, d, "", "CT abdomen", _weaken(al)) if c.kind == "misattributed"]


def test_pair_confident_matches_lanes():
    from rapid_reports_ai.review_engine import checks, lanes
    assert checks.PAIR_CONFIDENT == lanes.PAIR_CONFIDENT
