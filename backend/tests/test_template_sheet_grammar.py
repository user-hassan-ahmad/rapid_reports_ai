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
    """Grammar v1 (findings rules, IF_PRESENT, COVERS optional): the unit and lint tests below. The lean
    template and master modes have their own section at the end."""
    return g.parse_sheet(sheet, mode="v1")


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
        "List the dilated segments, if any.\n"  # closing idiom, not a condition
        "Give each segment (if any) its own clause\n"
        "Normal appearances take one sentence.\n"  # a keyword word as plain prose
        "Section order follows the structure above.\n"
        'NEGATIVE "No collection." WHEN [findings: an inflammatory process is reported]\n'
        'RULE WHEN [findings: a focal mass is reported] SUPPRESS "No collection."\n')
    r = parse(sheet)
    assert r.errors == [], r.errors
    assert r.structure.usable


FREE = ["Scan Context", "Impression Construction", "Measurement and Grading", "Reference Values",
        "Incidental Findings", "Domain Rules", "Open Questions", "Voice", "Style", "Terminology"]


@pytest.mark.parametrize("heading", FREE + ["voice", "MEASUREMENT AND GRADING"])
def test_free_prose_sections_skip_conditional_and_negative_checks(heading):
    r = parse(STRUCTURE + f"\n## {heading}\nWhen in doubt, be brief.\nNo paragraph headers in short reports.\n"
              "### A subheading\nIf the study is limited, say so.\n")
    assert r.errors == [] and r.structure.usable
    assert len(g.FREE_PROSE_SECTIONS) == len(FREE)


@pytest.mark.parametrize("heading", ["Measurement and Grading Rules", "Incidental Findings Rules", "Scan context notes",
                                     "Reporting notes", "Report-wide", "Paragraph: Organ (FINDINGS)"])
def test_other_headings_stay_checked(heading):
    r = parse(STRUCTURE + f"\n## {heading}\nWhen in doubt, be brief.\nNo paragraph headers in short reports.\n")
    assert [e.reason for e in r.warnings] == [g.PROSE_CONDITIONAL]
    assert [e.reason for e in r.errors] == [g.PROSE_NEGATIVE] and not r.structure.usable


def test_free_prose_ends_at_the_next_section_heading():
    r = parse(STRUCTURE + "\n## Domain Rules\nIf limited, say so.\n## Paragraph: Organ (FINDINGS)\nIf limited, say so.\n")
    assert [(e.line, e.reason) for e in r.warnings] == [(len(STRUCTURE.splitlines()) + 5, g.PROSE_CONDITIONAL)]
    assert r.errors == []


def test_preamble_prose_is_checked():
    r = parse("Use this sheet when reporting.\n" + STRUCTURE)
    assert [e.reason for e in r.warnings] == [g.PROSE_CONDITIONAL] and r.errors == []


def test_prose_conditional_is_a_stored_warning_not_an_error():
    sheet = PARA + "Mention the vessels when they are abnormal.\n"
    r = parse(sheet)
    assert r.errors == [] and r.structure.usable and r.structure.lint_errors == []
    (w,) = r.warnings
    assert (w.reason, w.detail, w.text) == (g.PROSE_CONDITIONAL, "when", "Mention the vessels when they are abnormal.")
    assert [(x.line, x.reason, x.text) for x in r.structure.lint_warnings] == [(w.line, w.reason, w.text)]


@pytest.mark.parametrize("mode", ["template", "v1"])
@pytest.mark.parametrize("prose", [
    "No collection if the organ is normal.",
    'If normal, write "No ascites."',
    'When the liver is normal, state "No focal liver lesion."',
    'State "No ascites." when there is none.',
    'When normal, write “No ascites.”',
    "Ensure no ascites is described when absent.",
    "If the study is normal, state the absence of free fluid without further comment.",
    "When the ducts are not dilated, say so in one clause.",
    'If clear, write "There is no pleural effusion."',
    "If negative for collection, say nothing more.",
])
def test_conditional_negatives_in_prose_block(prose, mode):
    sheet = PARA + prose + "\n"
    r = g.parse_sheet(sheet if mode == "v1" else sheet.replace(PARA, PARA + 'COVERS ["organ"]\n'), mode=mode)
    assert [e.reason for e in r.errors] == [g.CONDITIONAL_NEGATIVE], r.errors
    assert r.warnings == [] and not r.structure.usable


