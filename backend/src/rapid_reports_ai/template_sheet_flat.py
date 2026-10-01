"""Flat per-category structuring of a template skill sheet (E1b).

Code finds the candidate lines of each kind (conditional lines, negative lines, Normal pattern lines,
the Structural Pattern, ### paragraph headings, Terminology Rules, Fixed Blocks). One small call per
kind sees ONLY those numbered lines (with the heading each sits under) and returns a flat list of rows
keyed by line number. Code assembles a StructureDraft and runs the unchanged verifier
(template_sheet_structure.build_structure). A line no effect can represent is returned as effect
"other" with a reason: it never becomes a rule, so its line stays uncovered and the gate fails.

LAB ONLY: the LLM extractor is off in production (owner decision 2026-10-01). Its structures are
source="extracted" and template_sheet_structure.fresh() never serves them at generation time.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from typing import Dict, List, Literal, Optional

from pydantic import Field, field_validator

from . import template_sheet_structure as tss
from .enhancement_utils import _run_agent_with_model

CALL_TIMEOUT_S = 120.0
OtherReason = Literal["missing_values_list", "ordering", "insert_before", "implicit_target", "whole_section",
                      "header_choice", "other"]


# ── flat rows (no nested objects in model output) ───────────────────────────────

class SecRow(tss._Model):
    name: str
    role: tss.Role
    header: Optional[str] = None
    order: int


class ParaRow(tss._Model):
    line: int
    section: str


class LayoutOut(tss._Model):
    sections: List[SecRow] = Field(min_length=1)
    paragraphs: List[ParaRow] = []


class IfRow(tss._Model):
    line: int
    section: str = ""
    condition: str = ""
    condition_source: Literal["findings", "history", "context"] = "findings"
    effect: Literal["suppress", "replace", "append", "use", "other"]
    target: str = ""
    then_text: str = ""
    reason: Optional[OtherReason] = None
    note: str = ""


class NegRow(tss._Model):
    line: int
    section: str = ""
    text: str
    condition: Optional[str] = None

    @field_validator("condition", mode="before")
    @classmethod
    def _null_word(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in {"", "null", "none", "n/a"} else v


class NormRow(tss._Model):
    line: int
    section: str = ""
    structure: str = ""
    text: str


class TermRow(tss._Model):
    term: str
    kind: Literal["preferred", "suppressed"]


class FixedRow(tss._Model):
    section: str = ""
    text: str


class IfOut(tss._Model):
    rows: List[IfRow] = []


class NegOut(tss._Model):
    rows: List[NegRow] = []


class NormOut(tss._Model):
    rows: List[NormRow] = []


class TermOut(tss._Model):
    rows: List[TermRow] = []


class FixedOut(tss._Model):
    rows: List[FixedRow] = []


# ── candidate lines ─────────────────────────────────────────────────────────────

def _section_range(lines: List[str], title: str) -> List[int]:
    """1-based numbers of the lines inside '## <title>…' (heading excluded)."""
    out, inside = [], False
    for i, ln in enumerate(lines, 1):
        if ln.startswith("## "):
            inside = ln[3:].strip().lower().startswith(title.lower())
            continue
        if inside:
            out.append(i)
    return out


def candidates(sheet: str) -> Dict[str, List[int]]:
    lines = sheet.splitlines()
    per_section = set(_section_range(lines, "Per-Section Construction Rules"))
    return {
        "layout": [i for i in _section_range(lines, "Structural Pattern") if lines[i - 1].strip()],
        "paragraphs": [i for i in sorted(per_section) if lines[i - 1].startswith("### ")],
        "if": [i for i, ln in enumerate(lines, 1) if tss._IF.search(ln) and not ln.lstrip().startswith("#")],
        "negative": tss.negative_line_numbers(sheet),
        "normal": [i for i, ln in enumerate(lines, 1) if tss._NORMAL_PATTERN.search(tss._norm(ln))],
        "terminology": [i for i in _section_range(lines, "Terminology Rules") if lines[i - 1].strip()],
        "fixed": [i for i in _section_range(lines, "Fixed Blocks") if lines[i - 1].strip()],
    }


def _context(lines: List[str], i: int) -> tuple:
    """The ## and ### headings the line sits under, and the line it is nested under (if indented)."""
    h2 = h3 = ""
    for ln in lines[:i - 1]:
        if ln.startswith("## "):
            h2, h3 = ln.strip(), ""
        elif ln.startswith("### "):
            h3 = ln.strip()
    parent = ""
    ind = tss._indent(lines[i - 1])
    if ind:
        for ln in reversed(lines[:i - 1]):
            if ln.strip() and tss._indent(ln) < ind:
                parent = ln.strip()
                break
    return h2, h3, parent


