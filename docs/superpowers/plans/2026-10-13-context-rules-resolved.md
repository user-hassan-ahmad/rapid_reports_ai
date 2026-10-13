# Context Rules Resolved Before Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jev decides each template context rule (REPLACE / SUPPRESS / USE) once per Generate, and code applies
it to the sheet before the generator reads it. The generator never merges a rule's branches and never prints a
`{slot}`.

**Spec:** `docs/superpowers/specs/2026-10-13-context-rules-resolved-design.md` (read it first).

**Architecture:**
- New pure-code module `template_context_rules.py`:
  - parse the sheet;
  - collect the context rules in scope;
  - one Jev call, `hybrid_stack.jev_stack.ask_conditions`, with the same question wording and the same 0.5
    cut-off the scratchpad uses;
  - rewrite the sheet text line by line.
- `template_lean.generate_template_report_lean` calls it before the generator, on both paths: the scratchpad
  (`stack`) and straight dictation.
- After generation, it removes any sentence that still holds a `{slot}`.
- The evidence goes on the candidate record as `context_rules`.

**Tech stack:**
- Python 3.13, pytest with pytest-asyncio (`asyncio_mode = "auto"`: async tests need no decorator);
- the existing grammar parser `template_sheet_grammar.parse_sheet`;
- Jev via `jev_stack.ask_conditions`.

**Working directory for every command:**
`/Users/hassan/Code/rapid_reports_ai/.claude/worktrees/hybrid-stack/backend`.
- Branch `feat/template-stack`.
- Never push.
- Tests: `.venv/bin/python -m pytest <path> -q`.

**Known baseline:** backend 3848 pass, with 1 known environment failure: `test_provider_key_routing`, the
anthropic-key case. Do not try to fix it.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `src/rapid_reports_ai/template_context_rules.py` | create | rules in scope, apply, resolve (Jev), decided block, slot guard |
| `tests/test_template_context_rules.py` | create | unit tests for the module (no network) |
| `src/rapid_reports_ai/template_lean.py` | modify `generate_template_report_lean` (~line 401-515) | resolve before the generator, guard after, record |
| `src/rapid_reports_ai/template_pipeline.py:373-382` | modify `candidate_record` | carry `context_rules` |
| `src/rapid_reports_ai/template_stack.py:77-86` | modify the "Fixed lines" rule text | the Decided-for-This-Case exception |
| `tests/test_template_lean.py`, `tests/test_template_stack.py` | add tests | wiring and prompt |

Facts the engineer needs:
- **Rule source lines.** `parse_sheet(sheet, mode="template")` returns a `GrammarResult` with `.structure`
  (a `SheetStructure`) and `.errors`. Each `Rule` has:
  - `condition`, `condition_source` (`"context"` for these rules) and `effect` (`"replace"`, `"suppress"`,
    `"use"`, …);
  - `target` (the quoted text for replace/suppress) and `then_text` (the WITH/USE text);
  - `source_lines`, a list holding **the raw line text** (not a number).
- **Unit lines.** They look like `FIXED "text"`, `NORMAL [label] "text"` or `NEGATIVE "text" …`, with an
  optional leading `- ` bullet and an optional trailing `| section: NAME`. In all three, the first quoted string
  is the statement.
- **`norm_key`** (`hybrid_stack/template.py`) is the match key that `template_suppressions` already uses: case,
  spacing and a final full stop ignored.
- **`ask_conditions(state, conditions)`** returns one float per condition, in order, and raises on HTTP failure.
  `CONDITION_MIN = 0.5`.

---

### Task 1: Rules in scope and the code apply step

**Files:**
- Create: `src/rapid_reports_ai/template_context_rules.py`
- Create: `tests/test_template_context_rules.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_template_context_rules.py`:

```python
"""Context rules resolved before generation (spec 2026-10-13-context-rules-resolved-design)."""
from __future__ import annotations

from rapid_reports_ai import template_context_rules as cr
from rapid_reports_ai.template_sheet_grammar import parse_sheet

PRIOR = "the dictation names a previous imaging study for comparison"
NOCON = "the study was performed without intravenous contrast"
OFFSITE = "images were reviewed off site"
NOLIVER = "the liver was not imaged"

SHEET = '''## Report Structure
SECTION COMPARISON | header: "Comparison:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
FIXED "No previous imaging available for comparison." | section: COMPARISON
RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous imaging available for comparison." WITH "Comparison made with previous {study} dated {date}." | section: COMPARISON
RULE WHEN [context: the study was performed without intravenous contrast] USE "No contrast." | section: COMPARISON
FIXED "Images reviewed on PACS." | section: COMPARISON
RULE WHEN [context: images were reviewed off site] SUPPRESS "Images reviewed on PACS." | section: COMPARISON

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
NORMAL [liver] "The liver is normal."
RULE WHEN [context: the liver was not imaged] SUPPRESS "The liver is normal."
'''


def _apply(met: set[str], sheet: str = SHEET):
    rules = cr.rules_in_scope(sheet)
    return cr.apply_rules(sheet, rules, {r.condition: r.condition in met for r in rules})


def test_rules_in_scope_are_the_context_replace_suppress_use_rules():
    rules = cr.rules_in_scope(SHEET)
    assert [(r.effect, r.condition) for r in rules] == [
        ("replace", PRIOR), ("use", NOCON), ("suppress", OFFSITE), ("suppress", NOLIVER)]


def test_rules_in_scope_is_none_for_a_non_grammar_or_unclean_sheet():
    assert cr.rules_in_scope("# Skill Sheet\nSome prose only.\n") is None
    assert cr.rules_in_scope(SHEET + 'FIXED "unclosed\n') is None


def test_nothing_met_keeps_every_default_and_removes_every_rule_line():
    sheet, decided, per = _apply(set())
    assert "RULE " not in sheet and decided == []
    assert 'FIXED "No previous imaging available for comparison."' in sheet
    assert 'FIXED "Images reviewed on PACS."' in sheet and 'NORMAL [liver] "The liver is normal."' in sheet
    assert "No contrast." not in sheet
    assert [e["outcome"] for e in per] == ["applied"] * 4 and not any(e["met"] for e in per)


def test_met_replace_rewrites_the_default_line_and_records_the_slot_line():
    sheet, decided, _ = _apply({PRIOR})
    assert ('FIXED "Comparison made with previous {study} dated {date}." | section: COMPARISON' in sheet)
    assert "No previous imaging available" not in sheet
    assert decided == ["Comparison made with previous {study} dated {date}."]


def test_met_use_becomes_a_fixed_line_in_place_and_met_suppress_removes_the_line():
    sheet, decided, _ = _apply({NOCON, OFFSITE, NOLIVER})
    assert 'FIXED "No contrast." | section: COMPARISON' in sheet
    assert "Images reviewed on PACS." not in sheet and "The liver is normal." not in sheet
    assert decided == []   # no slots


def test_the_resolved_sheet_still_lints_clean():
    for met in (set(), {PRIOR, NOCON, OFFSITE, NOLIVER}):
        sheet, _, _ = _apply(met)
        res = parse_sheet(sheet, mode="template")
        assert res.errors == [] and res.structure.usable


def test_target_match_ignores_case_spacing_and_the_final_full_stop():
    sheet = SHEET.replace('SUPPRESS "Images reviewed on PACS."', 'SUPPRESS "images  reviewed on PACS"')
    out, _, per = _apply({OFFSITE}, sheet)
    assert "Images reviewed on PACS." not in out
    assert next(e for e in per if e["condition"] == OFFSITE)["outcome"] == "applied"


def test_an_unmatched_target_leaves_the_rule_line_for_the_generator():
    sheet = SHEET.replace('SUPPRESS "Images reviewed on PACS."', 'SUPPRESS "A sentence in no unit line."')
    out, _, per = _apply({OFFSITE}, sheet)
    assert 'RULE WHEN [context: images were reviewed off site] SUPPRESS "A sentence in no unit line."' in out
    assert next(e for e in per if e["condition"] == OFFSITE)["outcome"] == "unmatched"


def test_two_met_rules_on_one_target_apply_the_first_and_leave_the_second():
    extra = ('RULE WHEN [context: the patient declined comparison] REPLACE '
             '"No previous imaging available for comparison." WITH "Comparison declined." | section: COMPARISON\n')
    sheet = SHEET.replace("FIXED \"Images reviewed on PACS.\"", extra + "FIXED \"Images reviewed on PACS.\"")
    out, _, per = _apply({PRIOR, "the patient declined comparison"}, sheet)
    assert "Comparison made with previous {study} dated {date}." in out and 'FIXED "Comparison declined."' not in out
    assert "RULE WHEN [context: the patient declined comparison]" in out
    assert [e["outcome"] for e in per if e["condition"] == "the patient declined comparison"] == ["conflict"]


def test_rules_outside_scope_are_untouched():
    sheet = SHEET.replace("## Paragraph: Liver (FINDINGS)",
                          "RULE WHEN [context: T2 imaging was not acquired] SUPPRESS_SECTION CONCLUSION | section: CONCLUSION\n\n"
                          "## Paragraph: Liver (FINDINGS)")
    out, _, per = _apply(set(), sheet)
    assert "SUPPRESS_SECTION CONCLUSION" in out and len(per) == 4
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'rapid_reports_ai.template_context_rules'`.

