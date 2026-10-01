"""Template brief (spec 2026-09-30-template-pipeline-mirror §3 + grammar addendum effects table): one test per
decision row and per grammar effect, in-place rendering, state routing, If-present off. Synthetic sheet only."""
from __future__ import annotations

import ast
import pathlib

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import template_brief as tb
from rapid_reports_ai import template_sheet_grammar as g

SHEET = """# Synthetic CT Template

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history" | role: history
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION MEASUREMENTS | header: "Measurements" | role: other
SECTION IMPRESSION | header: "Impression" | role: impression

## Voice
Short declarative sentences. British spelling.
TERM PREFER "unremarkable"

## Paragraph: Primary organ (FINDINGS)
Size first, then contour, then the adjacent fat.
NORMAL [primary organ] "The primary organ is normal in size and contour."
- NEGATIVE "No focal lesion."
  - NEGATIVE "No surrounding collection." WHEN [findings: an inflammatory process of the primary organ is reported]
RULE WHEN [findings: a focal lesion of the primary organ is reported] REPLACE "No focal lesion." WITH "A {size} lesion is present."
RULE WHEN [history: prior surgery to the primary organ is stated] APPEND "Post-surgical appearances are noted."
RULE WHEN [context: a follow-up study of a known lesion] USE "stable appearances of the {lesion}"
RULE WHEN [findings: an abnormal adjacent vessel calibre is reported] INSERT "Adjacent vessels:" BEFORE "No focal lesion."
RULE WHEN [findings: the primary organ abnormality is the main finding] ORDER FIRST
IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core)

## Paragraph: Adjacent structures (FINDINGS)
NORMAL [adjacent vessels] "The adjacent vessels are of normal calibre."
NEGATIVE "No free fluid."
NEGATIVE "No lymphadenopathy or collection."
RULE WHEN [findings: multiple abnormal adjacent structures are reported] SUPPRESS NEGATIVES

## Paragraph: Measured values (MEASUREMENTS)
NEGATIVE "No measurement artefact."
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["chamber volume" | "wall thickness" | "ejection fraction"] AT TOP

## Report-wide
FIXED "Images reviewed on a diagnostic workstation."
NEGATIVE "No free fluid."
RULE WHEN [findings: a calcified focus in the primary organ is reported] SUPPRESS "No calcification."
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION MEASUREMENTS
RULE WHEN [context: a short-form report is requested by the referrer] SUPPRESS_HEADERS

## Impression Construction
Promoted to Impression: the main finding and its complications. Incidental findings stay in the body.

### Normal study impression
"No acute abnormality of the primary organ."

## Paragraph: Summary (IMPRESSION)
Numbered list, most important first.
"""

STRUCT = g.parse_sheet(SHEET, mode="v1").structure
# rule positions (Jev keys r<i>)
R_REPLACE, R_APPEND, R_USE, R_INSERT, R_ORDER, R_SUPNEG, R_LIST, R_SUPPRESS, R_SECTION, R_HEADERS = range(10)
CTX_RULES = {f"r{R_APPEND}", f"r{R_USE}", f"r{R_SECTION}", f"r{R_HEADERS}"}


def test_fixture_parses_usable():
    assert STRUCT.usable and STRUCT.source == "grammar", STRUCT.lint_errors
    assert [r.effect for r in STRUCT.rules] == ["replace", "append", "use", "insert_before", "order",
                                                "suppress_paragraph_negatives", "list_missing", "suppress",
                                                "suppress_section", "suppress_headers"]


def stub(monkeypatch, jev_f: dict | None = None, jev_c: dict | None = None, qwen=None,
         plan: rc.ImpressionPlan | None = None, fallback: rc.FallbackNegatives | None = None):
    """Jev answers by key ({"r0": 0.9}); unlisted keys score 0.1. Qwen: a QwenDecisions (returned as is) or a
    dict {negative text without stop: (action, finding)} plus {"affected": [normal text, …]}; every negative
    sent and not listed is "keep". Records every call."""
    calls: dict = {"jev": [], "qwen": [], "fallback": [], "plan": []}
    jev_f, jev_c = jev_f or {}, jev_c or {}

    async def fake_jev(state, qs):
        ctx = "CLINICAL HISTORY" in state
        calls["jev"].append((ctx, set(qs)))
        src = jev_c if ctx else jev_f
        return {k: {"noul": src.get(k, 0.1)} for k in qs}

    async def fake_qwen(state, negs, normals, measurements):
        calls["qwen"].append((list(negs), list(normals)))
        if isinstance(qwen, rc.QwenDecisions):
            return qwen
        spec = qwen or {}
        decs = [rc.NegativeDecision(index=i, action=spec.get(n.rstrip("."), ("keep", ""))[0],
                                    dictated_finding=spec.get(n.rstrip("."), ("keep", ""))[1]) for i, n in enumerate(negs)]
        aff = [i for i, t in enumerate(normals) if t in spec.get("affected", [])]
        return rc.QwenDecisions(negatives=decs, affected_normals=aff, applicable_measurements=[])

    async def no_split(negs):
        return [[n] for n in negs]

    async def fake_plan(scan_type, history, items, recs, inclusion_logic=""):
        calls["plan"].append(inclusion_logic)
        if plan is None:
            raise RuntimeError("no plan")
        return plan

    async def fake_fallback(state, items, keys):
        calls["fallback"].append(list(keys))
        return fallback

    for name, fn in (("_jev", fake_jev), ("_qwen", fake_qwen), ("_split_bundled", no_split),
                     ("_plan", fake_plan), ("_fallback", fake_fallback)):
        monkeypatch.setattr(tb.rc, name, fn)
    return calls


