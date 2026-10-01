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
    calls: dict = {"jev": [], "qwen": [], "fallback": [], "plan": [], "states": []}
    jev_f, jev_c = jev_f or {}, jev_c or {}

    async def fake_jev(state, qs):
        ctx = "CLINICAL HISTORY" in state
        calls["jev"].append((ctx, set(qs)))
        calls["states"].append((state, set(qs)))
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
        calls.setdefault("recs", []).append(list(recs))
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


async def test_history_and_context_conditions_never_see_the_findings(monkeypatch):
    calls = stub(monkeypatch)
    await compile_()
    findings = [qs for st, qs in calls["states"] if "DICTATED FINDINGS" in st]
    other = sorted((sorted(qs) for st, qs in calls["states"] if "DICTATED FINDINGS" not in st))
    assert other == [[f"r{R_APPEND}"], sorted({f"r{R_USE}", f"r{R_SECTION}", f"r{R_HEADERS}"})]  # history, context
    assert len(findings) == 1 and not (findings[0] & CTX_RULES)
    assert f"r{R_REPLACE}" in findings[0] and "c1" in findings[0]
    for st, qs in calls["states"]:
        if qs & CTX_RULES:
            assert "DICTATED FINDINGS" not in st and "lesion" not in st.split("CLINICAL HISTORY")[0]


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
    assert "COVERS" not in b.text and '"adjacent fat"' not in b.text  # metadata, not generator guidance
    assert b.decisions["differentials"] == [] and b.decisions["recommendations"] == []


async def test_context_condition_about_a_finding_is_not_met_by_the_findings(monkeypatch):
    """A context condition is judged without the dictated findings: a finding cannot satisfy it."""
    s = g.parse_sheet(LEAN).structure
    stub(monkeypatch)

    async def literal_jev(state, qs):  # Jev stand-in: true exactly when the state says "known lesion"
        return {k: {"noul": 0.9 if k == "r0" and "known lesion" in state.lower() else 0.1} for k in qs}
    monkeypatch.setattr(tb.rc, "_jev", literal_jev)
    b = await tb.compile_template_brief(LEAN, s, "CT AP", "Known lesion, unchanged at 2 cm.", "Abdominal pain.")
    assert "stable appearances" not in b.text
    b = await tb.compile_template_brief(LEAN, s, "CT AP", "A 2 cm lesion.", "Known lesion, follow-up.")
    assert '- USE: "stable appearances of the {lesion}"' in b.text


# ── master sheets: Phase-1 case units through quick's shared clinical routing (H4) ──

MASTER = """# Master CT Template

## Report Structure
SECTION CLINICAL HISTORY | header: "Clinical history" | role: history
SECTION TECHNIQUE | header: "Technique" | role: technique
SECTION FINDINGS | header: "FINDINGS" | role: findings
SECTION IMPRESSION | header: "Impression" | role: impression

## Paragraph: Protocol (TECHNIQUE)
Portal venous phase acquisition.

## Paragraph: Primary organ (FINDINGS)
COVERS ["primary organ" | "adjacent fat"]
Size first, then contour.
NORMAL [primary organ] "The primary organ is normal in size and contour."
NEGATIVE "No focal lesion."
NEGATIVE "No adjacent collection." TARGETS [Branch alpha] | origin: case
NEGATIVE "No free fluid." TARGETS [Branch beta] | origin: case
IF_PRESENT [focal lesion] "No regional lymphadenopathy." (core) | origin: case
IF_PRESENT [focal lesion] "No vascular invasion." (contextual) | origin: case
IF_PRESENT [focal lesion] "No focal lesion." (core) | origin: case

## Paragraph: Adjacent structures (FINDINGS)
COVERS ["adjacent vessels"]
NEGATIVE "No free fluid."
RULE WHEN [context: a follow-up study of a known lesion] USE "stable appearances of the {lesion}"

## Case Deliberation
QUESTION "Is there a focal process of the primary organ?"
DIFFERENTIAL [Branch alpha] TIER triage "a rim-enhancing collection" VISIBLE yes
DIFFERENTIAL [Branch beta] TIER aetiology "fluid tracking along the fascia" VISIBLE yes
DIFFERENTIAL [Branch gamma] TIER aetiology "a feature this phase cannot show" VISIBLE no
DIFFERENTIAL [Branch delta] TIER aetiology "a laboratory diagnosis" VISIBLE silent
RECOMMEND REFERRAL "Specialist team review" WHEN [findings: a focal lesion is reported]
RECOMMEND IMAGING "Dedicated MRI of the primary organ" WHEN [findings: an indeterminate lesion is reported]
RECOMMEND TISSUE "Image-guided biopsy" WHEN [findings: a solid lesion is reported]

## Impression Construction
Promoted to Impression: the main finding.

## Paragraph: Summary (IMPRESSION)
Numbered list, most important first.
"""