@pytest.mark.parametrize("prose", [
    "When present, give the maximal diameter.",
    "If any segment is dilated, give its calibre.",
    "List the dilated segments, if any.",
    'When an aneurysm is present, use "aneurysmal" rather than "ectatic".',
])
def test_conditionals_without_a_negative_cue_only_warn(prose):
    r = parse(PARA + prose + "\n")
    assert r.errors == [] and r.structure.usable
    assert [w.reason for w in r.warnings] in ([g.PROSE_CONDITIONAL], [])


@pytest.mark.parametrize("prose", [
    "Absent ascites.", "Ascites is absent.", "The pleural effusions are absent.", "Nil ascites.",
    "Negative for ascites.", "(No ascites.)", "“No ascites.”", "'No ascites.'", "_No ascites._",
    "Ascites: none.", "Ascites: nil.", "Ascites: not seen.", "Pleural effusion: not identified",
    "Free of ascites.", "Not seen: ascites.", "Not identified: free fluid.", "Not demonstrated: collection.",
    "Ascites not seen.", "Free fluid is not identified.", "A collection was not demonstrated.",
])
def test_absence_statements_in_prose_block(prose):
    r = parse(PARA + prose + "\n")
    assert [e.reason for e in r.errors] == [g.PROSE_NEGATIVE], r.errors


@pytest.mark.parametrize("prose", ["The bile ducts are not dilated.", "Lymph nodes are not enlarged.",
                                   "Unremarkable liver.", 'Prefer “unremarkable” over “normal”.',
                                   'Prefer “No aneurysm.” over longer forms.',
                                   "Field order: size, contour, then the adjacent fat.",
                                   "Describe what was not seen in the arterial phase in the next sentence.",
                                   "The ducts are not dilated and the fat is clear."])  # as with straight quotes
def test_normal_state_voice_prose_stays_prose(prose):
    r = parse(PARA + prose + "\n")
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


def test_fresh_serves_template_mode_grammar_structures_only():
    s = g.parse_sheet(LEAN).structure
    assert s.grammar_mode == "template"
    cfg = {"skill_sheet": LEAN, "sheet_structure": s.model_dump(mode="json")}
    got = tss.fresh(cfg)
    assert got is not None and got.source == "grammar" and got.rules[3].items == s.rules[3].items
    assert tss.current_grammar(cfg)
    assert tss.fresh({**cfg, "skill_sheet": LEAN + "\nedited"}) is None
    assert not tss.needs_restructure(cfg)
    bad = g.parse_sheet(LEAN + "\n## Paragraph: X (FINDINGS)\nNo abnormality.\n").structure
    assert tss.fresh({"skill_sheet": LEAN + "\n## Paragraph: X (FINDINGS)\nNo abnormality.\n",
                      "sheet_structure": bad.model_dump(mode="json")}) is None


@pytest.mark.parametrize("sheet,mode", [("FULL", "v1"), ("LEAN", "v1"), ("MASTER", "master")])
def test_fresh_never_serves_v1_or_master_structures(sheet, mode):
    sheet = globals()[sheet]
    s = g.parse_sheet(sheet, mode=mode).structure
    assert s.usable and s.grammar_mode == mode
    cfg = {"skill_sheet": sheet, "sheet_structure": s.model_dump(mode="json")}
    assert tss.fresh(cfg) is None and not tss.current_grammar(cfg)


def test_fresh_compares_the_raw_stored_version():
    raw = g.parse_sheet(LEAN).structure.model_dump(mode="json")
    for stored in ({**raw, "version": 1}, {k: v for k, v in raw.items() if k != "version"}):
        cfg = {"skill_sheet": LEAN, "sheet_structure": stored}
        assert tss.fresh(cfg) is None and tss.fresh_any_source(cfg) is None and not tss.current_grammar(cfg)
    no_mode = {k: v for k, v in raw.items() if k != "grammar_mode"}
    assert tss.fresh({"skill_sheet": LEAN, "sheet_structure": no_mode}) is None


# ── fail-closed sweep (review of G1) ─────────────────────────────────────────

HEAD = """## Report Structure
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION IMPRESSION | header: "Impression:" | role: impression
SECTION COMPARISON | header: none | role: comparison

## Paragraph: Aorta (FINDINGS)
Describe the aorta in one sentence.
"""


