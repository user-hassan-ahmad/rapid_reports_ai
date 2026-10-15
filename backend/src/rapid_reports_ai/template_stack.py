"""The brief of a templated scratchpad session (the template mirror of quick_report_brief.stack_fallback).

The radiologist confirmed every statement (dictated, answered, assumed normal), the conclusion and the removed
sentences in the scratchpad, so the template's grammar sheet keeps only what shapes the report: sections, headers,
paragraph order and patterns, terminology, fixed blocks, rules, reference values and impression format. The units
that state or decide content are taken out, by the grammar's own unit syntax (template_sheet_grammar: every
negative and normal in a lint-clean sheet is a unit line; a prose negative fails the save): NORMAL, NEGATIVE,
IF_PRESENT and the case units, plus interpretive phrasing, the impression's inclusion logic and the case
deliberation and open questions. The assumed normals the radiologist confirmed came from the same NORMAL and
NEGATIVE units (hybrid_stack.template.template_region_normals). Pure code; never raises. Read with
global_style_guide's _STACK prompts.
"""
from __future__ import annotations

import re
from typing import List, Sequence

from .template_sheet_grammar import _BULLET
from .hybrid_stack.session_rules import RECOMMENDATIONS_RULE

# Units that state or decide content (the grammar's keywords; optional indentation and "- " bullet, as it parses)
_CONTENT_UNITS = ("NORMAL", "NEGATIVE", "IF_PRESENT", "RECOMMEND", "DIFFERENTIAL", "QUESTION")
_CONTENT_UNIT = re.compile(rf"(?:{'|'.join(_CONTENT_UNITS)})\b")
# A habit question (spec 2026-10-13-findings-triggered-rows-design) is asked in the scratchpad, never by the generator:
# its answer reaches the FINDINGS input as "Answered by the radiologist". (Its required-statement twin is a NEGATIVE.)
_HABIT_RULE = re.compile(r"RULE\s+WHEN\s*\[\s*findings\s*:[^\]]*\]\s*ASK\b")
_INTERPRETIVE = re.compile(r"(?i)interpretive phrasing\s*:")
# Blocks that decide content: "#"/"##" headings (a grammar context) and the "###" inclusion logic prose
_DROP_SECTION = re.compile(r"(?i)^(?:case deliberation|open questions)\b")
_DROP_SUBSECTION = re.compile(r"(?i)^inclusion logic\b")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
# Code owns the template's required values (the value cluster's answers, or with no cluster a Jev check of every item):
# it removed LIST_MISSING from this sheet and writes the "Values not provided" line itself (template_required_values),
# so the generator writes none.
MISSING_VALUES_RULE = (
    "\n- **Missing values:** this template's required values are handled outside the report, and code "
    "adds the \"Values not provided\" line itself: write no list of missing or unprovided values, and no "
    "placeholder for one.")
# Dictation wins over an earlier removal (as the scratchpad's reconcile does, hybrid_stack.removed_guard): the writer
# must never resolve "every FINDINGS statement appears" against "no DO NOT ASSERT statement appears" by dropping a
# dictated statement about the same structure (fidelity track Q3, 2026-10-15).
REMOVED_RULE = (
    "The radiologist removed these default sentences. Dictated findings always win: every statement in the FINDINGS "
    "input appears with its meaning unchanged, even one about the same structure as a removed sentence, under "
    "another name or with a value. A DO NOT ASSERT line never removes, shortens or rewords a FINDINGS statement; it "
    "forbids only the removed sentence itself, in any wording, where no FINDINGS statement says it.")


def _strip(sheet: str) -> List[str]:
    out: List[str] = []
    skip_level = 0  # heading depth being skipped (0: none)
    for line in sheet.splitlines():
        if m := _HEADING.match(line):
            level, title = len(m.group(1)), m.group(2).strip()
            if skip_level and level > skip_level:
                continue
            skip_level = 0
            if (level <= 2 and _DROP_SECTION.match(title)) or (level == 3 and _DROP_SUBSECTION.match(title)):
                skip_level = level
                continue
            out.append(line)
            continue
        if skip_level:
            continue
        body = line[_BULLET.match(line).end():]
        if _CONTENT_UNIT.match(body) or _INTERPRETIVE.match(body) or _HABIT_RULE.match(body):
            continue
        out.append(line)
    return out