MSTRUCT = g.parse_sheet(MASTER, mode="master").structure
LYMPH, VASC = "No regional lymphadenopathy", "No vascular invasion"


def test_master_fixture_parses_usable():
    assert MSTRUCT.usable, MSTRUCT.lint_errors
    assert [d.visible for d in MSTRUCT.differentials] == ["yes", "yes", "no", "silent"]


async def master(monkeypatch, jev=None, qwen=None, plan=None, sheet=MASTER, struct=None):
    calls = stub(monkeypatch, jev or {}, qwen=qwen, plan=plan)
    b = await tb.compile_template_brief(sheet, struct or MSTRUCT, "CT AP", "A 3 cm focal lesion of the primary organ.",
                                        "Pain.")
    return b, calls


def case_block(text: str) -> str:
    return block(text, tb.CASE_HEADING)


def outcome(b, text):
    return next(f["outcome"] for f in b.decisions["finding_negatives"] if f["text"] == text)


async def test_master_end_to_end(monkeypatch):
    plan = rc.ImpressionPlan(recommendations=[
        rc.RecDecision(index=0, decision="include"),
        rc.RecDecision(index=1, decision="exclude", exclude_reason="routine_workup", reason="already characterised"),
        rc.RecDecision(index=2, decision="include")], impression=[0])
    b, calls = await master(monkeypatch, {"d0": 0.9, "f0": 0.95, "rec2": 0.9}, plan=plan)
    t = b.text
    # Case Deliberation: reasoning input, rewritten in place
    assert tb.CASE_HEADING in t and tb.CASE_NOTE in t and "\n## Case Deliberation\n" not in t
    cb = case_block(t)
    assert "- CLINICAL QUESTION: Is there a focal process of the primary organ?" in cb
    assert "- ADDRESS: Branch alpha — the dictation reports it" in cb
    assert "Branch beta" not in cb  # closed by silence: visible, not reported
    assert "- OPEN: Branch gamma — a feature this phase cannot show; not assessable on this study: defer" in cb
    assert "- OPEN: Branch delta — a laboratory diagnosis; imaging-silent: defer" in cb
    assert not any(k in t for k in ("QUESTION \"", "DIFFERENTIAL [", "RECOMMEND REFERRAL", "RECOMMEND IMAGING"))
    assert [d["action"] for d in b.decisions["differentials"]] == ["present", "closed", "open", "open"]
    # recommendations: keep / do not recommend (routine workup of an investigation) / removed (unmet), written
    # outside the reasoning block, before the Impression Plan
    assert "RECOMMEND" not in cb
    recs = block(t, tb.RECOMMENDATIONS_HEADING)
    assert recs.splitlines()[:2] == ["- RECOMMEND: Specialist team review",
                                     "- DO NOT RECOMMEND: Dedicated MRI of the primary organ"]
    assert t.index(tb.RECOMMENDATIONS_HEADING) < t.index("## Impression Plan")
    assert "biopsy" not in t
    assert [r["action"] for r in b.decisions["recommendations"]] == ["keep", "do_not_recommend", "removed"]
    assert calls["recs"][0][0] == "REFERRAL: Specialist team review (when a focal lesion is reported)"
    # case negatives: OMIT when the differential they help exclude is reported, else classified as usual
    assert '- OMIT: "No adjacent collection." — a dictated finding makes this negative inapplicable' in t
    assert "Branch alpha" not in block(t, "## Paragraph: Primary organ (FINDINGS)")
    case = [n for n in b.decisions["negatives"] if n["origin"] == "case"]
    assert [(n["targets"], n["action"]) for n in case] == [("Branch alpha", "differential_present"),
                                                         ("Branch beta", "labelled")]
    assert block(t, "## Paragraph: Primary organ (FINDINGS)").count('- KEEP: "No free fluid."') == 1
    sent = calls["qwen"][0][0]
    assert "No adjacent collection" not in sent and LYMPH in sent and VASC in sent
    # If-present: core + clearly reported -> stated in its paragraph; contextual -> offered; a negative the
    # sheet already carries is routed once (by the sheet negative)
    para = block(t, "## Paragraph: Primary organ (FINDINGS)")
    assert f'- KEEP: "{LYMPH}." (finding: focal lesion)' in para
    assert VASC not in t and "IF_PRESENT" not in t
    assert outcome(b, LYMPH) == "stated" and outcome(b, VASC) == "offered"
    assert [f["text"] for f in b.decisions["finding_negatives"]] == [LYMPH, VASC]
    assert b.decisions["options"][0] == {"kind": "finding_negative", "section": "FINDINGS", "paragraph": "Primary organ",
                                         "text": VASC, "finding": "focal lesion", "reason": "contextual"}
    assert para.count('"No focal lesion."') == 1
    # COVERS is metadata; context conditions see the protocol text, never the findings
    assert "COVERS" not in t
    ctx = [st for st, qs in calls["states"] if "r0" in qs]
    assert ctx and "PROTOCOL / TECHNIQUE:\nPortal venous phase acquisition." in ctx[0]
    assert "DICTATED FINDINGS" not in ctx[0]
    assert {"d0", "d1", "d2", "d3", "f0", "rec0", "rec1", "rec2"} <= next(qs for st, qs in calls["states"]
                                                                          if "DICTATED FINDINGS" in st)


