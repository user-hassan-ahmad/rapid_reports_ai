"""The brief of a templated scratchpad session (the template mirror of quick_report_brief.stack_fallback).

The radiologist confirmed every statement (dictated, answered, assumed normal), the conclusion and the removed
sentences in the scratchpad, so the template's skill sheet keeps only what shapes the report: sections, headers,
paragraph order and patterns, terminology, fixed blocks, reference values and impression format. Everything that
decides content of its own is taken out: negatives, normal statements, suppression and interpretive rules,
inclusion logic and case deliberation. Both sheet formats are handled (v1 bullets, grammar statements). Pure code;
never raises. Read with global_style_guide's _STACK prompts.
"""
from __future__ import annotations

import re
from typing import List, Sequence

# Whole sections (## headings) and sub-sections (### headings) that decide content
_DROP_SECTION = re.compile(r"(?i)^(?:interpretive clause rules|conditional suppression rules|negative finding rules"
                           r"|case deliberation|open questions)\b")
_DROP_SUBSECTION = re.compile(r"(?i)^inclusion logic\b")
# Grammar statements that state, offer or decide content
_DROP_LINE = re.compile(r"^\s*(?:NORMAL|NEGATIVE|IF_PRESENT|RECOMMEND|DIFFERENTIAL|QUESTION)\b|^\s*Interpretive phrasing\s*:")
# v1 bullets that state content, with their indented continuation lines
_DROP_BULLET = re.compile(r"(?i)^(\s*)-\s+\*\*(?:mandatory negatives|normal pattern)\b")
_HEADING = re.compile(r"^(#{2,3})\s+(.*)$")


def _strip(sheet: str) -> List[str]:
    out: List[str] = []
    skip_level = 0          # heading depth being skipped (0: none)
    bullet_indent = -1      # indent of a dropped bullet whose continuation lines are skipped
    for line in sheet.splitlines():
        if m := _HEADING.match(line):
            level, title = len(m.group(1)), m.group(2).strip()
            bullet_indent = -1
            if skip_level and level > skip_level:
                continue
            skip_level = 0
            if (level == 2 and _DROP_SECTION.match(title)) or (level == 3 and _DROP_SUBSECTION.match(title)):
                skip_level = level
                continue
            out.append(line)
            continue
        if skip_level:
            continue
        if bullet_indent >= 0:
            if line.strip() and len(line) - len(line.lstrip()) > bullet_indent:
                continue
            bullet_indent = -1
        if m := _DROP_BULLET.match(line):
            bullet_indent = len(m.group(1))
            continue
        if _DROP_LINE.match(line):
            continue
        out.append(line)
    return out


def stack_brief(sheet: str, conclusion: str, declined: Sequence[str] = ()) -> str:
    """The template skill sheet as structure and style, then the scratchpad's session rules, the removed sentences
    (DO NOT ASSERT) and the confirmed conclusion."""
    try:
        lines = _strip(sheet or "")
    except Exception:  # structure from the findings block and the global guide alone
        lines = []
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    parts = [text] if text else []
    parts.append(
        "## Scratchpad Session\n"
        "- **Content and flow:** the FINDINGS input is the radiologist's confirmed statements, grouped by scratchpad "
        "region only so each can be traced (lines marked 'Answered by the radiologist' or 'Assumed normal' are "
        "confirmed statements like the rest). Write them in the sections, paragraphs, order and joining the skill "
        "sheet sets (an abnormal finding leads its paragraph), never in the input's order or under its labels unless "
        "the skill sheet uses those headings. The skill sheet only decides WHERE the input's statements go: a "
        "structure or paragraph it describes that the input does not mention is left out entirely, never filled with "
        "a normal statement or an Opening pattern of its own. Every statement in the input appears, with its meaning "
        "unchanged; statements about the same structure may be joined into one sentence, naming only the structures "
        "the input names; nothing is added.")
    if declined:
        parts.append("## Removed by the Radiologist\n" + "\n".join(
            f'- DO NOT ASSERT: "{t}"' for t in declined if t.strip()))
    if conclusion.strip():
        parts.append(
            "## Confirmed Conclusion\n"
            "- The radiologist's own conclusion; write the impression from it in report style and in this sheet's "
            "impression format, keeping every finding it names and adding nothing it does not contain — no diagnosis, "
            f'grade, negative or recommendation: "{conclusion.strip()}"')
    return "\n\n".join(parts)
