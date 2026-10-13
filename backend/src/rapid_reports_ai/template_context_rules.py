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

import re
from typing import Dict, List, Optional, Tuple

from .hybrid_stack.template import norm_key
from .template_sheet_grammar import is_grammar_sheet, parse_sheet
from .template_sheet_structure import Rule

EFFECTS = ("replace", "suppress", "use")
_UNIT = re.compile(r"^\s*(?:-\s+)?(?:FIXED|NORMAL|NEGATIVE)\b")
_QUOTED = re.compile(r'"([^"]+)"')
_RULE_USE = re.compile(r'RULE\s+WHEN\s*\[[^\]]*\]\s*USE\s*("[^"]+")')
SLOT = re.compile(r"\{[^{}\n]*\}")


def rules_in_scope(sheet: str) -> Optional[List[Rule]]:
    """The context REPLACE / SUPPRESS / USE rules of a lint-clean grammar sheet, in sheet order. None when the
    sheet is not a grammar sheet or does not parse clean (the sheet is then used as today)."""
    if not is_grammar_sheet(sheet or ""):
        return None
    res = parse_sheet(sheet, mode="template")
    if res.errors or not res.structure.usable:
        return None
    return [r for r in res.structure.rules if r.condition_source == "context" and r.effect in EFFECTS]


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