@pytest.mark.parametrize("present,label,expected", [
    (0.95, "keep", "stated"), (0.6, "keep", "offered"), (0.95, "expected", "do_not_assert"),
    (0.95, "contradicted", "dropped"), (0.2, "keep", "dropped")])
async def test_master_if_present_rows(monkeypatch, present, label, expected):
    b, calls = await master(monkeypatch, {"f0": present}, qwen={LYMPH: (label, "a 3 cm focal lesion")})
    assert outcome(b, LYMPH) == expected
    para = block(b.text, "## Paragraph: Primary organ (FINDINGS)")
    assert (f'- KEEP: "{LYMPH}." (finding: focal lesion)' in para) == (expected == "stated")
    assert (f'- DO NOT ASSERT: "{LYMPH}." — expected consequence of: a 3 cm focal lesion' in para) \
        == (expected == "do_not_assert")
    assert any(o["text"] == LYMPH for o in b.decisions["options"]) == (expected == "offered")
    assert (LYMPH in calls["qwen"][0][0]) == (present >= rc.PRESENT_LOW)  # an unreported finding is not classified


async def test_master_if_present_offers_are_capped(monkeypatch):
    extra = "\n".join(f'IF_PRESENT [focal lesion] "No extension {i}." (contextual) | origin: case' for i in range(6))
    sheet = MASTER.replace('IF_PRESENT [focal lesion] "No focal lesion." (core) | origin: case', extra)
    s = g.parse_sheet(sheet, mode="master").structure
    assert s.usable, s.lint_errors
    b, _ = await master(monkeypatch, {"f0": 0.95}, sheet=sheet, struct=s)
    outs = [f["outcome"] for f in b.decisions["finding_negatives"]]
    assert outs.count("offered") == rc.MAX_FINDING_OPTIONS and outs.count("dropped") == 3  # VASC + 6 contextual
    # options are full: an optional recommendation is not offered (quick counts every option, as here)
    plan = rc.ImpressionPlan(recommendations=[rc.RecDecision(index=0, decision="optional", reason="either way")],
                             impression=[0])
    b, _ = await master(monkeypatch, {"f0": 0.95}, plan=plan, sheet=sheet, struct=s)
    assert b.decisions["recommendations"][0]["action"] == "removed"


async def test_master_optional_recommendation_is_offered_in_the_impression_section(monkeypatch):
    plan = rc.ImpressionPlan(recommendations=[rc.RecDecision(index=0, decision="optional", reason="either way")],
                             impression=[0])
    b, _ = await master(monkeypatch, plan=plan)
    assert "Specialist team review" not in b.text
    assert {"kind": "recommendation", "section": "IMPRESSION", "text": "REFERRAL: Specialist team review",
            "reason": "either way"} in b.decisions["options"]
    # no plan decision: kept (Jev alone), as in quick
    assert [r["action"] for r in b.decisions["recommendations"]] == ["optional", "keep", "keep"]


