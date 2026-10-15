"""The normals confirm record (spec 2026-10-15-stable-line-ids-design, decision 5): groups, chunks, state."""
import pytest

from rapid_reports_ai import template_line_registry as tlr
from rapid_reports_ai import template_normal_confirms as tnc
from rapid_reports_ai import template_sheet_grammar as tsg
from rapid_reports_ai import template_sheet_structure as tss
from tests.template_sheet_fixtures import HABIT_SHEET, LEDGER_SHEET


def _st(sheet):
    res = tsg.parse_sheet(sheet)
    assert not res.errors and res.structure.usable, res.errors
    return res.structure


def _reg(sheet, registry=None):
    return tlr.rebind(registry, _st(sheet), now="T")[0]


def _groups(sheet, reg):
    return tnc.groups(_st(sheet), sheet, reg)


def test_findings_paragraphs_are_groups_and_sections_without_attestable_units_are_none():
    reg = _reg(HABIT_SHEET)
    uids = tlr.uids_for(_st(HABIT_SHEET), reg)
    got = [(g.id, g.label, g.units) for g in _groups(HABIT_SHEET, reg)]
    assert got == [(uids["p1"], "Findings › Liver", (uids["m0"], uids["n0"])),
                   (uids["p2"], "Findings › Lower", (uids["m1"],))]
    # the technique section holds only a FIXED line (not attestable) and the impression nothing: no group


def test_a_non_findings_section_is_one_group_with_its_normals():
    sheet = LEDGER_SHEET.replace('FIXED "Axial images were acquired."',
                                 'FIXED "Axial images were acquired."\nNORMAL [coverage] "Coverage is complete."')
    reg = _reg(sheet)
    uids = tlr.uids_for(_st(sheet), reg)
    first = _groups(sheet, reg)[0]
    assert (first.id, first.label, first.units) == (uids["S:TECHNIQUE"], "Technique", (uids["m0"],))


def test_conditional_and_habit_negatives_are_not_attestable():
    sheet = HABIT_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                'NEGATIVE "No focal liver lesion."\nNEGATIVE "No duct dilatation." '
                                'WHEN [findings: a liver mass is reported]')
    reg = _reg(sheet)
    assert len(_groups(sheet, reg)[0].units) == 2


def test_a_group_over_eight_is_chunked_in_document_order():
    extra = "\n".join(f'NORMAL [s{k}] "Structure {k} is normal."' for k in range(9))
    sheet = LEDGER_SHEET.replace('COVERS ["liver" | "gallbladder"]',
                                 'COVERS ["liver" | "gallbladder" | ' + " | ".join(f'"s{k}"' for k in range(9)) + "]") \
                        .replace('NEGATIVE "No focal liver lesion."', f'NEGATIVE "No focal liver lesion."\n{extra}')
    reg = _reg(sheet)
    uids = tlr.uids_for(_st(sheet), reg)
    gs = _groups(sheet, reg)
    assert [g.id for g in gs] == [f"{uids['p1']}#1", f"{uids['p1']}#2"]
    assert [len(g.units) for g in gs] == [8, 3] and gs[0].label == "Findings › Liver (1/2)"
    assert gs[0].units[:2] == (uids["m0"], uids["n0"])          # document order: the NORMAL, then the NEGATIVE


def _confirmed(sheet, reg):
    g = _groups(sheet, reg)[0]
    return g, tnc.record(g, reg, sheet_rev=1, sheet_hash=tss.sheet_hash(sheet), user_id="u", now="T")


def test_state_is_valid_until_a_unit_changes_is_added_or_removed():
    reg = _reg(LEDGER_SHEET)
    g, rec = _confirmed(LEDGER_SHEET, reg)
    assert tnc.confirm_state(g, rec, reg) == "valid" and tnc.confirm_state(g, None, reg) == "missing"
    assert rec["units"] == {u: reg["units"][u]["text_hash"] for u in g.units} and rec["user_id"] == "u"
    reworded = LEDGER_SHEET.replace('"The liver is normal in size."\nNEGATIVE', '"The liver is unremarkable."\nNEGATIVE')
    reg2 = _reg(reworded, reg)
    g2 = _groups(reworded, reg2)[0]
    assert (g2.id, g2.units) == (g.id, g.units)                               # (a) the reworded normal kept its slot uid
    assert tnc.confirm_state(g2, rec, reg2) == "stale"                        # ... and its changed text_hash makes it stale
    added = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."',
                                 'NEGATIVE "No focal liver lesion."\nNORMAL [gallbladder] "The gallbladder is normal."')
    reg3 = _reg(added, reg)
    assert tnc.confirm_state(_groups(added, reg3)[0], rec, reg3) == "stale"
    removed = LEDGER_SHEET.replace('NEGATIVE "No focal liver lesion."\n', "")
    reg4 = _reg(removed, reg)
    assert tnc.confirm_state(_groups(removed, reg4)[0], rec, reg4) == "stale"
    assert tnc.confirm_states(_st(removed), removed, reg4, {g.id: rec}) == {g.id: "stale"}