async def compile_(findings="Enlarged primary organ with a 2 cm lesion.", history="Known lesion, follow-up."):
    return await tb.compile_template_brief(SHEET, STRUCT, "CT AP", findings, history)


def rule_decision(b, i):
    return b.decisions["rules"][i]


# ── rule effects ────────────────────────────────────────────────────────────

async def test_unmet_rules_are_all_removed_and_their_targets_stand(monkeypatch):
    stub(monkeypatch, {f"r{R_LIST}i{j}": 0.9 for j in range(3)})
    b = await compile_()
    assert "RULE WHEN" not in b.text and "IF_PRESENT" not in b.text
    assert '- KEEP: "No focal lesion."' in b.text
    assert all(r["action"] == "removed" for r in b.decisions["rules"])


async def test_met_replace_omits_the_target_where_it_sits_and_says_instead(monkeypatch):
    stub(monkeypatch, {f"r{R_REPLACE}": 0.9})
    b = await compile_()
    lines = b.text.splitlines()
    i = lines.index('- OMIT: "No focal lesion." — a focal lesion of the primary organ is reported')
    assert lines[i + 1] == '- INSTEAD: "A {size} lesion is present."'
    assert lines[i - 1] == '- KEEP NORMAL [primary organ]: "The primary organ is normal in size and contour."'
    assert 'REPLACE "No focal lesion."' not in b.text
    d = rule_decision(b, R_REPLACE)
    assert d["met"] is True and d["score"] == 0.9 and d["action"] == "applied" and d["id"] == "r0"


async def test_met_suppress_of_text_that_is_no_unit_omits_on_the_rule_line(monkeypatch):
    stub(monkeypatch, {f"r{R_SUPPRESS}": 0.8})
    b = await compile_()
    assert '- OMIT: "No calcification." — a calcified focus in the primary organ is reported' in b.text


async def test_append_is_applied_from_the_history_state(monkeypatch):
    stub(monkeypatch, jev_c={f"r{R_APPEND}": 0.9})
    b = await compile_()
    assert '- APPLY: "Post-surgical appearances are noted."' in b.text


async def test_use_is_applied_from_the_context_state(monkeypatch):
    stub(monkeypatch, {f"r{R_USE}": 0.9}, jev_c={f"r{R_USE}": 0.2})   # the findings-state score is never read
    b = await compile_()
    assert "stable appearances" not in b.text
    stub(monkeypatch, jev_c={f"r{R_USE}": 0.9})
    assert '- USE: "stable appearances of the {lesion}"' in (await compile_()).text


async def test_history_and_context_conditions_go_to_the_history_state_only(monkeypatch):
    calls = stub(monkeypatch)
    await compile_()
    ctx = [qs for c, qs in calls["jev"] if c]
    plain = [qs for c, qs in calls["jev"] if not c]
    assert ctx == [CTX_RULES]
    assert not (plain[0] & CTX_RULES) and f"r{R_REPLACE}" in plain[0] and "c1" in plain[0]


async def test_insert_before(monkeypatch):
    stub(monkeypatch, {f"r{R_INSERT}": 0.9})
    assert '- INSERT: "Adjacent vessels:" BEFORE "No focal lesion."' in (await compile_()).text


async def test_order(monkeypatch):
    stub(monkeypatch, {f"r{R_ORDER}": 0.9})
    assert "- PLACE THIS PARAGRAPH FIRST — the primary organ abnormality is the main finding" in (await compile_()).text