@pytest.mark.parametrize("line", [
    '* NEGATIVE "No aneurysm."', '1. NEGATIVE "No aneurysm."', '2) NEGATIVE "No aneurysm."',
    '– NEGATIVE "No aneurysm."', '• NEGATIVE "No aneurysm."', '+ NEGATIVE "No aneurysm."',
    '> NEGATIVE "No aneurysm."', '`NEGATIVE "No aneurysm."`', '**NEGATIVE** "No aneurysm."',
    'negative "No aneurysm."', 'Negative "No aneurysm."', '\u200bNEGATIVE "No aneurysm."',
    '* NEGATIVE "No dissection." WHEN [findings: aortic dissection is not reported]',
    '* RULE WHEN [findings: aortic dissection is reported] SUPPRESS NEGATIVES',
    'Rule WHEN [findings: aortic dissection is reported] SUPPRESS NEGATIVES',
    '1. NORMAL [aorta] "The aorta is normal."', '- `FIXED "Correlate clinically."`',
    '* TERM PREFER "aneurysmal"', 'term avoid "ectatic"', '* IF_PRESENT [aneurysm] "No mural thrombus." (core)',
])
def test_decorated_or_miscased_units_fail_closed(line):
    r = parse(HEAD + line + "\n")
    assert [e.reason for e in r.errors] == [g.DECORATED_UNIT], r.errors
    assert not r.structure.usable and not r.structure.negatives and not r.structure.rules


@pytest.mark.parametrize("line", [
    "* SECTION COMPARISON | header: none | role: comparison",
    "1. SECTION COMPARISON | header: none | role: comparison",
    "Section COMPARISON | header: none | role: comparison",
    "**SECTION** COMPARISON | header: none | role: comparison",
])
def test_decorated_or_miscased_section_lines_fail_closed(line):
    sheet = HEAD.replace("SECTION COMPARISON | header: none | role: comparison", line)
    r = parse(sheet)
    assert g.DECORATED_UNIT in [e.reason for e in r.errors] and not r.structure.usable
    assert [x.name for x in r.structure.sections] == ["FINDINGS", "IMPRESSION"]


@pytest.mark.parametrize("heading", [
    "### Paragraph: Heart (FINDINGS)", "##Paragraph: Heart (FINDINGS)", "**Paragraph: Heart (FINDINGS)**",
    "# Paragraph: Heart (FINDINGS)", "## Paragraph : Heart (FINDINGS)", "- Paragraph: Heart (FINDINGS)",
])
def test_mislevelled_paragraph_headings_fail_closed(heading):
    r = parse(HEAD + heading + '\nNEGATIVE "No pericardial effusion."\n')
    assert g.MISLEVELLED_PARAGRAPH in [e.reason for e in r.errors], r.errors
    assert not r.structure.usable
    assert [p.name for p in r.structure.paragraphs] == ["Aorta"]


@pytest.mark.parametrize("prose", [
    "If any aortic aneurysm is present, give its maximal diameter.",
    "Whenever an aneurysm is present, give its maximal diameter.",
    "Wherever the wall is thickened, say so.",
    "Where an aneurysm is present, give its maximal diameter.",
    "In case of aneurysm, give its maximal diameter.",
    "Provided the root is dilated, add a surveillance line.",
    "Should dissection be present, omit the normal sentence.",
    "For patients with prior repair, describe the graft.",
    "In the presence of dissection, omit the normal sentence.",
    "Once dissection is seen, omit the normal sentence.",
    "Otherwise say the aorta is normal.",
    "Wording depending on the root size.",
    "Give the diameter if any aneurysm is seen.",
    "Unless obscured, describe the wall.",
])
@pytest.mark.parametrize("where", ["", "\n## Report-wide\n", "\n## Reporting notes\n"])
def test_prose_conditionals_warn(prose, where):
    r = parse(HEAD + where + prose + "\n")
    assert [e.reason for e in r.warnings] == [g.PROSE_CONDITIONAL], r.warnings
    assert r.errors == [] and r.structure.usable


def test_prose_conditional_checked_in_report_structure_block():
    r = parse(HEAD.replace("SECTION COMPARISON", "Comparison appears when prior imaging exists.\nSECTION COMPARISON"))
    assert [e.reason for e in r.warnings] == [g.PROSE_CONDITIONAL] and r.errors == []


