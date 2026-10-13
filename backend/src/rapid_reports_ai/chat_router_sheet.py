"""Reading a grammar sheet line by line for the chat-edit router (spec 2026-10-13-chat-edit-router-design): which
lines are units (owned by code), which are prose (the only lines the style call may edit), each line's heading and
paragraph, splicing edited prose back, and the unit-line guard ("code rejects the result if any unit line differs
from the input"). Pure."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import template_sheet_grammar as tsg

_HEAD = re.compile(r"^(#{1,2})\s+(.*?)\s*$")       # "#"/"##" open a context; "###" is prose (grammar :158)
_FIRST = re.compile(r"^([A-Z][A-Z_]*)\b")
_QUOTED = re.compile(r'"([^"]*)"')
_TITLE = re.compile(r"^#\s+Skill Sheet:\s*(.+?)\s*$", re.M)
NO_STYLE = ("scan context", "report structure")      # prose the style call never sees or edits


def norm(s: str) -> str:
    return " ".join((s or "").lower().split())


@dataclass(frozen=True)
class Line:
    i: int            # 0-based index in sheet.splitlines()
    text: str
    heading: str      # the current "#"/"##" heading title ("" before the first)
    paragraph: str    # the paragraph name under "## Paragraph: …", else ""
    section: str      # that paragraph's section as written, else ""
    keyword: str      # a unit keyword (FIXED, NORMAL, …), "#" for a heading, "" for prose


@dataclass(frozen=True)
class Block:
    id: str           # "b1", "b2", … in sheet order
    heading: str
    start: int        # lines [start, end)
    end: int
    text: str


def _keyword(raw: str) -> str:
    m = _FIRST.match(tsg._undecorate(raw))
    return m.group(1) if m and m.group(1) in tsg.KEYWORDS else ""


def walk(sheet: str) -> List[Line]:
    out: List[Line] = []
    heading = para = sec = ""
    for i, raw in enumerate((sheet or "").splitlines()):
        h = _HEAD.match(raw)
        if h:
            heading = h.group(2)
            ph = tsg.paragraph_heading(heading) if h.group(1) == "##" else None
            para, sec = (ph[0], ph[1]) if ph else ("", "")
            out.append(Line(i, raw, heading, para, sec, "#"))
        else:
            out.append(Line(i, raw, heading, para, sec, _keyword(raw)))
    return out


def unit_lines(sheet: str) -> List[str]:
    """Every heading and unit line, in order (what a style edit must leave exactly as it was)."""
    return [l.text.strip() for l in walk(sheet) if l.keyword]


def units_unchanged(before: str, after: str) -> bool:
    return unit_lines(before) == unit_lines(after)


def prose_blocks(sheet: str) -> List[Block]:
    """Maximal runs of prose lines between units and headings, blank edges trimmed, outside NO_STYLE headings."""
    blocks: List[Block] = []
    run: List[Line] = []

    def flush() -> None:
        body = list(run)
        run.clear()
        while body and not body[0].text.strip():
            body.pop(0)
        while body and not body[-1].text.strip():
            body.pop()
        if body and norm(body[0].heading) not in NO_STYLE:
            blocks.append(Block(f"b{len(blocks) + 1}", body[0].heading, body[0].i, body[-1].i + 1,
                                "\n".join(l.text for l in body)))

    for l in walk(sheet):
        if l.keyword:
            flush()
        else:
            run.append(l)
    flush()
    return blocks


def join(lines: List[str], like: str) -> str:
    return "\n".join(lines) + ("\n" if (like or "").endswith("\n") else "")


def splice(sheet: str, edits: Dict[str, str]) -> str:
    """The sheet with each prose block (by id) replaced by its edited text; unknown ids are ignored."""
    blocks = {b.id: b for b in prose_blocks(sheet)}
    lines = (sheet or "").splitlines()
    for b in sorted((blocks[k] for k in edits if k in blocks), key=lambda b: -b.start):
        lines[b.start:b.end] = (edits[b.id] or "").strip("\n").splitlines()
    return join(lines, sheet)


def new_lines(before: str, after: str) -> List[str]:
    """Non-blank lines of `after` that `before` does not have (case and spacing ignored)."""
    old = {norm(x) for x in (before or "").splitlines() if x.strip()}
    return [x.strip() for x in (after or "").splitlines() if x.strip() and norm(x) not in old]


def quoted(line: str) -> str:
    m = _QUOTED.search(line or "")
    return m.group(1) if m else ""


def scan_type(sheet: str) -> str:
    m = _TITLE.search(sheet or "")
    return m.group(1) if m else ""


def paragraphs(sheet: str) -> List[Tuple[str, str]]:
    """(name, section as written) of every paragraph, in sheet order."""
    return [(l.paragraph, l.section) for l in walk(sheet) if l.keyword == "#" and l.paragraph]


def paragraph_span(sheet: str, name: str) -> Tuple[int, int]:
    """[start, end) lines of the paragraph block `name` (its heading up to the next heading); KeyError if absent."""
    walked = walk(sheet)
    start = next((l.i for l in walked if l.keyword == "#" and l.paragraph and norm(l.paragraph) == norm(name)), None)
    if start is None:
        raise KeyError(name)
    end = next((l.i for l in walked if l.keyword == "#" and l.i > start), len(walked))
    return start, end


def section_lines(sheet: str) -> List[Line]:
    return [l for l in walk(sheet) if l.keyword == "SECTION"]
