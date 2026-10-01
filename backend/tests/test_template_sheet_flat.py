"""E1b flat per-category structuring: candidates, rows, assembly through the unchanged verifier."""
from __future__ import annotations

import pathlib

from rapid_reports_ai import template_sheet_flat as flat
from rapid_reports_ai import template_sheet_structure as tss

SHEET = (pathlib.Path(__file__).parent / "fixtures" / "template_sheet.md").read_text()
LINES = SHEET.splitlines()


def no(text: str) -> int:
    return LINES.index(text) + 1


IF_APPEND = '- IF [inflammatory morphology] THEN append "consistent with {diagnosis}."'
IF_SUPPRESS = ('- IF [pneumoperitoneum is present] THEN suppress "No pneumoperitoneum." AND replace with '
               '"Free intra-abdominal air is present."')
IF_CONTEXT = '- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.'
MAND_BOTH = '  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."'
MAND_COND = '  - "No periappendiceal collection." (if appendicitis)'
NFR = '- "No pneumoperitoneum."'
NORMAL = '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'


def test_candidates_are_the_lines_the_gate_checks():
    c = flat.candidates(SHEET)
    assert c["if"] == [no(IF_APPEND), no(IF_SUPPRESS), no(IF_CONTEXT)]
    assert c["negative"] == [no(MAND_BOTH), no(MAND_COND), no(NFR)]
    assert [LINES[i - 1] for i in c["negative"]] == tss.negative_lines(SHEET)
    assert c["normal"] == [no(NORMAL)] and c["paragraphs"] == [no("### Primary Pathology Paragraph")]
    assert all(LINES[i - 1].strip() for i in c["layout"])


def test_lines_are_shown_numbered_under_their_headings():
    out = flat.show(SHEET, [no(MAND_COND)])
    assert "[## Per-Section Construction Rules > ### Primary Pathology Paragraph]" in out
    assert f"L{no(MAND_COND)}| {MAND_COND}" in out and "(under: - **Mandatory negatives**:)" in out


def test_prompts_are_case_agnostic():
    for p in (flat.LAYOUT_SYS, flat.IF_SYS, flat.NEG_SYS, flat.NORMAL_SYS, flat.TERM_SYS, flat.FIXED_SYS):
        for clinical in ("appendic", "pneumoperitoneum", "liver", "aort", "coronary"):
            assert clinical not in p.lower(), clinical


def fake(monkeypatch, outputs, seen):
    async def run(**kw):
        seen.append(kw)
        out = outputs[kw["output_type"]]
        if callable(out):
            out = out(kw)

        class R:
            output = out

            @staticmethod
            def usage():
                class U:
                    input_tokens, output_tokens = 10, 5
                return U
        return R
    monkeypatch.setattr(flat, "_run_agent_with_model", run)


def good_outputs(if_rows=None):
    return {
        flat.LayoutOut: flat.LayoutOut(
            sections=[flat.SecRow(name="CLINICAL HISTORY", role="history", header="CLINICAL HISTORY", order=0),
                      flat.SecRow(name="FINDINGS", role="findings", header=None, order=1),
                      flat.SecRow(name="IMPRESSION", role="impression", header="Impression", order=2)],
            paragraphs=[flat.ParaRow(line=no("### Primary Pathology Paragraph"), section="FINDINGS")]),
        flat.IfOut: flat.IfOut(rows=if_rows if if_rows is not None else [
            flat.IfRow(line=no(IF_APPEND), section="FINDINGS", condition="The dictated findings report inflammatory morphology",
                       effect="append", then_text="consistent with {diagnosis}."),
            flat.IfRow(line=no(IF_SUPPRESS), section="FINDINGS", condition="The dictated findings report pneumoperitoneum",
                       effect="replace", target="No pneumoperitoneum.", then_text="Free intra-abdominal air is present."),
            flat.IfRow(line=no(IF_CONTEXT), section="FINDINGS", condition="The clinical context is oncology",
                       condition_source="context", effect="use", then_text="no suspicious osseous lesion")]),
        flat.NegOut: flat.NegOut(rows=[
            flat.NegRow(line=no(MAND_BOTH), section="FINDINGS", text="No pneumoperitoneum."),
            flat.NegRow(line=no(MAND_BOTH), section="FINDINGS", text="No free intra-abdominal air or fluid."),
            flat.NegRow(line=no(MAND_COND), section="FINDINGS", text="No periappendiceal collection.",
                        condition="The dictated findings report appendicitis"),
            flat.NegRow(line=no(NFR), section="FINDINGS", text="No pneumoperitoneum.", condition="null")]),
        flat.NormOut: flat.NormOut(rows=[flat.NormRow(line=no(NORMAL), section="FINDINGS", structure="spleen",
                                                      text="Unremarkable appearances of the spleen.")]),
        flat.TermOut: flat.TermOut(rows=[flat.TermRow(term="unremarkable", kind="preferred")]),
        flat.FixedOut: flat.FixedOut(rows=[]),
    }


