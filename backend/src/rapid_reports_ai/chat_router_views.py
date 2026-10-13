"""What each targeted call of the chat-edit router sees (spec Flow 2: "gets only the part of the sheet it needs").
Plain text in report terms; section names in Title Case (plan decision 7: upper-case words are a Cerebras risk) and
matched back case-insensitively by code."""
from __future__ import annotations

import re
from typing import List

from . import chat_router_ledger as L
from . import chat_router_sheet as sh

_BRACKET = re.compile(r"\[([^\]]+)\]")
_ITEM = re.compile(r'"([^"]+)"')
_SEC = re.compile(r'SECTION\s+(?P<name>.+?)\s*\|\s*header:\s*(?:none|"(?P<header>[^"]*)")\s*\|\s*role:\s*(?P<role>\w+)')
NEED_TEXT = {"every": "every report must state it", "relevant": "stated only when relevant",
             "not_needed": "not needed"}


def _values(sheet: str, ledger: List[dict]) -> str:
    rows = [f"- {n}: {NEED_TEXT.get(need, need)}" for n, need in L.values(sheet, ledger)]
    return "VALUES:\n" + ("\n".join(rows) or "- (none yet)")


def _printed(sheet: str) -> List[str]:
    return [sh.quoted(l.text) for l in sh.walk(sheet) if l.keyword == "FIXED"]


def _concepts(sheet: str, ledger: List[dict]) -> str:
    rows = []
    for name, label in L.CONCEPTS.items():
        e = L.entry(ledger, "concept", name)
        try:
            choice = e["choice"] if e else L.current(sheet, "concept", name)
        except L.Rejected:
            choice = None
        state, d, w, cond = L.concept_state(choice)
        states = L.concept_states(name)
        when = next((s for s, c in states.items() if c and c == cond), "")
        usual = next((s for s in states if s != when), "") if when else ""
        head = f"- {name} ({label}; states: {', '.join(states)})"
        if state == "not_used":
            rows.append(f"{head}: not stated")
        elif state == "dictated":
            rows.append(f"{head}: whichever wording is dictated")
        else:
            rows.append(f'{head}: default "{d}" (printed when {usual or "nothing else is dictated"}); '
                        f'when_met "{w}" (condition: {when or "none"})')
    printed = [f'- "{t}"' for t in _printed(sheet)]
    return ("STUDY-LEVEL STATEMENTS (key (label): current wording):\n" + "\n".join(rows)
            + "\n\nSENTENCES PRINTED IN EVERY REPORT (a default may reuse one):\n" + ("\n".join(printed) or "- (none)"))


def _fixed(sheet: str, ledger: List[dict]) -> str:
    rows = [f'- in {l.paragraph or l.heading}: "{sh.quoted(l.text)}"' for l in sh.walk(sheet) if l.keyword == "FIXED"]
    return ("SENTENCES PRINTED IN EVERY REPORT:\n" + ("\n".join(rows) or "- (none)")
            + "\n\nPARAGRAPHS: " + ", ".join(n for n, _ in sh.paragraphs(sheet)))


def _normals(sheet: str, ledger: List[dict]) -> str:
    lines = sh.walk(sheet)
    out = []
    for name, _ in sh.paragraphs(sheet):
        start, end = sh.paragraph_span(sheet, name)
        block = lines[start:end]
        covers = [x for l in block if l.keyword == "COVERS" for x in _ITEM.findall(l.text)]
        out.append(f'Paragraph "{name}"' + (f" (reports: {', '.join(covers)})" if covers else "") + ":")
        for l in block:
            if l.keyword == "NORMAL":
                m = _BRACKET.search(l.text)
                out.append(f'  normal {m.group(1) if m else "?"}: "{sh.quoted(l.text)}"')
            elif l.keyword == "NEGATIVE":
                out.append(f'  negative: "{sh.quoted(l.text)}"')
    return "NORMAL FINDINGS BY PARAGRAPH:\n" + "\n".join(out)


def _layout(sheet: str, ledger: List[dict]) -> str:
    secs = []
    for l in sh.section_lines(sheet):
        m = _SEC.search(l.text)
        if m:
            head = f'"{m.group("header")}"' if m.group("header") else "none"
            secs.append(f"- {m.group('name').strip().title()} (printed heading {head}, role {m.group('role')})")
    paras = [f"- {n}, in section {s.title()}" for n, s in sh.paragraphs(sheet)]
    return "SECTIONS (in print order):\n" + "\n".join(secs) + "\n\nPARAGRAPHS (in order):\n" + "\n".join(paras)


def _style(sheet: str, ledger: List[dict]) -> str:
    return "PROSE BLOCKS:\n" + "\n\n".join(f'[{b.id}] under "{b.heading}":\n{b.text}' for b in sh.prose_blocks(sheet))


VIEWS = {"value": _values, "concept": _concepts, "fixed": _fixed, "normal": _normals, "layout": _layout,
         "style": _style}


def view(kind: str, sheet: str, ledger: List[dict]) -> str:
    return VIEWS[kind](sheet, ledger or [])
