from rapid_reports_ai import template_sheet_lab_prompts as P
from rapid_reports_ai.scripts import template_sheet_lab as lab

CLINICAL = ("appendic", "pneumoperitoneum", "liver", "aort", "coronary", "cardiac", "lung", "pleura", "pericard",
            "effusion", "tendon", "kidney", "renal", "bowel", "lymph", "fracture", "thromb", "stenosis", "lesion",
            "nodule", "valve", "ventric", "atri", "spine", "brain", "vessel", "artery", "bone", "osseous", "tumour",
            "cancer", "contrast", "gadolinium", "tesla", "agatston", "ejection", "lvef")


def test_prompts_are_case_agnostic():
    for p in (P.ANALYSER_SYSTEM_PROMPT, P.REPAIR_SYSTEM_PROMPT, P.analyser_user_prompt([], "<scan>")):
        for clinical in CLINICAL:
            assert clinical not in p.lower(), clinical


def test_analyser_prompt_teaches_the_lean_grammar():
    p = P.ANALYSER_SYSTEM_PROMPT
    for kw in ("## Report Structure", "## Paragraph:", "## Report-wide", "SECTION ", "COVERS [", "NORMAL [",
               'NEGATIVE "', 'FIXED "', "TERM PREFER", "TERM AVOID", "LIST_MISSING [", "AT TOP", "AT END",
               "RULE WHEN [context:", 'REPLACE "', 'SUPPRESS "', 'USE "', "SUPPRESS_SECTION", "SUPPRESS_HEADERS",
               "Abnormal pattern:", "Interpretive phrasing:", "Recommendation phrasing:", "(optional)", "## Voice",
               "## Impression Construction", "prose states no absence in any form", "never a WHEN"):
        assert kw in p, kw
    # case-dependent units are named only to forbid them; the v1 convention text is gone
    assert "NOT in this sheet" in p and "handled automatically" not in p
    for gone in ("IF_PRESENT [", "(core|contextual)", "ORDER FIRST", 'INSERT "<text>" BEFORE'):
        assert gone not in p, gone


def test_user_prompt_returns_the_sheet_between_delimiters():
    u = P.analyser_user_prompt([{"content": "EXAMPLE TEXT"}], "<scan>", protocol_notes="NOTE")
    assert P.SHEET_OPEN in u and P.SHEET_CLOSE in u and '"summary"' in u and '"questions"' in u
    assert "### Example 1\n```\nEXAMPLE TEXT\n```" in u and "NOTE" in u


def test_split_answer_keeps_the_sheet_when_the_json_breaks():
    ok = (P.SHEET_OPEN + '\n# Skill Sheet: x\nNEGATIVE "No <thing>."\n' + P.SHEET_CLOSE
          + '\n{"summary": {"a": 1}, "questions": []}')
    d = P.split_answer(ok)
    assert d["skill_sheet"] == '# Skill Sheet: x\nNEGATIVE "No <thing>."'
    assert d["summary"] == {"a": 1} and not d["json_error"]
    d = P.split_answer(ok.replace('"questions": []', '"questions": [ {"q": 1} {"q": 2} ]'))
    assert d["skill_sheet"].startswith("# Skill Sheet: x") and d["json_error"]


def test_repair_prompt_numbers_lines_and_errors():
    u = P.repair_user_prompt("a\nb", [{"line": 2, "reason": "malformed RULE", "text": "b"}])
    assert "L1| a\nL2| b" in u and '1. L2: malformed RULE — "b"' in u
    assert P.strip_fences("```markdown\nx\ny\n```") == "x\ny"
    assert P.strip_fences("L1| x\nL2| y") == "x\ny"
    assert P.strip_fences(P.SHEET_OPEN + "\nx\n" + P.SHEET_CLOSE) == "x"


SHEET = """# Skill Sheet: <scan>

## Scan Context
Prose.

## Report Structure
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
TERM PREFER "<term>"
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["<a>" | "<b>"] AT TOP | section: FINDINGS
RULE WHEN [context: the <part> of the study was not performed] SUPPRESS_SECTION FINDINGS | section: FINDINGS

## Paragraph: <para> (FINDINGS)
COVERS ["<structure>" | "<other structure>"]
Opening: the <structure> first.
Order: <structure>; <other structure> (optional).
Abnormal pattern: "There is a {size} <finding> of the <structure>."
Interpretive phrasing: "likely <cause>"
NORMAL [<structure>] "Normal <structure>."
NEGATIVE "No <thing>."
RULE WHEN [context: prior <modality> imaging is available for comparison] REPLACE "Normal <structure>." WITH "Stable <structure>."

## Paragraph: Conclusion (CONCLUSION)
Opening: numbered points.
"""


def test_a_lean_sheet_in_the_prompt_shapes_parses_usable():
    structure, errs = lab.parse(SHEET)
    assert errs == [] and structure["usable"]
    assert {r["effect"] for r in structure["rules"]} == {"suppress_section", "list_missing", "replace"}
    assert structure["paragraphs"][0]["covers"] == ["<structure>", "<other structure>"]
    v = lab.voice_stats(SHEET, structure)
    assert v["paragraphs"]["<para>"] == {"covers": 2, "quotes": 2, "exemplars": 2}


def test_case_units_are_lint_errors_that_reach_the_repair_prompt():
    bad = SHEET.replace('NEGATIVE "No <thing>."', 'NEGATIVE "No <thing>."\nIF_PRESENT [<finding>] "No <x>." (core)\n'
                        'RULE WHEN [findings: <named finding> is reported] APPEND "<clause> here."')
    _, errs = lab.parse(bad)
    assert len(errs) == 2 and {e["reason"] for e in errs} == {"unit not allowed in a template sheet"}
    u = P.repair_user_prompt(bad, errs)
    assert all(f"L{e['line']}: {e['reason']}" in u for e in errs)


def test_split_reports_dedupes_regenerations_and_holds_out_newest():
    rows = [{"created_at": f"2026-01-0{i}", "findings": f, "report_id": i}
            for i, f in enumerate(["a", "a", "b", "c", "d", "e", "f", "g"], 1)]
    ex, held = lab.split_reports(rows)
    assert [r["report_id"] for r in held] == [7, 8] and [r["report_id"] for r in ex] == [2, 3, 4, 5, 6]
    ex, held = lab.split_reports(rows[:4])
    assert held == [] and len(ex) == 3


def test_lean_prompt_tightening_rules():
    p = P.ANALYSER_SYSTEM_PROMPT
    assert "Exactly ONE sentence per NORMAL line" in p
    assert "Anatomical structures only: never a finding" in p and "never in a paragraph of any other section" in p
    assert "found at least twice" in p and "At most six TERM lines" in p
    assert "an item carries no condition or qualifier" in p
    assert "only when an example report actually omits that section" in p
    assert "never a negative sentence" in p
    # no instruction tells the analyser to quote a finding-specific negative as an exemplar
    assert "quote it as an exemplar in prose instead" not in p
    r = P.REPAIR_SYSTEM_PROMPT
    assert "An IF_PRESENT line is deleted" in r and "COVERS line outside a findings-role section is deleted" in r
