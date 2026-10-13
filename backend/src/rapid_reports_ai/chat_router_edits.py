"""Code edits of single unit lines for the chat-edit router (plan decision 6): reword or add an always-printed
sentence, add a normal or a negative line to a paragraph (extending COVERS), and the inverse of each, for undo. An
edit that adds a grammar error is refused (EditError). Layout operations live in chat_router_layout; apply_op
dispatches both and returns (sheet, inverse ops); undo applies the inverse ops in reverse order."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import chat_router_sheet as sh
from . import template_sheet_grammar as tsg
from .hybrid_stack.template import norm_key


class EditError(ValueError):
    """The edit cannot be made as asked (no such target, or it would break the sheet)."""


_PLAIN = re.compile(r'^[^"“”\[\]|]+$')
_SLOT = re.compile(r"\{[^{}\n]*\}")
STANDARD_SLOTS = frozenset({"{study}", "{date}"})

# Ops a proposal card (client-sent) may run forward. unit_drop / covers_drop / insert_block / insert_section_line are
# inverse-only: they undo an add or a removal and have no inverse of their own, so they never run forward.
FORWARD_OPS = frozenset({"fixed_reword", "fixed_add", "normal_add", "negative_add", "rename_paragraph",
                         "move_paragraph", "remove_paragraph", "add_paragraph", "rename_section", "move_section",
                         "remove_section", "add_section", "style_block"})


def bad_slots(text: str, sheet: str) -> List[str]:
    """{slots} in `text` that are neither standard ({study}, {date}) nor already used by the sheet."""
    allowed = STANDARD_SLOTS | set(_SLOT.findall(sheet or ""))
    return [s for s in _SLOT.findall(text or "") if s not in allowed]
_BRACKET = re.compile(r"\[([^\]]+)\]")
_ITEM = re.compile(r'"([^"]+)"')


def _errors(sheet: str) -> set:
    return {(e.text.strip(), e.reason) for e in tsg.parse_sheet(sheet, mode="template").errors}


def guarded(before: str, after: str) -> str:
    """`after`, or EditError when it has a grammar error `before` did not have."""
    new = _errors(after) - _errors(before)
    if new:
        raise EditError("the edit would break the template (" + "; ".join(sorted({r for _, r in new})) + ")")
    return after


def plain(t: str, what: str, slots_from: Optional[str] = None) -> str:
    """Plain wording: no quotes, brackets or bars. {slots}: none, unless `slots_from` (the sheet) is given, then only
    the slots bad_slots allows (the same rule the change validation uses)."""
    t = " ".join((t or "").split())
    if not t or not _PLAIN.match(t):
        raise EditError(f"{what}: plain wording expected (no quotes, brackets or bars)")
    if (slots_from is None and _SLOT.search(t)) or "{" in _SLOT.sub("", t) or "}" in _SLOT.sub("", t):
        raise EditError(f"{what}: no value to fill in")
    if slots_from is not None and bad_slots(t, slots_from):
        raise EditError(f"{what}: a value this template cannot fill")
    return t


def _span(sheet: str, paragraph: str) -> Tuple[int, int]:
    try:
        return sh.paragraph_span(sheet, paragraph)
    except KeyError:
        raise EditError(f"no paragraph {paragraph!r}") from None


def _unit(sheet: str, keyword: str, text: str, paragraph: str = "") -> sh.Line:
    for l in sh.walk(sheet):
        if l.keyword == keyword and norm_key(sh.quoted(l.text)) == norm_key(text) and (
                not paragraph or sh.norm(l.paragraph) == sh.norm(paragraph)):
            return l
    raise EditError(f"no {keyword} line {text!r}")


def _last_unit(sheet: str, paragraph: str) -> int:
    start, end = _span(sheet, paragraph)
    idx = [l.i for l in sh.walk(sheet)[start + 1:end] if l.keyword]
    return idx[-1] if idx else start


def _covers(sheet: str, paragraph: str) -> Optional[sh.Line]:
    start, end = _span(sheet, paragraph)
    return next((l for l in sh.walk(sheet)[start:end] if l.keyword == "COVERS"), None)


def _covers_line(items: List[str]) -> str:
    return "COVERS [" + " | ".join(f'"{x}"' for x in items) + "]"


def _insert_after(sheet: str, i: int, line: str) -> str:
    lines = sheet.splitlines()
    lines.insert(i + 1, line)
    return sh.join(lines, sheet)


def _replace(sheet: str, i: int, line: Optional[str]) -> str:
    lines = sheet.splitlines()
    if line is None:
        del lines[i]
    else:
        lines[i] = line
    return sh.join(lines, sheet)


# ── operations: (sheet, **args) -> (sheet, inverse ops) ──────────────────────────────────────────────────────────
def fixed_reword(sheet: str, line: str, text: str, paragraph: str = ""):
    l = _unit(sheet, "FIXED", line, paragraph)
    old, new = sh.quoted(l.text), plain(text, "new wording", slots_from=sheet)
    if any(x.keyword == "FIXED" and x.i != l.i and norm_key(sh.quoted(x.text)) == norm_key(new)
           for x in sh.walk(sheet)):
        raise EditError("that sentence is already printed")
    inverse = {"op": "fixed_reword", "line": new, "text": old}
    if paragraph:
        inverse["paragraph"] = paragraph
    return _replace(sheet, l.i, l.text.replace(f'"{old}"', f'"{new}"', 1)), [inverse]


def fixed_add(sheet: str, paragraph: str, text: str):
    t = plain(text, "sentence", slots_from=sheet)
    if any(l.keyword == "FIXED" and norm_key(sh.quoted(l.text)) == norm_key(t) for l in sh.walk(sheet)):
        raise EditError("that sentence is already printed")
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'FIXED "{t}"'), [
        {"op": "unit_drop", "keyword": "FIXED", "text": t, "paragraph": paragraph}]


def normal_add(sheet: str, paragraph: str, structure: str, text: str):
    s, t = plain(structure, "structure"), plain(text, "normal wording")
    start, end = _span(sheet, paragraph)
    if any(l.keyword == "NORMAL" and sh.norm((_BRACKET.search(l.text) or [None, ""])[1]) == sh.norm(s)
           for l in sh.walk(sheet)[start:end]):
        raise EditError("that structure already has a normal line")
    inverse: List[dict] = []
    cov = _covers(sheet, paragraph)
    if cov is None:
        sheet = _insert_after(sheet, start, _covers_line([s]))
        inverse.append({"op": "covers_drop", "paragraph": paragraph, "structure": s})
    else:
        items = _ITEM.findall(cov.text)
        if sh.norm(s) not in {sh.norm(x) for x in items}:
            sheet = _replace(sheet, cov.i, _covers_line([*items, s]))
            inverse.append({"op": "covers_drop", "paragraph": paragraph, "structure": s})
    inverse.append({"op": "unit_drop", "keyword": "NORMAL", "text": t, "paragraph": paragraph})
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'NORMAL [{s}] "{t}"'), inverse


def negative_add(sheet: str, paragraph: str, text: str):
    t = plain(text, "negative wording")
    start, end = _span(sheet, paragraph)
    if any(l.keyword == "NEGATIVE" and norm_key(sh.quoted(l.text)) == norm_key(t) for l in sh.walk(sheet)[start:end]):
        raise EditError("that negative is already stated")
    return _insert_after(sheet, _last_unit(sheet, paragraph), f'NEGATIVE "{t}"'), [
        {"op": "unit_drop", "keyword": "NEGATIVE", "text": t, "paragraph": paragraph}]


def unit_drop(sheet: str, keyword: str, text: str, paragraph: str = ""):
    return _replace(sheet, _unit(sheet, keyword, text, paragraph).i, None), []


def covers_drop(sheet: str, paragraph: str, structure: str):
    # The COVERS line is rewritten in canonical form (COVERS ["a" | "b"]): an undo is byte-exact only when the line
    # was canonical to begin with; otherwise the items come back with canonical spacing.
    cov = _covers(sheet, paragraph)
    if cov is None:
        raise EditError(f"{paragraph} has no COVERS line")
    items = [x for x in _ITEM.findall(cov.text) if sh.norm(x) != sh.norm(structure)]
    return _replace(sheet, cov.i, _covers_line(items) if items else None), []


def style_block(sheet: str, block: str, text: str, expect: str):
    """Replace one prose block (a tapped style card), only while it still reads `expect`; unit lines must not change
    (apply_op's grammar guard runs too). Its inverse puts the old text back the same way."""
    cur = {b.id: b for b in sh.prose_blocks(sheet)}.get(block)
    if cur is None or cur.text.strip("\n") != (expect or "").strip("\n"):
        raise EditError("that wording has changed since")
    after = sh.splice(sheet, {block: text})
    if not sh.units_unchanged(sheet, after):
        raise EditError("a style change cannot touch the template's rules")
    return after, [{"op": "style_block", "block": block, "text": expect, "expect": text}]


UNIT_OPS = {"style_block": style_block, "fixed_reword": fixed_reword, "fixed_add": fixed_add, "normal_add": normal_add,
            "negative_add": negative_add, "unit_drop": unit_drop, "covers_drop": covers_drop}


def apply_op(sheet: str, op: dict) -> Tuple[str, List[dict]]:
    """Apply one edit (unit or layout); (sheet, inverse ops). EditError when it cannot be made or breaks the sheet."""
    from . import chat_router_layout as lay
    fns = {**UNIT_OPS, **lay.OPS}
    name = (op or {}).get("op")
    if name not in fns:
        raise EditError(f"unknown edit {name!r}")
    try:
        after, inverse = fns[name](sheet, **{k: v for k, v in op.items() if k != "op"})
    except (KeyError, TypeError) as e:
        raise EditError(f"{name}: {e}") from e
    return guarded(sheet, after), inverse