async def test_suppress_paragraph_negatives_omits_that_paragraphs_negatives_only(monkeypatch):
    stub(monkeypatch, {f"r{R_SUPNEG}": 0.9})
    b = await compile_()
    para = b.text.split("## Paragraph: Adjacent structures (FINDINGS)")[1].split("## ")[0]
    why = "multiple abnormal adjacent structures are reported"
    assert f'- OMIT: "No free fluid." — {why}' in para
    assert f'- OMIT: "No lymphadenopathy or collection." — {why}' in para
    assert "- DESCRIBE FROM DICTATION: this paragraph's normal wording does not apply" in para
    report_wide = b.text.split("## Report-wide")[1].split("## ")[0]
    assert f'- OMIT: "No free fluid." — {why}' in report_wide   # a Report-wide copy in the same section follows
    assert '- KEEP: "No focal lesion."' in b.text                # other paragraphs are untouched


async def test_list_missing_partial(monkeypatch):
    stub(monkeypatch, {f"r{R_LIST}i0": 0.9})
    b = await compile_()
    assert "- MISSING (list at top): wall thickness, ejection fraction" in b.text
    assert "LIST_MISSING" not in b.text
    assert b.decisions["missing"] == [{"id": f"r{R_LIST}", "items": ["chamber volume", "wall thickness",
                                       "ejection fraction"], "missing": ["wall thickness", "ejection fraction"],
                                       "position": "top"}]


async def test_list_missing_none_missing_removes_the_line(monkeypatch):
    calls = stub(monkeypatch, {f"r{R_LIST}i{j}": 0.9 for j in range(3)})
    b = await compile_()
    assert "MISSING" not in b.text and "LIST_MISSING" not in b.text
    plain = next(qs for c, qs in calls["jev"] if not c)
    assert f"r{R_LIST}" not in plain and {f"r{R_LIST}i0", f"r{R_LIST}i1", f"r{R_LIST}i2"} <= plain


async def test_suppress_section_omits_the_section_and_drops_its_units(monkeypatch):
    stub(monkeypatch, jev_c={f"r{R_SECTION}": 0.9})
    b = await compile_()
    assert "- OMIT SECTION: MEASUREMENTS — a limited protocol is stated in the request" in b.text
    assert "No measurement artefact" not in b.text and "MISSING" not in b.text
    assert rule_decision(b, R_LIST)["action"] == "section_omitted"


async def test_suppress_headers(monkeypatch):
    stub(monkeypatch, jev_c={f"r{R_HEADERS}": 0.9})
    assert "- NO PARAGRAPH HEADERS — a short-form report is requested by the referrer" in (await compile_()).text


# ── negatives ───────────────────────────────────────────────────────────────

async def test_conditional_negative_unmet_is_removed_met_goes_to_the_classifier(monkeypatch):
    stub(monkeypatch)
    b = await compile_()
    assert "No surrounding collection" not in b.text
    stub(monkeypatch, {"c1": 0.9})
    assert '- KEEP: "No surrounding collection."' in (await compile_()).text


async def test_conditional_negative_with_a_history_source_is_asked_in_the_history_state(monkeypatch):
    sheet = SHEET.replace("[findings: an inflammatory process of the primary organ is reported]",
                          "[history: an inflammatory process of the primary organ is suspected]")
    s = g.parse_sheet(sheet, mode="v1").structure
    calls = stub(monkeypatch, jev_c={"c1": 0.9})
    b = await tb.compile_template_brief(sheet, s, "CT AP", "Lesion.", "?inflammation")
    assert '- KEEP: "No surrounding collection."' in b.text
    assert "c1" in next(qs for c, qs in calls["jev"] if c)


async def test_classifier_labels_and_every_copy_shares_one_label(monkeypatch):
    # distinct negatives in sheet order: focal lesion, surrounding collection, free fluid, lymphadenopathy…, artefact
    q = {"No free fluid": ("contradicted", "free fluid"), "No lymphadenopathy or collection": ("expected", "the mass")}
    calls = stub(monkeypatch, qwen=q)
    b = await compile_()
    assert calls["qwen"][0][0].count("No free fluid") == 1
    assert b.text.count('- OMIT: "No free fluid." — the dictation reports: free fluid') == 2
    assert '- DO NOT ASSERT: "No lymphadenopathy or collection." — expected consequence of: the mass' in b.text
    assert '- KEEP: "No measurement artefact."' in b.text


async def test_bundled_negative_split_renders_one_label_per_part(monkeypatch):
    stub(monkeypatch)

    async def split(negs):
        return [["No lymphadenopathy", "No collection"] if "or collection" in n else [n] for n in negs]
    monkeypatch.setattr(tb.rc, "_split_bundled", split)
    b = await compile_()
    assert '- KEEP: "No lymphadenopathy."\n- KEEP: "No collection."' in b.text


