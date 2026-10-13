"""Context rules resolved before generation (spec 2026-10-13-context-rules-resolved-design).

Jev decides, code applies, the generator only writes what is already decided. Per Generate, each distinct
condition of the sheet's context REPLACE / SUPPRESS / USE rules is asked once (jev_stack.ask_conditions: the
scratchpad's wording and cut-off, silence is not met) on the clinical history and the FINDINGS input, and code
rewrites the sheet text: a met REPLACE rewrites the unit line quoting its target, a met SUPPRESS removes it, a met
USE becomes a FIXED line where the rule stood; every resolved rule line is removed. The stored sheet is never
changed. Anything this step cannot settle (an unmatched target, a second met rule on one target, a sheet that does
not parse clean, a Jev failure) is left exactly as today: the rule line reaches the generator.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .hybrid_stack.jev_stack import CONDITION_MIN, ask_conditions
from .hybrid_stack.template import norm_key
from .template_sheet_grammar import is_grammar_sheet, parse_sheet
from .template_sheet_structure import Rule, SheetStructure

logger = logging.getLogger(__name__)

EFFECTS = ("replace", "suppress", "use")
_UNIT = re.compile(r"^\s*(?:-\s+)?(?:FIXED|NORMAL|NEGATIVE)\b")
_QUOTED = re.compile(r'"([^"]+)"')
_RULE_USE = re.compile(r'RULE\s+WHEN\s*\[[^\]]*\]\s*USE\s*("[^"]+")')
SLOT = re.compile(r"\{[^{}\n]*\}")


def _clean(sheet: str) -> Optional[SheetStructure]:
    """The parsed structure of a lint-clean grammar sheet; None otherwise."""
    if not is_grammar_sheet(sheet or ""):
        return None
    res = parse_sheet(sheet, mode="template")
    if res.errors or not res.structure.usable:
        return None
    return res.structure


def _in_scope(st: SheetStructure) -> List[Rule]:
    return [r for r in st.rules if r.condition_source == "context" and r.effect in EFFECTS]


def rules_in_scope(sheet: str) -> Optional[List[Rule]]:
    """The context REPLACE / SUPPRESS / USE rules of a lint-clean grammar sheet, in sheet order. None when the
    sheet is not a grammar sheet or does not parse clean (the sheet is then used as today)."""
    st = _clean(sheet)
    return None if st is None else _in_scope(st)


def _first_quote(line: str) -> Optional[str]:
    m = _QUOTED.search(line)
    return m.group(1) if m else None


def apply_rules(sheet: str, rules: List[Rule], met: Dict[str, bool]) -> Tuple[str, List[str], List[dict]]:
    """(resolved sheet, decided slot lines, one evidence entry per rule). `met`: condition -> met for this case.
    Outcome per rule: "applied" (rule line removed; its effect written when met), "unmatched" (no unit line
    quotes its target: rule line left for the generator) or "conflict" (an earlier met rule already settled the
    same target: rule line left)."""
    lines = sheet.splitlines()
    out: List[Optional[str]] = list(lines)
    taken: set[int] = set()        # rule lines already matched to a rule
    claimed: set[str] = set()      # target keys settled by a met rule
    decided: List[str] = []
    per: List[dict] = []
    for r in rules:
        raw = r.source_lines[0] if r.source_lines else None
        i = next((k for k, ln in enumerate(lines) if k not in taken and ln == raw), None)
        entry = {"line": None if i is None else i + 1, "condition": r.condition, "effect": r.effect,
                 "met": bool(met.get(r.condition))}
        per.append(entry)
        if i is None:
            entry["outcome"] = "unmatched"
            continue
        taken.add(i)
        if r.effect == "use":
            if entry["met"]:
                out[i] = _RULE_USE.sub(lambda m: f"FIXED {m.group(1)}", lines[i], count=1)
                if SLOT.search(r.then_text):
                    decided.append(r.then_text)
            else:
                out[i] = None
            entry["outcome"] = "applied"
            continue
        key = norm_key(r.target)
        targets = [k for k, ln in enumerate(lines)
                   if k not in taken and _UNIT.match(ln) and (q := _first_quote(ln)) is not None and norm_key(q) == key]
        entry["targets"] = len(targets)
        if not targets:
            entry["outcome"] = "unmatched"
        elif not entry["met"]:
            out[i] = None
            entry["outcome"] = "applied"
        elif key in claimed:
            entry["outcome"] = "conflict"
        else:
            claimed.add(key)
            for k in targets:
                out[k] = None if r.effect == "suppress" else _QUOTED.sub(lambda m: f'"{r.then_text}"', lines[k], count=1)
            out[i] = None
            if r.effect == "replace" and SLOT.search(r.then_text):
                decided.append(r.then_text)
            entry["outcome"] = "applied"
    text = "\n".join(x for x in out if x is not None)
    return (text + "\n" if sheet.endswith("\n") else text), decided, per



def _left_on_stack(st: SheetStructure, rules: List[Rule]) -> Set[str]:
    """Rule ids the scratchpad path leaves as today: template_stack strips NORMAL / NEGATIVE units (a met REPLACE
    of one would lose its WITH text) and a USE in a findings section would become a FIXED clinical assertion."""
    findings = {s.name for s in st.sections if s.role == "findings"}
    stripped = {norm_key(n.text) for n in st.normals} | {norm_key(n.text) for n in st.negatives}
    return {r.id for r in rules
            if r.section in findings or (r.effect in ("replace", "suppress") and norm_key(r.target) in stripped)}


_NOT_DICTATED = ("DO NOT ASSERT (removed by the radiologist):",
                 "Confirmed normal (not dictated; confirmed by the radiologist):")
_ASSUMED = "Assumed normal (confirmed by the radiologist):"
_BARE_LABEL = re.compile(r"^\s*[^:]{0,60}:\s*$")


def jev_findings(findings: str) -> str:
    """The findings block minus what the radiologist did not dictate (the prefixes the scratchpad's regionState
    writes): removed and confirmed-normal lines go, an "Assumed normal" tail is cut to the end of its line, and a
    region label left bare goes. A removed sentence must never meet a condition."""
    out: List[str] = []
    for line in (findings or "").splitlines():
        if line.lstrip().startswith(_NOT_DICTATED):
            continue
        i = line.find(_ASSUMED)
        if i >= 0:
            line = line[:i].rstrip()
            if not line.strip() or _BARE_LABEL.match(line):
                continue
        out.append(line)
    return "\n".join(out)


Ask = Callable[[str, List[str]], Awaitable[List[float]]]


@dataclass
class Resolved:
    sheet: str                                          # what the generator reads (the stored sheet if unresolved)
    decided: List[str] = field(default_factory=list)    # lines a met rule wrote that carry {slots}
    record: dict = field(default_factory=dict)          # evidence: the candidate record's "context_rules"


async def resolve_context_rules(sheet: str, history: str, findings: str, ask: Optional[Ask] = None,
                                stack: bool = False) -> Resolved:
    """Settle the sheet's context rules for this case. Never raises: any failure returns the stored sheet with
    the error in the record. `findings`: the scratchpad's confirmed findings block, or the dictation. `stack`:
    the scratchpad path, where findings-side rules are left as today (_left_on_stack)."""
    t0 = time.perf_counter()
    rec: dict = {"asked": 0, "ms": 0, "error": None, "skipped": None, "rules": [], "slot_leaks": 0}

    def done(text: str, decided: Optional[List[str]] = None) -> Resolved:
        rec["ms"] = int((time.perf_counter() - t0) * 1000)
        outcomes = [e["outcome"] for e in rec["rules"]]
        logger.log(logging.WARNING if rec["error"] else logging.INFO,
                   "[template.context_rules] asked=%d met=%d applied=%d unmatched=%d conflict=%d left_stack=%d "
                   "skipped=%s error=%s ms=%d", rec["asked"], sum(bool(e["met"]) for e in rec["rules"]),
                   outcomes.count("applied"), outcomes.count("unmatched"), outcomes.count("conflict"),
                   outcomes.count("left_stack"), rec["skipped"], rec["error"], rec["ms"])
        return Resolved(sheet=text, decided=list(decided or []), record=rec)

    try:
        st = _clean(sheet)
        if st is None:
            rec["skipped"] = "parse"
            return done(sheet)
        rules = _in_scope(st)
        if not rules:
            rec["skipped"] = "no_rules"
            return done(sheet)
        left = _left_on_stack(st, rules) if stack else set()
        applied = [r for r in rules if r.id not in left]
        conds = list(dict.fromkeys(r.condition for r in applied))
        rec["asked"] = len(conds)
        scores: List[float] = []
        if conds:
            state = f"CLINICAL HISTORY:\n{history or '(not given)'}\nDICTATED FINDINGS:\n{jev_findings(findings)}"
            scores = await (ask or ask_conditions)(state, conds)
        if len(scores) != len(conds):
            rec["error"] = "jev: answer count mismatch"
            return done(sheet)
        score_of = dict(zip(conds, scores))
        text, decided, per = apply_rules(sheet, applied, {c: score_of.get(c, 0.0) >= CONDITION_MIN for c in conds})
        entries = iter({**e, "score": round(float(score_of.get(e["condition"], 0.0)), 3)} for e in per)
        lines = sheet.splitlines()
        for r in rules:
            if r.id not in left:
                rec["rules"].append(next(entries))
                continue
            raw = r.source_lines[0] if r.source_lines else None
            i = next((k for k, ln in enumerate(lines) if ln == raw), None)
            rec["rules"].append({"line": None if i is None else i + 1, "condition": r.condition, "effect": r.effect,
                                 "met": None, "score": None, "outcome": "left_stack"})
        return done(text, decided)
    except Exception as e:  # noqa: BLE001 -- fail-soft: the generator reads the stored sheet, as today
        rec["error"], rec["rules"] = f"{type(e).__name__}: {e}"[:300], []
        return done(sheet)


DECIDED_HEADING = "## Decided for This Case"
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"(])')
_LEAD = re.compile(r"^\s*(?:[-*•]\s+)?(?:\d+[.)]\s+)?(?:[*_#]*\s*[^:{}.\n]{1,40}:(?!\d)[*_]*\s*)?")   # indent, bullet, "**Header:** "


def decided_block(decided: List[str]) -> str:
    """The generator's instruction for lines a met rule wrote with {slots} (appended to the sheet it reads)."""
    if not decided:
        return ""
    lines = "\n".join(f'- "{t}"' for t in dict.fromkeys(decided))
    return (f"{DECIDED_HEADING}\n"
            "The template's rules decided these lines for this case. Write each in its place. Fill each {slot} "
            "with the value the FINDINGS input or the clinical history states; where neither states a slot's value, "
            "leave out the words that carry it. Never print a {slot}.\n" + lines)


