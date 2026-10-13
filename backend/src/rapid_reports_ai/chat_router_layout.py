"""Layout operations for the chat-edit router (spec Flow 2: "Layout changes use the same structure operations on
SECTION / paragraph headings"; plan decision 7): rename, move, remove or add a paragraph or a section. Each returns
(sheet, inverse ops). Names match case-insensitively; a section matches by its name or its printed heading. Called
through chat_router_edits.apply_op, which refuses any result that adds a grammar error."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import chat_router_sheet as sh
from . import template_sheet_grammar as tsg
from .chat_router_edits import EditError

_PLAIN_NAME = re.compile(r'^[A-Za-z0-9][^()|"“”#\[\]{}]{0,59}$')
_SECTION_NAME = re.compile(r"^[A-Z0-9][A-Z0-9 /&-]*$")
_SEC = re.compile(r'SECTION\s+(?P<name>.+?)\s*\|\s*header:\s*(?:none|"(?P<header>[^"]*)")')
_HEADER_ATTR = re.compile(r'header:\s*(?:none|"[^"]*")')
_ITEM_BAD = re.compile(r'["|\[\]{}]')


def _name(t: str, what: str) -> str:
    t = " ".join((t or "").split())
    if not _PLAIN_NAME.match(t):
        raise EditError(f"{what}: a short plain name")
    return t


def _para(sheet: str, name: str) -> sh.Line:
    l = next((l for l in sh.walk(sheet) if l.keyword == "#" and l.paragraph and sh.norm(l.paragraph) == sh.norm(name)),
             None)
    if l is None:
        raise EditError(f"no paragraph {name!r}")
    return l


def _sections(sheet: str) -> List[Tuple[sh.Line, str, Optional[str]]]:
    out = []
    for l in sh.section_lines(sheet):
        m = _SEC.match(tsg._undecorate(l.text))
        if m:
            out.append((l, m.group("name").strip(), m.group("header")))
    return out


def _section(sheet: str, target: str) -> Tuple[sh.Line, str, Optional[str]]:
    t = sh.norm((target or "").strip().rstrip(":"))
    for l, name, header in _sections(sheet):
        if sh.norm(name) == t or (header and sh.norm(header.strip().rstrip(":")) == t):
            return l, name, header
    raise EditError(f"no section {target!r}")


def section_name(sheet: str, target: str) -> str:
    return _section(sheet, target)[1]


def _heading(name: str, section: str, header: Optional[str] = None) -> str:
    return f"## Paragraph: {name} ({section})" + (f' | header: "{header}"' if header else "")


def _covers_items(covers) -> List[str]:
    items = [" ".join(str(c).split()) for c in covers or [] if str(c).strip()]
    if any(_ITEM_BAD.search(c) for c in items):
        raise EditError("covered structures: plain names only")
    return items


# ── paragraphs ──────────────────────────────────────────────────────────────────────────────────────────────────
def rename_paragraph(sheet: str, paragraph: str, to: str):
    l = _para(sheet, paragraph)
    new = _name(to, "paragraph name")
    if sh.norm(new) != sh.norm(l.paragraph) and any(sh.norm(n) == sh.norm(new) for n, _ in sh.paragraphs(sheet)):
        raise EditError(f"there is already a paragraph called {new}")
    header = tsg.paragraph_heading(l.heading)[2]
    lines = sheet.splitlines()
    lines[l.i] = _heading(new, l.section, header)
    return sh.join(lines, sheet), [{"op": "rename_paragraph", "paragraph": new, "to": l.paragraph}]


def move_paragraph(sheet: str, paragraph: str, before: str = "", after: str = ""):
    l = _para(sheet, paragraph)
    if not (before or after):
        raise EditError("move: say which paragraph it goes before or after")
    a = _para(sheet, before or after)
    if sh.norm(a.section) != sh.norm(l.section):
        raise EditError("those paragraphs are in different sections")
    if a.i == l.i:
        raise EditError("a paragraph cannot move next to itself")
    same = [n for n, s in sh.paragraphs(sheet) if sh.norm(s) == sh.norm(l.section)]
    k = [sh.norm(n) for n in same].index(sh.norm(l.paragraph))
    inverse = ({"op": "move_paragraph", "paragraph": l.paragraph, "before": same[k + 1]} if k + 1 < len(same)
               else {"op": "move_paragraph", "paragraph": l.paragraph, "after": same[k - 1]})
    start, end = sh.paragraph_span(sheet, l.paragraph)
    lines = sheet.splitlines()
    block = lines[start:end]
    del lines[start:end]
    cut = sh.join(lines, sheet)
    s2, e2 = sh.paragraph_span(cut, a.paragraph)
    if block and block[-1].strip():
        block = [*block, ""]
    lines = cut.splitlines()
    lines[(s2 if before else e2):(s2 if before else e2)] = block
    return sh.join(lines, sheet), [inverse]


def remove_paragraph(sheet: str, paragraph: str):
    _para(sheet, paragraph)
    start, end = sh.paragraph_span(sheet, paragraph)
    lines = sheet.splitlines()
    block = lines[start:end]
    del lines[start:end]
    following = sh.walk(sh.join(lines, sheet))
    before = following[start].heading if start < len(following) and following[start].keyword == "#" else None
    return sh.join(lines, sheet), [{"op": "insert_block", "lines": block, "before_heading": before}]


def insert_block(sheet: str, lines: List[str], before_heading: Optional[str] = None):
    cur = sheet.splitlines()
    at = len(cur)
    if before_heading is not None:
        at = next((l.i for l in sh.walk(sheet) if l.keyword == "#" and l.heading == before_heading), len(cur))
    block = list(lines)
    if at == len(cur) and cur and cur[-1].strip():
        block = ["", *block]
    cur[at:at] = block
    return sh.join(cur, sheet), []


def add_paragraph(sheet: str, name: str, section: str, covers=None, after: str = ""):
    nm = _name(name, "paragraph name")
    if any(sh.norm(n) == sh.norm(nm) for n, _ in sh.paragraphs(sheet)):
        raise EditError(f"there is already a paragraph called {nm}")
    sec = section_name(sheet, section)
    items = _covers_items(covers)
    block = [_heading(nm, sec)] + (["COVERS [" + " | ".join(f'"{c}"' for c in items) + "]"] if items else []) + [""]
    paras = sh.paragraphs(sheet)
    order = [sh.norm(n) for _, n, _ in _sections(sheet)]
    if after:
        a = _para(sheet, after)
        if sh.norm(a.section) != sh.norm(sec):
            raise EditError("that paragraph is in a different section")
        at = sh.paragraph_span(sheet, a.paragraph)[1]
    else:
        same = [n for n, s in paras if sh.norm(s) == sh.norm(sec)]
        rank = order.index(sh.norm(sec))
        earlier = [n for n, s in paras if sh.norm(s) in order and order.index(sh.norm(s)) < rank]
        if same:
            at = sh.paragraph_span(sheet, same[-1])[1]
        elif earlier:
            at = sh.paragraph_span(sheet, earlier[-1])[1]
        elif paras:
            at = sh.paragraph_span(sheet, paras[0][0])[0]
        else:
            at = len(sheet.splitlines())
    lines = sheet.splitlines()
    if at > 0 and at <= len(lines) and lines[at - 1].strip():
        block = ["", *block]
    lines[at:at] = block
    return sh.join(lines, sheet), [{"op": "remove_paragraph", "paragraph": nm}]


# ── sections ────────────────────────────────────────────────────────────────────────────────────────────────────
def rename_section(sheet: str, section: str, header: str):
    l, name, old = _section(sheet, section)
    new = (header or "").strip()
    if new.lower() == "none":
        new = ""
    if '"' in new or "|" in new:
        raise EditError("section heading: plain wording only")
    lines = sheet.splitlines()
    lines[l.i] = _HEADER_ATTR.sub(f'header: "{new}"' if new else "header: none", l.text, count=1)
    return sh.join(lines, sheet), [{"op": "rename_section", "section": name, "header": old or "none"}]


def move_section(sheet: str, section: str, before: str = "", after: str = ""):
    l, name, _ = _section(sheet, section)
    if not (before or after):
        raise EditError("move: say which section it goes before or after")
    a, _, _ = _section(sheet, before or after)
    if a.i == l.i:
        raise EditError("a section cannot move next to itself")
    names = [n for _, n, _ in _sections(sheet)]
    k = names.index(name)
    inverse = ({"op": "move_section", "section": name, "before": names[k + 1]} if k + 1 < len(names)
               else {"op": "move_section", "section": name, "after": names[k - 1]})
    lines = sheet.splitlines()
    text = lines.pop(l.i)
    ai = a.i - (1 if a.i > l.i else 0)
    lines.insert(ai if before else ai + 1, text)
    return sh.join(lines, sheet), [inverse]


def remove_section(sheet: str, section: str):
    _, name, _ = _section(sheet, section)
    st = tsg.parse_sheet(sheet, mode="template").structure
    role = next((s.role for s in st.sections if sh.norm(s.name) == sh.norm(name)), "")
    if role in ("findings", "impression") and sum(s.role == role for s in st.sections) <= 1:
        raise EditError(f"every report needs a {role} section")
    inverses: List[dict] = []
    for pname, psec in reversed(sh.paragraphs(sheet)):
        if sh.norm(psec) == sh.norm(name):
            sheet, inv = remove_paragraph(sheet, pname)
            inverses.extend(inv)
    l, _, _ = _section(sheet, name)
    names = [n for _, n, _ in _sections(sheet)]
    k = names.index(name)
    lines = sheet.splitlines()
    text = lines.pop(l.i)
    inverses.append({"op": "insert_section_line", "line": text,
                     "before_section": names[k + 1] if k + 1 < len(names) else None})
    return sh.join(lines, sheet), inverses


def insert_section_line(sheet: str, line: str, before_section: Optional[str] = None):
    secs = sh.section_lines(sheet)
    if before_section:
        at = _section(sheet, before_section)[0].i
    elif secs:
        at = secs[-1].i + 1
    else:
        raise EditError("the template has no Report Structure sections")
    lines = sheet.splitlines()
    lines.insert(at, line)
    return sh.join(lines, sheet), []


def add_section(sheet: str, name: str, header: str, role: str, after: str = "", covers=None):
    nm = " ".join((name or "").upper().replace(":", " ").split())
    if not _SECTION_NAME.match(nm):
        raise EditError("section name: plain words")
    if role not in tsg.ROLES:
        raise EditError(f"section role: one of {', '.join(tsg.ROLES)}")
    if any(sh.norm(n) == sh.norm(nm) for _, n, _ in _sections(sheet)):
        raise EditError(f"there is already a section called {nm}")
    head = (header or "").strip()
    if '"' in head or "|" in head:
        raise EditError("section heading: plain wording only")
    line = f"SECTION {nm} | header: " + (f'"{head}"' if head else "none") + f" | role: {role}"
    if after:
        at = _section(sheet, after)[0].i + 1
    else:
        secs = sh.section_lines(sheet)
        if not secs:
            raise EditError("the template has no Report Structure sections")
        at = secs[-1].i + 1
    lines = sheet.splitlines()
    lines.insert(at, line)
    sheet2 = sh.join(lines, sheet)
    pname = _name((head.rstrip(":").strip() or nm.title()), "paragraph name")
    sheet3, _ = add_paragraph(sheet2, pname, nm, covers or [])
    return sheet3, [{"op": "remove_section", "section": nm}]


OPS = {"rename_paragraph": rename_paragraph, "move_paragraph": move_paragraph, "remove_paragraph": remove_paragraph,
       "insert_block": insert_block, "add_paragraph": add_paragraph, "rename_section": rename_section,
       "move_section": move_section, "remove_section": remove_section, "insert_section_line": insert_section_line,
       "add_section": add_section}