# ── normals ─────────────────────────────────────────────────────────────────

async def test_normals_kept_or_not_asserted_by_jev_or_qwen(monkeypatch):
    stub(monkeypatch, {"m0": 0.9})
    b = await compile_()
    assert '- DO NOT ASSERT AS NORMAL [primary organ]: "The primary organ is normal in size and contour."' in b.text
    assert '- KEEP NORMAL [adjacent vessels]: "The adjacent vessels are of normal calibre."' in b.text
    stub(monkeypatch, qwen={"affected": ["The adjacent vessels are of normal calibre."]})
    b = await compile_()
    assert '- DO NOT ASSERT AS NORMAL [adjacent vessels]: "The adjacent vessels are of normal calibre."' in b.text
    assert [n["action"] for n in b.decisions["normals"]] == ["keep", "do_not_assert"]


async def test_stated_normal_routes_like_a_normal_not_through_the_negative_classifier(monkeypatch):
    negs = list(STRUCT.negatives)
    negs[4] = negs[4].model_copy(update={"kind": "stated_normal"})   # "No measurement artefact."
    s = STRUCT.model_copy(update={"negatives": negs})
    calls = stub(monkeypatch, {"s4": 0.9})
    b = await tb.compile_template_brief(SHEET, s, "CT AP", "Lesion.", "")
    assert '- DO NOT ASSERT AS NORMAL [Measured values]: "No measurement artefact."' in b.text
    negs_sent, normals_sent = calls["qwen"][0]
    assert "No measurement artefact" not in negs_sent and "No measurement artefact." in normals_sent


# ── in-place rendering, If-present off, impression, options ─────────────────

async def test_rendering_is_in_place_and_prose_passes_through(monkeypatch):
    stub(monkeypatch)
    b = await compile_()
    lines = b.text.splitlines()
    for kept in ("Size first, then contour, then the adjacent fat.", 'TERM PREFER "unremarkable"',
                 'FIXED "Images reviewed on a diagnostic workstation."', "Short declarative sentences. British spelling.",
                 'SECTION FINDINGS | header: "FINDINGS" | role: findings', "## Paragraph: Adjacent structures (FINDINGS)"):
        assert kept in lines
    order = [lines.index(x) for x in ("## Paragraph: Primary organ (FINDINGS)",
                                      '- KEEP NORMAL [primary organ]: "The primary organ is normal in size and contour."',
                                      '- KEEP: "No focal lesion."', "## Paragraph: Adjacent structures (FINDINGS)")]
    assert order == sorted(order)
    assert '  - KEEP: "No surrounding collection."' not in b.text   # unmet: removed, not relabelled


async def test_indentation_of_a_unit_line_is_kept(monkeypatch):
    stub(monkeypatch, {"c1": 0.9})
    assert '\n  - KEEP: "No surrounding collection."\n' in (await compile_()).text


async def test_if_present_is_ignored(monkeypatch):
    calls = stub(monkeypatch, plan=rc.ImpressionPlan(recommendations=[], impression=[0]))
    b = await compile_()
    assert not any(k.startswith("f") for _, qs in calls["jev"] for k in qs)
    assert "IF_PRESENT" not in b.text and "regional lymphadenopathy" not in b.text
    assert calls["fallback"] == [[]]   # every dictated item is unanticipated
    assert not [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]


async def test_finding_negatives_come_from_the_fallback_offered_in_the_findings_section(monkeypatch):
    fb = rc.FallbackNegatives(items=[rc.FallbackItem(index=0, covered=False, negatives=["No perforation.", "No abscess"]),
                                     rc.FallbackItem(index=1, covered=False, negatives=["No x"])])
    plan = rc.ImpressionPlan(recommendations=[], impression=[0], optional_impression=[1])
    stub(monkeypatch, plan=plan, fallback=fb)
    b = await compile_(findings="Enlarged primary organ. Small cyst in the adjacent fat.")
    fn = [o for o in b.decisions["options"] if o["kind"] == "finding_negative"]
    assert [o["text"] for o in fn] == ["No perforation", "No abscess"]
    assert all(o["section"] == "FINDINGS" and o["finding"] == "Enlarged primary organ" for o in fn)
    imp = [o for o in b.decisions["options"] if o["kind"] == "impression"]
    assert imp == [{"kind": "impression", "section": "IMPRESSION", "text": "Small cyst in the adjacent fat", "reason": ""}]
    assert "No perforation" not in b.text   # offered, never stated


