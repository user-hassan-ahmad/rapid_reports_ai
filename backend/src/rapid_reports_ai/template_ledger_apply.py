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

import functools
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
    restated: List[dict] = field(default_factory=list)   # lint warnings: paragraph prose quoting a decided concept's
                                                         # FIXED line ({"line", "text", "reason", "detail"})

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


def _targeting(st: tss.SheetStructure, texts: Set[str]) -> List[tss.Rule]:
    """Context REPLACE / SUPPRESS rules whose target is one of `texts` (norm_key)."""
    return [r for r in st.rules if r.condition_source == "context" and r.effect in ("replace", "suppress")
            and norm_key(r.target) in texts]


def _concept_rules(st: tss.SheetStructure, name: str) -> List[tss.Rule]:
    """The context rules carrying one of the concept's standard conditions (how a concept is found)."""
    return [r for r in st.rules if r.condition_source == "context" and td.concept_of_condition(r.condition) == name]


def _concept_lines(choice: dict, fixed_suffix: str = "", rule_suffix: str = "") -> List[str]:
    """A used concept's lines: FIXED default + REPLACE, FIXED default + SUPPRESS (no alternative wording), or USE."""
    default, when_met, cond = choice.get("default", ""), choice.get("when_met", ""), choice["condition"]
    out = []
    if default:
        out.append(f'FIXED "{default}"{fixed_suffix}')
    effect = "replace" if default and when_met else ("suppress" if default else "use")
    rule = tss.Rule(id="ledger", section="", condition=cond, condition_source="context", effect=effect,
                    target=default, then_text=when_met, source_lines=[])
    out.append(tsg.render_rule(rule) + rule_suffix)
    return out


def _home(lines, st, c: td.Concept) -> Optional[int]:
    """Insert index for a concept written from scratch: the end of the first paragraph of the first non-optional
    section with one of the concept's roles, else of the first findings section."""
    ordered = sorted(st.sections, key=lambda s: s.order)
    for role in [*c.roles, "findings"]:
        for s in ordered:
            if s.role != role or s.optional:
                continue
            para = next((p for p in st.paragraphs if p.section == s.name), None)
            span = _paragraph_span(lines, para.id) if para else None
            if span:
                return _block_end(lines, *span)
    return None


def _orphan_extra(lines, st, rules, texts: Set[str], added: Optional[Set[str]]) -> Optional[Tuple[int, str]]:
    """(index, text) of the FIXED line a reworded default left beside the concept's REPLACE / SUPPRESS rule, whose
    target now matches no FIXED line. With a before-sheet (`added`: FIXED texts new since then) it is the added
    line; without one, the FIXED line directly above the orphaned rule. None when there is no orphan or no such
    line (never guessed further)."""
    fixed = {norm_key(f.text) for f in st.fixed_blocks}
    orphans = [r for r in rules if r.effect in ("replace", "suppress") and norm_key(r.target) not in fixed]
    if not orphans:
        return None
    cands = [f for f in st.fixed_blocks if norm_key(f.text) not in texts
             and (added is None or norm_key(f.text) in added)]
    rule_at = {_index(lines, r.source_lines[0]) for r in orphans}
    for f in cands:
        i = _index(lines, f.source_line)
        if i is not None and i + 1 in rule_at:
            return i, f.text
    if added is not None and len(cands) == 1:
        i = _index(lines, cands[0].source_line)
        if i is not None:
            return i, cands[0].text
    return None


