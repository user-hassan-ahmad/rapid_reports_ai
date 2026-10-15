"""The line registry (spec 2026-10-15-stable-line-ids-design): stable uids per line-bound sheet unit, re-bound by code.
Pure code: no model, no database. Pass condition for the adversarial pairs: zero wrong matches."""
import hashlib

import pytest

from rapid_reports_ai import template_line_match as tlm
from tests.template_sheet_fixtures import LEDGER_SHEET


# ── text identity: exact after representation-only normalising (decision 7) ─────────────────────────────────────

ADVERSARIAL = [
    ("No pleural effusion.", "No pericardial effusion."),
    ("Left kidney is normal.", "Right kidney is normal."),
    ("Mild narrowing.", "Moderate narrowing."),
    ("No evidence of fracture.", "Evidence of fracture."),
    ("Lesion with enhancement.", "Lesion without enhancement."),
    ("Calcium score > 0.", "Calcium score < 0."),
    ("Calcium score > 0.", "Calcium score ≥ 100."),
    ("Measures 1.5 mm.", "Measures 15 mm."),
    ("Dose 10 mGycm.", "Dose 10 mGy."),
    ("Left kidney, right adrenal.", "Right kidney, left adrenal."),
    ("Non-enhancing lesion.", "Enhancing lesion."),
    ("Small effusion.", "Large effusion."),
    ("Measures .5 mm.", "Measures 5 mm."),
    ("No fracture. Dislocation.", "No fracture, dislocation."),
    ("No mass; effusion.", "No mass effusion."),
    ("Stenosis <25%.", "Stenosis 25%."),
    ("Measures 5 x 3 mm.", "Measures 53 mm."),
    ("Effusion is seen.", "Effusion is not seen."),
    ("Likely pneumonia.", "Pneumonia."),
    ("Malignancy cannot be excluded.", "Malignancy excluded."),
    ("Possible collection.", "Probable collection."),
    ("Well-defined margin.", "Defined margin."),
    ("No collapse, there is consolidation.", "No collapse, consolidation."),
    ("No mass, fluid is seen.", "No mass, fluid."),
    ("Length 5'.", "Length 5."),
]


@pytest.mark.parametrize("a,b", ADVERSARIAL)
def test_adversarial_texts_are_never_the_same_line(a, b):
    """Near misses: once guarded by the cosmetic layer's gates, now non-matching by construction. They stay as a
    tripwire against fuzzy matching being re-added."""
    assert not tlm.same_text(a, b) and not tlm.same_text(b, a)


@pytest.mark.parametrize("a,b", [
    ("There is no pleural effusion.", "No pleural effusion"),         # filler words
    ("Oedema is seen.", "Edema"),                                      # spelling
    ("Oedema.", "Edema."),
    ("No focal liver lesion.", "no focal liver lesion."),              # case
    ("No focal liver lesion.", "No focal liver lesion"),               # a final full stop
    ("No mass. There is fluid.", "No mass. Fluid."),
    ("Possible mass; there is fluid.", "Possible mass; fluid."),
    ("Well-defined margin.", "Well defined margin."),                  # a hyphen is punctuation
])
def test_rewordings_case_punctuation_and_spelling_are_other_lines(a, b):
    assert not tlm.same_text(a, b) and not tlm.same_text(b, a)


@pytest.mark.parametrize("a,b", [
    ("No fracture \u2013 left side.", "No fracture - left side."),
    ("No fracture \u2014 left side.", "No fracture - left side."),
    ("Change of \u22121 mm.", "Change of -1 mm."),
    ("The patient\u2019s \u201cnormal\u201d study.", "The patient's \"normal\" study."),
    ("Measures 5 \u00d7 3 mm.", "Measures 5 x 3 mm."),
    ("No\u00a0effusion.", "No effusion."),
    ("No\u202feffusion.", "No effusion."),
    ("  No   effusion. ", "No effusion."),
])
def test_typography_only_differences_are_the_same_line(a, b):
    assert tlm.same_text(a, b) and tlm.rep_key(a) == tlm.rep_key(b)


