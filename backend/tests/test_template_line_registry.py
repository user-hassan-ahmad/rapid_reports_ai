"""The line registry (spec 2026-10-15-stable-line-ids-design): stable uids per line-bound sheet unit, re-bound by code.
Pure code: no model, no database. Pass condition for the adversarial pairs: zero wrong matches."""
import hashlib

import pytest

from rapid_reports_ai import template_line_match as tlm
from tests.template_sheet_fixtures import LEDGER_SHEET


# ── tokeniser and gates ────────────────────────────────────────────────────────────────────────────────────────

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
    assert tlm.same_text(a, b) is None and tlm.same_text(b, a) is None


def test_cosmetic_rewordings_are_the_same_line():
    assert tlm.same_text("There is no pleural effusion.", "No pleural effusion") == "cosmetic"
    assert tlm.same_text("Oedema is seen.", "Edema") == "cosmetic"
    assert tlm.same_text("No focal liver lesion.", "no focal liver lesion") == "exact"
    assert tlm.same_text("No mass. There is fluid.", "No mass. Fluid.") == "cosmetic"   # the scope ends at "."
    assert tlm.same_text("Possible mass; there is fluid.", "Possible mass; fluid.") == "cosmetic"   # and at ";"


@pytest.mark.parametrize("a,b", [
    ("No fracture \u2013 left side.", "No fracture - left side."),
    ("No fracture \u2014 left side.", "No fracture - left side."),
    ("Change of \u22121 mm.", "Change of -1 mm."),
    ("The patient\u2019s \u201cnormal\u201d study.", "The patient's \"normal\" study."),
    ("Measures 5 \u00d7 3 mm.", "Measures 5 x 3 mm."),
    ("No\u00a0effusion.", "No effusion."),
    ("No\u202feffusion.", "No effusion."),
])
def test_cosmetic_typography_always_matches(a, b):
    assert tlm.same_text(a, b) in ("exact", "cosmetic")


def test_meaningful_tokens_are_their_own_tokens():
    assert tlm.tokens("1.5mm<2") == ("1.5", "mm", "<", "2")
    assert tlm.tokens(".5 x3, (well-defined)?") == (".5", "x", "3", ",", "(", "well-defined", ")", "?")
    assert tlm.gates("Mild left 1.5 mm effusion, no mass.") == ("mild", "left", "1.5", "mm", "no")
    assert tlm.gates("Possibly 5 x 3 mm; cannot be excluded.") == ("possibly", "5", "x", "3", "mm", "cannot be excluded")
    assert tlm.gates("Unremarkable, non-enhancing.") == ("unremarkable", "non-enhancing")
    assert tlm.tokens("5' and \"x\" 6\"") == ("5", "\u2032", "and", '"', "x", '"', "6", "\u2033")


def test_spelling_table_lookalikes_and_filler_list_do_not_collide():
    keys, values = set(tlm.SPELLING), set(tlm.SPELLING.values())
    assert len(values) == len(tlm.SPELLING)          # no two UK words map to one US word
    assert not keys & values                         # no word is both a source and a target
    gate_words = tlm.NEGATION | tlm.HEDGE_WORDS | tlm.LATERALITY | tlm.SEVERITY | tlm.UNITS
    assert not (keys | values) & gate_words          # spelling never touches a gate token
    assert len(set(tlm.FILLERS)) == len(tlm.FILLERS)
    assert set(tlm.LOOKALIKES.values()) <= {"-", '"', "'", "x", " "}    # lookalikes merge into these forms only


def test_no_filler_contains_or_can_delete_a_negation_or_hedge_word():
    protected = tlm.NEGATION | tlm.HEDGE_WORDS | {w for p in tlm.HEDGE_PHRASES for w in p}
    assert not {w for f in tlm.FILLERS for w in f} & protected
    for f in tlm.FILLERS:                            # a protected word inside a filler phrase stops the removal
        words = list(f)
        for k in range(1, len(words)):
            for w in sorted(tlm.NEGATION | tlm.HEDGE_WORDS):
                broken = " ".join(words[:k] + [w] + words[k:])
                assert tlm.same_text(f"Effusion {broken}.", f"Effusion {' '.join(words)}.") is None

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