async def test_impression_plan_uses_the_impression_construction_prose(monkeypatch):
    calls = stub(monkeypatch, plan=rc.ImpressionPlan(recommendations=[], impression=[0], findings_only=[1]))
    b = await compile_(findings="Enlarged primary organ. Small cyst in the adjacent fat.")
    assert calls["plan"][0].startswith("Promoted to Impression") and "Normal study impression" in calls["plan"][0]
    plan = b.text.split("## Impression Plan\n")[1]
    assert '- **Carry forward (the impression addresses each):** "Enlarged primary organ"' in plan
    assert '- **Findings only (not in the impression):** "Small cyst in the adjacent fat"' in plan


async def test_plan_failure_still_compiles_without_a_plan_section(monkeypatch):
    stub(monkeypatch)
    b = await compile_()
    assert "## Impression Plan" not in b.text and b.decisions["impression_plan"] is None


async def test_normal_study_impression_dropped_when_anything_is_positive(monkeypatch):
    stub(monkeypatch)
    assert "No acute abnormality of the primary organ" not in (await compile_()).text
    assert "No acute abnormality of the primary organ" in (await compile_(findings="No abnormality.")).text


# ── failure → raw path ──────────────────────────────────────────────────────

async def test_jev_failure_raises_for_the_raw_path(monkeypatch):
    stub(monkeypatch)

    async def boom(state, qs):
        raise RuntimeError("jev down")
    monkeypatch.setattr(tb.rc, "_jev", boom)
    with pytest.raises(RuntimeError):
        await compile_()


async def test_unusable_structure_raises(monkeypatch):
    stub(monkeypatch)
    with pytest.raises(ValueError):
        await tb.compile_template_brief(SHEET, STRUCT.model_copy(update={"usable": False}), "CT", "x", "")


def test_template_brief_imports_no_quick_report_module():
    path = pathlib.Path(tb.__file__)
    mods = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.lstrip("."))
        elif isinstance(n, ast.Import):
            mods.update(a.name for a in n.names)
    assert not [m for m in mods if "quick_report" in m]


# ── follow-ups: suppressed paragraphs drop their normals, omitted sections drop their shells ──

async def test_suppress_negatives_makes_the_paragraphs_normals_not_assertable(monkeypatch):
    stub(monkeypatch, {f"r{R_SUPNEG}": 0.9})   # m1 scores 0.1 and Qwen flags nothing: the rule decides
    b = await compile_()
    assert '- DO NOT ASSERT AS NORMAL [adjacent vessels]: "The adjacent vessels are of normal calibre."' in b.text
    assert '- KEEP NORMAL [primary organ]: "The primary organ is normal in size and contour."' in b.text
    assert [n["action"] for n in b.decisions["normals"]] == ["keep", "suppressed_by_rule"]


async def test_suppress_negatives_covers_stated_normals(monkeypatch):
    sheet = SHEET.replace('NEGATIVE "No lymphadenopathy or collection."',
                          'NEGATIVE "No lymphadenopathy or collection."\nNEGATIVE "The adjacent fat is clear."')
    s = g.parse_sheet(sheet, mode="v1").structure
    negs = [n.model_copy(update={"kind": "stated_normal"}) if n.text == "The adjacent fat is clear." else n
            for n in s.negatives]
    s = s.model_copy(update={"negatives": negs})
    stub(monkeypatch, {f"r{R_SUPNEG}": 0.9})
    b = await tb.compile_template_brief(sheet, s, "CT AP", "Lesion.", "")
    assert '- DO NOT ASSERT AS NORMAL [Adjacent structures]: "The adjacent fat is clear."' in b.text
    assert next(n for n in b.decisions["normals"] if n.get("kind") == "stated_normal")["action"] == "suppressed_by_rule"


async def test_omitted_section_drops_its_paragraph_shells(monkeypatch):
    sheet = SHEET.replace('NEGATIVE "No measurement artefact."',
                          'Values in a single line.\nNEGATIVE "No measurement artefact."')
    s = g.parse_sheet(sheet, mode="v1").structure
    assert s.usable
    stub(monkeypatch, jev_c={f"r{R_SECTION}": 0.9})
    b = await tb.compile_template_brief(sheet, s, "CT AP", "Lesion.", "")
    assert "## Paragraph: Measured values (MEASUREMENTS)" not in b.text and "Values in a single line." not in b.text
    assert "- OMIT SECTION: MEASUREMENTS — a limited protocol is stated in the request" in b.text
    assert 'SECTION MEASUREMENTS | header: "Measurements" | role: other' in b.text
    assert "## Report-wide" in b.text and "## Paragraph: Adjacent structures (FINDINGS)" in b.text
    stub(monkeypatch)
    b = await tb.compile_template_brief(sheet, s, "CT AP", "Lesion.", "")
    assert "## Paragraph: Measured values (MEASUREMENTS)" in b.text and "Values in a single line." in b.text


