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


def test_impression_exemplars_keep_their_line_breaks():
    from rapid_reports_ai import template_sheet_lab_prompts as P
    text = " ".join(str(v) for k, v in vars(P).items() if isinstance(v, str))
    assert "keeping its line breaks (each numbered or separate item on its own line" in text


def test_grammar_asks_one_named_structure_per_normal_and_slotted_examples():
    from rapid_reports_ai import template_sheet_lab_prompts as P

    assert "(or group)" not in P.GRAMMAR
    assert "names its structure in its own words" in P.GRAMMAR
    assert "never a specific value, code, grade or time window" in P.ANALYSER_SYSTEM_PROMPT
    assert "never contains a {slot}" in P.GRAMMAR
    for prompt in (P.ANALYSER_SYSTEM_PROMPT, P.REPAIR_SYSTEM_PROMPT, P.TEMPLATE_SHEET_CONVERT_PROMPT):
        assert "names its structure in its own words" in prompt


def test_convert_prompt_exemplars_are_slotted_and_diagnosis_slotted():
    from rapid_reports_ai import template_sheet_lab_prompts as P

    t = P.TEMPLATE_SHEET_CONVERT_PROMPT
    assert "every specific value, code, grade or time window becomes a {slot}" in t
    assert "any diagnosis is dropped from the quote" not in t
    assert "the diagnosis itself becomes a {diagnosis} slot" in t
    assert "which most likely represents {diagnosis}" in t
    assert "is kept, word for word" not in t


def test_analyser_exemplars_keep_interpretive_wording_with_diagnosis_slotted():
    from rapid_reports_ai import template_sheet_lab_prompts as P

    a = P.ANALYSER_SYSTEM_PROMPT
    assert "never a diagnosis" not in a
    assert "keep the radiologist's interpretive wording" in a
    assert "the diagnosis itself goes in a {diagnosis} slot" in a
    assert "which most likely represents {diagnosis}" in a


def test_labelled_openings_reach_the_analyser_repair_and_convert_prompts():
    for prompt in (P.ANALYSER_SYSTEM_PROMPT, P.REPAIR_SYSTEM_PROMPT, P.TEMPLATE_SHEET_CONVERT_PROMPT):
        assert 'Opening (normal): "<opening words>"' in prompt and "LABELLED OPENINGS" in prompt
        assert 'Never write the variation as a "When ..." or "If ..." prose sentence' in prompt
        assert "it is a context RULE" in prompt
    for prompt in (P.ANALYSER_SYSTEM_PROMPT, P.TEMPLATE_SHEET_CONVERT_PROMPT):  # the layout
        assert 'one labelled line per state instead: Opening (normal): "..."' in prompt


def test_the_labelled_opening_shape_in_the_prompt_parses_clean():
    from rapid_reports_ai import template_sheet_grammar as tsg
    sheet = ('## Report Structure\nSECTION FINDINGS | header: "Findings:" | role: findings\n'
             'SECTION IMPRESSION | header: "Impression:" | role: impression\n\n## Paragraph: P (FINDINGS)\n'
             'COVERS ["<structure>"]\nOpening (normal): "<opening words>"\nOpening (abnormal): "<opening words>"\n')
    r = tsg.parse_sheet(sheet, mode="template")
    assert r.errors == [] and r.warnings == [] and r.structure.usable


# ── Task 28: the writer's next prompts (built here, wired into write_sheet only after the writer lab) ──────────

def test_the_older_analyser_prompts_stay_for_the_sheet_lab_script():
    # write_sheet sends WRITER_SYSTEM_PROMPT / writer_user_prompt; the older pair is kept for template_sheet_lab
    assert "so it can be raised as a question" in P.ANALYSER_SYSTEM_PROMPT
    assert "the measured part goes in a FIXED field line" not in P.ANALYSER_SYSTEM_PROMPT + P.GRAMMAR
    assert '"questions"' in P.analyser_user_prompt([{"content": "X"}], "<scan>")


def test_the_decided_prompt_replaces_the_guessing_and_stays_case_agnostic():
    p = P.analyser_system_prompt(True)
    assert P.analyser_system_prompt(False) == P.WRITER_SYSTEM_PROMPT
    assert P.DECIDED_HEADING in p and "Use it when an example shows a list of values not provided" not in p
    assert "write exactly the lines given there" in p and "LIST_MISSING [" in p
    for prompt in (p, P.WRITER_SYSTEM_PROMPT, P.writer_user_prompt([], "<scan>")):
        for clinical in CLINICAL:
            assert clinical not in prompt.lower(), clinical