- [ ] **Step 3: Implement the module (rules in scope and apply)**

`src/rapid_reports_ai/template_context_rules.py`:

```python
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
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: 10 passed.

If `import rapid_reports_ai.template_context_rules` raises a circular-import error, move the `norm_key` import
into `apply_rules`. Do not copy the function.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_context_rules.py tests/test_template_context_rules.py
git commit -m "feat(template): apply context rules to the sheet by code (rules in scope + apply)"
```

---

### Task 2: Resolve with Jev, with fail-soft and evidence

**Files:**
- Modify: `src/rapid_reports_ai/template_context_rules.py`
- Modify: `tests/test_template_context_rules.py`

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
def _ask(scores: dict, calls: list | None = None):
    async def ask(state, conditions):
        if calls is not None:
            calls.append((state, list(conditions)))
        return [scores.get(c, 0.0) for c in conditions]
    return ask


async def test_resolve_asks_each_distinct_condition_once_on_history_and_findings():
    calls: list = []
    res = await cr.resolve_context_rules(SHEET, "?lesion", "Compared with the CT of 02/12/2025.",
                                         ask=_ask({PRIOR: 0.9}, calls))
    (state, conds), = calls
    assert conds == [PRIOR, NOCON, OFFSITE, NOLIVER]
    assert state == "CLINICAL HISTORY:\n?lesion\nDICTATED FINDINGS:\nCompared with the CT of 02/12/2025."
    assert "Comparison made with previous {study} dated {date}." in res.sheet
    assert res.decided == ["Comparison made with previous {study} dated {date}."]
    rec = res.record
    assert rec["asked"] == 4 and rec["error"] is None and rec["skipped"] is None and rec["slot_leaks"] == 0
    first = rec["rules"][0]
    assert first == {"line": 8, "condition": PRIOR, "effect": "replace", "met": True, "score": 0.9,
                     "outcome": "applied"}


async def test_the_cut_off_is_the_scratchpads_and_silence_is_not_met():
    res = await cr.resolve_context_rules(SHEET, "", "Liver normal.", ask=_ask({PRIOR: 0.49, NOCON: 0.5}))
    assert "No previous imaging available for comparison." in res.sheet
    assert 'FIXED "No contrast."' in res.sheet
    assert "(not given)" not in res.sheet   # the history placeholder is state only


