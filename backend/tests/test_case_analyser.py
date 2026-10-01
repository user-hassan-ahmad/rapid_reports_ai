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


def test_merge_master_places_units_under_a_sub_headed_paragraph():
    sub = TEMPLATE.replace("## Paragraph: Primary organ (FINDINGS)",
                           '## Paragraph: Primary organ (FINDINGS) | header: "Primary organ:"')
    r = ca.parse_and_check(OUTPUT, ca.summarise_template(sub))
    assert r.usable, r.errors
    lines = ca.merge_master(sub, r).splitlines()
    i = lines.index('NEGATIVE "No surrounding collection."')
    assert lines[i + 1] == 'NEGATIVE "No dilatation of the adjacent duct." TARGETS [primary lesion] | origin: case'
    assert [p["name"] for p in ca.summarise_template(sub)["paragraphs"]][:2] == ["Technique", "Primary organ"]


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


def test_prompt_location_never_makes_a_companion_specific_and_differentials_are_diagnoses():
    p = ca.CASE_ANALYSER_SYSTEM_PROMPT
    assert "Naming where a shared companion lies never makes it specific to a branch" in p
    assert "Each DIFFERENTIAL is a diagnosis, never a finding" in p


# ── duplicate and bundled checks by Jev (regex is the fallback) ──

TEMPLATE_J = TEMPLATE.replace(
    'NEGATIVE "No surrounding collection."',
    'NEGATIVE "No surrounding collection."\nNEGATIVE "No free fluid."\n'
    'NORMAL [adjacent duct] "No left ventricular thrombus. The left atrial size is normal."')
HEAD = OUTPUT.split("## Placements")[0] + "## Placements\n"
CASE_NEGS = ["No ascites.", "No left atrial thrombus.", "No focal, suspicious lesion."]
OUT_J = HEAD + "".join(f'PLACE [Remainder] IF_PRESENT [finding {i}] "{t}" (core)\n' for i, t in enumerate(CASE_NEGS))


def jev_stub(same: dict, bundled: dict, calls=None, fail=False, drop=()):
    """P(same) and bundled yes score by negative text (default 0.1); keys in ``drop`` are left unanswered."""
    async def fake(state, qs):
        if calls is not None:
            calls.append((state, dict(qs)))
        if fail:
            raise TimeoutError("jev down")
        out = {}
        for k, q in qs.items():
            if k in drop:
                continue
            text = q["instructions"].split('"')[1] if q["type"] == "choice" else q["instructions"].split(": ", 1)[1]
            if q["type"] == "choice":
                p = same.get(text, 0.1)
                out[k] = {"choice": "same" if p >= 0.5 else "different", "confidence": max(p, 1 - p),
                          "probabilities": {"same": p, "narrower": 0.0, "different": 1 - p}}
            else:
                out[k] = {"noul": bundled.get(text, 0.1)}
        return out
    return fake


def _kept(r):
    return [p.text for p in r.placements]


async def test_jev_duplicate_and_bundled_judgements_replace_the_regex():
    s = ca.summarise_template(TEMPLATE_J)
    regex = ca.parse_and_check(OUT_J, s, TEMPLATE_J)
    assert _kept(regex) == ["No ascites."]  # the regex keeps the synonym and rejects the other two
    calls = []
    r = await ca.parse_and_check_async(OUT_J, s, TEMPLATE_J, jev=jev_stub(
        {"No ascites.": 0.9, "No left atrial thrombus.": 0.1}, {"No focal, suspicious lesion.": 0.2}, calls))
    assert r.usable, r.errors
    assert _kept(r) == ["No left atrial thrombus.", "No focal, suspicious lesion."]
    assert ('PLACE [Remainder] IF_PRESENT [finding 0] "No ascites." (core)', ca.R_DUPLICATE) in r.rejected
    (state, qs), = calls  # one batched call per Phase 1 run
    assert state == ("TEMPLATE STATEMENTS (written on every report from this template):\n"
                     "- No surrounding collection.\n- No free fluid.\n"
                     "- The primary organ is unremarkable.\n"
                     "- No left ventricular thrombus. The left atrial size is normal.\n"
                     "- The remaining structures are unremarkable with no focal lesion.\n- No acute abnormality.")
    assert len(qs) == 2 * len(CASE_NEGS)
    assert qs["dup0"] == ca.q_duplicate("No ascites.") and qs["bun0"] == ca.q_bundled("No ascites.")
    assert qs["dup0"]["type"] == "choice" and set(qs["dup0"]["criteria"]) == {"same", "narrower", "different"}
    assert qs["bun0"]["type"] == "noul" and qs["bun0"]["instructions"].startswith(
        "This negative could be split into two or more shorter negatives")


