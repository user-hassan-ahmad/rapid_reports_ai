"""Conversion plumbing (plan G6, lab): prompt assembly, delimiter parsing, repair loop, snap-to-source and the
code half of the faithfulness check. No model calls: the model call is injected."""
import asyncio

from rapid_reports_ai import template_sheet_lab_prompts as P
from rapid_reports_ai.scripts import template_sheet_convert as C

from tests.test_template_sheet_lab_prompts import CLINICAL, SHEET

OLD = """# Skill Sheet: <scan>

## Structural Pattern
- FINDINGS: `header: "FINDINGS"`
- CONCLUSION: `header: "Conclusion:"`

## Per-Section Construction Rules

### <para>
- **Mandatory negatives**:
  - "No <thing>."
- **Normal pattern**: "Normal <structure>."
- **Abnormal pattern**: "There is a {size} <finding> of the <structure>."
"""


# ------------------------------------------------------------------------------------------- prompt

def test_convert_prompt_is_case_agnostic_and_uses_the_lean_grammar():
    p = P.TEMPLATE_SHEET_CONVERT_PROMPT
    for clinical in CLINICAL:
        assert clinical not in p.lower(), clinical
    assert P.GRAMMAR in p and P.SHEET_LAYOUT in p
    assert P.SHEET_OPEN in p and P.SHEET_CLOSE in p and '"accounting"' in p and '"dropped"' in p
    for rule in ("They never add a unit", "Never invent", "Never drop a section", "never a FIXED line of its own",
                 "is such a context RULE", "every exemplar the old sheet gives is kept", "letter for letter"):
        assert rule in p, rule


def test_convert_user_prompt_carries_sheet_reports_and_coverage():
    u = P.convert_user_prompt(OLD, "<scan>", [{"content": "REPORT ONE"}, {"label": "Edited", "content": "TWO"}],
                              ["A", "B"])
    assert "scan type: **<scan>**" in u
    assert "## OLD SHEET\n```\n" + OLD.strip() + "\n```" in u
    assert "### Report 1\n```\nREPORT ONE\n```" in u and "### Edited\n```\nTWO\n```" in u
    assert "## COVERAGE LIST\nA | B" in u
    bare = P.convert_user_prompt(OLD, "<scan>", [], None)
    assert "## REPORTS" not in bare and "## COVERAGE LIST" not in bare


# ------------------------------------------------------------------------------------------ parsing

def test_split_conversion_keeps_the_sheet_when_the_json_breaks():
    ok = P.SHEET_OPEN + "\n" + SHEET + "\n" + P.SHEET_CLOSE + '\n{"accounting": [{"old": "a", "new": "b"}], "dropped": []}'
    d = P.split_conversion(ok)
    assert d["skill_sheet"] == SHEET.strip() and d["accounting"] == [{"old": "a", "new": "b"}] and not d["json_error"]
    broken = P.split_conversion(ok.replace('"dropped": []', '"dropped": [ {"x": 1} {"y": 2} ]'))
    assert broken["skill_sheet"] == SHEET.strip() and broken["json_error"]
    no_close = P.split_conversion(P.SHEET_OPEN + "\n# Skill Sheet: x\nbody\n{\n\"accounting\": [], \"dropped\": []}")
    assert no_close["skill_sheet"] == "# Skill Sheet: x\nbody" and no_close["accounting"] == []
    assert P.split_conversion(P.SHEET_OPEN + "\nx\n" + P.SHEET_CLOSE)["json_error"] == "no JSON after the sheet"
    try:
        P.split_conversion("no delimiters")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ---------------------------------------------------------------------------------------- repair loop

def _fake(answers):
    calls = []

    async def call(system, user, settings):
        calls.append((system, user, settings))
        return answers[len(calls) - 1]
    return call, calls


def _wrap(sheet):
    return P.SHEET_OPEN + "\n" + sheet + "\n" + P.SHEET_CLOSE + '\n{"accounting": [], "dropped": []}'