@pytest.mark.parametrize("qwen_label,lost", [("keep", "KEEP"), ("expected", "DO NOT ASSERT")])
async def test_one_label_per_claim_safer_wins(monkeypatch, qwen_label, lost):
    # Branch beta reported: its case negative "No free fluid." is OMIT, and so is the template sweep's copy
    b, calls = await master(monkeypatch, {"d1": 0.9}, qwen={"No free fluid": (qwen_label, "a 3 cm focal lesion")})
    adj = block(b.text, "## Paragraph: Adjacent structures (FINDINGS)")
    omit = '- OMIT: "No free fluid." — a dictated finding makes this negative inapplicable'
    assert omit in adj and omit in block(b.text, "## Paragraph: Primary organ (FINDINGS)")
    assert "KEEP: \"No free fluid" not in b.text and "DO NOT ASSERT: \"No free fluid" not in b.text
    (c,) = [c for c in b.decisions["conflicts"] if c.get("winner")]
    assert c["text"] == "No free fluid." and c["winner"] == "OMIT" and c["differential"] == "Branch beta"
    assert c["source"] == "case_negative_same_claim"
    assert c["labels"][0]["origin"] == "template" and c["labels"][0]["label"] == lost


async def test_one_label_per_claim_no_conflict_when_already_omitted(monkeypatch):
    b, _ = await master(monkeypatch, {"d1": 0.9}, qwen={"No free fluid": ("contradicted", "free fluid")})
    assert '- OMIT: "No free fluid." — the dictation reports: free fluid' in b.text
    assert not [c for c in b.decisions["conflicts"] if c.get("winner")]


async def test_master_case_units_not_in_the_sheet_fail_closed(monkeypatch):
    stub(monkeypatch)
    no_block = MASTER.split("## Case Deliberation")[0] + "## Paragraph: Summary (IMPRESSION)\nNumbered.\n"
    with pytest.raises(ValueError, match="Case Deliberation"):
        await tb.compile_template_brief(no_block, MSTRUCT, "CT", "x", "")
    no_ifp = MASTER.replace('IF_PRESENT [focal lesion] "No vascular invasion." (contextual) | origin: case\n', "")
    with pytest.raises(ValueError, match="IF_PRESENT"):
        await tb.compile_template_brief(no_ifp, MSTRUCT, "CT", "x", "")


# ── H4 review probes (P1-P10): claim conflicts via Jev, non-visible targets, recommendations, context ──

FIND = "A 3 cm focal lesion of the primary organ."
CASE_OMIT = '— a dictated finding makes this negative inapplicable'


async def probe(monkeypatch, sheet=MASTER, jev=None, denials=(), plan=None, qwen=None, struct=None):
    """Compile a master sheet. Jev answers by key from `jev` (else 0.1); a "denies" question (x<k>_<unit>) is
    yes when one of `denials` (differential name, statement fragment) matches it."""
    s = struct or g.parse_sheet(sheet, mode="master").structure
    assert s.usable, s.lint_errors
    calls = stub(monkeypatch, qwen=qwen, plan=plan)
    scores = jev or {}

    async def fake_jev(state, qs):
        calls["states"].append((state, set(qs)))
        out = {}
        for k, q in qs.items():
            ins = q["instructions"]
            if k.startswith("x"):
                stmt = ins.split("Statement: ", 1)[1]
                out[k] = {"noul": 0.9 if any(n in ins and f in stmt for n, f in denials) else 0.1}
            else:
                out[k] = {"noul": scores.get(k, 0.1)}
        return out
    monkeypatch.setattr(tb.rc, "_jev", fake_jev)
    return await tb.compile_template_brief(sheet, s, "CT AP", FIND, "Pain."), calls


ADJ = '## Paragraph: Adjacent structures (FINDINGS)\nCOVERS ["adjacent vessels"]\nNEGATIVE "No free fluid."'


async def test_p1_reworded_template_copy_of_a_present_differentials_negative_is_omitted(monkeypatch):
    sheet = MASTER.replace(ADJ, ADJ.replace("No free fluid.", "No free intraperitoneal fluid."))
    b, calls = await probe(monkeypatch, sheet, {"d1": 0.9}, denials=[("Branch beta", "free intraperitoneal fluid")])
    adj = block(b.text, "## Paragraph: Adjacent structures (FINDINGS)")
    assert f'- OMIT: "No free intraperitoneal fluid." {CASE_OMIT}' in adj
    (c,) = [c for c in b.decisions["conflicts"] if c.get("source") == "jev_denies_present_differential"]
    assert c["differential"] == "Branch beta" and c["labels"][0]["label"] == "KEEP"
    asked = [q for st, qs in calls["states"] for q in qs if q.startswith("x")]
    assert asked and all(q.startswith("x1_") for q in asked)  # only the present differential, template units only
    # without Jev's yes, the reworded copy stands: the exact-key path alone cannot see it
    b, _ = await probe(monkeypatch, sheet, {"d1": 0.9})
    assert '- KEEP: "No free intraperitoneal fluid."' in b.text