def _concept(lines, st, entry, added: Optional[Set[str]] = None):
    name, choice = entry["key"], entry["choice"]
    row = {"kind": "concept", "key": name, "action": "kept"}
    rules = _concept_rules(st, name)
    texts = {norm_key(r.target) for r in rules if r.target}
    if choice.get("default"):
        texts.add(norm_key(choice["default"]))
    drop: Set[int] = set()
    rule_line = fixed_line = None
    for r in [*rules, *(x for x in _targeting(st, texts) if x not in rules)]:
        i = _index(lines, r.source_lines[0], drop)
        if i is not None:
            drop.add(i)
            rule_line = rule_line or lines[i]
    for f in st.fixed_blocks:
        if norm_key(f.text) in texts:
            i = _index(lines, f.source_line, drop)
            if i is not None:
                drop.add(i)
                fixed_line = fixed_line or lines[i]
    olds = [t for r in rules for t in (r.target, r.then_text) if t]
    unmatched: List[dict] = []
    extra = _orphan_extra(lines, st, rules, texts, added) if choice["use"] else None
    if extra is not None:   # never two lines: the ledger's line stays, the extra one goes and is asked about
        drop.add(extra[0])
        unmatched = [{**entry, "dropped": extra[1]}]
    if drop:
        at = min(drop)
    elif choice["use"]:
        at = _home(lines, st, td.CONCEPTS[name])
        if at is None:
            return lines, [], [entry], []
    else:
        return lines, [row], [], []
    # each new line keeps the trailing "| section:" of the line it replaces (a Report-wide unit without one belongs
    # to the first findings section, so nothing is added)
    fixed_suffix = _suffix(fixed_line) if fixed_line else (_suffix(rule_line) if rule_line else "")
    rule_suffix = _suffix(rule_line) if rule_line else fixed_suffix
    new = _concept_lines(choice, fixed_suffix, rule_suffix) if choice["use"] else []
    old = [lines[i] for i in sorted(drop)]
    if [ln.strip() for ln in old] == [ln.strip() for ln in new]:
        return lines, [row], [], []
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    if new:
        prefix = _prefix(old[0]) if old else ""
        out[at:at] = [prefix + ln for ln in new]
    action = "removed" if not new else ("rewritten" if drop else "inserted")
    keep = {norm_key(choice.get("default", "")), norm_key(choice.get("when_met", ""))}
    return out, [{**row, "action": action}], unmatched, [t for t in olds if norm_key(t) not in keep]


def _uses(st: tss.SheetStructure, key: str) -> List[tss.Rule]:
    """Context USE rules writing this sentence (a line printed when its condition is met)."""
    return [r for r in st.rules if r.condition_source == "context" and r.effect == "use" and norm_key(r.then_text) == key]


def _fixed(lines, st, entry):
    key = norm_key(entry["key"])
    found = [f for f in st.fixed_blocks if norm_key(f.text) == key]
    uses = _uses(st, key)
    row = {"kind": "fixed", "key": entry["key"], "action": "kept"}
    if entry["choice"]["keep"] == "always":
        return (lines, [row], [], []) if found or uses else (lines, [], [entry], [])
    if not found and not uses:
        return lines, [row], [], []
    drop: Set[int] = set()
    raws = [f.source_line for f in found] + [r.source_lines[0] for r in [*_targeting(st, {key}), *uses]]
    for raw in raws:
        i = _index(lines, raw, drop)
        if i is not None:
            drop.add(i)
    out = [ln for i, ln in enumerate(lines) if i not in drop]
    return out, [{**row, "action": "removed"}], [], [found[0].text if found else uses[0].then_text]


def _paragraph(st: tss.SheetStructure, name: str) -> Optional[tss.Paragraph]:
    """The one paragraph with this name; None when there is none or more than one (never guessed)."""
    hits = [p for p in st.paragraphs if td._name(p.name) == td._name(name)]
    return hits[0] if len(hits) == 1 else None


