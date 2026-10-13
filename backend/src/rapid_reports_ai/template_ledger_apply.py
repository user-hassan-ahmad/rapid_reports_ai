"""Apply the decision ledger to a grammar sheet (Rules-step spec, "Decision ledger"). Pure code, no model call.

apply_ledger(sheet, ledger) runs as the save function's last step on every origin. Each entry is located through the
parsed structure (the grammar stores each unit's own sheet line) and its stable key; unit lines are rewritten,
removed or inserted in canonical form (template_sheet_grammar renderers); the sheet is re-parsed after each entry,
and an entry whose edit would add a lint error is not applied (`failed`: a bug, logged). Prose is never rewritten;
`stale_quotes` lists a sentence an entry rewrote or removed that a free-prose block still quotes.

Where an entry's target cannot be found: values and concepts are written from scratch (code knows where); a fixed
line to keep, or a normal whose paragraph is gone, is returned in `unmatched` (a card at the next review), never
guessed.

observe() reads what a sheet currently says for a ledger item; reconcile_chat() folds a chat rewrite's changes to
ledger items back into the ledger (source "chat") before the ledger is applied."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

from . import template_decisions as td
from . import template_sheet_grammar as tsg
from . import template_sheet_structure as tss
from .hybrid_stack.template import norm_key

logger = logging.getLogger(__name__)

_SECTION_SUFFIX = re.compile(r'\s*\|\s*section:\s*[^"]*$')
_PREFIX = re.compile(r"^\s*(?:-\s+)?")


@dataclass
class LedgerResult:
    sheet: str
    applied: List[dict] = field(default_factory=list)    # {"kind", "key", "action": kept|rewritten|removed|inserted}
    unmatched: List[dict] = field(default_factory=list)  # entries shown as cards at the next review
    failed: List[dict] = field(default_factory=list)     # entries whose edit would break the sheet (a bug)
    stale_quotes: List[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(a["action"] != "kept" for a in self.applied)


def _parse(sheet: str) -> tss.SheetStructure:
    return tsg.parse_sheet(sheet, mode="template").structure


def _err_keys(sheet: str) -> Set[tuple]:
    return {(e.text.strip(), e.reason) for e in tsg.parse_sheet(sheet, mode="template").errors}


def _prefix(line: str) -> str:
    return _PREFIX.match(line).group(0)


def _suffix(line: str) -> str:
    m = _SECTION_SUFFIX.search(line)
    return m.group(0) if m else ""


def _index(lines: List[str], raw: str, taken: Set[int] = frozenset()) -> Optional[int]:
    return next((i for i, ln in enumerate(lines) if i not in taken and ln == raw), None)


def _blocks(lines: List[str]) -> List[Tuple[str, int, int]]:
    """(title, heading index, end index exclusive) of every "## " block, in order."""
    heads = [(i, ln[3:].strip()) for i, ln in enumerate(lines) if ln.startswith("## ")]
    return [(t, i, heads[k + 1][0] if k + 1 < len(heads) else len(lines)) for k, (i, t) in enumerate(heads)]


def _paragraph_span(lines: List[str], pid: str) -> Optional[Tuple[int, int]]:
    """(heading index, end exclusive) of paragraph `pid` (the parser numbers paragraph headings p0, p1, …)."""
    n = 0
    for title, start, end in _blocks(lines):
        if tsg.paragraph_heading(title) is not None:
            if f"p{n}" == pid:
                return start, end
            n += 1
    return None


def _block_end(lines: List[str], start: int, end: int) -> int:
    """The index after a block's last non-blank line (an insert there keeps the blank line before the next block)."""
    k = end
    while k > start + 1 and not lines[k - 1].strip():
        k -= 1
    return k


def _free_prose_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    for title, start, end in _blocks(lines):
        if title.lower() in tsg.FREE_PROSE_SECTIONS:
            out += lines[start + 1:end]
    return out


# ── operations: (lines, structure, arg) -> (lines, applied rows, unmatched entries, old texts) ─────────────────

