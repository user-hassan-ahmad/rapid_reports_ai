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

STRUCT = g.parse_sheet(SHEET).structure
# rule positions (Jev keys r<i>)
R_REPLACE, R_APPEND, R_USE, R_INSERT, R_ORDER, R_SUPNEG, R_LIST, R_SUPPRESS, R_SECTION, R_HEADERS = range(10)
CTX_RULES = {f"r{R_APPEND}", f"r{R_USE}", f"r{R_SECTION}", f"r{R_HEADERS}"}


def test_fixture_parses_usable():
    assert STRUCT.usable and STRUCT.source == "grammar", STRUCT.lint_errors
    assert [r.effect for r in STRUCT.rules] == ["replace", "append", "use", "insert_before", "order",
                                                "suppress_paragraph_negatives", "list_missing", "suppress",
                                                "suppress_section", "suppress_headers"]


def stub(monkeypatch, jev_f: dict | None = None, jev_c: dict | None = None, qwen: rc.QwenDecisions | None = None,
         plan: rc.ImpressionPlan | None = None, fallback: rc.FallbackNegatives | None = None):
    """Jev answers by key ({"r0": 0.9}); unlisted keys score 0.1. Records every call."""
    calls: dict = {"jev": [], "qwen": [], "fallback": [], "plan": []}
    jev_f, jev_c = jev_f or {}, jev_c or {}

    async def fake_jev(state, qs):
        ctx = "CLINICAL HISTORY" in state
        calls["jev"].append((ctx, set(qs)))
        src = jev_c if ctx else jev_f
        return {k: {"noul": src.get(k, 0.1)} for k in qs}

    async def fake_qwen(state, negs, normals, measurements):
        calls["qwen"].append((list(negs), list(normals)))
        return qwen or rc.QwenDecisions(negatives=[], affected_normals=[], applicable_measurements=[])

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
    assert '- KEEP: "No free fluid."' in report_wide   # the same negative elsewhere is not suppressed


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
    s = g.parse_sheet(sheet).structure
    calls = stub(monkeypatch, jev_c={"c1": 0.9})
    b = await tb.compile_template_brief(sheet, s, "CT AP", "Lesion.", "?inflammation")
    assert '- KEEP: "No surrounding collection."' in b.text
    assert "c1" in next(qs for c, qs in calls["jev"] if c)


async def test_classifier_labels_and_every_copy_shares_one_label(monkeypatch):
    # distinct negatives in sheet order: focal lesion, surrounding collection, free fluid, lymphadenopathy…, artefact
    q = rc.QwenDecisions(negatives=[rc.NegativeDecision(index=2, action="contradicted", dictated_finding="free fluid"),
                                    rc.NegativeDecision(index=3, action="expected", dictated_finding="the mass")],
                         affected_normals=[], applicable_measurements=[])
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
    q = rc.QwenDecisions(negatives=[], affected_normals=[1], applicable_measurements=[])
    stub(monkeypatch, qwen=q)
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