@pytest.mark.parametrize("prose", [
    "- No aortic aneurysm or dissection.", "No aortic aneurysm.", "There is no aortic aneurysm.",
    "There are no aortic aneurysms.", "Without aneurysm or dissection.", '- "No aneurysm." / "No dissection."',
    '"No aneurysm."', "**No aortic aneurysm.**", "1. No aortic aneurysm.",
])
@pytest.mark.parametrize("where", ["", "\n## Report-wide\n"])
def test_prose_negatives_fail_closed(prose, where):
    r = parse(HEAD + where + prose + "\n")
    assert [e.reason for e in r.errors] == [g.PROSE_NEGATIVE], r.errors
    assert not r.structure.usable


def test_quoted_negative_inside_instruction_prose_is_not_a_prose_negative():
    r = parse(HEAD + 'Prefer "No aneurysm." over longer forms.\n')
    assert r.errors == [] and r.structure.usable


def test_section_attribute_inside_quotes_is_text():
    r = parse(HEAD + 'NEGATIVE "No mass | section: IMPRESSION"\n'
              'RULE WHEN [findings: aortic dissection is reported] APPEND "x | section: FINDINGS"\n')
    assert r.errors == [], r.errors
    assert r.structure.negatives[0].text == "No mass | section: IMPRESSION"
    assert r.structure.negatives[0].section == "FINDINGS" and r.structure.rules[0].then_text == "x | section: FINDINGS"


def test_probe_baselines_still_parse():
    for line in ['NEGATIVE "No aneurysm."', '\tNEGATIVE\t"No aneurysm."', '\u00a0- NEGATIVE "No aneurysm."',
                 'RULE WHEN [findings: aortic dissection is reported] REPLACE "No dissection." WITH "Dissection."',
                 'RULE WHEN [history: coronary study is not requested] SUPPRESS_SECTION COMPARISON',
                 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["LVEF | %" | "LVEDV"] AT TOP',
                 '## Paragraph: Heart (findings)\nNEGATIVE "No pericardial effusion."',
                 '## Paragraph: Heart (and pericardium) (FINDINGS)\nNEGATIVE "No pericardial effusion."']:
        r = parse(HEAD + line + "\n")
        assert r.errors == [] and r.structure.usable, (line, r.errors)


def test_mixed_sheet_fresh_rejects_mislevelled_paragraph():
    sheet = (HEAD.replace("Describe the aorta in one sentence.\n", "") + 'NEGATIVE "No aneurysm."\n'
             "RULE WHEN [findings: aortic dissection is reported] SUPPRESS NEGATIVES\n"
             "### Paragraph: Heart (FINDINGS)\n"
             'NEGATIVE "No pericardial effusion."\n')
    s = parse(sheet).structure
    assert not s.usable
    assert tss.fresh({"skill_sheet": sheet, "sheet_structure": s.model_dump()}) is None


# ── lean template sheet + master sheet (spec 2026-10-01-template-two-phase) ─────

LEAN = STRUCTURE + """
## Voice
Short declarative sentences.
TERM PREFER "unremarkable"

## Paragraph: Primary organ (FINDINGS)
COVERS ["primary organ" | "adjacent fat"]
When present, give the maximal diameter.
NORMAL [primary organ] "The primary organ is normal in size and contour."
NEGATIVE "No focal lesion."
NEGATIVE "No contrast extravasation."
RULE WHEN [context: prior imaging is available for comparison] REPLACE "No focal lesion." WITH "No new focal lesion."
RULE WHEN [context: a follow-up study of a known lesion] USE "stable appearances of the {lesion}"
RULE WHEN [context: a non-contrast study is performed] SUPPRESS "No contrast extravasation."

## Paragraph: Measured values (MEASUREMENTS)
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["chamber volume" | "wall thickness"] AT TOP

## Report-wide
FIXED "Images reviewed on a diagnostic workstation."
NEGATIVE "No incidental finding of note."
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION MEASUREMENTS
RULE WHEN [context: a short-form report is requested by the referrer] SUPPRESS_HEADERS

## Paragraph: Summary (IMPRESSION)
Numbered list, most important first.
"""

