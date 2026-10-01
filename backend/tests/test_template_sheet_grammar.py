"""Template sheet grammar v1: parser, lint, schema (spec 2026-10-01-template-sheet-grammar-design)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import template_sheet_grammar as g
from rapid_reports_ai import template_sheet_structure as tss

STRUCTURE = """# Example CT Template

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history" | role: history
SECTION TECHNIQUE | header: none | role: technique
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION MEASUREMENTS | header: "Measurements" | role: other
SECTION IMPRESSION | header: "Impression" | role: impression
"""

FULL = STRUCTURE + """
## Voice
Short declarative sentences. British spelling.
TERM PREFER "unremarkable"
- TERM AVOID "grossly normal"

## Paragraph: Primary organ (FINDINGS)
Field ordering: size, then contour, then the adjacent structures.
NORMAL [primary organ] "The primary organ is normal in size and contour."
- NEGATIVE "No focal lesion."
  - NEGATIVE "No surrounding collection." WHEN [findings: an inflammatory process of the primary organ is reported]
RULE WHEN [findings: a focal lesion of the primary organ is reported] SUPPRESS "No focal lesion."
RULE WHEN [findings: a focal lesion of the primary organ is reported] REPLACE "No focal lesion." WITH "A {size} lesion is present."
RULE WHEN [history: prior surgery to the primary organ is stated] APPEND "Post-surgical appearances are noted."
RULE WHEN [context: a follow-up study of a known lesion] USE "stable appearances of the {lesion}"
RULE WHEN [findings: an abnormal adjacent vessel calibre is reported] INSERT "Adjacent vessels:" BEFORE "No focal lesion."
RULE WHEN [findings: multiple abnormal adjacent structures are reported] SUPPRESS NEGATIVES
RULE WHEN [findings: the primary organ abnormality is the main finding] ORDER FIRST
IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core)

## Paragraph: Measured values (MEASUREMENTS)
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["chamber volume" | "wall thickness" | "ejection fraction"] AT TOP
RULE WHEN [findings: every measured value is within normal limits] ORDER LAST

## Report-wide
FIXED "Images reviewed on a diagnostic workstation."
NEGATIVE "No incidental finding of note."
FIXED "Measurements follow the local protocol." | section: MEASUREMENTS
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION MEASUREMENTS
RULE WHEN [context: a short-form report is requested by the referrer] SUPPRESS_HEADERS