# ── G3 review: rule scope, bundled targets, fail-closed model answers (probes P/Q/S/L) ──

HEAD = """# T

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history" | role: history
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION MEASUREMENTS | header: "Measurements" | role: other
SECTION IMPRESSION | header: "Impression" | role: impression
"""
TAIL = "\n## Paragraph: Summary (IMPRESSION)\nNumbered.\n"


async def brief(monkeypatch, body: str, findings="A finding.", history="", split=None, **kw):
    sheet = HEAD + body + TAIL
    s = g.parse_sheet(sheet, mode="v1").structure
    assert s.usable, s.lint_errors
    calls = stub(monkeypatch, **kw)
    if split:
        async def fake_split(negs):
            return split(negs)
        monkeypatch.setattr(tb.rc, "_split_bundled", fake_split)
    return await tb.compile_template_brief(sheet, s, "CT", findings, history), calls


def block(text: str, heading: str) -> str:
    return text.split(heading + "\n", 1)[1].split("\n## ", 1)[0]


P1 = """
## Paragraph: A (FINDINGS)
NEGATIVE "No free fluid."
RULE WHEN [findings: multiple abnormal adjacent structures are reported] SUPPRESS NEGATIVES

## Paragraph: B (FINDINGS)
NEGATIVE "No free fluid."

## Report-wide
NEGATIVE "No free fluid."
"""


async def test_p1_suppress_negatives_scope_and_conflict_telemetry(monkeypatch):
    b, _ = await brief(monkeypatch, P1, jev_f={"r0": 0.9})
    why = "multiple abnormal adjacent structures are reported"
    assert f'- OMIT: "No free fluid." — {why}' in block(b.text, "## Paragraph: A (FINDINGS)")
    assert '- KEEP: "No free fluid."' in block(b.text, "## Paragraph: B (FINDINGS)")
    assert f'- OMIT: "No free fluid." — {why}' in block(b.text, "## Report-wide")
    assert b.decisions["conflicts"] == [{"text": "No free fluid.", "omitted_in": ["A", "Report-wide (FINDINGS)"],
                                         "kept_in": ["B"]}]


async def test_p1b_contradicted_labels_every_copy_without_conflict(monkeypatch):
    b, _ = await brief(monkeypatch, P1, qwen={"No free fluid": ("contradicted", "ascites")})
    assert b.text.count('- OMIT: "No free fluid." — the dictation reports: ascites') == 3
    assert b.decisions["conflicts"] == []


async def test_p2_paragraph_replace_acts_on_its_own_paragraph_only(monkeypatch):
    body = """
## Paragraph: Liver (FINDINGS)
NEGATIVE "No focal lesion."
RULE WHEN [findings: a focal liver lesion is reported] REPLACE "No focal lesion." WITH "A 2 cm lesion is present."

## Paragraph: Spleen (FINDINGS)
NEGATIVE "No focal lesion."
"""
    b, _ = await brief(monkeypatch, body, jev_f={"r0": 0.9})
    liver = block(b.text, "## Paragraph: Liver (FINDINGS)")
    assert '- OMIT: "No focal lesion." — a focal liver lesion is reported\n- INSTEAD: "A 2 cm lesion is present."' in liver
    assert '- KEEP: "No focal lesion."' in block(b.text, "## Paragraph: Spleen (FINDINGS)")
    assert b.text.count("INSTEAD") == 1 and "REPLACE" not in b.text


async def test_report_wide_rule_acts_on_its_section(monkeypatch):
    body = """
## Paragraph: A (FINDINGS)
NEGATIVE "No calcification."

## Paragraph: M (MEASUREMENTS)
NEGATIVE "No calcification."

## Report-wide
RULE WHEN [findings: a calcified focus is reported] SUPPRESS "No calcification." | section: MEASUREMENTS
"""
    b, _ = await brief(monkeypatch, body, jev_f={"r0": 0.9})
    assert '- KEEP: "No calcification."' in block(b.text, "## Paragraph: A (FINDINGS)")
    assert '- OMIT: "No calcification." — a calcified focus is reported' in block(b.text, "## Paragraph: M (MEASUREMENTS)")


P3 = """
## Paragraph: A (FINDINGS)
NEGATIVE "No lymphadenopathy or collection."
RULE WHEN [findings: a collection adjacent to the organ is reported] SUPPRESS "No collection."
"""