CASE_NEG = 'NEGATIVE "No surrounding fat stranding." TARGETS [inflammatory process] | origin: case'
CASE_IP = 'IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core) | origin: case'
CASE_BLOCK = """
## Case Deliberation
QUESTION "Is there a cause for the presenting symptom?"
DIFFERENTIAL [focal mass] TIER triage "a discrete lesion of the primary organ" VISIBLE yes
DIFFERENTIAL [Inflammatory process] TIER aetiology "surrounding fat stranding" VISIBLE silent
RECOMMEND IMAGING "Further characterisation with a dedicated study is suggested." WHEN [findings: an indeterminate lesion of the primary organ is reported]
"""
ANCHOR = 'RULE WHEN [context: a non-contrast study is performed] SUPPRESS "No contrast extravasation."\n'
MASTER = LEAN.replace(ANCHOR, ANCHOR + CASE_NEG + "\n" + CASE_IP + "\n") + CASE_BLOCK


def in_paragraph(line: str, sheet: str = LEAN) -> str:
    return sheet.replace(ANCHOR, ANCHOR + line + "\n")


def test_parse_sheet_defaults_to_template_mode_and_rejects_unknown_modes():
    assert [e.reason for e in g.parse_sheet(in_paragraph(CASE_IP)).errors] == [g.CASE_IN_TEMPLATE]
    with pytest.raises(ValueError):
        g.parse_sheet(LEAN, mode="quick")


def test_lean_template_sheet_parses_usable():
    r = g.parse_sheet(LEAN, mode="template")
    assert r.errors == [], r.errors
    s = r.structure
    assert s.usable and s.source == "grammar"
    assert [(p.name, p.covers) for p in s.paragraphs] == [
        ("Primary organ", ["primary organ", "adjacent fat"]), ("Measured values", []), ("Summary", [])]
    assert [(x.effect, x.condition_source) for x in s.rules] == [
        ("replace", "context"), ("use", "context"), ("suppress", "context"), ("list_missing", "findings"),
        ("suppress_section", "context"), ("suppress_headers", "context")]
    assert [(n.condition, n.origin) for n in s.negatives] == [(None, "template")] * 3
    assert s.grammar_mode == "template"
    assert (s.question, s.differentials, s.recommendations) == ("", [], [])
    # the voice line "When present, give the maximal diameter." is a stored warning, not an error
    assert [(w.reason, w.text) for w in s.lint_warnings] == [
        (g.PROSE_CONDITIONAL, "When present, give the maximal diameter.")]


NOT_LEAN_LINES = [
    'RULE WHEN [findings: a focal lesion of the primary organ is reported] SUPPRESS "No focal lesion."',
    'RULE WHEN [findings: a focal lesion of the primary organ is reported] REPLACE "No focal lesion." WITH "A lesion."',
    'RULE WHEN [findings: a focal lesion of the primary organ is reported] APPEND "Further assessment advised."',
    'RULE WHEN [findings: a focal lesion of the primary organ is reported] USE "lesion"',
    'RULE WHEN [findings: abnormal adjacent vessel calibre is reported] INSERT "Vessels:" BEFORE "No focal lesion."',
    'RULE WHEN [findings: several organ abnormalities are reported] SUPPRESS NEGATIVES',
    'RULE WHEN [findings: organ abnormality is the main finding] ORDER FIRST',
    'RULE WHEN [findings: a focal lesion of the primary organ is reported] SUPPRESS_HEADERS',
    'RULE WHEN [history: prior surgery to the primary organ is stated] APPEND "Post-surgical change."',
    'RULE WHEN [history: prior surgery to the primary organ is stated] SUPPRESS "No focal lesion."',
    'RULE WHEN [context: a follow-up study of a known lesion] APPEND "Compared with the prior study."',
    'RULE WHEN [context: a follow-up study of a known lesion] INSERT "Comparison:" BEFORE "No focal lesion."',
    'RULE WHEN [context: a follow-up study of a known lesion] SUPPRESS NEGATIVES',
    'RULE WHEN [context: a follow-up study of a known lesion] ORDER FIRST',
    'RULE WHEN [history: any listed value is not stated in the request] LIST_MISSING ["volume"] AT END',
    'NEGATIVE "No surrounding collection." WHEN [findings: an inflammatory process of the organ is reported]',
    'NEGATIVE "No surrounding collection." WHEN [history: recent surgery to the organ is stated]',
    'NEGATIVE "No contrast extravasation." WHEN [context: a contrast-enhanced study is performed]',
    'IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core)',
]