async def test_a_jev_failure_leaves_the_stored_sheet_unchanged():
    async def down(state, conditions):
        raise RuntimeError("jev 503")
    res = await cr.resolve_context_rules(SHEET, "", "x", ask=down)
    assert res.sheet == SHEET and res.decided == []
    assert res.record["error"].startswith("RuntimeError: jev 503") and res.record["rules"] == []


async def test_a_non_grammar_sheet_or_a_sheet_without_rules_asks_nothing():
    calls: list = []
    legacy = "# Skill Sheet\nSome prose only.\n"
    res = await cr.resolve_context_rules(legacy, "", "x", ask=_ask({}, calls))
    assert res.sheet == legacy and res.record["skipped"] == "parse" and calls == []
    bare = SHEET.split("## Report-wide")[0] + "## Paragraph: Liver (FINDINGS)\nCOVERS [\"liver\"]\n"
    res = await cr.resolve_context_rules(bare, "", "x", ask=_ask({}, calls))
    assert res.sheet == bare and res.record["skipped"] == "no_rules" and calls == []
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: 4 failures with `AttributeError: module ... has no attribute 'resolve_context_rules'`.

- [ ] **Step 3: Implement** (append to the module; extend the imports at the top)

Add to the imports:

```python
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .hybrid_stack.jev_stack import CONDITION_MIN, ask_conditions

logger = logging.getLogger(__name__)
```

(Merge the new `typing` names into the existing `from typing import …` line.)

Append:

```python
Ask = Callable[[str, List[str]], Awaitable[List[float]]]


@dataclass
class Resolved:
    sheet: str                                          # what the generator reads (the stored sheet if unresolved)
    decided: List[str] = field(default_factory=list)    # lines a met rule wrote that carry {slots}
    record: dict = field(default_factory=dict)          # evidence: the candidate record's "context_rules"


async def resolve_context_rules(sheet: str, history: str, findings: str, ask: Optional[Ask] = None) -> Resolved:
    """Settle the sheet's context rules for this case. Never raises: any failure returns the stored sheet with
    the error in the record. `findings`: the scratchpad's confirmed findings block, or the dictation."""
    t0 = time.perf_counter()
    rec: dict = {"asked": 0, "ms": 0, "error": None, "skipped": None, "rules": [], "slot_leaks": 0}

    def done(text: str, decided: Optional[List[str]] = None) -> Resolved:
        rec["ms"] = int((time.perf_counter() - t0) * 1000)
        outcomes = [e["outcome"] for e in rec["rules"]]
        logger.log(logging.WARNING if rec["error"] else logging.INFO,
                   "[template.context_rules] asked=%d met=%d applied=%d unmatched=%d conflict=%d skipped=%s "
                   "error=%s ms=%d", rec["asked"], sum(e["met"] for e in rec["rules"]), outcomes.count("applied"),
                   outcomes.count("unmatched"), outcomes.count("conflict"), rec["skipped"], rec["error"], rec["ms"])
        return Resolved(sheet=text, decided=list(decided or []), record=rec)

    try:
        rules = rules_in_scope(sheet)
        if rules is None:
            rec["skipped"] = "parse"
            return done(sheet)
        if not rules:
            rec["skipped"] = "no_rules"
            return done(sheet)
        conds = list(dict.fromkeys(r.condition for r in rules))
        rec["asked"] = len(conds)
        state = f"CLINICAL HISTORY:\n{history or '(not given)'}\nDICTATED FINDINGS:\n{findings}"
        scores = await (ask or ask_conditions)(state, conds)
        score_of = dict(zip(conds, scores))
        text, decided, per = apply_rules(sheet, rules, {c: score_of.get(c, 0.0) >= CONDITION_MIN for c in conds})
        rec["rules"] = [{**e, "score": round(float(score_of.get(e["condition"], 0.0)), 3)} for e in per]
        return done(text, decided)
    except Exception as e:  # noqa: BLE001 -- fail-soft: the generator reads the stored sheet, as today
        rec["error"], rec["rules"] = f"{type(e).__name__}: {e}"[:300], []
        return done(sheet)
```