def test_a_renamed_group_is_stale_even_when_every_sentence_carried():
    reg = _reg(LEDGER_SHEET)
    g, rec = _confirmed(LEDGER_SHEET, reg)
    assert rec["group_name"] == "Liver"
    for new_name in ("Hepatobiliary", "liver"):                          # (b) a rename, a case-only one included
        renamed = LEDGER_SHEET.replace("## Paragraph: Liver (FINDINGS)", f"## Paragraph: {new_name} (FINDINGS)")
        reg2 = _reg(renamed, reg)
        g2 = _groups(renamed, reg2)[0]
        assert (g2.id, g2.units) == (g.id, g.units)                   # every sentence identical, every uid kept
        assert all(reg2["units"][u]["text_hash"] == reg["units"][u]["text_hash"] for u in g.units)
        assert tnc.confirm_state(g2, rec, reg2) == "stale"


def test_a_unit_without_text_hash_is_never_confirmable_and_never_crashes():
    reg = _reg(LEDGER_SHEET)
    g = _groups(LEDGER_SHEET, reg)[0]
    bad = {**reg, "units": {**reg["units"], g.units[0]: {k: v for k, v in reg["units"][g.units[0]].items()
                                                         if k != "text_hash"}}}
    rec = tnc.record(g, bad, sheet_rev=1, sheet_hash="h", user_id="u")
    assert g.units[0] not in rec["units"]
    assert tnc.confirm_state(g, rec, bad) == tnc.STALE
    good = tnc.record(g, reg, sheet_rev=1, sheet_hash="h", user_id="u")
    assert tnc.confirm_state(g, good, bad) == tnc.STALE


# ── a rule on the group's units makes a confirm stale when added, removed or changed (end review M5) ────────────

_NEG = 'NEGATIVE "No focal liver lesion."'
_SUPPRESS = 'RULE WHEN [context: the dictation states contrast was given] SUPPRESS "No focal liver lesion."'


def _with(sheet, after, line):
    return sheet.replace(after, f"{after}\n{line}", 1)


def _state_after(base, edited):
    reg = _reg(base)
    _, rec = _confirmed(base, reg)
    reg2 = _reg(edited, reg)
    return tnc.confirm_state(_groups(edited, reg2)[0], rec, reg2)


@pytest.mark.parametrize("line, after", [
    (_SUPPRESS, _NEG),
    ('RULE WHEN [context: the dictation states contrast was given] REPLACE "The liver is normal in size." '
     'WITH "The liver is normal."', _NEG),
    ("RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION FINDINGS",
     'TERM PREFER "hepatic"'),
])
def test_adding_a_rule_that_suppresses_or_replaces_a_confirmed_unit_makes_the_confirm_stale(line, after):
    edited = _with(LEDGER_SHEET, after, line)
    _st(edited)
    assert _state_after(LEDGER_SHEET, edited) == "stale"


def test_removing_or_changing_such_a_rule_makes_the_confirm_stale():
    base = _with(LEDGER_SHEET, _NEG, _SUPPRESS)
    assert _state_after(base, LEDGER_SHEET) == "stale"
    changed = base.replace("contrast was given", "a contrast agent was given")
    assert _state_after(base, changed) == "stale"


def test_an_unrelated_rule_leaves_the_confirm_valid():
    edited = _with(LEDGER_SHEET, 'FIXED "No previous imaging available."',
                   'RULE WHEN [context: the dictation names a previous study] SUPPRESS "No previous imaging available."')
    _st(edited)
    assert _state_after(LEDGER_SHEET, edited) == "valid"
    with_rule = _with(LEDGER_SHEET, _NEG, _SUPPRESS)
    assert _state_after(with_rule, with_rule) == "valid"