def test_convert_clean_sheet_makes_one_call():
    call, calls = _fake([_wrap(SHEET)])
    rec = asyncio.run(C.convert(OLD, "<scan>", [{"final_content": "R"}], ["A"], call=call))
    assert len(calls) == 1 and calls[0][0] == P.TEMPLATE_SHEET_CONVERT_PROMPT and calls[0][2] == P.ANALYSER_SETTINGS
    assert "R" in calls[0][1] and rec["usable"] and rec["first_errors"] == [] and "repair_s" not in rec["lat"]


def test_convert_runs_one_repair_on_lint_errors():
    bad = SHEET.replace('NEGATIVE "No <thing>."', 'NEGATIVE "No <thing>."\nIF_PRESENT [<finding>] "No <x>." (core)')
    call, calls = _fake([_wrap(bad), "```markdown\n" + SHEET + "\n```"])
    rec = asyncio.run(C.convert(OLD, "<scan>", [], None, call=call))
    assert len(calls) == 2 and calls[1][0] == P.REPAIR_SYSTEM_PROMPT and calls[1][2] == P.REPAIR_SETTINGS
    assert "IF_PRESENT" in calls[1][1] and "LINT ERRORS" in calls[1][1]
    assert rec["first_errors"] and rec["repair_errors"] == [] and rec["usable"] and rec["sheet"].strip() == SHEET.strip()


def test_convert_still_failing_after_repair_is_not_usable():
    bad = SHEET.replace('NEGATIVE "No <thing>."', 'IF_PRESENT [<finding>] "No <x>." (core)')
    call, calls = _fake([_wrap(bad), bad])
    rec = asyncio.run(C.convert(OLD, "<scan>", [], None, call=call))
    assert len(calls) == 2 and not rec["usable"] and rec["errors"]


# ------------------------------------------------------------------------------- snap + faithfulness

def test_snap_to_source_repairs_a_copy_typo_on_unit_lines_only():
    sheet = SHEET.replace('NEGATIVE "No <thing>."', 'NEGATIVE "No suspicious <things> or <other> lesons."\n'
                                                   'Abnormal pattern: "No suspicious <things> or <other> lesons."')
    out, snaps = C.snap_to_source(sheet, ['- "No suspicious <things> or <other> lesions."'])
    assert 'NEGATIVE "No suspicious <things> or <other> lesions."' in out
    assert 'Abnormal pattern: "No suspicious <things> or <other> lesons."' in out  # prose untouched
    assert len(snaps) == 1 and snaps[0]["to"] == "No suspicious <things> or <other> lesions."
    # a genuinely different sentence is left alone
    out2, snaps2 = C.snap_to_source(sheet, ['"Something else entirely written here."'])
    assert snaps2 == [] and out2 == sheet


def test_faithfulness_reports_kept_missing_and_additions():
    structure, errs, _ = C.parse(SHEET)
    assert errs == []
    fx = C.faithfulness(OLD, SHEET, [{"final_content": "Stable <structure>."}], structure)
    assert fx["kept"]["negative"]["missing"] == [] and fx["kept"]["normal"]["missing"] == []
    assert fx["headings_missing"] == ["Structural Pattern", "Per-Section Construction Rules"]
    # "<clause> ..." style quotes with no source show up as additions; sourced ones do not
    assert "Stable <structure>." not in fx["additions"] and "likely <cause>" in fx["additions"]
    lost = C.faithfulness(OLD, SHEET.replace('NEGATIVE "No <thing>."', ""), [], structure)
    assert lost["kept"]["negative"]["missing"] == ["No <thing>."]


def test_split_evidence_holds_out_newest_real_dictations():
    reps = [{"report_id": i, "findings": "x" * (200 if i != 1 else 5)} for i in range(1, 8)]
    ev, held, leak = C.split_evidence(reps)
    assert [r["report_id"] for r in held] == [2, 3] and [r["report_id"] for r in ev] == [1, 4, 5, 6, 7] and not leak
    ev, held, leak = C.split_evidence(reps[:3])
    assert [r["report_id"] for r in held] == [2, 3] and len(ev) == 3 and leak


def test_old_units_classifies_by_heading_and_bullet():
    k = C.old_units(OLD)
    assert k["negative"] == ["No <thing>."] and k["normal"] == ["Normal <structure>."]
    assert "There is a {size} <finding> of the <structure>." in k["other"]