Note: the expected `first` dict in the test fixes the key order. Python dict equality ignores order, so that is
fine.

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_context_rules.py tests/test_template_context_rules.py
git commit -m "feat(template): resolve context rules with one Jev call; fail-soft to the stored sheet"
```

---

### Task 3: Decided block and slot guard

**Files:**
- Modify: `src/rapid_reports_ai/template_context_rules.py`
- Modify: `tests/test_template_context_rules.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_decided_block_lists_each_slot_line_once_with_the_partial_fill_instruction():
    assert cr.decided_block([]) == ""
    block = cr.decided_block(["Compared with the {study} of {date}.", "Compared with the {study} of {date}."])
    assert block.startswith(cr.DECIDED_HEADING + "\n")
    assert block.count('- "Compared with the {study} of {date}."') == 1
    assert "leave out the words that carry it" in block


def test_slot_guard_removes_only_the_sentence_holding_a_slot():
    report = ("Comparison: Comparison made with previous CT dated {date}.\n"
              "Findings: The liver is normal. A {size} cyst. No ascites.\n"
              "- Note made of previous {study}.\n"
              "Conclusion: Normal study.")
    out, n = cr.strip_slot_sentences(report)
    assert n == 3
    assert out == "Comparison:\nFindings: The liver is normal. No ascites.\nConclusion: Normal study."


def test_slot_guard_leaves_a_report_without_slots_untouched():
    report = "Findings: Normal.\n\nConclusion: Normal study."
    assert cr.strip_slot_sentences(report) == (report, 0)
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: 3 failures (`AttributeError`).

- [ ] **Step 3: Implement** (append to the module)

```python
DECIDED_HEADING = "## Decided for This Case"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LEAD = re.compile(r"^\s*(?:[-*•]\s+)?(?:[^:{}.]{1,40}:\s+)?")   # indent, bullet, "Header: "


def decided_block(decided: List[str]) -> str:
    """The generator's instruction for lines a met rule wrote with {slots} (appended to the sheet it reads)."""
    if not decided:
        return ""
    lines = "\n".join(f'- "{t}"' for t in dict.fromkeys(decided))
    return (f"{DECIDED_HEADING}\n"
            "The template's rules decided these lines for this case. Write each in its place. Fill each {slot} "
            "with the value the FINDINGS input or the clinical history states; where neither states a slot's value, "
            "leave out the words that carry it. Never print a {slot}.\n" + lines)


def strip_slot_sentences(report: str) -> Tuple[str, int]:
    """Remove every sentence that still holds a {slot}, keeping the line's indent, bullet and "Header: " prefix;
    a line left empty is dropped (a bare header is kept). Returns (report, sentences removed)."""
    if not SLOT.search(report or ""):
        return report, 0
    out: List[str] = []
    removed = 0
    for line in report.splitlines():
        if not SLOT.search(line):
            out.append(line)
            continue
        lead = _LEAD.match(line).group(0)
        parts = _SENTENCE_END.split(line[len(lead):])
        keep = [p for p in parts if not SLOT.search(p)]
        removed += len(parts) - len(keep)
        if keep:
            out.append(lead + " ".join(keep))
        elif ":" in lead:
            out.append(lead.rstrip())
    return "\n".join(out), removed
```

Check against the test:
- `"- Note made of previous {study}."` has lead `"- "`, no header and one part that is removed, so the line is
  dropped.