def _normal(lines, st, entry):
    para_name, label, neg = td.split_normal_key(entry["key"])
    text = entry["choice"]["text"]
    row = {"kind": "normal", "key": entry["key"], "action": "kept"}
    para = _paragraph(st, para_name)
    if para is None:
        return lines, [], [entry], []
    if neg:
        keys = {norm_key(label)} | ({norm_key(text)} if text else set())
        units = [n for n in st.negatives if n.paragraph == para.id and n.origin == "template" and not n.condition
                 and norm_key(n.text) in keys]
        raws = [n.source_lines[0] for n in units]
    else:
        units = [n for n in st.normals if n.paragraph == para.id
                 and td._name(td.structure_label(n.structure)) == td._name(label)]
        raws = [n.source_line for n in units]
    if not units:
        if not text:
            if neg and any(n.paragraph == para.id and n.origin == "template" and not n.condition
                           for n in st.negatives):   # the paragraph's negative was reworded: ask, never "kept"
                return lines, [], [entry], []
            return lines, [row], [], []
        if neg:   # a negative is keyed by its own wording: when neither wording is found, ask (never insert)
            return lines, [], [entry], []
        span = _paragraph_span(lines, para.id)
        if span is None:
            return lines, [], [entry], []
        at = _block_end(lines, *span)
        out = list(lines)
        out[at:at] = [f'NORMAL [{label}] "{text}"']
        return out, [{**row, "action": "inserted"}], [], []
    idx: List[int] = []
    for raw in raws:
        i = _index(lines, raw, set(idx))
        if i is not None:
            idx.append(i)
    if not idx:
        return lines, [], [entry], []
    if text and len(idx) == 1 and units[0].text == text:
        return lines, [row], [], []
    olds = [u.text for u in units]
    old_keys = {norm_key(t) for t in olds}
    out2: List[Optional[str]] = list(lines)
    for i in idx[1:]:
        out2[i] = None
    rules = _targeting(st, old_keys)
    if text:
        first = lines[idx[0]]
        body = f'NEGATIVE "{text}"' if neg else f'NORMAL [{units[0].structure}] "{text}"'
        out2[idx[0]] = _prefix(first) + body + _suffix(first)
        for r in rules:   # a context rule on the old wording follows it
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = _prefix(lines[i]) + tsg.render_rule(r.model_copy(update={"target": text})) + _suffix(lines[i])
        action = "rewritten"
    else:
        out2[idx[0]] = None
        for r in rules:
            i = _index(lines, r.source_lines[0])
            if i is not None:
                out2[i] = None
        action = "removed"
    stale = [t for t in olds if norm_key(t) != norm_key(text)]
    return [x for x in out2 if x is not None], [{**row, "action": action}], [], stale


_OPS: List[Tuple[str, Callable]] = [("concept", _concept), ("fixed", _fixed), ("normal", _normal)]


def apply_ledger(sheet: str, ledger: List[dict], before: str = "") -> LedgerResult:
    """The sheet with every ledger entry applied (module doc). A non-grammar sheet or an empty ledger is unchanged.
    `before`: the sheet this one replaces, when known; it tells a reworded concept default's added line apart."""
    res = LedgerResult(sheet=sheet)
    if not ledger or not tsg.is_grammar_sheet(sheet or ""):
        return res
    added: Optional[Set[str]] = None
    if before and tsg.is_grammar_sheet(before):
        had = {norm_key(f.text) for f in _parse(before).fixed_blocks}
        added = {norm_key(f.text) for f in _parse(sheet).fixed_blocks} - had
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
            steps.append((functools.partial(op, added=added) if op is _concept else op, e, [e]))
    # a stored concept whose wording is not a full sentence is never a rule: it applies its default-only shape (or,
    # with no valid default, "whichever is dictated") and is returned as unmatched, a review card
    # (template_rules_cards.unmatched_cards)
    fragments = [e for e in ledger if td.fragment_wording(e)]
    steps = [(op, ({**arg, "choice": td.fragment_fallback(arg)} if isinstance(arg, dict) and td.fragment_wording(arg)
                   else arg), entries) for op, arg, entries in steps]
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
    res.unmatched += [e for e in fragments if e not in res.failed]
    res.restated = restated_quotes(res.sheet, ledger)
    return res


RESTATED = "prose quotes a decided standard line"
_EXAMPLE_PROSE = re.compile(r"^\s*(?:-\s+)?(?:Opening|Order|Measurement)\b")
_QUOTED = re.compile(r'"([^"]*)"')