## Paragraph: Summary (IMPRESSION)
NEGATIVE "No acute abnormality."
"""


def parse(sheet: str) -> g.GrammarResult:
    return g.parse_sheet(sheet)


def one_rule(effect_line: str, paragraph: str = "## Paragraph: Organ (FINDINGS)") -> tss.Rule:
    r = parse(STRUCTURE + f"\n{paragraph}\n{effect_line}\n")
    assert r.errors == [], r.errors
    assert r.structure.usable
    (rule,) = r.structure.rules
    assert rule.source_lines == [effect_line]
    return rule


def reasons(sheet: str):
    return [e.reason for e in parse(sheet).errors]


# ── schema ─────────────────────────────────────────────────────────────────────

def test_schema_defaults_keep_stored_structures_loading():
    stored = {"sections": [{"name": "FINDINGS", "role": "findings", "order": 0}],
              "rules": [{"id": "r0", "section": "FINDINGS", "condition": "c", "effect": "suppress", "target": "t",
                         "source_lines": ["x"]}],
              "sheet_hash": "h", "model": "m", "created_at": "2026-09-30T00:00:00+00:00", "usable": True}
    s = tss.SheetStructure.model_validate(stored)
    assert s.source == "extracted"
    assert (s.rules[0].items, s.rules[0].anchor, s.rules[0].position) == ([], "", None)


def test_draft_rules_keep_legacy_effects_only():
    rule = {"id": "r0", "section": "FINDINGS", "condition": "c", "effect": "order", "source_lines": ["x"]}
    with pytest.raises(Exception):
        tss.StructureDraft(sections=[{"name": "F", "role": "findings", "order": 0}], rules=[rule])
    schema = tss.StructureDraft.model_json_schema()["$defs"]["DraftRule"]
    assert schema["properties"]["effect"]["enum"] == ["suppress", "replace", "append", "use"]
    assert not {"items", "anchor", "position"} & set(schema["properties"])


# ── units ──────────────────────────────────────────────────────────────────────

def test_section_lines_in_order():
    s = parse(STRUCTURE).structure
    assert [(x.name, x.role, x.header, x.order) for x in s.sections] == [
        ("CLINICAL HISTORY", "history", "Clinical history", 0), ("TECHNIQUE", "technique", None, 1),
        ("FINDINGS", "findings", "FINDINGS", 2), ("MEASUREMENTS", "other", "Measurements", 3),
        ("IMPRESSION", "impression", "Impression", 4)]
    assert s.usable and s.source == "grammar" and s.model == "grammar"


def test_normal():
    r = parse(STRUCTURE + '\n## Paragraph: Organ (FINDINGS)\nNORMAL [organ] "The organ is normal."\n')
    (n,) = r.structure.normals
    assert (n.id, n.section, n.paragraph, n.structure, n.text) == ("m0", "FINDINGS", "p0", "organ", "The organ is normal.")
    assert n.source_line == 'NORMAL [organ] "The organ is normal."'


def test_negative_plain_and_conditional():
    r = parse(STRUCTURE + '\n## Paragraph: Organ (FINDINGS)\nNEGATIVE "No mass."\n'
              'NEGATIVE "No collection." WHEN [history: recent surgery to the organ is stated]\n')
    assert r.errors == []
    a, b = r.structure.negatives
    assert (a.id, a.text, a.condition, a.paragraph) == ("n0", "No mass.", None, "p0")
    assert (b.id, b.condition, b.condition_source) == ("n1", "recent surgery to the organ is stated", "history")


def test_fixed():
    (f,) = parse(STRUCTURE + '\n## Paragraph: Organ (FINDINGS)\nFIXED "Fixed text {slot}."\n').structure.fixed_blocks
    assert (f.id, f.section, f.text) == ("f0", "FINDINGS", "Fixed text {slot}.")


def test_term_prefer_and_avoid_are_sheet_wide():
    r = parse(STRUCTURE + '\nTERM PREFER "unremarkable"\nTERM AVOID "grossly normal"\nTERM PREFER "unremarkable"\n')
    assert r.errors == []
    assert r.structure.terminology == tss.Terminology(preferred=["unremarkable"], suppressed=["grossly normal"])


def test_if_present_stored():
    r = parse(STRUCTURE + '\n## Paragraph: Organ (FINDINGS)\nIF_PRESENT [focal lesion] "No nodes." (contextual)\n')
    (ip,) = r.structure.if_present
    assert (ip.finding, ip.section, ip.paragraph, ip.negatives[0].text, ip.negatives[0].tag) == (
        "focal lesion", "FINDINGS", "p0", "No nodes.", "contextual")


@pytest.mark.parametrize("line,expect", [
    ('RULE WHEN [findings: a focal mass is reported] REPLACE "No mass." WITH "A {size} mass."',
     {"effect": "replace", "target": "No mass.", "then_text": "A {size} mass."}),
    ('RULE WHEN [findings: a focal mass is reported] SUPPRESS "No mass."', {"effect": "suppress", "target": "No mass."}),
    ('RULE WHEN [findings: a focal mass is reported] APPEND "Further assessment advised."',
     {"effect": "append", "then_text": "Further assessment advised."}),
    ('RULE WHEN [context: follow-up imaging of a lesion] USE "stable appearances"',
     {"effect": "use", "then_text": "stable appearances", "condition_source": "context"}),
    ('RULE WHEN [findings: abnormal vessel calibre is reported] INSERT "Vessels:" BEFORE "No mass."',
     {"effect": "insert_before", "then_text": "Vessels:", "anchor": "No mass."}),
    ('RULE WHEN [findings: several organ abnormalities are reported] SUPPRESS NEGATIVES',
     {"effect": "suppress_paragraph_negatives", "target": "", "then_text": ""}),
    ('RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["volume" | "mass index"] AT END',
     {"effect": "list_missing", "items": ["volume", "mass index"], "position": "end"}),
    ('RULE WHEN [context: limited protocol is requested] SUPPRESS_SECTION TECHNIQUE',
     {"effect": "suppress_section", "target": "TECHNIQUE"}),
    ('RULE WHEN [context: short-form report is requested] SUPPRESS_HEADERS', {"effect": "suppress_headers"}),
    ('RULE WHEN [findings: organ abnormality is the main finding] ORDER LAST', {"effect": "order", "position": "last"}),
])
def test_rule_effects(line, expect):
    rule = one_rule(line)
    assert (rule.id, rule.section, rule.paragraph) == ("r0", "FINDINGS", "p0")
    for k, v in expect.items():
        assert getattr(rule, k) == v, k
    assert g.render_rule(rule) == line  # canonical form round-trips


def test_bullets_and_indentation_are_optional():
    rule = one_rule('    - RULE WHEN [history: prior organ surgery is stated] APPEND "Post-surgical change."')
    assert rule.condition == "prior organ surgery is stated" and rule.condition_source == "history"


# ── lint ───────────────────────────────────────────────────────────────────────

PARA = STRUCTURE + "\n## Paragraph: Organ (FINDINGS)\n"


@pytest.mark.parametrize("sheet,reason", [
    (PARA + 'NEGATIVES "No mass."\n', g.UNKNOWN_KEYWORD),
    (PARA + 'OMIT WHEN [findings: a focal mass is reported]\n', g.UNKNOWN_KEYWORD),
    (PARA + 'NEGATIVE "No mass.\n', g.MALFORMED_QUOTES),
    (PARA + 'NEGATIVE “No mass.”\n', g.MALFORMED_QUOTES),
    (PARA + 'RULE WHEN [imaging: a focal mass is reported] SUPPRESS "No mass."\n', g.UNKNOWN_SOURCE),
    (PARA + 'RULE WHEN [a focal mass is reported] SUPPRESS "No mass."\n', g.UNKNOWN_SOURCE),
    (PARA + 'RULE WHEN [findings: abnormal] SUPPRESS "No mass."\n', g.NO_SUBJECT),
    (PARA + 'NEGATIVE "No collection." WHEN [findings: abnormal is reported]\n', g.NO_SUBJECT),
    (STRUCTURE + '\n## Paragraph: Organ (BODY)\nNEGATIVE "No mass."\n', g.UNKNOWN_PARAGRAPH_SECTION),
    (STRUCTURE.replace("SECTION TECHNIQUE", "SECTION FINDINGS"), g.DUPLICATE_SECTION),
    (STRUCTURE + '\n## Notes\nNEGATIVE "No mass."\n', g.NO_SECTION),
    ('NEGATIVE "No mass."\n' + STRUCTURE, g.NO_SECTION),
    (PARA + "Mention the vessels when they are abnormal.\n", g.PROSE_CONDITIONAL),
    (PARA + "- If the organ is enlarged, give its length.\n", g.PROSE_CONDITIONAL),
    (PARA + "Describe the margins unless obscured.\n", g.PROSE_CONDITIONAL),
    (PARA + '- IF [mass] THEN suppress "No mass."\n', g.OLD_SYNTAX),
    (STRUCTURE + '\n## Report-wide\nWrite IF [x] rules carefully.\n', g.OLD_SYNTAX),
    (PARA + 'RULE WHEN [findings: a focal mass is reported] DELETE "No mass."\n', g.MALFORMED_UNIT),
    (PARA + 'NORMAL "The organ is normal."\n', g.MALFORMED_UNIT),
    (STRUCTURE + '\n## Report-wide\nRULE WHEN [findings: organ abnormality is the main finding] ORDER FIRST\n', g.MALFORMED_UNIT),
    (PARA + 'RULE WHEN [context: limited protocol is requested] SUPPRESS_SECTION APPENDIX\n', g.UNKNOWN_SECTION),
    (STRUCTURE + '\n## Report-wide\nFIXED "x" | section: APPENDIX\n', g.UNKNOWN_SECTION),
    (STRUCTURE + "\n## Notes\nSECTION EXTRA | header: none | role: other\n", g.SECTION_OUTSIDE_STRUCTURE),
    (STRUCTURE + "\n" + STRUCTURE.split("\n", 2)[2], g.DUPLICATE_STRUCTURE),
])
def test_lint_reason(sheet, reason):
    r = parse(sheet)
    assert reason in [e.reason for e in r.errors], r.errors
    assert not r.structure.usable
    e = next(e for e in r.errors if e.reason == reason)
    assert e.text == sheet.splitlines()[e.line - 1]


def test_prose_conditional_heuristic_spares_units_headings_and_plain_prose():
    sheet = STRUCTURE + (
        "\n## Paragraph: When abnormal (FINDINGS)\n"  # a heading is not prose
        "Field ordering: size, contour, then adjacent structures.\n"
        'Write "if any" in the radiologist\'s phrasing: "no collection when imaged".\n'  # quoted text is voice
        "List the dilated segments, if any.\n"  # idiom, not a condition
        "Whenever possible keep to one paragraph.\n"  # not if/when/unless as a word
        'NEGATIVE "No collection." WHEN [findings: an inflammatory process is reported]\n'
        'RULE WHEN [findings: a focal mass is reported] SUPPRESS "No collection."\n')
    r = parse(sheet)
    assert r.errors == [], r.errors
    assert r.structure.usable


def test_prose_conditional_only_under_a_paragraph():
    r = parse(STRUCTURE + "\n## Voice\nWhen in doubt, be brief.\n")
    assert r.errors == [] and r.structure.usable


def test_unusable_without_findings_and_impression_roles():
    s = parse(STRUCTURE.replace("role: impression", "role: other")).structure
    assert parse(STRUCTURE.replace("role: impression", "role: other")).errors == [] and not s.usable
    assert not parse("# Just prose\nNo grammar here.\n").structure.usable


# ── full sheet ─────────────────────────────────────────────────────────────────

def test_full_sheet():
    r = parse(FULL)
    assert r.errors == [], r.errors
    s = r.structure
    assert s.usable and s.source == "grammar" and s.model == "grammar"
    assert s.sheet_hash == tss.sheet_hash(FULL)
    assert [(p.id, p.name, p.section) for p in s.paragraphs] == [
        ("p0", "Primary organ", "FINDINGS"), ("p1", "Measured values", "MEASUREMENTS"), ("p2", "Summary", "IMPRESSION")]
    assert s.terminology == tss.Terminology(preferred=["unremarkable"], suppressed=["grossly normal"])
    assert [n.text for n in s.normals] == ["The primary organ is normal in size and contour."]
    assert [(n.id, n.section, n.paragraph, n.condition) for n in s.negatives] == [
        ("n0", "FINDINGS", "p0", None),
        ("n1", "FINDINGS", "p0", "an inflammatory process of the primary organ is reported"),
        ("n2", "FINDINGS", "", None),  # Report-wide: first findings-role section
        ("n3", "IMPRESSION", "p2", None)]
    assert [(r.id, r.effect, r.section, r.paragraph, r.condition_source) for r in s.rules] == [
        ("r0", "suppress", "FINDINGS", "p0", "findings"),
        ("r1", "replace", "FINDINGS", "p0", "findings"),
        ("r2", "append", "FINDINGS", "p0", "history"),
        ("r3", "use", "FINDINGS", "p0", "context"),
        ("r4", "insert_before", "FINDINGS", "p0", "findings"),
        ("r5", "suppress_paragraph_negatives", "FINDINGS", "p0", "findings"),
        ("r6", "order", "FINDINGS", "p0", "findings"),
        ("r7", "list_missing", "MEASUREMENTS", "p1", "findings"),
        ("r8", "order", "MEASUREMENTS", "p1", "findings"),
        ("r9", "suppress_section", "FINDINGS", "", "context"),
        ("r10", "suppress_headers", "FINDINGS", "", "context")]
    assert s.rules[4].anchor == "No focal lesion." and s.rules[4].then_text == "Adjacent vessels:"
    assert s.rules[7].items == ["chamber volume", "wall thickness", "ejection fraction"] and s.rules[7].position == "top"
    assert (s.rules[6].position, s.rules[8].position) == ("first", "last")
    assert s.rules[9].target == "MEASUREMENTS"
    assert s.rules[2].condition == "prior surgery to the primary organ is stated"
    assert [(f.section, f.text) for f in s.fixed_blocks] == [
        ("FINDINGS", "Images reviewed on a diagnostic workstation."),
        ("MEASUREMENTS", "Measurements follow the local protocol.")]
    assert s.if_present[0].negatives[0].tag == "core"
    # every unit's source line is the line as written in the sheet
    lines = set(FULL.splitlines())
    assert all(ln in lines for x in s.rules + s.negatives for ln in x.source_lines)
    assert s.coverage.if_lines == s.coverage.if_covered == 12  # 11 rules + 1 conditional negative
    assert s.coverage.negative_lines == s.coverage.negative_covered == 4
    assert s.coverage.uncovered == []


def test_prose_passes_through_untouched():
    s = parse(FULL).structure
    dumped = s.model_dump_json()
    assert "Short declarative sentences" not in dumped and "Field ordering" not in dumped


def test_parse_is_deterministic():
    a, b = parse(FULL), parse(FULL)
    assert a.errors == b.errors
    assert a.structure.model_dump(exclude={"created_at"}) == b.structure.model_dump(exclude={"created_at"})


def test_fresh_serves_grammar_structures():
    s = parse(FULL).structure
    cfg = {"skill_sheet": FULL, "sheet_structure": s.model_dump(mode="json")}
    got = tss.fresh(cfg)
    assert got is not None and got.source == "grammar" and got.rules[7].items == s.rules[7].items
    assert tss.fresh({**cfg, "skill_sheet": FULL + "\nedited"}) is None
    assert not tss.needs_restructure(cfg)
    bad = parse(FULL + "\n## Paragraph: X (FINDINGS)\nWhen abnormal, say so.\n").structure
    assert tss.fresh({"skill_sheet": FULL + "\n## Paragraph: X (FINDINGS)\nWhen abnormal, say so.\n",
                      "sheet_structure": bad.model_dump(mode="json")}) is None