def _values(lines, st, entries):
    every = [e["key"] for e in entries if e["choice"]["need"] == "every"]
    rules = [r for r in st.rules if r.effect == "list_missing"]
    idx: List[int] = []
    for r in rules:
        i = _index(lines, r.source_lines[0], set(idx))
        if i is not None:
            idx.append(i)
    if idx:
        first = rules[0]
        spell = {td._name(k): k for k in every}
        ordered = [spell[td._name(x)] for x in first.items if td._name(x) in spell]
        ordered += [k for k in every if td._name(k) not in {td._name(x) for x in first.items}]
        out: List[Optional[str]] = list(lines)
        for i in idx[1:]:
            out[i] = None
        if not ordered:
            out[idx[0]] = None
            action = "removed"
        else:
            new = _prefix(lines[idx[0]]) + tsg.render_rule(first.model_copy(update={"items": ordered})) \
                + _suffix(lines[idx[0]])
            action = "kept" if new == lines[idx[0]] and len(idx) == 1 else "rewritten"
            out[idx[0]] = new
        return [x for x in out if x is not None], [{"kind": "value", "key": "*", "action": action}], [], []
    if not every:
        return lines, [{"kind": "value", "key": "*", "action": "kept"}], [], []
    findings = next((s.name for s in sorted(st.sections, key=lambda s: s.order) if s.role == "findings"), None)
    if findings is None:
        return lines, [], list(entries), []
    rule = tss.Rule(id="ledger", section=findings, condition="any listed value is not stated",
                    condition_source="findings", effect="list_missing", items=every, position="top", source_lines=[])
    line = f"{tsg.render_rule(rule)} | section: {findings}"
    out2 = list(lines)
    wide = next(((s, e) for t, s, e in _blocks(lines) if t.lower() == "report-wide"), None)
    if wide:
        at = _block_end(out2, *wide)
        out2[at:at] = [line]
    else:
        first_para = next((s for t, s, e in _blocks(lines) if tsg.paragraph_heading(t) is not None), len(out2))
        out2[first_para:first_para] = ["## Report-wide", line, ""]
    return out2, [{"kind": "value", "key": "*", "action": "inserted"}], [], []


_OPS: List[Tuple[str, Callable]] = []   # (kind, op) for single-entry kinds; filled in by the tasks that add them


def apply_ledger(sheet: str, ledger: List[dict]) -> LedgerResult:
    """The sheet with every ledger entry applied (module doc). A non-grammar sheet or an empty ledger is unchanged."""
    res = LedgerResult(sheet=sheet)
    if not ledger or not tsg.is_grammar_sheet(sheet or ""):
        return res
    steps: List[Tuple[Callable, object, List[dict]]] = []
    values = [e for e in ledger if e.get("kind") == "value"]
    if values:
        steps.append((_values, values, values))
    owned = td.concept_texts(ledger)
    for kind, op in _OPS:
        for e in ledger:
            if e.get("kind") != kind:
                continue
            if kind == "fixed" and norm_key(e["key"]) in owned:   # a concept's line: the concept entry decides it
                res.applied.append({"kind": "fixed", "key": e["key"], "action": "kept"})
                continue
            steps.append((op, e, [e]))
    stale: List[str] = []
    for op, arg, entries in steps:
        before_errors = _err_keys(res.sheet)
        try:
            lines, applied, unmatched, olds = op(res.sheet.split("\n"), _parse(res.sheet), arg)
            new = "\n".join(lines)
            added = _err_keys(new) - before_errors
            if added:
                raise ValueError(f"lint: {sorted(added)[:3]}")
        except Exception as e:  # a bug, never a refused save: the sheet stays without this decision
            logger.error("[ledger] %s not applied: %s: %s", [x.get("key") for x in entries], type(e).__name__,
                         str(e)[:200])
            res.failed += entries
            continue
        res.sheet = new
        res.applied += applied
        res.unmatched += unmatched
        stale += olds
    prose = _free_prose_lines(res.sheet.split("\n"))
    res.stale_quotes = sorted({t for t in stale if t and any(f'"{t}"' in ln for ln in prose)})
    return res