@pytest.mark.parametrize("mode", ["template", "master"])
@pytest.mark.parametrize("line", NOT_LEAN_LINES)
def test_findings_and_history_conditioned_units_are_not_lean(line, mode):
    sheet = in_paragraph(line, MASTER if mode == "master" else LEAN)
    r = g.parse_sheet(sheet, mode=mode)
    assert [e.reason for e in r.errors] == [g.NOT_LEAN], r.errors
    (e,) = r.errors
    assert e.text == line and sheet.splitlines()[e.line - 1] == line
    assert not r.structure.usable and line in r.structure.coverage.uncovered


@pytest.mark.parametrize("line", NOT_LEAN_LINES)
def test_v1_mode_keeps_the_full_grammar(line):
    r = g.parse_sheet(in_paragraph(line), mode="v1")
    assert r.errors == [] and r.structure.usable, r.errors


# ── COVERS ──

@pytest.mark.parametrize("mode", ["template", "master"])
def test_covers_required_on_findings_paragraphs(mode):
    base = MASTER if mode == "master" else LEAN
    sheet = base.replace('COVERS ["primary organ" | "adjacent fat"]\n', "")
    r = g.parse_sheet(sheet, mode=mode)
    assert [(e.reason, e.detail, e.text) for e in r.errors] == [
        (g.MISSING_COVERS, "Primary organ", "## Paragraph: Primary organ (FINDINGS)")]
    assert not r.structure.usable


def test_covers_not_required_outside_findings_role_and_optional_in_v1():
    # MEASUREMENTS (role other) and IMPRESSION paragraphs have no COVERS in LEAN and parse clean
    no_covers = LEAN.replace('COVERS ["primary organ" | "adjacent fat"]\n', "")
    r = g.parse_sheet(no_covers, mode="v1")
    assert r.errors == [] and r.structure.usable
    r = g.parse_sheet(LEAN + '\n## Paragraph: Extra (MEASUREMENTS)\nCOVERS ["volume"]\n', mode="v1")
    assert r.structure.paragraphs[-1].covers == ["volume"]


@pytest.mark.parametrize("sheet,reason", [
    (in_paragraph('COVERS ["kidneys"]'), g.DUPLICATE_COVERS),
    (LEAN.replace("## Report-wide\n", '## Report-wide\nCOVERS ["kidneys"]\n'), g.MALFORMED_UNIT),
    (LEAN.replace('COVERS ["primary organ" | "adjacent fat"]', 'COVERS [primary organ]'), g.MALFORMED_UNIT),
    (LEAN.replace('COVERS ["primary organ" | "adjacent fat"]', 'COVERS []'), g.MALFORMED_UNIT),
    (LEAN.replace('COVERS ["primary organ" | "adjacent fat"]', 'COVERS "primary organ"'), g.MALFORMED_UNIT),
    (LEAN.replace('COVERS ["primary organ" | "adjacent fat"]', '* COVERS ["primary organ"]'), g.DECORATED_UNIT),
])
def test_covers_lint(sheet, reason):
    r = g.parse_sheet(sheet, mode="template")
    assert reason in [e.reason for e in r.errors], r.errors
    assert not r.structure.usable


def test_duplicate_covers_keeps_the_first():
    r = g.parse_sheet(in_paragraph('COVERS ["kidneys"]'), mode="template")
    assert r.structure.paragraphs[0].covers == ["primary organ", "adjacent fat"]


# ── case units ──