async def test_p1b_bundled_template_copy_is_omitted(monkeypatch):
    sheet = MASTER.replace(ADJ, ADJ.replace("No free fluid.", "No free fluid or adjacent collection."))
    b, _ = await probe(monkeypatch, sheet, {"d0": 0.9, "d1": 0.9}, denials=[("Branch beta", "free fluid")])
    assert f'- OMIT: "No free fluid or adjacent collection." {CASE_OMIT}' in b.text


async def test_p1c_normal_stating_the_absence_is_not_asserted(monkeypatch):
    sheet = MASTER.replace(ADJ, ADJ.replace('NEGATIVE "No free fluid."',
                                            'NORMAL [peritoneum] "The peritoneum is clear with no free fluid."'))
    b, _ = await probe(monkeypatch, sheet, {"d1": 0.9}, denials=[("Branch beta", "no free fluid")])
    assert '- DO NOT ASSERT AS NORMAL [peritoneum]: "The peritoneum is clear with no free fluid."' in b.text
    assert any(c.get("winner") == "DO NOT ASSERT AS NORMAL" for c in b.decisions["conflicts"])


async def test_p1d_missing_denies_answer_fails_closed(monkeypatch):
    stub(monkeypatch)

    async def partial(state, qs):
        return {k: {"noul": 0.9 if k == "d1" else 0.1} for k in qs if not k.startswith("x")}
    monkeypatch.setattr(tb.rc, "_jev", partial)
    with pytest.raises(ValueError, match="x1_"):
        await tb.compile_template_brief(MASTER, MSTRUCT, "CT AP", FIND, "Pain.")


OMIT_SHEET = MASTER.replace(
    'SECTION IMPRESSION | header: "Impression" | role: impression',
    'SECTION EXTRA | header: "Extra" | role: findings\nSECTION IMPRESSION | header: "Impression" | role: impression',
).replace(
    "## Case Deliberation",
    '## Paragraph: Extra organ (EXTRA)\nCOVERS ["extra organ"]\nNEGATIVE "No free fluid." TARGETS [Branch beta] | origin: case\n'
    'IF_PRESENT [focal lesion] "No distant metastasis." (core) | origin: case\n\n'
    '## Report-wide\nRULE WHEN [context: a limited study] SUPPRESS_SECTION EXTRA\n\n## Case Deliberation',
).replace('NEGATIVE "No free fluid." TARGETS [Branch beta] | origin: case\nIF_PRESENT [focal lesion] "No regional',
          'IF_PRESENT [focal lesion] "No regional')


async def test_p2_case_negative_in_an_omitted_section_still_omits_its_claim(monkeypatch):
    s = g.parse_sheet(OMIT_SHEET, mode="master").structure
    ridx = next(i for i, r in enumerate(s.rules) if r.effect == "suppress_section")
    b, _ = await probe(monkeypatch, OMIT_SHEET, {"d1": 0.9, f"r{ridx}": 0.9, "f0": 0.95}, struct=s)
    assert f'- OMIT: "No free fluid." {CASE_OMIT}' in block(b.text, "## Paragraph: Adjacent structures (FINDINGS)")
    assert '- KEEP: "No free fluid."' not in b.text
    case = next(n for n in b.decisions["negatives"] if n["origin"] == "case" and n["text"] == "No free fluid.")
    assert case["action"] == "section_omitted"
    assert outcome(b, "No distant metastasis") == "section_omitted" and "metastasis" not in b.text
    # an If-present negative carrying the claim is OMIT, checked before route_finding
    sheet = OMIT_SHEET.replace(ADJ, ADJ.replace('\nNEGATIVE "No free fluid."', "")).replace(
        f'IF_PRESENT [focal lesion] "{VASC}." (contextual) | origin: case',
        f'IF_PRESENT [focal lesion] "{VASC}." (contextual) | origin: case\n'
        'IF_PRESENT [focal lesion] "No free fluid." (core) | origin: case')
    s = g.parse_sheet(sheet, mode="master").structure
    b, calls = await probe(monkeypatch, sheet, {"d1": 0.9, f"r{ridx}": 0.9, "f0": 0.95}, struct=s)
    assert outcome(b, "No free fluid") == "differential_present"
    assert f'- OMIT: "No free fluid." {CASE_OMIT}' in block(b.text, "## Paragraph: Primary organ (FINDINGS)")
    assert "No free fluid" not in calls["qwen"][0][0]


