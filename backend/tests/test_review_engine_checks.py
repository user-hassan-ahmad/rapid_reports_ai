# tests/test_review_engine_checks.py
"""Code checks (spec §6.2 laterality, §6.3 unsupported / overstated / misattributed / inconsistent)."""
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
])
def test_hedge_tag(clause, tag):
    assert hedge_tag(clause) == tag


def test_overstated():
    cs = [c for c in run("FINDINGS:\nSmall left pleural effusion.\n", "- Possible small left effusion") if c.kind == "overstated"]
    assert cs and cs[0].evidence == {"dictated": "possible", "report": "definite"} and cs[0].detector == "code.hedge"


@pytest.mark.parametrize("dictated,report,overstated", [
    ("- may represent an undisplaced fracture", "In keeping with an undisplaced fracture.", True),
    ("- suggestive of contained rupture", "Contained rupture is present.", True),
    ("- likely metastatic", "Likely representing metastatic deposits.", False),
])
def test_overstated_hedge_steps(dictated, report, overstated):
    cs = [c for c in run(f"FINDINGS:\n{report}\n", dictated) if c.kind == "overstated"]
    assert bool(cs) is overstated
    if overstated:
        assert cs[0].detector == "code.hedge" and cs[0].lane == "accuracy"


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