def test_master_sheet_parses_case_units():
    r = g.parse_sheet(MASTER, mode="master")
    assert r.errors == [], r.errors
    s = r.structure
    assert s.usable
    assert s.question == "Is there a cause for the presenting symptom?"
    assert [(d.id, d.name, d.tier, d.discriminator, d.visible) for d in s.differentials] == [
        ("d0", "focal mass", "triage", "a discrete lesion of the primary organ", "yes"),
        ("d1", "Inflammatory process", "aetiology", "surrounding fat stranding", "silent")]
    (rec,) = s.recommendations
    assert (rec.id, rec.tag, rec.text, rec.condition, rec.condition_source) == (
        "rec0", "IMAGING", "Further characterisation with a dedicated study is suggested.",
        "an indeterminate lesion of the primary organ is reported", "findings")
    case = [n for n in s.negatives if n.origin == "case"]
    assert [(n.text, n.targets, n.paragraph, n.section, n.condition) for n in case] == [
        ("No surrounding fat stranding.", "Inflammatory process", "p0", "FINDINGS", None)]  # canonical name
    assert [n.origin for n in s.negatives if n.origin != "case"] == ["template"] * 3
    (ip,) = s.if_present
    assert (ip.finding, ip.origin, ip.paragraph, ip.negatives[0].tag) == ("focal lesion", "case", "p0", "core")
    assert g.render_negative(case[0]) == CASE_NEG.replace("[inflammatory process]", "[Inflammatory process]")


@pytest.mark.parametrize("mode", ["template", "v1"])
@pytest.mark.parametrize("sheet", [
    in_paragraph(CASE_NEG), in_paragraph(CASE_IP),
    LEAN + '\n## Case Deliberation\n',
    LEAN + '\n## Case Deliberation\nQUESTION "Is there a cause for the presenting symptom?"\n',
    LEAN + '\n## Case Deliberation\nDIFFERENTIAL [focal mass] TIER triage "a discrete lesion" VISIBLE yes\n',
    LEAN + '\n## Case Deliberation\nRECOMMEND MDT "Discussion at the MDT is suggested." WHEN [findings: a focal mass is reported]\n',
])
def test_case_units_outside_a_master_sheet_are_errors(sheet, mode):
    r = g.parse_sheet(sheet, mode=mode)
    assert r.errors and {e.reason for e in r.errors} == {g.CASE_IN_TEMPLATE}, r.errors
    assert not r.structure.usable
    assert not [n for n in r.structure.negatives if n.origin == "case"] and not r.structure.differentials


def _master(old: str, new: str) -> str:
    assert old in MASTER
    return MASTER.replace(old, new)


Q = 'QUESTION "Is there a cause for the presenting symptom?"\n'
D0 = 'DIFFERENTIAL [focal mass] TIER triage "a discrete lesion of the primary organ" VISIBLE yes\n'
REC = ('RECOMMEND IMAGING "Further characterisation with a dedicated study is suggested." '
       'WHEN [findings: an indeterminate lesion of the primary organ is reported]\n')


@pytest.mark.parametrize("sheet,reason", [
    (_master(Q, ""), g.QUESTION_COUNT),
    (MASTER.replace(CASE_BLOCK, "").replace(CASE_NEG + "\n", ""), g.QUESTION_COUNT),
    (_master(Q, Q + 'QUESTION "A second question about the organ?"\n'), g.QUESTION_COUNT),
    (_master("TARGETS [inflammatory process]", "TARGETS [vascular cause]"), g.UNKNOWN_TARGET),
    (_master(D0, D0 + D0.replace("triage", "aetiology")), g.DUPLICATE_DIFFERENTIAL),
    (_master(D0, D0.replace("TIER triage", "TIER urgent")), g.MALFORMED_UNIT),
    (_master(D0, D0.replace("VISIBLE yes", "VISIBLE maybe")), g.MALFORMED_UNIT),
    (_master(D0, D0.replace(" VISIBLE yes", "")), g.MALFORMED_UNIT),
    (_master(D0, D0.replace("[focal mass]", "[  ]")), g.MALFORMED_UNIT),
    (in_paragraph(CASE_IP, MASTER).replace("## Paragraph: Summary (IMPRESSION)\n",
                                           "## Paragraph: Summary (IMPRESSION)\n" + CASE_IP + "\n"), g.MALFORMED_UNIT),
    (MASTER.replace("## Paragraph: Measured values (MEASUREMENTS)\n",
                    "## Paragraph: Measured values (MEASUREMENTS)\n" + CASE_IP + "\n"), g.MALFORMED_UNIT),
    (_master(REC, REC.replace("IMAGING", "SURGERY")), g.MALFORMED_UNIT),
    (_master(REC, REC.replace("[findings:", "[history:")), g.MALFORMED_UNIT),
    (_master(REC, REC.split(" WHEN")[0] + "\n"), g.MALFORMED_UNIT),
    (_master(REC, REC.replace("[findings: an indeterminate lesion of the primary organ is reported]",
                              "[findings: abnormal]")), g.NO_SUBJECT),
    (_master(Q, Q.replace('"Is', '"Is') + 'NEGATIVE "No mass."\n'), g.MALFORMED_UNIT),  # unit in the block
    (_master(Q, Q + "No incidental finding of note.\n"), g.PROSE_NEGATIVE),  # block prose is checked
    (_master(CASE_BLOCK, CASE_BLOCK + "\n## Case Deliberation\n"), g.DUPLICATE_CASE_BLOCK),
    (in_paragraph(Q.strip(), MASTER), g.MALFORMED_UNIT),  # QUESTION outside the block
    (in_paragraph('NEGATIVE "No abscess." | origin: case', MASTER), g.MALFORMED_UNIT),  # no TARGETS
    (in_paragraph('NEGATIVE "No abscess." TARGETS [focal mass]', MASTER), g.MALFORMED_UNIT),  # TARGETS, no origin
    (in_paragraph('NEGATIVE "No abscess." WHEN [findings: a focal mass is reported] TARGETS [focal mass] | origin: case',
                  MASTER), g.MALFORMED_UNIT),
    (in_paragraph('NORMAL [organ] "The organ is normal." | origin: case', MASTER), g.MALFORMED_UNIT),
    (in_paragraph('NEGATIVE "No abscess." TARGETS [focal mass] | origin: phase1', MASTER), g.MALFORMED_UNIT),
    (MASTER.replace("## Report-wide\n", "## Report-wide\n" + CASE_NEG + "\n"), g.MALFORMED_UNIT),  # outside a paragraph
])
def test_case_unit_lint(sheet, reason):
    r = g.parse_sheet(sheet, mode="master")
    assert reason in [e.reason for e in r.errors], r.errors
    assert not r.structure.usable