def restated_quotes(sheet: str, ledger: List[dict]) -> List[dict]:
    """Lint warnings (never blocking): an Opening, Order or Measurement line of a paragraph whose quote holds a used
    decided concept's FIXED line word for word. The line prints itself, so the writer would state it twice."""
    owned = {" ".join(e["choice"]["default"].split()) for e in td.clean_ledger(ledger)
             if e["kind"] == "concept" and e["choice"]["use"] and e["choice"]["default"]
             and (not td.fragment_wording(e) or td.fragment_fallback(e)["use"])}
    if not owned:
        return []
    lines = sheet.split("\n")
    out: List[dict] = []
    for title, start, end in _blocks(lines):
        if tsg.paragraph_heading(title) is None:
            continue
        for i in range(start, end):
            ln = lines[i]
            if not _EXAMPLE_PROSE.match(ln):
                continue
            quotes = [" ".join(q.split()) for q in _QUOTED.findall(ln)]
            for text in sorted(t for t in owned if any(t in q for q in quotes)):
                out.append({"line": i + 1, "text": ln, "reason": RESTATED, "detail": text})
    return out


# ── reading a sheet for a ledger item (chat reconciliation; the router's targeted calls) ───────────────────────

def observe(st: tss.SheetStructure, kind: str, key: str) -> Optional[dict]:
    """The choice the sheet currently expresses for (kind, key), in the ledger's choice form. A value: "every" when
    the LIST_MISSING line lists it, else "not_needed". A concept: read from the rule carrying one of its standard
    conditions (REPLACE: default + when_met; SUPPRESS: default only; USE: when_met only). A normal: the unit's text
    ("" when absent); None when its paragraph is gone or its name is not unique."""
    if kind == "value":
        items = [td._name(x) for r in st.rules if r.effect == "list_missing" for x in r.items]
        return {"need": "every" if td._name(key) in items else "not_needed"}
    if kind == "concept":
        rules = _concept_rules(st, key)
        if not rules:
            return {"use": False, "default": "", "when_met": "", "condition": "", "dictated": False}
        r = rules[0]
        cond = next(c for c in td.CONCEPTS[key].conditions if td._name(c) == td._name(r.condition))
        default = r.target if r.effect in ("replace", "suppress") else ""
        when_met = r.then_text if r.effect in ("replace", "use") else ""
        return {"use": True, "default": default, "when_met": when_met, "condition": cond, "dictated": False}
    if kind == "fixed":
        k = norm_key(key)
        present = any(norm_key(f.text) == k for f in st.fixed_blocks) or bool(_uses(st, k))
        return {"keep": "always" if present else "remove"}
    para_name, label, neg = td.split_normal_key(key)
    para = _paragraph(st, para_name)
    if para is None:
        return None
    if neg:
        u = next((n for n in st.negatives if n.paragraph == para.id and norm_key(n.text) == norm_key(label)), None)
    else:
        u = next((n for n in st.normals if n.paragraph == para.id
                  and td._name(td.structure_label(n.structure)) == td._name(label)), None)
    return {"text": u.text if u else ""}


def _orphaned(st: tss.SheetStructure, name: str) -> bool:
    """A concept's REPLACE / SUPPRESS rule whose target matches no FIXED line (the line was reworded, the rule
    still names the old text)."""
    fixed = {norm_key(f.text) for f in st.fixed_blocks}
    return any(r.effect in ("replace", "suppress") and norm_key(r.target) not in fixed
               for r in _concept_rules(st, name))


def _fixed_reword(sb: tss.SheetStructure, sa: tss.SheetStructure) -> Optional[Tuple[str, str]]:
    """(old, new) when the FIXED lines before and after differ by exactly one removed and one added line."""
    b = {norm_key(f.text): f.text for f in sb.fixed_blocks}
    a = {norm_key(f.text): f.text for f in sa.fixed_blocks}
    gone, new = [b[k] for k in b if k not in a], [a[k] for k in a if k not in b]
    return (gone[0], new[0]) if len(gone) == 1 and len(new) == 1 else None