async def test_bundled_cut_off_is_0_6_and_same_is_0_5():
    s = ca.summarise_template(TEMPLATE_J)
    r = await ca.parse_and_check_async(OUT_J, s, TEMPLATE_J, jev=jev_stub(
        {"No ascites.": 0.49}, {"No ascites.": 0.6, "No left atrial thrombus.": 0.59}))
    assert ('PLACE [Remainder] IF_PRESENT [finding 0] "No ascites." (core)', ca.R_BUNDLED) in r.rejected
    assert "No left atrial thrombus." in _kept(r)
    r = await ca.parse_and_check_async(OUT_J, s, TEMPLATE_J, jev=jev_stub({"No left atrial thrombus.": 0.5}, {}))
    assert ('PLACE [Remainder] IF_PRESENT [finding 1] "No left atrial thrombus." (core)', ca.R_DUPLICATE) in r.rejected


async def test_jev_failure_falls_back_to_the_regex():
    s = ca.summarise_template(TEMPLATE_J)
    regex = ca.parse_and_check(OUT_J, s, TEMPLATE_J)
    r = await ca.parse_and_check_async(OUT_J, s, TEMPLATE_J, jev=jev_stub({}, {}, fail=True))
    assert _kept(r) == _kept(regex) and r.rejected == regex.rejected


async def test_an_unanswered_key_falls_back_to_the_regex_for_that_check_only():
    s = ca.summarise_template(TEMPLATE_J)
    # dup1 unanswered: "No left atrial thrombus." is judged duplicate by the regex; bun2 unanswered: the comma
    # in "No focal, suspicious lesion." is judged bundled by the regex
    r = await ca.parse_and_check_async(OUT_J, s, TEMPLATE_J, jev=jev_stub({}, {}, drop=("dup1", "bun2")))
    reasons = dict(r.rejected)
    assert reasons['PLACE [Remainder] IF_PRESENT [finding 1] "No left atrial thrombus." (core)'] == ca.R_DUPLICATE
    assert reasons['PLACE [Remainder] IF_PRESENT [finding 2] "No focal, suspicious lesion." (core)'] == ca.R_BUNDLED
    assert _kept(r) == ["No ascites."]


async def test_no_case_negatives_no_jev_call():
    calls = []
    r = await ca.parse_and_check_async(HEAD, _summary(), TEMPLATE, jev=jev_stub({}, {}, calls))
    assert r.usable and calls == []


async def test_deliberate_uses_the_jev_checks(monkeypatch):
    from rapid_reports_ai import enhancement_utils as eu, report_reconcile as rc

    async def fake_agent(**kw):
        return type("R", (), {"output": OUT_J})()
    monkeypatch.setattr(eu, "_run_agent_with_model", fake_agent)
    monkeypatch.setattr(rc, "_jev", jev_stub({}, {}))
    r = await ca.deliberate(TEMPLATE_J, None, "CT", "History.")
    assert _kept(r) == CASE_NEGS


# ── Old-format sheets (lean design, arm E): Phase 1 grounded on the sheet's own prose ──────────────

OLD_SHEET = """# Skill Sheet: Example study

## Scan Context
- Modality: single contrast-enhanced acquisition of the region

## Structural Pattern
- Sections included, in order:
  1. FINDINGS (Always present)
  2. CONCLUSION (Always present)

## Per-Section Construction Rules

### [PRIMARY FINDINGS]
- **Mandatory negatives**:
  - "No surrounding collection."
- **Normal pattern**: "The primary organ is unremarkable."

### Remainder Paragraph
- **Normal pattern**: "The remaining structures are unremarkable."

### [CONCLUSION]
- **header**: "Conclusion:"

## Terminology Rules
- Prefer "lesion".

## Negative Finding Rules
- "No free fluid." when the sweep is negative.
"""