def sheet_headers(sheet: str) -> Set[str]:
    """The declared section and paragraph headers of a clean grammar sheet (empty otherwise): the only bare
    leads the slot guard may keep."""
    st = _clean(sheet)
    if st is None:
        return set()
    heads = {h for s in st.sections for h in [s.header, *s.alt_headers] if h}
    return heads | {p.header for p in st.paragraphs if p.header}


def _head_key(text: str) -> str:
    return re.sub(r"[*_#]", "", text).strip().rstrip(":").strip().lower()


_ORPHAN = re.compile(r"\d+[.)]")
_ABBREV_END = re.compile(r"(?:^|\s)(?:Dr|Mr|Mrs|Ms|Prof|St|Fig|vs|approx|cf|e\.g|i\.e)\.$")


def _merge_numbers(parts: List[str]) -> List[str]:
    """A part that is only a list number ("2.") or a title/abbreviation ("Dr.") belongs to the sentence after it."""
    out: List[str] = []
    pending = ""
    for p in parts:
        if _ORPHAN.fullmatch(p) or _ABBREV_END.search(p):
            pending = p + " "
            continue
        out.append(pending + p)
        pending = ""
    if pending:
        out.append(pending.strip())
    return out


def strip_slot_sentences(report: str, headers=()) -> Tuple[str, int]:
    """Remove every sentence that still holds a {slot}, keeping the line's indent, bullet and "Header: " prefix.
    A line left empty is dropped, unless its lead is a declared header (`headers`), which is kept bare: a label
    like "Scan quality:" is not a header and goes with its value. Returns (report, sentences removed)."""
    if not SLOT.search(report or ""):
        return report, 0
    declared = {_head_key(h) for h in headers}
    out: List[str] = []
    removed = 0
    for line in report.splitlines():
        if not SLOT.search(line):
            out.append(line)
            continue
        lead = _LEAD.match(line).group(0)
        parts = _merge_numbers(_SENTENCE_END.split(line[len(lead):]))
        keep = [p for p in parts if not SLOT.search(p)]
        removed += len(parts) - len(keep)
        if keep:
            out.append(lead + " ".join(keep))
        elif ":" in lead and _head_key(lead) in declared:
            out.append(lead.rstrip())
    return "\n".join(out), removed