- `"Comparison: …"` has lead `"Comparison: "`, so the line becomes `"Comparison:"`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/bin/python -m pytest tests/test_template_context_rules.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_context_rules.py tests/test_template_context_rules.py
git commit -m "feat(template): decided-lines block and a code guard that no {slot} reaches a report"
```

---

### Task 4: Wire into the lean Generate, the candidate record and the stack prompt

**Files:**
- Modify: `src/rapid_reports_ai/template_lean.py` (`generate_template_report_lean`, ~401-515)
- Modify: `src/rapid_reports_ai/template_pipeline.py:373-382` (`candidate_record`)
- Modify: `src/rapid_reports_ai/template_stack.py:77-86` (the "Fixed lines" rule)
- Test: `tests/test_template_lean.py`, `tests/test_template_stack.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_template_lean.py`. `_gen_fakes`, `CASE` and `REPORT` already exist in that file.
`fake_gen` records `calls["gen"] = {"sheet": template_config["skill_sheet"], …, "stack": stack}`: read lines
136-141 to confirm the key names before you write the asserts.

```python
from rapid_reports_ai import template_context_rules as cr
from rapid_reports_ai import template_pipeline as tp

RULED = '''## Report Structure
SECTION COMPARISON | header: "Comparison:" | role: technique
SECTION FINDINGS | header: "Findings:" | role: findings
SECTION CONCLUSION | header: "Conclusion:" | role: impression

## Report-wide
FIXED "No previous imaging available for comparison." | section: COMPARISON
RULE WHEN [context: the dictation names a previous imaging study for comparison] REPLACE "No previous imaging available for comparison." WITH "Comparison made with previous {study} dated {date}." | section: COMPARISON

## Paragraph: Liver (FINDINGS)
COVERS ["liver"]
'''


def _met(score):
    async def ask(state, conditions):
        return [score for _ in conditions]
    return ask


async def test_both_paths_give_the_generator_the_resolved_sheet_and_record_it(monkeypatch):
    for stack in (None, {"conclusion": "Normal.", "declined": []}):
        calls = {}
        _gen_fakes(monkeypatch, calls)
        monkeypatch.setattr(cr, "ask_conditions", _met(0.9))
        out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Compared with CT 02/12/2025.",
                                                     history="", case=CASE, signature=None, stack=stack)
        sent = calls["gen"]["sheet"]
        assert "RULE WHEN" not in sent and "No previous imaging available" not in sent
        assert 'FIXED "Comparison made with previous {study} dated {date}."' in sent
        assert sent.rstrip().endswith('- "Comparison made with previous {study} dated {date}."')
        assert out["context_rules"]["rules"][0]["outcome"] == "applied" and "rules_s" in out["lat"]
        if out.get("options_job") is not None:
            await out["options_job"]


async def test_a_slot_left_in_the_generated_report_is_removed_and_counted(monkeypatch):
    calls = {}
    _gen_fakes(monkeypatch, calls)

    async def gen(self, template_config, user_inputs, stack=None, **kw):
        return {"report_content": "Comparison: Comparison made with previous CT dated {date}.\n\nFindings: Normal.",
                "model_used": "q", "description": "d", "scan_type": "CT"}
    monkeypatch.setattr(tl.TemplateManager, "_generate_report_skill_sheet_guided", gen)
    monkeypatch.setattr(cr, "ask_conditions", _met(0.9))
    out = await tl.generate_template_report_lean(sheet=RULED, scan_type="CT", findings="Previous CT.", history="",
                                                 case=None, signature=None, stack={"conclusion": "", "declined": []})
    assert "{date}" not in out["report_content"] and "{date}" not in out["report_generated"]
    assert out["context_rules"]["slot_leaks"] == 1


def test_candidate_record_carries_context_rules():
    rec = tp.candidate_record({"report_content": "x", "context_rules": {"asked": 1}}, 10)
    assert rec["context_rules"] == {"asked": 1}
