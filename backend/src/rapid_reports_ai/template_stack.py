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

# Units that state or decide content (the grammar's keywords; optional indentation and "- " bullet, as it parses)
_CONTENT_UNITS = ("NORMAL", "NEGATIVE", "IF_PRESENT", "RECOMMEND", "DIFFERENTIAL", "QUESTION")
_CONTENT_UNIT = re.compile(rf"(?:{'|'.join(_CONTENT_UNITS)})\b")
_INTERPRETIVE = re.compile(r"(?i)interpretive phrasing\s*:")
# Blocks that decide content: "#"/"##" headings (a grammar context) and the "###" inclusion logic prose
_DROP_SECTION = re.compile(r"(?i)^(?:case deliberation|open questions)\b")
_DROP_SUBSECTION = re.compile(r"(?i)^inclusion logic\b")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


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
        if _CONTENT_UNIT.match(body) or _INTERPRETIVE.match(body):
            continue
        out.append(line)
    return out


def stack_brief(sheet: str, conclusion: str, declined: Sequence[str] = ()) -> str:
    """The template's grammar sheet as structure and style, then the scratchpad's session rules, the removed
    sentences (DO NOT ASSERT) and the confirmed conclusion."""
    try:
        lines = _strip(sheet or "")
    except Exception:  # structure from the findings block and the global guide alone
        lines = []
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    parts = [text] if text else []
    parts.append(
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
        "do not apply to it), unless a RULE whose condition the input meets suppresses or replaces it. "
        "A FIXED line with a {slot} is written only when the input gives that value; otherwise it is left out.\n"
        "- **Examples are wording only:** quoted Opening, Order, Abnormal pattern and Measurement lines are examples "
        "of the radiologist's wording. Copy their phrasing for what the input states; never their content: no finding, "
        "descriptor, value, grade, code, time window or interpretation from an example appears unless the input "
        "states it. The same holds for a style note or logic line that says the report states such content: it "
        "applies only when the input states it.")
    removed = [t.strip() for t in declined if t.strip()]
    if removed:
        parts.append("## Removed by the Radiologist\n" + "\n".join(f'- DO NOT ASSERT: "{t}"' for t in removed))
    if conclusion.strip():
        parts.append(
            "## Confirmed Conclusion\n"
            "- The radiologist's own conclusion; write the impression from it in report style and in this sheet's "
            "impression format, keeping every finding it names and adding nothing it does not contain — no diagnosis, "
            f'grade, negative or recommendation: "{conclusion.strip()}"')
    return "\n\n".join(parts)