def test_targets_resolve_case_insensitively_against_a_block_after_the_paragraphs():
    r = g.parse_sheet(_master("TARGETS [inflammatory process]", "TARGETS [FOCAL  MASS]"), mode="master")
    assert r.errors == [] and r.structure.usable
    assert [n.targets for n in r.structure.negatives if n.origin == "case"] == ["focal mass"]


def test_unknown_target_points_at_the_negative_line():
    sheet = _master("TARGETS [inflammatory process]", "TARGETS [vascular cause]")
    (e,) = g.parse_sheet(sheet, mode="master").errors
    assert (e.reason, e.detail) == (g.UNKNOWN_TARGET, "vascular cause")
    assert e.text == CASE_NEG.replace("inflammatory process", "vascular cause")


def test_missing_question_points_at_the_case_block_or_line_zero():
    (e,) = g.parse_sheet(_master(Q, ""), mode="master").errors
    assert (e.reason, e.text) == (g.QUESTION_COUNT, "## Case Deliberation")
    (e,) = g.parse_sheet(LEAN, mode="master").errors
    assert (e.reason, e.line, e.text) == (g.QUESTION_COUNT, 0, "")


def test_case_deliberation_is_not_a_free_prose_section():
    assert g.CASE_BLOCK not in g.FREE_PROSE_SECTIONS
    r = g.parse_sheet(_master(Q, Q + "Weigh the differentials when the history is vague.\n"), mode="master")
    assert r.errors == [] and r.structure.usable
    assert ("Weigh the differentials when the history is vague.", g.PROSE_CONDITIONAL) in [
        (w.text, w.reason) for w in r.warnings]


def test_master_mode_is_deterministic():
    a, b = g.parse_sheet(MASTER, mode="master"), g.parse_sheet(MASTER, mode="master")
    assert a.structure.model_dump(exclude={"created_at"}) == b.structure.model_dump(exclude={"created_at"})
    stored = tss.SheetStructure.model_validate(a.structure.model_dump(mode="json"))
    assert stored.differentials == a.structure.differentials and stored.negatives == a.structure.negatives


def test_case_fields_stay_out_of_the_extractor_schema():
    schema = tss.StructureDraft.model_json_schema()["$defs"]
    assert "origin" not in schema["Negative"]["properties"] and "targets" not in schema["Negative"]["properties"]
    assert "covers" not in schema["Paragraph"]["properties"]
    assert "origin" not in schema["IfPresent"]["properties"]