@pytest.mark.parametrize("a,b", [
    ("Measures 5 X 3 mm.", "Measures 5 x 3 mm."),     # only the multiplication sign merges into "x", never case
    ("Length 5\u2032.", "Length 5'."),                # prime is not a lookalike
    ("Grade \u2264 2.", "Grade < 2."),                # comparators never merge
    ("Grade \u2265 2.", "Grade > 2."),
    ("Change of -1 mm.", "Change of 1 mm."),
    ("No\u200beffusion.", "No effusion."),            # a zero-width space is not a space
])
def test_lookalikes_never_collide_with_a_different_character(a, b):
    assert not tlm.same_text(a, b)


def test_lookalike_map_merges_only_into_ascii_forms():
    assert set(tlm.LOOKALIKES.values()) <= {"-", '"', "'", "x", " "}
    assert all(ord(k) > 127 for k in tlm.LOOKALIKES) and not set(tlm.LOOKALIKES) & set(tlm.LOOKALIKES.values())

# ── the registry module ────────────────────────────────────────────────────────────────────────────────────────

from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_sheet_grammar as tsg


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def test_units_lists_every_line_bound_unit_parents_first():
    us = tlr.units(_st(LEDGER_SHEET))
    assert [u.ref for u in us] == ["S:TECHNIQUE", "S:FINDINGS", "S:IMPRESSION", "p0", "p1", "p2", "m0", "n0", "f0", "f1"]
    neg = next(u for u in us if u.ref == "n0")
    assert (neg.kind, neg.raw, neg.text, neg.section, neg.paragraph) == (
        "negative", 'NEGATIVE "No focal liver lesion."', "No focal liver lesion.", "S:FINDINGS", "p1")
    assert tlr.text_hash("x") == "sha256:" + hashlib.sha256(b"x").hexdigest()


def test_load_drops_malformed_units_and_never_raises():
    assert tlr.load(None) == tlr.empty() and tlr.load("x") == tlr.empty()
    raw = {"v": 1, "units": {"n_aaaaaa": {"kind": "normal", "identity": {}}, "bad": {"kind": "normal", "identity": {}},
                             "g_bbbbbb": {"kind": "nope", "identity": {}}, "f_cccccc": "x"}, "salt": "0a1b2c3d"}
    assert list(tlr.load(raw)["units"]) == ["n_aaaaaa"] and tlr.load(raw)["salt"] == "0a1b2c3d"
    assert "salt" not in tlr.load({**raw, "salt": "not hex!"})

# ── rebind ─────────────────────────────────────────────────────────────────────────────────────────────────────

HEAD = """## Report Structure
SECTION TECHNIQUE | header: "Technique:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression
"""
TAIL = "\n## Paragraph: Impression (IMPRESSION)\nOpening: \"Normal study.\"\n"


def _sheet(*paragraphs: str) -> str:
    return HEAD + "".join(f"\n{p.strip()}\n" for p in paragraphs) + TAIL


def _bind(sheet, registry=None, carried=None):
    return tlr.rebind(registry, _st(sheet), carried, now="T")


def _live(registry, text):
    (uid,) = [u for u, e in registry["units"].items() if e["status"] == "live" and e["text"] == text]
    return uid


def _counts(report):
    return {k: len(v) for k, v in report.items() if v}


def test_first_save_mints_one_uid_per_line_bound_unit_and_a_second_is_all_exact():
    reg, rep = _bind(LEDGER_SHEET)
    st = _st(LEDGER_SHEET)
    n = len(st.sections) + len(st.paragraphs) + len(st.normals) + len(st.negatives) + len(st.fixed_blocks) + len(st.rules)
    assert _counts(rep) == {"new": n} and len(reg["units"]) == n
    assert {u[:2] for u in reg["units"]} == {"s_", "p_", "n_", "g_", "f_"}
    assert all(e["status"] == "live" and e["minted"] == "T" for e in reg["units"].values())
    again, rep2 = _bind(LEDGER_SHEET, reg)
    assert _counts(rep2) == {"exact": n} and again == reg


def test_rebind_is_deterministic_and_never_mutates_its_input():
    reg, _ = _bind(LEDGER_SHEET)
    snapshot = repr(reg)
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', 'NEGATIVE "No focal hepatic lesion."')
    assert _bind(edited, reg) == _bind(edited, reg)
    assert repr(reg) == snapshot


def test_normal_text_lives_in_text_hash_not_identity():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "The liver is normal in size.")
    edited = LEDGER_SHEET.replace('"The liver is normal in size."\nNEGATIVE', '"The liver is unremarkable."\nNEGATIVE')
    reg2, rep = _bind(edited, reg)
    assert uid in rep["exact"] and reg2["units"][uid]["text"] == "The liver is unremarkable."
    assert reg2["units"][uid]["text_hash"] != reg["units"][uid]["text_hash"]