async def test_p3_target_inside_an_unsplit_bundle_omits_the_bundle(monkeypatch):
    b, calls = await brief(monkeypatch, P3, jev_f={"r0": 0.9})
    para = block(b.text, "## Paragraph: A (FINDINGS)")
    assert para.strip() == '- OMIT: "No lymphadenopathy or collection." — a collection adjacent to the organ is reported'
    assert "KEEP" not in b.text and calls["qwen"] == []


async def test_p3b_target_equal_to_a_split_part_omits_that_part_only(monkeypatch):
    b, calls = await brief(monkeypatch, P3, jev_f={"r0": 0.9},
                           split=lambda negs: [["No lymphadenopathy", "No collection"] if " or " in n else [n] for n in negs])
    para = block(b.text, "## Paragraph: A (FINDINGS)")
    assert para.strip() == ('- KEEP: "No lymphadenopathy."\n'
                            '- OMIT: "No collection." — a collection adjacent to the organ is reported')
    assert calls["qwen"][0][0] == ["No lymphadenopathy"]


P4 = """
## Paragraph: A (FINDINGS)
NEGATIVE "No focal lesion."

## Paragraph: M (MEASUREMENTS)
Measured on axial.
NEGATIVE "No measurement artefact."
NORMAL [ventricle] "Normal ventricular volume."

## Report-wide
NEGATIVE "No measurement artefact." | section: MEASUREMENTS
NEGATIVE "No measurement artefact."
RULE WHEN [findings: a limited measurement set is reported] REPLACE "No measurement artefact." WITH "Measurements limited by artefact." | section: MEASUREMENTS
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION MEASUREMENTS
RULE WHEN [findings: a limited measurement set is reported] SUPPRESS_HEADERS | section: MEASUREMENTS
RULE WHEN [findings: a short report is requested by the referrer] SUPPRESS_HEADERS
"""


async def test_p4_suppress_section_removes_tagged_units_only(monkeypatch):
    b, _ = await brief(monkeypatch, P4, jev_f={"r0": 0.9, "r2": 0.9, "r3": 0.9}, jev_c={"r1": 0.9})
    rw = block(b.text, "## Report-wide")
    assert rw.strip().splitlines() == ['- KEEP: "No measurement artefact."',
                                       "- OMIT SECTION: MEASUREMENTS — a limited protocol is stated in the request",
                                       "- NO PARAGRAPH HEADERS — a short report is requested by the referrer"]
    assert "## Paragraph: M" not in b.text and "Measured on axial" not in b.text and "INSTEAD" not in b.text
    assert [r["action"] for r in b.decisions["rules"]] == ["section_omitted", "applied", "section_omitted", "applied"]


async def test_replace_whose_target_is_only_in_an_omitted_section_is_dropped(monkeypatch):
    body = """
## Paragraph: A (FINDINGS)
NEGATIVE "No focal lesion."

## Report-wide
RULE WHEN [findings: a focal lesion of the organ is reported] REPLACE "No focal lesion." WITH "A lesion."
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION FINDINGS
"""
    b, _ = await brief(monkeypatch, body, jev_f={"r0": 0.9}, jev_c={"r1": 0.9})
    assert "INSTEAD" not in b.text and "No focal lesion" not in b.text
    assert b.decisions["rules"][0]["action"] == "target_omitted"


async def test_insert_whose_anchor_is_omitted_is_dropped(monkeypatch):
    stub(monkeypatch, {f"r{R_REPLACE}": 0.9, f"r{R_INSERT}": 0.9})
    b = await compile_()
    assert "INSERT:" not in b.text and rule_decision(b, R_INSERT)["action"] == "anchor_removed"
    stub(monkeypatch, {f"r{R_INSERT}": 0.9})
    assert '- INSERT: "Adjacent vessels:" BEFORE "No focal lesion."' in (await compile_()).text


Q = """
## Paragraph: A (FINDINGS)
NORMAL [organ] "The organ is normal."
NEGATIVE "No focal lesion."
NEGATIVE "No free fluid."
NEGATIVE "No collection." WHEN [history: prior surgery is stated]
NEGATIVE "No stent fracture." WHEN [findings: an aortic stent graft is reported]
RULE WHEN [findings: a calcified focus is reported] SUPPRESS "No calcification."
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["chamber volume" | "wall thickness"] AT END
"""


async def test_removed_negatives_are_not_sent_to_the_classifier(monkeypatch):
    _, calls = await brief(monkeypatch, Q)
    assert calls["qwen"][0][0] == ["No focal lesion", "No free fluid"]