def stack_brief(sheet: str, conclusion: str, declined: Sequence[str] = (), values_decided: bool = False) -> str:
    """The template's grammar sheet as structure and style, then the scratchpad's session rules, the removed
    sentences (DO NOT ASSERT) and the confirmed conclusion."""
    try:
        lines = _strip(sheet or "")
    except Exception:  # structure from the findings block and the global guide alone
        lines = []
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    parts = [text] if text else []
    session = (
        "## Scratchpad Session\n"
        "These rules outrank every other rule in this sheet and in the Global Style Guide.\n"
        "- **Content and flow:** the FINDINGS input is the radiologist's confirmed statements, grouped by scratchpad "
        "region only so each can be traced (lines marked 'Answered by the radiologist' or 'Assumed normal' are "
        "confirmed statements like the rest). Write them in the sections, paragraphs, order and joining the skill "
        "sheet sets (an abnormal finding leads its paragraph), never in the input's order or under its labels unless "
        "the skill sheet uses those headings. The skill sheet only decides WHERE the input's statements go: a "
        "structure or paragraph it describes that the input does not mention is left out entirely, never filled with "
        "a normal statement or an Opening pattern of its own. Every statement in the input appears, with its meaning "
        "unchanged; statements about the same structure may be joined into one sentence, naming only the structures "
        "the input names; nothing is added.\n"
        "- **Required statements:** a rule in this sheet that requires a statement (always mention, always state, "
        "always close with) applies only when the FINDINGS input contains that statement, and then only decides "
        "where it goes; otherwise the rule is skipped and that structure is not mentioned.\n"
        "- **Fixed lines:** a FIXED line is the template's fixed wording (what was performed, standard text): it is "
        "written as it stands in its place, even when the input does not mention its structure (the two rules above "
        "do not apply to it), unless a RULE whose condition the input meets suppresses or replaces it, or the input "
        "or the clinical history states otherwise: a FIXED line never contradicts the input, the clinical history "
        "or their values (side, contrast, sequence, dates). Where they give different values, adapt the line's "
        "values; where the line asserts something they contradict, leave it out. A FIXED line that is a RULE's replacement (WITH) text is written only when that "
        "RULE applies. A FIXED line with {slots} is written only when the input gives every slot's value; otherwise "
        "it is left out, except a line listed under Decided for This Case, which is written as that block says.\n"
        "- **Examples are wording only:** quoted Opening, Order, Abnormal pattern and Measurement lines are examples "
        "of the radiologist's wording. Copy their phrasing for what the input states; never their content: no finding, "
        "descriptor, value, grade, code, time window or interpretation from an example appears unless the input "
        "states it. The same holds for a style note or logic line that says the report states such content: it "
        "applies only when the input states it.\n"
        "- **Scores, grades and values:** a sheet instruction to state a score, grade, classification, time window, "
        "measurement, value, image coordinate or recommendation applies only when the FINDINGS input or the "
        "confirmed conclusion supplies it, even where the sheet calls it mandatory or always stated; otherwise "
        "leave it out — never estimate, infer or fill one in.\n"
        + RECOMMENDATIONS_RULE)   # the one rule both stack briefs share (D22)
    if values_decided:
        session += MISSING_VALUES_RULE
    parts.append(session)
    removed = [t.strip() for t in declined if t.strip()]
    if removed:
        parts.append("## Removed by the Radiologist\n" + REMOVED_RULE + "\n"
                     + "\n".join(f'- DO NOT ASSERT: "{t}"' for t in removed))
    if conclusion.strip():
        parts.append(
            "## Confirmed Conclusion\n"
            "- The radiologist's own conclusion; write the impression from it in report style and in this sheet's "
            "impression format, keeping every finding it names and adding nothing it does not contain — no diagnosis, "
            f'grade or negative; a recommendation only as the session rules allow: "{conclusion.strip()}"')
    return "\n\n".join(parts)