async def test_p3_not_visible_or_silent_differential_reported_is_addressed(monkeypatch):
    b, _ = await probe(monkeypatch, jev={"d2": 0.9, "d3": 0.9})
    cb = case_block(b.text)
    assert "- ADDRESS: Branch gamma — the dictation reports it" in cb and "- ADDRESS: Branch delta" in cb
    assert "- OPEN:" not in cb


async def test_p4_unmet_condition_beats_include_at_the_threshold(monkeypatch):
    plan = rc.ImpressionPlan(recommendations=[rc.RecDecision(index=i, decision="include") for i in range(3)],
                             impression=[0])
    b, _ = await probe(monkeypatch, jev={"rec0": 0.9, "rec1": 0.5, "rec2": 0.49}, plan=plan)
    assert [r["action"] for r in b.decisions["recommendations"]] == ["removed", "removed", "keep"]
    assert block(b.text, tb.RECOMMENDATIONS_HEADING).strip() == "- RECOMMEND: Image-guided biopsy"


async def test_p4b_unmet_investigation_excluded_as_routine_workup_is_barred(monkeypatch):
    plan = rc.ImpressionPlan(recommendations=[
        rc.RecDecision(index=1, decision="exclude", exclude_reason="routine_workup")], impression=[0])
    b, _ = await probe(monkeypatch, jev={"rec1": 0.9}, plan=plan)
    assert "- DO NOT RECOMMEND: Dedicated MRI of the primary organ" in block(b.text, tb.RECOMMENDATIONS_HEADING)


async def test_p5_finding_at_085_states_core_offers_contextual(monkeypatch):
    b, _ = await probe(monkeypatch, jev={"f0": 0.85})
    assert outcome(b, LYMPH) == "stated" and outcome(b, VASC) == "offered"


@pytest.mark.parametrize("drop", ["d0", "f0", "rec1", "r0"])
async def test_p6_partial_jev_answer_fails_closed(monkeypatch, drop):
    stub(monkeypatch)

    async def partial(state, qs):
        return {k: {"noul": 0.1} for k in qs if k != drop}
    monkeypatch.setattr(tb.rc, "_jev", partial)
    with pytest.raises(ValueError, match=drop):
        await tb.compile_template_brief(MASTER, MSTRUCT, "CT AP", FIND, "Pain.")


async def test_p6b_plan_failure_offers_investigations_never_writes_them(monkeypatch):
    b, _ = await probe(monkeypatch, plan=None)
    assert [(r["tag"], r["action"]) for r in b.decisions["recommendations"]] == [
        ("REFERRAL", "keep"), ("IMAGING", "optional"), ("TISSUE", "optional")]
    assert "MRI" not in b.text and "biopsy" not in b.text
    assert [o["text"] for o in b.decisions["options"] if o["kind"] == "recommendation"] == [
        "IMAGING: Dedicated MRI of the primary organ", "TISSUE: Image-guided biopsy"]


def test_p8_differential_names_differing_only_in_case_are_duplicates():
    r = g.parse_sheet(MASTER.replace("DIFFERENTIAL [Branch beta]", "DIFFERENTIAL [branch ALPHA]"), mode="master")
    assert g.DUPLICATE_DIFFERENTIAL in [e.reason for e in r.errors] and not r.structure.usable


async def test_p9_reasoning_block_holds_only_question_address_open(monkeypatch):
    plan = rc.ImpressionPlan(recommendations=[rc.RecDecision(index=0, decision="include"),
                                              rc.RecDecision(index=1, decision="exclude",
                                                             exclude_reason="routine_workup")], impression=[0])
    b, _ = await probe(monkeypatch, jev={"d0": 0.9, "f0": 0.95}, plan=plan)
    cb = [ln for ln in case_block(b.text).splitlines() if ln.strip()]
    assert cb[0] == tb.CASE_NOTE
    assert all(ln.startswith(("- CLINICAL QUESTION:", "- ADDRESS:", "- OPEN:")) for ln in cb[1:])
    assert "CLINICAL QUESTION" in tb.CASE_NOTE and "ADDRESS" in tb.CASE_NOTE and "OPEN" in tb.CASE_NOTE
    assert "RECOMMEND" not in tb.CASE_NOTE