@pytest.mark.parametrize("indices", [[1], [0, 2], [0, 1, 1], [0, 1, 2]])
async def test_q1_classifier_must_cover_exactly_the_negatives_sent(monkeypatch, indices):
    q = rc.QwenDecisions(negatives=[rc.NegativeDecision(index=i, action="keep") for i in indices],
                         affected_normals=[], applicable_measurements=[])
    with pytest.raises(ValueError):
        await brief(monkeypatch, Q, qwen=q)


async def test_q1_affected_normal_out_of_range_fails(monkeypatch):
    q = rc.QwenDecisions(negatives=[rc.NegativeDecision(index=i, action="keep") for i in range(2)],
                         affected_normals=[5], applicable_measurements=[])
    with pytest.raises(ValueError):
        await brief(monkeypatch, Q, qwen=q)


@pytest.mark.parametrize("answer", [None, {}, {"noul": None}, {"noul": "high"}, {"noul": True}, {"noul": float("nan")}])
async def test_q2_partial_or_non_numeric_jev_answer_fails(monkeypatch, answer):
    stub(monkeypatch)

    async def partial(state, qs):
        out = {k: {"noul": 0.1} for k in qs}
        if "r1i0" in out:
            if answer is None:
                del out["r1i0"]
            else:
                out["r1i0"] = answer
        return out
    sheet = HEAD + Q + TAIL
    monkeypatch.setattr(tb.rc, "_jev", partial)
    with pytest.raises(ValueError):
        await tb.compile_template_brief(sheet, g.parse_sheet(sheet, mode="v1").structure, "CT", "x", "")


async def test_unlocatable_unit_fails(monkeypatch):
    stub(monkeypatch)
    with pytest.raises(ValueError):
        await tb.compile_template_brief(SHEET.replace('NEGATIVE "No free fluid."\n', "", 1), STRUCT, "CT", "x", "")


async def test_l5_normal_study_heading_tolerates_case_and_colon(monkeypatch):
    body = """
## Paragraph: A (FINDINGS)
NEGATIVE "No free fluid."

## Impression Construction
Promote the main finding.

### Normal Study Impression:
"No acute abnormality."
"""
    b, _ = await brief(monkeypatch, body, findings="2 cm liver lesion.")
    assert "No acute abnormality" not in b.text and "Promote the main finding." in b.text


async def test_s1_split_keeps_the_original_when_a_part_loses_its_negation_or_is_empty(monkeypatch):
    class R:
        def __init__(self, o):
            self.output = o

    async def agent(**kw):
        return R(rc.Split(negatives=[["No lymphadenopathy", "collection"], [""], ["No A", "No B"]]))
    monkeypatch.setattr(rc, "_run_agent_with_model", agent)
    out = await rc._split_bundled(["No lymphadenopathy or collection", "No fluid, or gas", "No A or B"])
    assert out == [["No lymphadenopathy or collection"], ["No fluid, or gas"], ["No A", "No B"]]


# ── lean template sheet (H1: template-mode parse, spec 2026-10-01-template-two-phase) ──

LEAN = """# Lean CT Template

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history" | role: history
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION MEASUREMENTS | header: "Measurements" | role: other
SECTION IMPRESSION | header: "Impression" | role: impression

## Paragraph: Primary organ (FINDINGS)
COVERS ["primary organ" | "adjacent fat"]
When present, give the maximal diameter.
NORMAL [primary organ] "The primary organ is normal in size and contour."
NEGATIVE "No focal lesion."
RULE WHEN [context: a follow-up study of a known lesion] USE "stable appearances of the {lesion}"

## Paragraph: Measured values (MEASUREMENTS)
RULE WHEN [findings: any listed value is not stated] LIST_MISSING ["chamber volume" | "wall thickness"] AT TOP

## Report-wide
RULE WHEN [context: a limited protocol is stated in the request] SUPPRESS_SECTION MEASUREMENTS

## Paragraph: Summary (IMPRESSION)
Numbered list, most important first.
"""


async def test_brief_compiles_over_a_template_mode_structure(monkeypatch):
    s = g.parse_sheet(LEAN).structure  # default mode: template
    assert s.usable and s.lint_warnings, s.lint_errors
    stub(monkeypatch, {"r1i0": 0.9}, jev_c={"r0": 0.9})
    b = await tb.compile_template_brief(LEAN, s, "CT AP", "A 2 cm lesion. Chamber volume 120 ml.", "Follow-up.")
    assert '- KEEP: "No focal lesion."' in b.text
    assert '- USE: "stable appearances of the {lesion}"' in b.text
    assert "- MISSING (list at top): wall thickness" in b.text
    assert "When present, give the maximal diameter." in b.text  # voice prose passes through