OLD_OUT = """## Case Deliberation
QUESTION "Is there a lesion of the primary organ, to gate specialty referral?"
DIFFERENTIAL [primary lesion] TIER triage "focal abnormality of the primary organ" VISIBLE yes
RECOMMEND REFERRAL "Referral to the relevant specialty service is recommended." WHEN [findings: a focal lesion of the primary organ is reported]

## Placements
PLACE [PRIMARY FINDINGS] NEGATIVE "No dilatation of the adjacent duct." TARGETS [primary lesion]
PLACE [Remainder Paragraph] IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core)
PLACE [PRIMARY FINDINGS] IF_PRESENT [focal lesion] "No surrounding collection." (core)
PLACE [CONCLUSION] IF_PRESENT [focal lesion] "No distant spread." (core)
"""


def test_old_sheet_summary_reads_the_sheet_prose():
    s = ca.summarise_old_sheet(OLD_SHEET)
    assert s["errors"] == [] and s["mode"] == "old_sheet"
    roles = {p["name"]: p["role"] for p in s["paragraphs"]}
    assert roles["PRIMARY FINDINGS"] == "findings" and roles["Remainder Paragraph"] == "findings"
    assert roles["CONCLUSION"] != "findings"
    primary = next(p for p in s["paragraphs"] if p["name"] == "PRIMARY FINDINGS")
    assert "No surrounding collection." in primary["negatives"]
    assert "The primary organ is unremarkable." in primary["normals"]
    assert "single contrast-enhanced acquisition" in s["technique"]
    # The sheet's relevant prose is carried as grounding text (sections, routine negatives, terms)
    assert "Mandatory negatives" in s["sheet_text"] and "No free fluid." in s["sheet_text"]
    assert "Prefer \"lesion\"" in s["sheet_text"]
    # report-wide negatives are template claims too (duplicate check), never a placement paragraph
    assert any("No free fluid." in n for p in s["paragraphs"] for n in p["negatives"])


def test_old_sheet_prompt_embeds_the_sheet_text():
    p = ca.build_user_prompt(ca.summarise_old_sheet(OLD_SHEET), "CT", "History.")
    assert "PRIMARY FINDINGS" in p and "No free fluid." in p and "Structural Pattern" in p
    assert "{{" not in p


async def test_deliberate_falls_back_to_the_old_sheet_and_places_by_its_paragraphs(monkeypatch):
    from rapid_reports_ai import enhancement_utils as eu, report_reconcile as rc
    seen = {}

    async def fake_agent(**kw):
        seen["user"] = kw["user_prompt"]
        return type("R", (), {"output": OLD_OUT})()
    monkeypatch.setattr(eu, "_run_agent_with_model", fake_agent)

    async def no_jev(state, qs):
        raise RuntimeError("down")
    monkeypatch.setattr(rc, "_jev", no_jev)
    assert ca.summarise_template(OLD_SHEET)["errors"]  # the grammar parse is unusable
    r = await ca.deliberate(OLD_SHEET, None, "CT", "History.")
    assert r.usable and r.grounding == "old_sheet" and "Structural Pattern" in seen["user"]
    kept = [(p.kind, p.paragraph, p.text) for p in r.placements]
    assert ("NEGATIVE", "PRIMARY FINDINGS", "No dilatation of the adjacent duct.") in kept
    assert ("IF_PRESENT", "Remainder Paragraph", "No regional lymphadenopathy.") in kept
    texts = [t for _, _, t in kept]
    assert "No surrounding collection." not in texts      # duplicates the sheet's own negative
    assert "No distant spread." not in texts              # CONCLUSION is not a findings paragraph
    assert r.recommendations and r.recommendations[0]["tag"] == "REFERRAL"