def _wholesale(e: dict, ob: dict, oa: dict, sb: tss.SheetStructure, sa: tss.SheetStructure) -> bool:
    """A rewrite that removed a whole decided item: the whole LIST_MISSING list, or every line of a used concept.
    Product decision D3: never folded into the ledger silently; the ledger is kept and a card asks."""
    if e["kind"] == "value":
        had = any(r.effect == "list_missing" and r.items for r in sb.rules)
        return had and not any(r.effect == "list_missing" for r in sa.rules) and e["choice"]["need"] == "every"
    if e["kind"] == "concept":
        return bool(ob.get("use")) and not oa.get("use") and bool(e["choice"].get("use"))
    return False


def reconcile_chat(before: str, after: str, ledger: List[dict]) -> Tuple[List[dict], List[td.Change], List[dict]]:
    """Fold a chat rewrite into the ledger: an entry whose item the rewrite changed (before != after) takes the new
    state (source "chat"; the reply names a confirmed one); values the rewrite added to LIST_MISSING become entries
    when the ledger owns the value list. A rewrite that removed a whole item (_wholesale) leaves the entry as it was
    and returns a one-tap card instead. Returns (ledger, changes, cards)."""
    from . import template_rules_cards as trc
    if not ledger or not tsg.is_grammar_sheet(before or "") or not tsg.is_grammar_sheet(after or ""):
        return list(ledger or []), [], []
    sb, sa = _parse(before), _parse(after)
    out, changes, cards = list(ledger), [], []
    for e in ledger:
        try:
            ob, oa = observe(sb, e["kind"], e["key"]), observe(sa, e["kind"], e["key"])
            rw = _fixed_reword(sb, sa)
            if (e["kind"] == "concept" and e["choice"].get("use") and _orphaned(sa, e["key"])
                    and not _orphaned(sb, e["key"])):
                if not (rw and norm_key(rw[0]) == norm_key(e["choice"].get("default", ""))):
                    cards.append(trc.card_for_change(e["kind"], e["key"], e["choice"]))   # kept, asked
                    continue
                # the default reworded in place: the new wording becomes the default (apply_ledger retargets
                # the standard rule to it)
                out, ch = td.set_decision(out, "concept", e["key"], {**e["choice"], "default": rw[1]}, source="chat")
            elif (e["kind"] == "fixed" and ob == {"keep": "always"} and oa == {"keep": "remove"} and rw
                  and norm_key(rw[0]) == norm_key(e["key"])):   # an always-printed line reworded: same choice, new key
                out, ch = td.rekey_decision(out, "fixed", e["key"], rw[1], source="chat")
            elif oa is None or ob == oa:
                continue
            elif _wholesale(e, ob, oa, sb, sa):
                cards.append(trc.card_for_change(e["kind"], e["key"], e["choice"]))
                continue
            else:
                out, ch = td.set_decision(out, e["kind"], e["key"], oa, source="chat")
        except (td.DecisionError, KeyError, StopIteration):
            continue
        if ch:
            changes.append(ch)
    if any(e["kind"] == "value" for e in ledger):
        known = {td._name(e["key"]) for e in out if e["kind"] == "value"}
        before_items = {td._name(x) for r in sb.rules if r.effect == "list_missing" for x in r.items}
        for x in [x for r in sa.rules if r.effect == "list_missing" for x in r.items]:
            if td._name(x) in known or td._name(x) in before_items:
                continue
            try:
                out, ch = td.set_decision(out, "value", x, {"need": "every"}, source="chat")
            except td.DecisionError:
                continue
            known.add(td._name(x))
            if ch:
                changes.append(ch)
    return out, changes, cards


# ── rendering for the writer's prompt (the same lines apply_ledger writes) ─────────────────────────────────────

def render_list_missing(items: List[str]) -> str:
    rule = tss.Rule(id="ledger", section="", condition="any listed value is not stated", condition_source="findings",
                    effect="list_missing", items=list(items), position="top", source_lines=[])
    return tsg.render_rule(rule)


def render_concept(name: str, choice: dict) -> List[str]:
    """A concept's lines inside a paragraph ([] for "not used" and "whichever is dictated")."""
    entry = {"kind": "concept", "key": name, "choice": choice}
    if td.fragment_wording(entry):
        choice = td.fragment_fallback(entry)
    if not choice.get("use"):
        return []
    return _concept_lines(td.validate("concept", name, choice)[1])