def test_reordering_sections_and_paragraphs_keeps_every_uid():
    a = _sheet('## Paragraph: Liver (FINDINGS)\nCOVERS ["liver"]\nNORMAL [liver] "The liver is normal."',
               '## Paragraph: Spleen (FINDINGS)\nCOVERS ["spleen"]\nNORMAL [spleen] "The spleen is normal."')
    b = _sheet('## Paragraph: Spleen (FINDINGS)\nCOVERS ["spleen"]\nNORMAL [spleen] "The spleen is normal."',
               '## Paragraph: Liver (FINDINGS)\nCOVERS ["liver"]\nNORMAL [liver] "The liver is normal."')
    b = b.replace('SECTION TECHNIQUE | header: "Technique:" | role: technique\n', "") \
         .replace('SECTION IMPRESSION | header: "Impression:" | role: impression\n',
                  'SECTION IMPRESSION | header: "Impression:" | role: impression\n'
                  'SECTION TECHNIQUE | header: "Technique:" | role: technique\n')
    reg, _ = _bind(a)
    reg2, rep = _bind(b, reg)
    assert set(_counts(rep)) == {"exact"} and reg2 == reg


def test_inserting_a_normal_mints_one_uid_and_changes_no_other():
    reg, _ = _bind(LEDGER_SHEET)
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                  'NORMAL [gallbladder] "The gallbladder is normal."\nNEGATIVE "No focal liver lesion."')
    reg2, rep = _bind(edited, reg)
    assert len(rep["new"]) == 1 and rep["new"][0].startswith("n_") and not rep["gone"]
    assert {u: e for u, e in reg2["units"].items() if u not in rep["new"]} == reg["units"]


def test_a_rewording_is_a_new_unit_and_a_typography_change_keeps_the_uid():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    reg2, rep = _bind(reworded, reg)
    assert rep["gone"] == [uid] and len(rep["new"]) == 1 and reg2["units"][uid]["status"] == "gone"
    for variant in ('"No focal liver lesion"', '"no focal liver lesion."'):        # a full stop, case: other lines
        _, repv = _bind(LEDGER_SHEET.replace('"No focal liver lesion."', variant), reg)
        assert repv["gone"] == [uid]
    typo = LEDGER_SHEET.replace('"No focal liver lesion."', '"No focal\u00a0liver  lesion."')
    reg4, rep4 = _bind(typo, reg)
    assert uid in rep4["exact"] and not rep4["gone"] and reg4["units"][uid]["text"] == "No focal\u00a0liver  lesion."
    changed = LEDGER_SHEET.replace('"No focal liver lesion."', '"No focal hepatic lesion."')
    reg3, rep3 = _bind(changed, reg)
    assert rep3["gone"] == [uid] and len(rep3["new"]) == 1 and reg3["units"][uid]["status"] == "gone"


@pytest.mark.parametrize("a,b", ADVERSARIAL)
def test_adversarial_negatives_never_keep_a_uid(a, b):
    para = '## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nNEGATIVE "{}"'
    reg, _ = _bind(_sheet(para.format(a)))
    uid = _live(reg, a)
    _, rep = _bind(_sheet(para.format(b)), reg)
    assert rep["gone"] == [uid] and uid not in rep["exact"]


def test_the_same_normal_text_under_another_structure_is_another_unit():
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["alpha" | "beta"]\nNORMAL [alpha] "Normal appearance."')
    b = a.replace("NORMAL [alpha]", "NORMAL [beta]")
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert len(rep["gone"]) == 1 and len(rep["new"]) == 1


def test_a_conditional_and_an_unconditional_negative_with_the_same_text_differ():
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nNEGATIVE "No free fluid."')
    b = a.replace('NEGATIVE "No free fluid."', 'NEGATIVE "No free fluid." WHEN [findings: a body mass is reported]')
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert len(rep["gone"]) == 1 and len(rep["new"]) == 1