```

Note: `resolve_context_rules` reads `ask_conditions` from the module global when `ask` is None, so
monkeypatching `cr.ask_conditions` takes effect. Implement `(ask or ask_conditions)` exactly as in Task 2: a
name looked up at call time.

Append to `tests/test_template_stack.py`:

```python
def test_fixed_line_rule_names_the_decided_block_exception():
    from rapid_reports_ai.template_context_rules import DECIDED_HEADING
    from rapid_reports_ai.template_stack import stack_brief
    assert DECIDED_HEADING.lstrip("# ") in stack_brief("", "", ())
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `.venv/bin/python -m pytest tests/test_template_lean.py tests/test_template_stack.py -q`
Expected: the 4 new tests fail. The existing ones pass.

- [ ] **Step 3: Implement**

**(a) `template_lean.py`.** Add near the other imports:

```python
from .template_context_rules import decided_block, resolve_context_rules, strip_slot_sentences
```

Replace the body of `gen()`:

```python
    async def gen():
        t0 = time.time()
        # Context rules settled by Jev and applied by code (spec 2026-10-13-context-rules-resolved-design): the
        # generator reads one decided line where the sheet had a default plus a rule. Fail-soft: stored sheet.
        resolved = await resolve_context_rules(sheet, history, findings)
        rec["context_rules"] = resolved.record
        block = decided_block(resolved.decided)
        gen_sheet = resolved.sheet + ("\n\n" + block if block else "")
        rec["lat"]["rules_s"] = round(time.time() - t0, 1)
        t1 = time.time()
        out = await TemplateManager()._generate_report_skill_sheet_guided(
            template_config={"generation_mode": "skill_sheet_guided", "skill_sheet": gen_sheet, "scan_type": scan_type},
            user_inputs={"FINDINGS": findings, "CLINICAL_HISTORY": history}, stack=stack)
        rec["lat"]["generator_s"] = round(time.time() - t1, 1)
        return out
```

Replace the two lines right after `out = await gen()` / the `except` block:

```python
    report = out["report_content"]
    rec["report_generated"] = report
```

with:

```python
    # No {slot} ever reaches a report: a sentence still holding one is removed (and counted)
    report, leaks = strip_slot_sentences(out["report_content"])
    rec["context_rules"]["slot_leaks"] = leaks
    if leaks:
        logger.warning("[template.context_rules] slot_leaks=%d removed from the generated report", leaks)
    rec["report_generated"] = report
```

Leave every later use of `sheet` (`report_sections(report, sheet)`, `undictated_numbers(…, sheet)`) on the
**stored** sheet. Also update the docstring of `generate_template_report_lean`. Add one sentence: "Context rules
are resolved before the generator (template_context_rules) and any {slot} left in the report is removed."

**(b) `template_pipeline.py` `candidate_record`.** Add one key to the returned dict, after `"lat"`:

```python
            "context_rules": result.get("context_rules"),
```

**(c) `template_stack.py`.** In the "Fixed lines" string, find:

```
"RULE applies. A FIXED line with {slots} is written only when the input gives every slot's value; otherwise "
"it is left out.\n"
```

Change it to:

```
"RULE applies. A FIXED line with {slots} is written only when the input gives every slot's value; otherwise "
"it is left out, except a line listed under Decided for This Case, which is written as that block says.\n"
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/bin/python -m pytest tests/test_template_lean.py tests/test_template_stack.py tests/test_template_context_rules.py -q`
Expected: all pass.