def show(sheet: str, numbers: List[int]) -> str:
    """The candidate lines, numbered, grouped under their headings."""
    lines = sheet.splitlines()
    out, last = [], None
    for i in numbers:
        h2, h3, parent = _context(lines, i)
        head = " > ".join(h for h in (h2, h3) if h)
        if head != last:
            out.append(f"\n[{head or 'top'}]")
            last = head
        out.append(f"L{i}| {lines[i - 1]}" + (f"    (under: {parent[:160]})" if parent else ""))
    return "\n".join(out).strip()


# ── prompts (case-agnostic: structural placeholders only) ───────────────────────

COMMON = """You read numbered lines taken from a radiology report skill sheet (the reporter's own style guide) and return flat JSON rows. Each line is shown as "L<n>| <text>" under the heading it sits in; "(under: …)" shows the line it is nested under. The "L<n>| " prefix is not part of the line. Cite a line by its number (an integer). Copy text exactly as written between the quote marks on that line: same words and punctuation, nothing added, nothing from another line. Return at least one row for EVERY listed line. Return JSON only."""

LAYOUT_SYS = COMMON + """

sections — the report's OUTPUT sections exactly as the Structural Pattern lists them: one row per listed section (conditionally present ones included), name spelled exactly as the sheet writes it (a section listed as "[A] or [B]" is one row named that way); role: history | technique | comparison | findings | impression | other; header exactly as reports write it (null when the sheet says none or implicit); order (0-based). A paragraph grouping inside a section is not a section.

paragraphs — one row per "### " heading line listed under PARAGRAPH HEADINGS: line, and section: the name (as in your sections) of the output section that paragraph belongs to."""

IF_SYS = COMMON + """

Each line holds an uppercase IF conditional. One row per line; several rows citing the same line when it suppresses or replaces several quoted texts (one per text).
- section: the output section (one of SECTIONS, written exactly) the line applies to.
- condition: the IF condition as one plain statement that can be judged true or false for a case: "The dictated findings report [X]" for an imaging condition, "The clinical history reports [Y]" or "The clinical context is [Z]" otherwise. Keep the subject: when the IF names no subject of its own ("IF abnormal", "IF present"), take it from the line's label or from the line it is under ("<Label>: IF abnormal THEN …" gives "The dictated findings report abnormal <Label>").
- condition_source: findings | history | context.
- effect: suppress (drop the target text) | replace (drop the target text and write then_text) | append (add then_text) | use (write then_text as a phrasing variant) | other.
- A line "IF [X] THEN "[text]"" that only says what to write (nothing quoted is dropped) is use (a whole sentence) or append (a clause added to a sentence), never replace.
- target: the quoted text it suppresses or replaces, else "". then_text: the quoted or [bracketed] text it adds or uses, else "". suppress and replace need a target; replace, append and use need a then_text.
- effect other, when none of the four fits; reason: missing_values_list (generate a list of missing values) | ordering (place or move content) | insert_before (insert text before a named text) | implicit_target (drop or replace something not quoted on the line, e.g. "the phrase", "the standard sentence") | whole_section (drop a whole section or block) | header_choice (choose a header) | other; note: a few words."""