def test_two_suppress_rules_with_one_condition_and_different_targets_differ():
    cond = "RULE WHEN [context: the dictation states contrast was given] SUPPRESS"
    a = _sheet('## Paragraph: Body (FINDINGS)\nCOVERS ["body"]\nFIXED "Line one."\nFIXED "Line two."\n'
               f'{cond} "Line one."')
    b = a.replace(f'{cond} "Line one."', f'{cond} "Line two."')
    reg, _ = _bind(a)
    _, rep = _bind(b, reg)
    assert [u[:2] for u in rep["gone"]] == ["r_"] and [u[:2] for u in rep["new"]] == ["r_"]


def test_identical_fixed_lines_in_two_paragraphs_are_two_units():
    a = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nFIXED "Same line."',
               '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nNORMAL [lower] "Lower is normal."')
    b = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nNORMAL [upper] "Upper is normal."',
               '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nNORMAL [lower] "Lower is normal."\nFIXED "Same line."')
    reg, _ = _bind(a)
    fixed = _live(reg, "Same line.")
    reg2, rep = _bind(b, reg)
    assert fixed in rep["gone"] and _live(reg2, "Same line.") != fixed


def test_identical_fixed_lines_in_two_paragraphs_each_keep_their_own_uid():
    sheet = _sheet('## Paragraph: Upper (FINDINGS)\nCOVERS ["upper"]\nFIXED "Same line."',
                   '## Paragraph: Lower (FINDINGS)\nCOVERS ["lower"]\nFIXED "Same line."')
    reg, rep = _bind(sheet)
    uids = [u for u, e in reg["units"].items() if e["text"] == "Same line."]
    assert len(set(uids)) == 2 and not rep["ambiguous"]
    reg2, rep2 = _bind(sheet, reg)
    assert set(uids) <= set(rep2["exact"]) and reg2 == reg


def test_each_registry_has_its_own_salt_and_keeps_it():
    a, _ = _bind(LEDGER_SHEET)
    b, _ = _bind(LEDGER_SHEET)
    assert a["salt"] != b["salt"] and set(a["units"]).isdisjoint(b["units"])
    assert _bind(LEDGER_SHEET, a)[0]["salt"] == a["salt"]


def test_a_paragraph_rename_keeps_uids_only_with_the_same_covers():
    a = _sheet('## Paragraph: Liver (FINDINGS)\nCOVERS ["liver" | "gallbladder"]\nNORMAL [liver] "The liver is normal."')
    reg, _ = _bind(a)
    para, normal = _live(reg, "Liver"), _live(reg, "The liver is normal.")
    renamed = a.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)")
    _, rep = _bind(renamed, reg)
    assert para in rep["exact"] and normal in rep["exact"]   # a COVERS rename reports as exact
    other_covers = renamed.replace('COVERS ["liver" | "gallbladder"]', 'COVERS ["liver"]')
    _, rep3 = _bind(other_covers, reg)
    assert para in rep3["gone"]
    no_covers = _sheet('## Paragraph: Protocol (TECHNIQUE)\nFIXED "Axial CT."')
    reg5, _ = _bind(no_covers)
    _, rep5 = _bind(no_covers.replace("Paragraph: Protocol", "Paragraph: Method"), reg5)
    assert _live(reg5, "Protocol") in rep5["gone"]                         # no COVERS: a rename is a new paragraph
    sided = _sheet('## Paragraph: Left kidney (FINDINGS)\nCOVERS ["left kidney"]\nNORMAL [left kidney] "Normal."')
    reg4, _ = _bind(sided)
    _, rep4 = _bind(sided.replace("Left kidney", "Right kidney").replace("left kidney", "right kidney"), reg4)
    assert _live(reg4, "Left kidney") in rep4["gone"]                     # the side lives in COVERS
    _, rep6 = _bind(a.replace("Paragraph: Liver", "Paragraph: liver"), reg)
    assert para in rep6["exact"]                                          # case only: the COVERS rule keeps it