async def test_p10_context_state_carries_prose_and_fixed_text_never_unit_lines(monkeypatch):
    sheet = MASTER.replace("Portal venous phase acquisition.",
                           "Portal venous phase acquisition.\n"
                           'RULE WHEN [context: intravenous contrast was not given] USE "Non-contrast study."\n'
                           'FIXED "Contrast: 100 ml intravenous."\n'
                           "Delayed phase WHEN [context: a urinary question is asked] only.")
    b, calls = await probe(monkeypatch, sheet)
    (ctx,) = [st for st, qs in calls["states"] if "PROTOCOL" in st]
    tech = ctx.split("PROTOCOL / TECHNIQUE:\n", 1)[1]
    assert "Portal venous phase acquisition." in tech and "Contrast: 100 ml intravenous." in tech
    assert "Delayed phase" in tech and "urinary" not in tech
    assert not any(w in tech for w in ("RULE", "USE", "WHEN", "intravenous contrast was not given", "FIXED"))


async def test_case_negative_targeting_a_differential_the_study_cannot_show_is_not_asserted(monkeypatch):
    # the parser blocks it (UNSUPPORTED_TARGET); the brief defends anyway
    negs = [n.model_copy(update={"targets": "Branch gamma"}) if n.targets == "Branch beta" else n
            for n in MSTRUCT.negatives]
    s = MSTRUCT.model_copy(update={"negatives": negs})
    b, calls = await probe(monkeypatch, struct=s)
    assert f'- DO NOT ASSERT: "No free fluid." — {tb.NOT_VISIBLE_REASON}' in block(
        b.text, "## Paragraph: Primary organ (FINDINGS)")
    assert next(n for n in b.decisions["negatives"] if n.get("targets") == "Branch gamma")["action"] == \
        "target_not_visible"
    assert g.UNSUPPORTED_TARGET in [e.reason for e in g.parse_sheet(
        MASTER.replace("TARGETS [Branch beta]", "TARGETS [Branch gamma]"), mode="master").errors]


# ── H4 round 2 (R3/R5/R6/R7): denial scope spans every written findings section and case units; chunked ──

async def probe_x(monkeypatch, sheet, jev, denials=(), struct=None):
    """probe() that also records every denial question as (key, statement) and the size of each Jev call."""
    s = struct or g.parse_sheet(sheet, mode="master").structure
    assert s.usable, s.lint_errors
    asked, sizes = [], []

    async def fake_jev(state, qs):
        xs = {k: q for k, q in qs.items() if k.startswith("x")}
        if xs:
            sizes.append(len(qs))
        out = {}
        for k, q in qs.items():
            ins = q["instructions"]
            if k.startswith("x"):
                stmt = ins.split("Statement: ", 1)[1]
                asked.append((k, stmt))
                out[k] = {"noul": 0.9 if any(n in ins and f in stmt for n, f in denials) else 0.1}
            else:
                out[k] = {"noul": jev.get(k, 0.1)}
        return out
    stub(monkeypatch)
    monkeypatch.setattr(tb.rc, "_jev", fake_jev)
    b = await tb.compile_template_brief(sheet, s, "CT AP", FIND, "Pain.")
    return b, asked, sizes


TWO_SECT = MASTER.replace(ADJ, ADJ.replace("No free fluid.", "No free intraperitoneal fluid.")).replace(
    'SECTION IMPRESSION | header: "Impression" | role: impression',
    'SECTION OTHER | header: "Other" | role: findings\nSECTION IMPRESSION | header: "Impression" | role: impression',
).replace("## Case Deliberation",
          '## Paragraph: Pelvis (OTHER)\nCOVERS ["pelvis"]\nNEGATIVE "No pelvic free fluid."\n'
          'NORMAL [pelvis] "The pelvic organs are normal, with no free fluid."\n\n## Case Deliberation')