async def test_flat_rows_assemble_into_a_usable_verified_structure(monkeypatch):
    seen = []
    fake(monkeypatch, good_outputs(), seen)
    s, stats, _ = await flat.structure_sheet_flat(SHEET, model="m")
    assert s.usable, s.coverage
    assert [n.text for n in s.negatives] == ["No pneumoperitoneum.", "No free intra-abdominal air or fluid.",
                                             "No periappendiceal collection."]
    assert len(s.negatives[0].source_lines) == 2 and s.negatives[0].paragraph == "p0"   # the repeat folded in
    assert s.paragraphs[0].name == "Primary Pathology Paragraph" and s.rules[0].paragraph == ""
    assert stats["missing_rows"] == {"if": [], "negative": [], "normal": [], "terminology": [], "fixed": []}
    neg_call = next(k for k in seen if k["output_type"] is flat.NegOut)
    assert "SECTIONS: CLINICAL HISTORY | FINDINGS | IMPRESSION" in neg_call["user_prompt"]
    assert "No pneumoperitoneum" not in neg_call["user_prompt"].split("LINES:")[0]


async def test_an_other_row_is_tallied_never_a_rule(monkeypatch):
    seen = []
    rows = good_outputs()[flat.IfOut].rows
    rows[2] = flat.IfRow(line=no(IF_CONTEXT), effect="other", reason="implicit_target", note="no quoted target")
    fake(monkeypatch, good_outputs(rows), seen)
    s, stats, _ = await flat.structure_sheet_flat(SHEET, model="m")
    assert not s.usable and IF_CONTEXT.strip() in s.coverage.uncovered
    assert stats["other"] == {"implicit_target": 1} and stats["other_rows"][0]["line"] == no(IF_CONTEXT)


async def test_lines_without_a_row_are_asked_for_once_more(monkeypatch):
    seen = []
    outs = good_outputs()
    full = outs[flat.IfOut].rows

    def if_rows(kw):        # the first answer skips the context line; the follow-up supplies it
        asked = kw["user_prompt"].split("LINES:")[1]
        return flat.IfOut(rows=[r for r in full if f"L{r.line}|" in asked][: 2 if f"L{no(IF_APPEND)}|" in asked else 1])
    outs[flat.IfOut] = if_rows
    fake(monkeypatch, outs, seen)
    s, stats, _ = await flat.structure_sheet_flat(SHEET, model="m")
    assert s.usable and stats["missing_rows"]["if"] == []
    assert sum(k["output_type"] is flat.IfOut for k in seen) == 2


async def test_a_failed_category_leaves_its_lines_uncovered(monkeypatch):
    seen = []
    outs = good_outputs()

    def boom(kw):
        raise RuntimeError("down")
    outs[flat.NegOut] = boom
    fake(monkeypatch, outs, seen)
    s, stats, _ = await flat.structure_sheet_flat(SHEET, model="m")
    assert not s.usable and "RuntimeError" in stats["errors"]["negative"]
