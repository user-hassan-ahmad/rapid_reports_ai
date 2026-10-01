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


def test_analyser_prompt_teaches_every_keyword_and_effect():
    p = P.ANALYSER_SYSTEM_PROMPT
    for kw in ("## Report Structure", "## Paragraph:", "## Report-wide", "SECTION ", "NORMAL [", "NEGATIVE \"",
               "FIXED \"", "TERM PREFER", "TERM AVOID", "IF_PRESENT [", "RULE WHEN [", "REPLACE \"", "SUPPRESS \"",
               "SUPPRESS NEGATIVES", "APPEND \"", "USE \"", "INSERT \"", "BEFORE \"", "LIST_MISSING [", "AT TOP",
               "AT END", "SUPPRESS_SECTION", "SUPPRESS_HEADERS", "ORDER FIRST", "ORDER LAST", "(core|contextual)",
               "findings (what is dictated"):
        assert kw in p, kw
    assert "IF [" in p and "carries no conditional wording outside double quotes" in p and "no prose line states a negative" in p and "## Voice" in p  # old syntax named only to forbid it


def test_user_prompt_keeps_production_contract():
    u = P.analyser_user_prompt([{"content": "EXAMPLE TEXT"}], "<scan>", protocol_notes="NOTE")
    assert '"skill_sheet"' in u and '"summary"' in u and '"questions"' in u
    assert "### Example 1\n```\nEXAMPLE TEXT\n```" in u and "NOTE" in u


def test_repair_prompt_numbers_lines_and_errors():
    u = P.repair_user_prompt("a\nb", [{"line": 2, "reason": "malformed RULE", "text": "b"}])
    assert "L1| a\nL2| b" in u and '1. L2: malformed RULE — "b"' in u
    assert P.strip_fences("```markdown\nx\ny\n```") == "x\ny"
    assert P.strip_fences("L1| x\nL2| y") == "x\ny"


SHEET = """# Skill Sheet: <scan>

## Scan Context
Prose.

## Report Structure
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
TERM PREFER "<term>"
RULE WHEN [context: the <part> of the study was not performed] SUPPRESS_SECTION FINDINGS

## Paragraph: <para> (FINDINGS)
Heading: none
NORMAL [<structure>] "Normal <structure>."
NEGATIVE "No <thing>."
RULE WHEN [findings: <named finding> is reported] SUPPRESS NEGATIVES
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["<a>" | "<b>"] AT TOP
IF_PRESENT [<finding>] "No <thing>." (core)

## Paragraph: Conclusion (CONCLUSION)
RULE WHEN [findings: no abnormal finding is reported anywhere in the study] USE "Normal study."
"""


def test_the_prompt_shapes_parse_clean_with_the_grammar_parser():
    structure, errs = lab.parse(SHEET)
    assert errs == [] and structure["usable"]
    kinds = {r["effect"] for r in structure["rules"]}
    assert {"suppress_section", "suppress_paragraph_negatives", "list_missing", "use"} <= kinds


def test_lint_errors_reach_the_repair_prompt():
    bad = SHEET.replace("[findings: <named finding> is reported]", "[findings: abnormal]")
    bad += "Opening: written first when abnormal\n"
    _, errs = lab.parse(bad)
    reasons = {e["reason"] for e in errs}
    assert {"statement without subject", "conditional phrase in prose"} <= reasons
    u = P.repair_user_prompt(bad, errs)
    assert all(f"L{e['line']}: {e['reason']}" in u for e in errs)


def test_split_reports_dedupes_regenerations_and_holds_out_newest():
    rows = [{"created_at": f"2026-01-0{i}", "findings": f, "report_id": i}
            for i, f in enumerate(["a", "a", "b", "c", "d", "e", "f", "g"], 1)]
    ex, held = lab.split_reports(rows)
    assert [r["report_id"] for r in held] == [7, 8] and [r["report_id"] for r in ex] == [2, 3, 4, 5, 6]
    ex, held = lab.split_reports(rows[:4])
    assert held == [] and len(ex) == 3