NEG_SYS = COMMON + """

Each line lists negative or normal-state statements a report states. One row per quoted statement: a line with two quotes gives two rows; a quote holding several sentences gives one row per sentence.
- text: the statement exactly as written.
- condition: read the line outside its quotes. When it says in which case the statement is written or dropped (an if, when, only, unless, used-if or "in … cases" qualifier, or a label naming a kind of case, study or context), condition is the case in which the statement IS written, as a plain statement ("The dictated findings report [X]", "The dictated findings do not report [Y]", "The clinical context is [Z]"). Otherwise null. Never add a condition the line does not state.
  - "No [A]." (if [X])  →  condition "The dictated findings report [X]"
  - "No [A]." (Suppress if [Y])  →  condition "The dictated findings do not report [Y]"
  - **[Label]**: "No [B]."  →  condition null
- section: the output section (one of SECTIONS, written exactly) the statement belongs to."""

NORMAL_SYS = COMMON + """

Each line is a Normal pattern. Split it into one row per structure it names: structure (the structure's name); text: a sentence for that structure alone, using only words from the line in their order ("Unremarkable appearances of the [A], [B] and [C]." gives "Unremarkable appearances of the [A]." and so on); never add values or findings the line does not state as normal; section: one of SECTIONS, written exactly."""

TERM_SYS = COMMON + """

These are the sheet's terminology rules. One row per term: term exactly as written; kind: preferred | suppressed. A line naming no term gives no row (then return its other terms only)."""

FIXED_SYS = COMMON + """

These lines are the sheet's Fixed Blocks section. One row per fixed block: section (one of SECTIONS, written exactly), text: the block's text exactly (line breaks kept, without the "L<n>| " prefixes). No rows when the sheet says none were identified."""


# ── calls ───────────────────────────────────────────────────────────────────────

def _settings(model: str) -> dict:
    return {"temperature": 0, "max_tokens": 16384, "reasoning_effort": "medium"}


async def _call(model: str, system: str, user: str, out_type, stats: dict, kind: str):
    t0 = time.time()
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=model, output_type=out_type, system_prompt=system, user_prompt=user, api_key="",
        model_settings=_settings(model)), CALL_TIMEOUT_S)
    st = stats.setdefault(kind, {"ms": 0, "in": 0, "out": 0, "calls": 0})
    st["ms"] += int((time.time() - t0) * 1000)
    st["calls"] += 1
    try:
        u = r.usage()
        st["in"] += getattr(u, "input_tokens", None) or getattr(u, "request_tokens", 0) or 0
        st["out"] += getattr(u, "output_tokens", None) or getattr(u, "response_tokens", 0) or 0
    except Exception:
        pass
    return r.output


async def _rows(model, system, sheet, numbers, out_type, stats, kind, sections_note):
    """Rows for the candidate lines; lines left without a row are asked for once more."""
    if not numbers:
        return []
    rows = (await _call(model, system, f"{sections_note}LINES:\n{show(sheet, numbers)}", out_type, stats, kind)).rows
    keyed = out_type in (IfOut, NegOut, NormOut)   # rows cite a line; every candidate line needs one
    missing = [i for i in numbers if i not in {r.line for r in rows}] if keyed else []
    if missing:
        more = (await _call(model, system, f"{sections_note}LINES:\n{show(sheet, missing)}", out_type, stats, kind)).rows
        rows += more
        missing = [i for i in missing if i not in {r.line for r in more}]
    stats.setdefault("missing_rows", {})[kind] = missing
    return rows