def test_across_a_paragraph_rename_a_normal_keeps_its_uid_only_with_the_same_text():
    a = _sheet('## Paragraph: Arterial phase (FINDINGS)\nCOVERS ["liver" | "spleen"]\n'
               'NORMAL [liver] "The liver enhances normally."\nNORMAL [spleen] "The spleen is normal."')
    reg, _ = _bind(a)
    changed, same = _live(reg, "The liver enhances normally."), _live(reg, "The spleen is normal.")
    renamed = a.replace("Arterial phase", "Portal venous phase")
    _, rep = _bind(renamed.replace("The liver enhances normally.", "The liver enhances homogeneously."), reg)
    assert _live(reg, "Arterial phase") in rep["exact"]                    # the paragraph kept its uid (COVERS)
    assert changed in rep["gone"] and same in rep["exact"]                 # a reworded normal is a new unit
    _, rep2 = _bind(renamed.replace('"The liver enhances normally."', '"There is normal liver enhancement"'), reg)
    assert changed in rep2["gone"]
    _, rep3 = _bind(renamed, reg)
    assert changed in rep3["exact"]                                        # exact text: kept
    _, rep4 = _bind(renamed.replace('"The liver enhances normally."', '"The liver enhances normally"'), reg)
    assert changed in rep4["gone"]                                         # a full stop is significant
    _, rep5 = _bind(renamed.replace('"The liver enhances normally."', '"The liver enhances\u00a0normally."'), reg)
    assert changed in rep5["exact"]                                        # typography only: kept


def test_one_old_uid_claimed_by_two_new_lines_is_ambiguous():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    twice = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNEGATIVE "No focal liver lesion."')
    _, rep = _bind(twice, reg)
    assert len(rep["ambiguous"]) == 2 and uid in rep["gone"] and uid not in rep["ambiguous"]


def test_two_old_uids_matching_one_new_line_are_ambiguous():
    twice = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNEGATIVE "No focal liver lesion."')
    reg, _ = _bind(twice)
    olds = sorted(u for u in reg["units"] if u.startswith("g_"))
    _, rep = _bind(LEDGER_SHEET, reg)
    assert len(rep["ambiguous"]) == 1 and sorted(rep["gone"]) == olds


def test_carried_units_keep_their_uid_whatever_the_new_text():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    new_line = 'NEGATIVE "No focal hepatic lesion."'
    edited = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."', new_line)
    reg2, rep = _bind(edited, reg, carried={uid: new_line})
    assert rep["carried"] == [uid] and reg2["units"][uid]["text"] == "No focal hepatic lesion." and not rep["gone"]


def test_a_carried_uid_the_registry_does_not_know_is_ignored():
    reg, _ = _bind(LEDGER_SHEET)
    _, rep = _bind(LEDGER_SHEET, reg, carried={"g_zzzzzz": 'NEGATIVE "No focal liver lesion."'})
    assert not rep["carried"] and set(_counts(rep)) == {"exact"}


def test_gone_units_revive_on_exact_identity_only():
    reg, _ = _bind(LEDGER_SHEET)
    uid = _live(reg, "No focal liver lesion.")
    away = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reg2, _ = _bind(away, reg)
    assert reg2["units"][uid]["status"] == "gone"
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    _, rep = _bind(reworded, reg2)
    assert not rep["revived"] and len(rep["new"]) == 1
    reg4, rep4 = _bind(LEDGER_SHEET, reg2)
    assert rep4["revived"] == [uid] and reg4["units"][uid]["status"] == "live"

# ── reading uids ───────────────────────────────────────────────────────────────────────────────────────────────

def test_uids_for_reads_exact_identity_against_live_units_only():
    assert tlr.uids_for(_st(LEDGER_SHEET), None) == {}
    reg, _ = _bind(LEDGER_SHEET)
    got = tlr.uids_for(_st(LEDGER_SHEET), reg)
    assert set(got) == {"S:TECHNIQUE", "S:FINDINGS", "S:IMPRESSION", "p0", "p1", "p2", "m0", "n0", "f0", "f1"}
    assert got["n0"] == _live(reg, "No focal liver lesion.")
    reworded = LEDGER_SHEET.replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    assert "n0" not in tlr.uids_for(_st(reworded), reg)    # a rewording is another line


def test_match_pairs_renames_but_never_rewordings_without_minting():
    reg, _ = _bind(LEDGER_SHEET)
    snapshot = repr(reg)
    exact = tlr.uids_for(_st(LEDGER_SHEET), reg)
    renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", "## Paragraph: Hepatobiliary (FINDINGS)") \
                          .replace('"No focal liver lesion."', '"There is no focal liver lesion"')
    got = tlr.match(_st(renamed), reg)
    assert (got["p1"], got["m0"]) == (exact["p1"], exact["m0"]) and "n0" not in got
    assert "p1" not in tlr.uids_for(_st(renamed), reg) and repr(reg) == snapshot
    assert tlr.match(_st(LEDGER_SHEET), None) == {}