If an existing test compares `candidate_record(...)` to an exact dict, add `"context_rules": None` to its
expected dict. That is the only acceptable change to existing tests.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_lean.py src/rapid_reports_ai/template_pipeline.py src/rapid_reports_ai/template_stack.py tests/test_template_lean.py tests/test_template_stack.py
git commit -m "feat(template): resolve context rules before both lean Generates; slot guard; evidence on the candidate"
```

---

### Task 5: Full suite

- [ ] **Step 1:** Run the whole backend suite.

Run: `.venv/bin/python -m pytest -q -x --deselect tests/test_provider_key_routing.py 2>&1 | tail -5`
Expected: all pass. The count should be about 3848 + 21, with the known environment failure deselected.

- [ ] **Step 2:** If anything fails, fix it in the task's own files and commit with
  `fix(template): …`. Never edit unrelated tests to make them pass.

---

### Task 6: Lab — the 23 prior / no-prior cases, before and after (controller-run; reported, Hassan decides)

This task runs outside the repository, in the private folder `~/Code/rr-template-conversion-private`.
- Production-derived data never enters the repo.
- It makes live Jev and Cerebras calls, so run it in its **own** agent, separate from any agent that edits code.
- The existing `e2e.py` calls `generate_report_from_config`, which is today's fallback path and not the lean
  function. A new runner is needed.

- [ ] **Step 1:** Write `~/Code/rr-template-conversion-private/e2e_lean.py`.
  - Copy `e2e.py`.
  - Replace both generator calls with `template_lean.generate_template_report_lean(sheet=…, scan_type=…,
    findings=<block or dictation>, history=…, case=None, signature=None, stack=<stack or None>)`.
  - Await the returned `options_job` if it is not None, then discard it.
  - Store `report_content` and `context_rules` for both arms (`report`, `plain_report`, `context_rules_sp`,
    `context_rules_pl`).
  - Add a `--before` flag that monkeypatches
    `template_context_rules.resolve_context_rules` to return
    `Resolved(sheet=sheet, record={"asked": 0, "ms": 0, "error": None, "skipped": "before", "rules": [], "slot_leaks": 0})`.
    Also patch `template_lean.resolve_context_rules`, because the lean module imports the name.
- [ ] **Step 2:** Run every `final/*.e2e_prior*_case.json` twice: with `--before` into `<slug>.lean_before.json`,
  and without it into `<slug>.lean_after.json`. Use `DATABASE_URL=sqlite:///<scratchpad>/lab.db` and
  `PYTHONPATH=src`, from the hybrid-stack `backend/`. Never overwrite an existing output file.
- [ ] **Step 3:** Run `check_prior_e2e.py` (or a copy pointed at the new file names) on both sets. Write
  `final/E2E_CONTEXT_RULES.md`:
  - a table per case and arm: before / after, SP / PL, and the comparison line printed;
  - counts of merged-branch lines, raw `{slot}`, missing comparison lines, `slot_leaks`, and unmatched / conflict
    rules;
  - Jev condition scores per case;
  - the garbled case (ct_trauma_polytrauma) and the vague case (ct_abdomen_and_pelvis_with_contrast) called out.
- [ ] **Step 4:** Report the results and recommendations to Hassan. No pass/fail gate.

---

### Task 7: Synthetic follow-up lab (controller-run; after Task 6 is reported)

- [ ] **Step 1:** An Opus subagent writes about 30 synthetic cases into
  `~/Code/rr-template-conversion-private/synthetic/context_rules/`, seeded from the 31 `final/*.final.md`
  sheets.
  - Six context rules: the prior-imaging pattern plus five others (contrast, artefact, protocol variant, and two
    more chosen by the agent from different sheets).
  - Variants per rule: stated, silent, negated, vague (no date or study), and two priors. Real-style messy
    dictation.
  - Each case: `{sheet_slug, rule_condition, dictation, history, expected_met: bool, expected_line_shape}`. The
    planted truth is written before any run.
- [ ] **Step 2:** In a separate agent, run only `resolve_context_rules` (real Jev; no generator) over the cases.
  Report the met accuracy per rule and variant, against the planted truth. Then run the full lean Generate on 10
  cases (both arms) and hand-read the comparison lines.
- [ ] **Step 3:** Write `synthetic/context_rules/REPORT.md`. Say how the synthetic set may be cleaner than
  production. Report to Hassan.