async def structure_sheet_flat(sheet: str, model: Optional[str] = None):
    """Returns (SheetStructure, diagnostics)."""
    model = model or tss.structure_model()
    c = candidates(sheet)
    stats: dict = {"errors": {}}
    lines = sheet.splitlines()

    layout_user = (f"STRUCTURAL PATTERN:\n{show(sheet, c['layout'])}\n\nPARAGRAPH HEADINGS:\n"
                   f"{show(sheet, c['paragraphs']) if c['paragraphs'] else '(none)'}")
    layout = await _call(model, LAYOUT_SYS, layout_user, LayoutOut, stats, "layout")
    names = [s.name for s in layout.sections]
    note = "SECTIONS: " + " | ".join(names) + "\n\n"

    async def safe(kind, coro):
        try:
            return await coro
        except Exception as e:
            stats["errors"][kind] = f"{type(e).__name__}: {str(e)[:200]}"
            return []

    if_rows, neg_rows, norm_rows, term_rows, fixed_rows = await asyncio.gather(
        safe("if", _rows(model, IF_SYS, sheet, c["if"], IfOut, stats, "if", note)),
        safe("negative", _rows(model, NEG_SYS, sheet, c["negative"], NegOut, stats, "negative", note)),
        safe("normal", _rows(model, NORMAL_SYS, sheet, c["normal"], NormOut, stats, "normal", note)),
        safe("terminology", _rows(model, TERM_SYS, sheet, c["terminology"], TermOut, stats, "terminology", note)),
        safe("fixed", _rows(model, FIXED_SYS, sheet, c["fixed"], FixedOut, stats, "fixed", note)))

    # paragraphs: the heading as written; items take the paragraph of the ### heading they sit under
    para_of_heading = {}
    paragraphs = []
    for p in layout.paragraphs:
        if p.line in c["paragraphs"] and p.line not in para_of_heading:
            pid = f"p{len(paragraphs)}"
            para_of_heading[p.line] = pid
            paragraphs.append(tss.Paragraph(id=pid, section=p.section, name=lines[p.line - 1][4:].strip()))

    def para(line: int) -> str:
        for i in range(line - 1, 0, -1):
            if lines[i - 1].startswith("## "):
                return ""
            if lines[i - 1].startswith("### "):
                return para_of_heading.get(i, "")
        return ""

    others = Counter()
    other_rows = []
    rules = []
    for r in if_rows:
        if r.effect == "other":
            others[r.reason or "other"] += 1
            other_rows.append({"line": r.line, "reason": r.reason or "other", "note": r.note,
                               "text": lines[r.line - 1].strip() if 0 < r.line <= len(lines) else ""})
            continue
        rules.append(tss.Rule(id=f"r{len(rules)}", section=r.section, paragraph=para(r.line), condition=r.condition,
                              condition_source=r.condition_source, effect=r.effect, target=r.target,
                              then_text=r.then_text, source_lines=[r.line]))
    negatives = [tss.Negative(id=f"n{i}", section=r.section, paragraph=para(r.line), text=r.text,
                              condition=r.condition, source_lines=[r.line]) for i, r in enumerate(neg_rows)]
    normals = [tss.Normal(id=f"m{i}", section=r.section, paragraph=para(r.line), structure=r.structure, text=r.text,
                          source_line=r.line) for i, r in enumerate(norm_rows)]
    term = tss.Terminology(preferred=[t.term for t in term_rows if t.kind == "preferred"],
                           suppressed=[t.term for t in term_rows if t.kind == "suppressed"])
    fixed = [tss.FixedBlock(id=f"f{i}", section=r.section, text=r.text) for i, r in enumerate(fixed_rows)]
    draft = tss.StructureDraft(
        sections=[tss.StructSection(name=s.name, role=s.role, header=s.header, order=s.order) for s in layout.sections],
        paragraphs=paragraphs, rules=rules, negatives=negatives, normals=normals, fixed_blocks=fixed, terminology=term)
    stats["other"] = dict(others)
    stats["other_rows"] = other_rows
    stats["candidates"] = {k: len(v) for k, v in c.items()}
    return tss.build_structure(sheet, draft, model), stats, draft
