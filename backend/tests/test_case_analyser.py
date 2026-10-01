"""Phase 1 case analyser (lab): prompt is case-agnostic; code checks fail closed; master merge."""
from __future__ import annotations

import re

from rapid_reports_ai import case_analyser as ca

TEMPLATE = """# Template Sheet: Example study

## Scan Context
Modality and single acquisition as written in the examples.

## Report Structure
SECTION TECHNIQUE | header: none | role: technique
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION IMPRESSION | header: "Impression" | role: impression

## Paragraph: Technique (TECHNIQUE)
FIXED "Single acquisition of the region."

## Paragraph: Primary organ (FINDINGS)
COVERS ["primary organ" | "adjacent duct"]
NORMAL [primary organ] "The primary organ is unremarkable."
NEGATIVE "No surrounding collection."

## Paragraph: Remainder (FINDINGS)
COVERS ["remaining structures"]
NORMAL [remaining structures] "The remaining structures are unremarkable with no focal lesion."

## Paragraph: Summary (IMPRESSION)
NORMAL [study] "No acute abnormality."
"""

OUTPUT = """## Case Deliberation
QUESTION "Is there a lesion of the primary organ, to gate specialty referral?"
DIFFERENTIAL [primary lesion] TIER triage "focal abnormality of the primary organ" VISIBLE yes
DIFFERENTIAL [hidden cause] TIER aetiology "feature only another phase shows" VISIBLE no
DIFFERENTIAL [systemic cause] TIER aetiology "requires laboratory correlation" VISIBLE silent
DIFFERENTIAL [untagged] TIER triage "something"
RECOMMEND REFERRAL "Referral to the relevant specialty service is recommended." WHEN [findings: a focal lesion of the primary organ is reported]
RECOMMEND TREATMENT "Start therapy." WHEN [findings: a focal lesion of the primary organ is reported]
RECOMMEND IMAGING "Further imaging is suggested." WHEN [findings: abnormal]

## Placements
PLACE [Primary organ] NEGATIVE "No dilatation of the adjacent duct." TARGETS [primary lesion]
PLACE [primary organ] NEGATIVE "No surrounding collection." TARGETS [primary lesion]
PLACE [Primary organ] NEGATIVE "No focal lesion." TARGETS [primary lesion]
PLACE [Primary organ] NEGATIVE "No mass or stricture of the duct." TARGETS [primary lesion]
PLACE [Primary organ] NEGATIVE "No wall thickening of the duct." TARGETS [nonexistent]
PLACE [Primary organ] NEGATIVE "No enhancing feature." TARGETS [hidden cause]
PLACE [Missing paragraph] NEGATIVE "No calcification of the duct." TARGETS [primary lesion]
PLACE [Summary] NEGATIVE "No calcification of the duct." TARGETS [primary lesion]
PLACE [Remainder] IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core)
PLACE [Remainder] IF_PRESENT [focal lesion] "No regional lymphadenopathy." (contextual)
"""


def _summary():
    return ca.summarise_template(TEMPLATE)


def test_summary_reads_lean_template():
    s = _summary()
    roles = {p["name"]: p["role"] for p in s["paragraphs"]}
    assert roles == {"Technique": "technique", "Primary organ": "findings", "Remainder": "findings",
                     "Summary": "impression"}
    primary = next(p for p in s["paragraphs"] if p["name"] == "Primary organ")
    assert primary["covers"] == ["primary organ", "adjacent duct"]
    assert primary["negatives"] == ["No surrounding collection."]
    assert "Single acquisition of the region." in s["technique"]
    assert "Modality and single acquisition" in s["technique"]
    assert s["errors"] == []


def test_template_without_covers_is_not_deliberated():
    s = ca.summarise_template(TEMPLATE.replace('COVERS ["remaining structures"]\n', ""))
    assert s["errors"] and "COVERS" in s["errors"][0]


def test_master_sheet_parses_in_master_mode():
    from rapid_reports_ai import template_sheet_grammar as g
    r = ca.parse_and_check(OUTPUT, _summary(), TEMPLATE)
    assert r.usable, r.errors
    parsed = g.parse_sheet(ca.merge_master(TEMPLATE, r), mode="master")
    assert parsed.errors == [] and parsed.structure.usable
    assert parsed.structure.question.startswith("Is there a lesion")
    assert [d.name for d in parsed.structure.differentials] == ["primary lesion", "hidden cause", "systemic cause"]
    case_negs = [n for n in parsed.structure.negatives if n.origin == "case"]
    assert [(n.text, n.targets) for n in case_negs] == [("No dilatation of the adjacent duct.", "primary lesion")]


def test_checks_fail_closed_per_unit():
    r = ca.parse_and_check(OUTPUT, _summary())
    assert r.usable
    reasons = {line: why for line, why in r.rejected}
    assert [d["name"] for d in r.differentials] == ["primary lesion", "hidden cause", "systemic cause"]
    assert any(why == ca.R_NO_VISIBLE for why in reasons.values())
    assert any(why == ca.R_BAD_TAG for why in reasons.values())
    assert any(why == ca.R_NO_SUBJECT for why in reasons.values())
    assert [x["tag"] for x in r.recommendations] == ["REFERRAL"]
    texts = [(p.paragraph, p.text) for p in r.placements]
    assert texts == [("Primary organ", "No dilatation of the adjacent duct."),
                     ("Remainder", "No regional lymphadenopathy.")]
    why = list(reasons.values())
    assert why.count(ca.R_DUPLICATE) == 2  # restated template negative; split-out template normal
    for reason in (ca.R_BUNDLED, ca.R_UNKNOWN_DIFF, ca.R_NOT_VISIBLE, ca.R_NO_PARAGRAPH, ca.R_NOT_FINDINGS,
                   ca.R_DUPLICATE_CASE):
        assert reason in why, reason