async def test_r3_denial_check_spans_every_findings_section(monkeypatch):
    b, asked, _ = await probe_x(monkeypatch, TWO_SECT, {"d1": 0.9}, denials=[("Branch beta", "fluid")])
    pelvis = block(b.text, "## Paragraph: Pelvis (OTHER)")
    assert f'- OMIT: "No pelvic free fluid." {CASE_OMIT}' in pelvis
    assert '- DO NOT ASSERT AS NORMAL [pelvis]: "The pelvic organs are normal, with no free fluid."' in pelvis
    assert f'- OMIT: "No free intraperitoneal fluid." {CASE_OMIT}' in b.text
    stmts = {st for _, st in asked}
    assert "No pelvic free fluid." in stmts and "No free fluid." not in stmts  # its own case negative: not asked


CASEREWORD = MASTER.replace(f'IF_PRESENT [focal lesion] "{VASC}." (contextual) | origin: case',
                            'IF_PRESENT [focal lesion] "No intraperitoneal fluid." (core) | origin: case\n'
                            'NEGATIVE "No peritoneal fluid collection." TARGETS [Branch alpha] | origin: case')


async def test_r5_case_units_are_checked_for_denial(monkeypatch):
    b, asked, _ = await probe_x(monkeypatch, CASEREWORD, {"d1": 0.9, "f0": 0.95}, denials=[("Branch beta", "fluid")])
    para = block(b.text, "## Paragraph: Primary organ (FINDINGS)")
    assert f'- OMIT: "No peritoneal fluid collection." {CASE_OMIT}' in para  # case negative, other target
    assert f'- OMIT: "No intraperitoneal fluid." {CASE_OMIT}' in para  # case If-present, finding reported
    assert outcome(b, "No intraperitoneal fluid") == "denies_present_differential"
    assert '- KEEP: "No intraperitoneal fluid."' not in b.text
    # an If-present negative of an unreported finding is not asked (it is dropped anyway)
    _, asked, _ = await probe_x(monkeypatch, CASEREWORD, {"d1": 0.9, "f0": 0.2})
    assert "No intraperitoneal fluid." not in {st for _, st in asked}


async def test_r6_many_denial_questions_are_chunked_never_capped(monkeypatch, caplog):
    many = "\n".join(f'NEGATIVE "No abnormality of structure {i}."' for i in range(60)) + "\n" + \
        "\n".join(f'NORMAL [structure {i}] "Structure {i} is normal."' for i in range(40))
    sheet = MASTER.replace(ADJ, ADJ + "\n" + many)
    b, asked, sizes = await probe_x(monkeypatch, sheet, {"d0": 0.9, "d1": 0.9})
    assert len(asked) > tb.X_BUDGET_WARN and len(asked) == len({k for k, _ in asked})
    assert sizes and max(sizes) <= tb.X_CHUNK and sum(sizes) == len(asked) and len(sizes) >= 3
    assert "denial questions" in caplog.text


async def test_r6b_any_failed_denial_chunk_fails_closed(monkeypatch):
    many = "\n".join(f'NEGATIVE "No abnormality of structure {i}."' for i in range(100))
    sheet = MASTER.replace(ADJ, ADJ + "\n" + many)
    s = g.parse_sheet(sheet, mode="master").structure
    stub(monkeypatch)
    seen = []

    async def flaky(state, qs):
        if any(k.startswith("x") for k in qs):
            seen.append(1)
            if len(seen) == 2:
                raise TimeoutError("jev chunk timed out")
        return {k: {"noul": 0.9 if k == "d1" else 0.1} for k in qs}
    monkeypatch.setattr(tb.rc, "_jev", flaky)
    with pytest.raises(TimeoutError):
        await tb.compile_template_brief(sheet, s, "CT AP", FIND, "Pain.")


async def test_r7_omitted_section_units_are_not_asked_and_the_claim_is_still_omitted(monkeypatch):
    s = g.parse_sheet(OMIT_SHEET, mode="master").structure
    ridx = next(i for i, r in enumerate(s.rules) if r.effect == "suppress_section")
    b, asked, _ = await probe_x(monkeypatch, OMIT_SHEET, {"d1": 0.9, f"r{ridx}": 0.9, "f0": 0.95}, struct=s)
    stmts = {st for _, st in asked}
    assert "No distant metastasis." not in stmts  # in the omitted EXTRA section
    assert "No focal lesion." in stmts and "No free fluid." in stmts  # every written findings unit
    assert f'- OMIT: "No free fluid." {CASE_OMIT}' in block(b.text, "## Paragraph: Adjacent structures (FINDINGS)")