def test_the_writer_asks_no_questions_and_places_a_normals_measured_part():
    u = P.writer_user_prompt([{"content": "X"}], "<scan>")
    assert '"questions"' not in u and 'exactly one key, "summary"' in u and "questions:" not in u
    assert P.SHEET_OPEN in u and P.SHEET_CLOSE in u and "### Example 1\n```\nX\n```" in u
    assert "so it can be raised as a question" not in P.WRITER_SYSTEM_PROMPT
    assert "[NEEDS CLARIFICATION]." in P.WRITER_SYSTEM_PROMPT
    assert "the measured part goes in a FIXED field line" in P.WRITER_SYSTEM_PROMPT
    assert P.WRITER_SYSTEM_PROMPT.count("A NORMAL or NEGATIVE line is the exception: it never holds a slot.") == 1


def _ledger():
    from rapid_reports_ai import template_decisions as td
    led, _ = td.set_decision([], "value", "Value A", {"need": "every"}, source="creation")
    led, _ = td.set_decision(led, "value", "Value B", {"need": "relevant"}, source="creation")
    led, _ = td.set_decision(led, "concept", "comparison", {"use": True, "default": "No previous imaging.",
                                                            "when_met": "Compared with the {study} of {date}."},
                             source="creation")
    led, _ = td.set_decision(led, "concept", "limitation", {"use": False}, source="creation")
    return led


def test_the_user_prompt_carries_the_decided_lines():
    u = P.writer_user_prompt([{"content": "X"}], "<scan>", decisions=_ledger())
    assert P.DECIDED_HEADING in u
    assert 'RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["Value A"] AT TOP' in u
    assert "Not required in every report (never list them): Value B." in u
    assert ('FIXED "No previous imaging."\nRULE WHEN [context: the dictation names a previous imaging study for '
            'comparison] REPLACE "No previous imaging." WITH "Compared with the {study} of {date}."') in u
    assert "Technical limitation: not used." in u
    assert P.decided_block([]) == "" and P.SHEET_OPEN in u
    assert u.index(P.DECIDED_HEADING) < u.index("### Example 1")
    assert P.DECIDED_HEADING not in P.writer_user_prompt([{"content": "X"}], "<scan>")


def test_the_decided_block_follows_the_current_card_shapes():
    """Contrast has two conditions (a default-only wording is FIXED + SUPPRESS); "whichever is dictated" writes no
    line; a ledger with only non-required values asks for no LIST_MISSING line; the lines are the ones apply_ledger
    writes."""
    from rapid_reports_ai import template_decisions as td
    from rapid_reports_ai import template_ledger_apply as tla
    from rapid_reports_ai import template_rules_cards as trc
    given = td.CONCEPTS["contrast"].states["given"]
    usual = trc.usual_card("contrast", {"given": "", "not_given": "No agent was given."}, [])
    not_given = next(c["choice"] for c in usual["choices"] if c["id"] == "usual:not_given")
    dictated = next(c["choice"] for c in trc.disagree_card("sequences", [{"text": "All parts done.", "reports": [1]}],
                                                           "", "default", [], "")["choices"]
                    if c["id"] == "dictated")
    led, errors = td.ledger_from_changes([
        {"kind": "value", "key": "Value B", "choice": {"need": "not_needed"}},
        {"kind": "concept", "key": "contrast", "choice": not_given},
        {"kind": "concept", "key": "sequences", "choice": dictated, "source": "default"}])
    assert errors == []
    block = P.decided_block(led)
    assert "Required values: none. Write no LIST_MISSING line." in block
    assert f'FIXED "No agent was given."\nRULE WHEN [context: {given}] SUPPRESS "No agent was given."' in block
    assert "Parts of the study not performed: whichever is dictated. Write no line and no rule about it." in block
    assert tla.render_concept("contrast", led[1]["choice"]) == ['FIXED "No agent was given."',
                                                               f'RULE WHEN [context: {given}] SUPPRESS "No agent was given."']
    assert tla.render_concept("sequences", led[2]["choice"]) == []