def test_if_present_negative_may_follow_different_findings():
    out = OUTPUT + ('PLACE [Remainder] IF_PRESENT [second finding] "No regional lymphadenopathy." (core)\n'
                    'PLACE [Remainder] IF_PRESENT [third finding] "No dilatation of the adjacent duct." (core)\n')
    r = ca.parse_and_check(out, _summary(), TEMPLATE)
    assert [(p.key, p.text) for p in r.placements if p.kind == "IF_PRESENT"] == [
        ("focal lesion", "No regional lymphadenopathy."), ("second finding", "No regional lymphadenopathy.")]
    assert ('PLACE [Remainder] IF_PRESENT [third finding] "No dilatation of the adjacent duct." (core)',
            ca.R_DUPLICATE_CASE) in r.rejected  # already a targeted negative
    assert r.usable, r.errors


def test_unusable_without_question_or_differentials():
    r = ca.parse_and_check("## Placements\nPLACE [Remainder] IF_PRESENT [x y] \"No thing.\" (core)\n", _summary())
    assert not r.usable
    assert set(r.errors) == {"no QUESTION", "no DIFFERENTIAL"}
    assert r.placements == []
    assert ca.merge_master(TEMPLATE, r) == TEMPLATE


def test_merge_master_inserts_after_paragraph_units_and_appends_block():
    r = ca.parse_and_check(OUTPUT, _summary())
    master = ca.merge_master(TEMPLATE, r)
    lines = master.splitlines()
    i = lines.index('NEGATIVE "No surrounding collection."')
    assert lines[i + 1] == 'NEGATIVE "No dilatation of the adjacent duct." TARGETS [primary lesion] | origin: case'
    j = lines.index('NORMAL [remaining structures] "The remaining structures are unremarkable with no focal lesion."')
    assert lines[j + 1] == 'IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core) | origin: case'
    assert lines[j + 2] == ""
    assert lines[j + 3] == "## Paragraph: Summary (IMPRESSION)"
    tail = master[master.index("## Case Deliberation"):].splitlines()
    assert tail[1].startswith('QUESTION "')
    assert sum(1 for x in tail if x.startswith("DIFFERENTIAL")) == 3
    assert tail[-1].startswith('RECOMMEND REFERRAL "')
    # template text is preserved verbatim
    assert [x for x in lines if "origin: case" not in x][: len(TEMPLATE.splitlines())] == TEMPLATE.splitlines()


# Case-agnostic prompt (feedback_case_agnostic_prompts): structural placeholders only, no clinical stems.
_CLINICAL_STEMS = (
    "append", "fractur", "coronar", "haemorrh", "hemorrh", "embol", "pancrea", "aneurys", "stenos", "tumour",
    "cancer", "carcinom", "pneumothor", "infarct", "ligament", "menisc", "stroke", "nodul", "lymph", "thromb",
    "abscess", "obstruct", "perforat", "calcul", "cardi", "hepat", "renal", "kidney", "lung", "brain", "spine",
    "spinal", "aort", "bowel", "liver", "bone", "joint", "knee", "chest", "abdom", "pelvi", "trauma", "oncolog",
    "sarcoma", "neuro", "vascular", "biops", "gadolin", "ultrasound", "fleischner", "rads", "recist", "bosniak",
)
_CLINICAL_WORDS = ("ct", "mri", "pet", "tnm", "aspects", "cta")


def test_prompt_is_case_agnostic():
    text = (ca.CASE_ANALYSER_SYSTEM_PROMPT + ca.CASE_ANALYSER_USER_TEMPLATE).lower()
    hits = [s for s in _CLINICAL_STEMS if re.search(r"\b" + re.escape(s), text)]
    hits += [w for w in _CLINICAL_WORDS if re.search(rf"\b{w}\b", text)]
    assert hits == []


def test_prompt_carries_the_rules():
    p = ca.CASE_ANALYSER_SYSTEM_PROMPT
    for must in ("VISIBLE yes", "One finding per negative", "Never duplicate the template", "UK NHS",
                 "Clinical history is never emitted", "IMAGING", "REFERRAL", "MDT", "TISSUE", "CORRELATION",
                 "COVERS", "If present"):
        assert must in p, must


def test_prompt_step1c_rules():
    p = ca.CASE_ANALYSER_SYSTEM_PROMPT
    assert "One targeted negative for every differential you listed with VISIBLE yes" in p
    assert "Editorial restraint applies to duplication only" in p
    assert "plausibly reports" in p
    assert "names the service or the test, and the urgency" in p and '"for consideration of …"' in p
    assert 'never joins findings with "or"' in p
    assert "recommend that named test" in p
    assert "Six well-targeted" in p and "Default toward omission" not in p


def test_one_targeted_negative_per_differential_first_kept():
    out = OUTPUT + 'PLACE [Remainder] NEGATIVE "No wall thickening of the remaining structures." TARGETS [primary lesion]\n'
    r = ca.parse_and_check(out, _summary(), TEMPLATE)
    assert [(p.text, p.key) for p in r.placements if p.kind == "NEGATIVE"] == [
        ("No dilatation of the adjacent duct.", "primary lesion")]
    assert ('PLACE [Remainder] NEGATIVE "No wall thickening of the remaining structures." TARGETS [primary lesion]',
            ca.R_SECOND_TARGET) in r.rejected
    assert r.usable, r.errors


def test_prompt_asks_for_one_branch_specific_negative_never_a_shared_companion():
    p = ca.CASE_ANALYSER_SYSTEM_PROMPT
    assert "never more than one" in p and "specific to its branch" in p
    assert "A companion many branches share is never a targeted negative" in p
    assert "repeating the shared wording, even when the findings belong to the same differential" not in p
