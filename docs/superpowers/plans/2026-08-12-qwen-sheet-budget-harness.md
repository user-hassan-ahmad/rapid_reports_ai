# Qwen Sheet-Budget Experiment Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a harness that measures report quality as a function of skill-sheet structural budget on the matched Qwen 3.6 27B analyser→generator pair, and emits a quality-vs-tokens curve.

**Architecture:** A budget directive is appended to the existing analyser prompt as an override block; five tiers cut sheet content breadth-first then depth-first. Each run is scored by a free structural gate, then by the existing v2.2 Sonnet judge (survivors only) called against an ad-hoc case dict rather than a DB row. Output is a CSV plus a published artifact plotting judge score against achieved sheet tokens.

**Tech Stack:** Python 3.11, pydantic-ai, pytest (`asyncio_mode = "auto"`, `pythonpath = ["src"]`), Groq via `qwen/qwen3.6-27b`, Anthropic Sonnet 4.5 as judge.

**Spec:** `docs/superpowers/specs/2026-08-12-qwen-sheet-budget-experiment-design.md`

---

## Deliberate deviation from the spec

The spec calls for a separate `ANALYSER_SYSTEM_PROMPT_QWEN` constant. **Don't build one.** Duplicating a 25KB prompt creates a third copy to maintain, and `project_report_integrity_hardening` already records that the analyser prompt existing twice is a live source of edit errors.

Instead the budget is an **override block appended to the existing GLM prompt** when a directive is supplied. This is strictly better for the experiment: with an empty directive the function returns the GLM prompt **byte-identical**, so T1 is a true control that exactly reproduces what the bake-off ran — removing the confound the spec flagged in §4 ("if T1 lands far from ~3,400 tokens, the Qwen prompt has itself moved sheet length"). That risk disappears entirely.

`get_analyser_prompt()` gains an optional second parameter with an empty default, so every existing caller is unchanged. Task 1 includes a regression test asserting byte-identical output for the two production models.

---

## File Structure

**Create:**
- `backend/test_cases/qwen_sheet_budget.json` — the five tier definitions
- `backend/src/rapid_reports_ai/scripts/sheet_budget/__init__.py` — package marker
- `backend/src/rapid_reports_ai/scripts/sheet_budget/tiers.py` — tier loading, validation, directive rendering
- `backend/src/rapid_reports_ai/scripts/sheet_budget/compliance.py` — counts structural elements in a produced sheet
- `backend/src/rapid_reports_ai/scripts/sheet_budget/gate.py` — free structural/integrity checks
- `backend/src/rapid_reports_ai/scripts/sheet_budget/judge.py` — ad-hoc v2.2 judge adapter (no DB)
- `backend/src/rapid_reports_ai/scripts/sheet_budget/runner.py` — orchestration + CLI
- `backend/src/rapid_reports_ai/scripts/sheet_budget/report.py` — CSV + artifact HTML emitter
- `backend/tests/test_sheet_budget_suite.py` — all unit tests

**Modify:**
- `backend/src/rapid_reports_ai/quick_report_analyser.py` — `get_analyser_prompt()` signature, `BUDGET_OVERRIDE_BLOCK`, `generate_ephemeral_skill_sheet()` passthrough

Split by responsibility: parsing, scoring, judging, and orchestration each stand alone and are separately testable. `runner.py` is the only module that performs network calls, which keeps every other module unit-testable with no mocking of providers.

---

### Task 1: Budget directive plumbing in the analyser

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py:628-637` (`get_analyser_prompt`), `:662-750` (`generate_ephemeral_skill_sheet`)
- Test: `backend/tests/test_sheet_budget_suite.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sheet_budget_suite.py`:

```python
"""Tests for the Qwen sheet-budget experiment harness.

Spec: docs/superpowers/specs/2026-08-12-qwen-sheet-budget-experiment-design.md
"""
from __future__ import annotations

from rapid_reports_ai import quick_report_analyser as qra


def test_production_prompts_are_byte_identical_without_a_budget():
    """Regression guard: the two production analysers must not change at all."""
    assert qra.get_analyser_prompt("zai-glm-4.7") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )


def test_empty_budget_leaves_no_override_block():
    """T1 is a true control - identical to what the bake-off ran."""
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "") == qra.ANALYSER_SYSTEM_PROMPT_GLM
    assert qra.get_analyser_prompt("qwen/qwen3.6-27b", "   ") == qra.ANALYSER_SYSTEM_PROMPT_GLM


def test_budget_directive_is_appended_and_placeholder_is_consumed():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    assert "Cover exactly 3 findings." in prompt
    assert "{{BUDGET_DIRECTIVE}}" not in prompt
    assert prompt.startswith(qra.ANALYSER_SYSTEM_PROMPT_GLM)


def test_budget_block_declares_itself_an_override():
    prompt = qra.get_analyser_prompt("qwen/qwen3.6-27b", "Cover exactly 3 findings.")
    tail = prompt[len(qra.ANALYSER_SYSTEM_PROMPT_GLM):]
    assert "OVERRIDE" in tail.upper()


def test_anthropic_ignores_the_budget():
    """Sonnet path is out of scope for this experiment and must not change."""
    assert (
        qra.get_analyser_prompt("claude-haiku-4-5-20251001", "Cover exactly 3 findings.")
        == qra.ANALYSER_SYSTEM_PROMPT_SONNET
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v`
Expected: FAIL — `TypeError: get_analyser_prompt() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Add the override block and widen the dispatcher**

In `backend/src/rapid_reports_ai/quick_report_analyser.py`, directly above `def get_analyser_prompt`:

```python
# Appended to the analyser prompt only when a structural budget is supplied.
# Placed last so it wins on recency against the counts stated in Phases 4-7,
# and labelled as an override so the contradiction is explicit rather than
# left for the model to arbitrate.
BUDGET_OVERRIDE_BLOCK = """

---

## Structural Budget — OVERRIDES all counts stated above

The counts below replace any conflicting quantity given earlier in this prompt.
Where a section is budgeted, emit exactly the stated number of items. Where a
budget is not stated for a section, follow the guidance above unchanged. Emit a
complete, well-formed sheet at every budget — cover less, never stop early.

{{BUDGET_DIRECTIVE}}
"""
```

Replace `get_analyser_prompt` with:

```python
def get_analyser_prompt(model_name: str, budget_directive: str = "") -> str:
    """Dispatch the analyser system prompt by model identifier.

    - any model starting with "claude" → Sonnet-bespoke principle-led prompt
    - everything else → GLM prompt

    ``budget_directive`` appends a structural-budget override block used by the
    sheet-budget experiment. Empty (the default, and every production caller)
    returns the prompt byte-identical to its pre-experiment form. Anthropic
    models ignore the budget — that path is out of the experiment's scope.
    """
    if model_name.startswith("claude"):
        return ANALYSER_SYSTEM_PROMPT_SONNET
    if budget_directive.strip():
        return ANALYSER_SYSTEM_PROMPT_GLM + BUDGET_OVERRIDE_BLOCK.replace(
            "{{BUDGET_DIRECTIVE}}", budget_directive
        )
    return ANALYSER_SYSTEM_PROMPT_GLM
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Thread the directive through the analyser call**

In `generate_ephemeral_skill_sheet` (`quick_report_analyser.py:662`), add the parameter to the signature after `model_override`:

```python
    budget_directive: str = "",
```

Then change the `system_prompt` line (currently `quick_report_analyser.py:739`) from:

```python
    system_prompt = get_analyser_prompt(model_name)
```

to:

```python
    system_prompt = get_analyser_prompt(model_name, budget_directive)
```

- [ ] **Step 6: Verify the existing analyser suite still passes**

Run: `cd backend && poetry run pytest tests/test_quick_report_prompts.py -v`
Expected: PASS — no regression in existing prompt tests

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/quick_report_analyser.py backend/tests/test_sheet_budget_suite.py
git commit -m "feat(analyser): optional structural-budget override block

Additive: empty directive returns the GLM prompt byte-identical, so both
production analysers are unchanged and T1 of the budget experiment is a
true control."
```

---

### Task 2: Tier configuration and loader

**Files:**
- Create: `backend/test_cases/qwen_sheet_budget.json`, `backend/src/rapid_reports_ai/scripts/sheet_budget/__init__.py`, `backend/src/rapid_reports_ai/scripts/sheet_budget/tiers.py`
- Test: `backend/tests/test_sheet_budget_suite.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sheet_budget_suite.py`:

```python
from rapid_reports_ai.scripts.sheet_budget import tiers as T


def test_tiers_load_all_five():
    loaded = T.load_tiers()
    assert [t["id"] for t in loaded] == ["T1", "T2", "T3", "T4", "T5"]


def test_t1_is_the_unbudgeted_control():
    t1 = T.load_tiers()[0]
    assert t1["findings"] is None
    assert t1["variants_per_finding"] is None
    assert T.render_directive(t1) == ""


def test_budgets_are_non_increasing_down_the_ladder():
    T.validate_tiers(T.load_tiers())  # raises if not


def test_validate_rejects_an_increasing_ladder():
    bad = [
        {"id": "A", "findings": 2, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
        {"id": "B", "findings": 4, "variants_per_finding": 1, "impression_exemplars": 1,
         "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "full"},
    ]
    try:
        T.validate_tiers(bad)
    except ValueError as exc:
        assert "findings" in str(exc)
    else:
        raise AssertionError("expected ValueError on an increasing ladder")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k tier`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.scripts.sheet_budget'`

- [ ] **Step 3: Create the tier config**

Create `backend/test_cases/qwen_sheet_budget.json`:

```json
[
  {"id": "T1", "cuts": "control",
   "findings": null, "variants_per_finding": null, "impression_exemplars": null,
   "interpretive_clauses": null, "mandatory_negatives": null, "normal_study_path": null},
  {"id": "T2", "cuts": "breadth",
   "findings": 4, "variants_per_finding": 3, "impression_exemplars": 2,
   "interpretive_clauses": 4, "mandatory_negatives": 4, "normal_study_path": "full"},
  {"id": "T3", "cuts": "breadth",
   "findings": 3, "variants_per_finding": 3, "impression_exemplars": 2,
   "interpretive_clauses": 3, "mandatory_negatives": 3, "normal_study_path": "full"},
  {"id": "T4", "cuts": "depth",
   "findings": 3, "variants_per_finding": 2, "impression_exemplars": 2,
   "interpretive_clauses": 3, "mandatory_negatives": 3, "normal_study_path": "full"},
  {"id": "T5", "cuts": "depth+scaffold",
   "findings": 2, "variants_per_finding": 1, "impression_exemplars": 1,
   "interpretive_clauses": 2, "mandatory_negatives": 2, "normal_study_path": "primary_only"}
]
```

- [ ] **Step 4: Write the loader**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/__init__.py` (empty file).

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/tiers.py`:

```python
"""Tier definitions for the sheet-budget experiment.

The integer fields do double duty: they render into the prompt directive AND
become the expected counts the compliance checker asserts against the produced
sheet. T1 is the unbudgeted control - every field null, directive empty.
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
TIERS_PATH = BACKEND_ROOT / "test_cases" / "qwen_sheet_budget.json"

BUDGETED_INTS = (
    "findings",
    "variants_per_finding",
    "impression_exemplars",
    "interpretive_clauses",
    "mandatory_negatives",
)


def load_tiers(path: Path | None = None) -> list[dict]:
    return json.loads((path or TIERS_PATH).read_text())


def validate_tiers(tiers: list[dict]) -> None:
    """Every budgeted integer must be non-increasing down the ladder.

    A tier that budgets *more* than the tier above it breaks the monotonic
    reading of the curve, so it is a config error rather than a warning.
    """
    for field in BUDGETED_INTS:
        seen = [(t["id"], t[field]) for t in tiers if t.get(field) is not None]
        for (prev_id, prev), (cur_id, cur) in zip(seen, seen[1:]):
            if cur > prev:
                raise ValueError(
                    f"{field} increases from {prev_id}={prev} to {cur_id}={cur}; "
                    "budgets must be non-increasing down the ladder"
                )


def render_directive(tier: dict) -> str:
    """Turn a tier's integers into prompt text. Empty string for the control."""
    if all(tier.get(f) is None for f in BUDGETED_INTS):
        return ""
    lines = []
    if tier.get("findings") is not None and tier.get("variants_per_finding") is not None:
        lines.append(
            f"- **Style Exemplars:** cover exactly {tier['findings']} findings, "
            f"with exactly {tier['variants_per_finding']} severity-graded "
            f"variant(s) each."
        )
    if tier.get("impression_exemplars") is not None:
        lines.append(
            f"- **Impression Exemplars:** emit exactly "
            f"{tier['impression_exemplars']} exemplar(s)."
        )
    if tier.get("interpretive_clauses") is not None:
        lines.append(
            f"- **Interpretive Clause Rules:** emit exactly "
            f"{tier['interpretive_clauses']} clause(s)."
        )
    if tier.get("mandatory_negatives") is not None:
        lines.append(
            f"- **Mandatory negatives:** emit exactly "
            f"{tier['mandatory_negatives']} negative(s)."
        )
    if tier.get("normal_study_path") == "primary_only":
        lines.append(
            "- **Normal-study path:** cover the primary system only. Omit the "
            "per-system sweep and the Canonical default-normal lines list."
        )
    return "\n".join(lines)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k tier`
Expected: PASS, 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/test_cases/qwen_sheet_budget.json backend/src/rapid_reports_ai/scripts/sheet_budget/ backend/tests/test_sheet_budget_suite.py
git commit -m "feat(sheet-budget): tier config, loader, directive renderer"
```

---

### Task 3: Compliance counter

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/compliance.py`
- Test: `backend/tests/test_sheet_budget_suite.py`

Parses the sheet template defined at `quick_report_analyser.py:589-600` (Style Exemplars), `:586` (Mandatory negatives), and the Interpretive Clause Rules / Impression Exemplars blocks.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sheet_budget_suite.py`:

```python
from rapid_reports_ai.scripts.sheet_budget import compliance as C

FIXTURE_SHEET = """# Skill Sheet: CT thorax

## Companion Matrix
- **In-scope companions:** Nodule — long-axis in mm
- **Mandatory negatives:** "No pleural effusion.", "No bone destruction.", "No contralateral adenopathy."
- **Out-of-scope suppressed:** cardiac source (requires echocardiography)

## Style Exemplars

For each likely finding, variants:

- **Pulmonary nodule**
  - Normal: "No pulmonary nodule identified."
  - Abnormal (uncomplicated): "A 22 mm nodule is present."
- **Hilar lymphadenopathy**
  - Normal: "No hilar lymphadenopathy."
  - Abnormal (uncomplicated): "Right hilar node measures 14 mm."

## Interpretive Clause Rules

- IF [spiculated margin AND pleural tethering] THEN append "suspicious for primary malignancy"
- IF [short-axis node >10 mm] THEN append "nodal involvement"

## Impression Exemplars

- **Normal exemplar:** "No focal abnormality."
- **Abnormal exemplar:** "Right upper lobe nodule. Urgent referral."
"""


def test_counts_findings_and_variants():
    counts = C.count_sheet(FIXTURE_SHEET)
    assert counts["findings"] == 2
    assert counts["variants_per_finding"] == 2


def test_counts_negatives_clauses_and_impression_exemplars():
    counts = C.count_sheet(FIXTURE_SHEET)
    assert counts["mandatory_negatives"] == 3
    assert counts["interpretive_clauses"] == 2
    assert counts["impression_exemplars"] == 2


def test_compliance_reports_each_field_separately():
    tier = {"id": "T3", "findings": 3, "variants_per_finding": 3,
            "impression_exemplars": 2, "interpretive_clauses": 3,
            "mandatory_negatives": 3, "normal_study_path": "full"}
    result = C.check(FIXTURE_SHEET, tier)
    # partial compliance must be visible per-field, not collapsed to pass/fail
    assert result["findings"] == {"want": 3, "got": 2, "ok": False}
    assert result["mandatory_negatives"] == {"want": 3, "got": 3, "ok": True}


def test_control_tier_is_always_compliant():
    tier = {"id": "T1", "findings": None, "variants_per_finding": None,
            "impression_exemplars": None, "interpretive_clauses": None,
            "mandatory_negatives": None, "normal_study_path": None}
    result = C.check(FIXTURE_SHEET, tier)
    assert all(v["ok"] for v in result.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "count or compliance or control_tier"`
Expected: FAIL with `ModuleNotFoundError: No module named '...compliance'`

- [ ] **Step 3: Write the counter**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/compliance.py`:

```python
"""Count structural elements in a produced skill sheet.

This is what makes structural budgets better than word budgets: compliance is
measurable. Counts are reported per-field so partial compliance (findings
honoured, variants ignored) stays visible instead of collapsing to pass/fail.
"""
from __future__ import annotations

import re

from .tiers import BUDGETED_INTS

_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_FINDING_BULLET = re.compile(r"^-\s+\*\*(?!Mandatory|In-scope|Out-of-scope)[^*]+\*\*\s*$", re.M)
_VARIANT_BULLET = re.compile(r"^\s{2,}-\s+(Normal|Abnormal)[^:]*:", re.M)
_CLAUSE = re.compile(r"^-\s+IF\b", re.M)
_IMPRESSION_EX = re.compile(r"^-\s+\*\*\w+ exemplar:\*\*", re.M)
_NEGATIVES_LINE = re.compile(r"^-\s+\*\*Mandatory negatives:\*\*\s*(.+)$", re.M)


def _section_body(sheet: str, title: str) -> str:
    """Return the text between `## <title>` and the next `## ` heading."""
    matches = list(_SECTION.finditer(sheet))
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == title.lower():
            end = matches[i + 1].start() if i + 1 < len(matches) else len(sheet)
            return sheet[m.end():end]
    return ""


def count_sheet(sheet: str) -> dict[str, int]:
    """Count each budgeted element. variants_per_finding is the max observed.

    Max rather than mean because the budget is an upper bound: the prompt
    allows omitting the complicated variant where no meaningful complicated
    form exists, so a mean would penalise legitimate clinical judgement.
    """
    exemplars = _section_body(sheet, "Style Exemplars")
    findings = _FINDING_BULLET.findall(exemplars)

    per_finding: list[int] = []
    blocks = _FINDING_BULLET.split(exemplars)
    for block in blocks[1:] if len(blocks) > 1 else []:
        per_finding.append(len(_VARIANT_BULLET.findall(block)))
    if not per_finding:
        chunks = re.split(r"^-\s+\*\*[^*]+\*\*\s*$", exemplars, flags=re.M)[1:]
        per_finding = [len(_VARIANT_BULLET.findall(c)) for c in chunks]

    neg_match = _NEGATIVES_LINE.search(sheet)
    negatives = len(re.findall(r'"[^"]+"', neg_match.group(1))) if neg_match else 0

    return {
        "findings": len(findings),
        "variants_per_finding": max(per_finding) if per_finding else 0,
        "mandatory_negatives": negatives,
        "interpretive_clauses": len(_CLAUSE.findall(_section_body(sheet, "Interpretive Clause Rules"))),
        "impression_exemplars": len(_IMPRESSION_EX.findall(_section_body(sheet, "Impression Exemplars"))),
    }


def check(sheet: str, tier: dict) -> dict[str, dict]:
    """Compare counts against a tier's budget, one verdict per field."""
    got = count_sheet(sheet)
    out: dict[str, dict] = {}
    for field in BUDGETED_INTS:
        want = tier.get(field)
        if want is None:  # unbudgeted (control tier, or field not budgeted)
            out[field] = {"want": None, "got": got[field], "ok": True}
        else:
            out[field] = {"want": want, "got": got[field], "ok": got[field] == want}
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "count or compliance or control_tier"`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/compliance.py backend/tests/test_sheet_budget_suite.py
git commit -m "feat(sheet-budget): structural compliance counter"
```

---

### Task 4: Structural gate

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/gate.py`
- Test: `backend/tests/test_sheet_budget_suite.py`

Ports the contradiction detector built during the 2026-08-12 bake-off, which caught the real failure in `ct_thorax_smoker_lung_nodule` (GLM sheet → Qwen generator asserted 14 mm hilar lymphadenopathy *and* "No mediastinal or hilar lymphadenopathy").

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sheet_budget_suite.py`:

```python
from rapid_reports_ai.scripts.sheet_budget import gate as G

CONTRADICTORY = """COMPARISON:
None.

TECHNIQUE:
CT thorax with contrast.

FINDINGS:
A 22 mm spiculated nodule is present in the right upper lobe. Right hilar
lymphadenopathy is present, with the largest node measuring 14 mm in short axis.
No mediastinal or hilar lymphadenopathy. No suspicious pulmonary nodule identified.

IMPRESSION:
Right upper lobe nodule. Urgent referral recommended.
"""

CLEAN = """COMPARISON:
None.

TECHNIQUE:
CT thorax with contrast.

FINDINGS:
A 22 mm spiculated nodule is present in the right upper lobe. Right hilar
lymphadenopathy is present, with the largest node measuring 14 mm in short axis.
No pleural effusion. No bone destruction.

IMPRESSION:
Right upper lobe nodule. Urgent referral recommended.
"""


def test_gate_flags_a_self_contradicting_report():
    result = G.run_gate(CONTRADICTORY)
    assert result["passed"] is False
    assert "self_contradiction" in result["failures"]


def test_gate_passes_a_clean_report():
    result = G.run_gate(CLEAN)
    assert result["passed"] is True
    assert result["failures"] == []


def test_gate_flags_a_missing_section():
    result = G.run_gate(CLEAN.replace("IMPRESSION:", "SUMMARY:"))
    assert "missing_section" in result["failures"]


def test_gate_flags_thinking_leak():
    result = G.run_gate(CLEAN + "\n[Done] Output Generation.")
    assert "thinking_leak" in result["failures"]


def test_gate_flags_truncation():
    result = G.run_gate(CLEAN.rstrip(".\n") + " and the patient")
    assert "truncation" in result["failures"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k gate`
Expected: FAIL with `ModuleNotFoundError: No module named '...gate'`

- [ ] **Step 3: Write the gate**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/gate.py`:

```python
"""Free structural/integrity checks. Every run passes through these; only
survivors reach the (paid) v2.2 judge.

The contradiction pairs were derived from the 2026-08-12 bake-off, where a
Qwen generation asserted hilar lymphadenopathy at 14 mm and then denied it in
the same FINDINGS section.
"""
from __future__ import annotations

import re

REQUIRED_SECTIONS = ("TECHNIQUE", "FINDINGS", "IMPRESSION")

LEAK_MARKERS = (
    "[Done]", "Self-Correction", "Proceeds.", "Output Generation",
    "<think>", "</think>", "Matches all constraints", "I should ensure",
    "Final check",
)

# (positive assertion, blanket negation of the same entity)
CONTRADICTION_PAIRS = (
    (r"lymphadenopathy is present|lymphadenopathy[^.]*measur|enlarged .{0,20}node",
     r"[Nn]o (?:mediastinal or hilar |hilar |mediastinal |significant )?lymphadenopathy"),
    (r"\d+\s?mm[^.]*nodule|nodule[^.]*\d+\s?mm|spiculated nodule",
     r"[Nn]o (?:suspicious )?(?:pulmonary )?nodule(?![^.]*adrenal)"),
    (r"h(?:a)?emorrhage (?:is )?(?:present|identified|noted)",
     r"[Nn]o (?:acute |intracranial )?h(?:a)?emorrhage"),
    (r"effusion is (?:present|noted|identified)|moderate .{0,15}effusion",
     r"[Nn]o (?:pleural )?effusion"),
    (r"consolidation is (?:present|noted|identified)",
     r"[Nn]o (?:focal )?consolidation"),
    (r"free (?:intraperitoneal )?(?:fluid|gas) is (?:present|noted|identified)",
     r"[Nn]o free (?:intraperitoneal )?(?:fluid|gas)"),
)


def run_gate(report: str) -> dict:
    """Return {passed, failures, detail}. Failures are check names."""
    failures: list[str] = []
    detail: dict[str, list[str]] = {}

    missing = [s for s in REQUIRED_SECTIONS if s not in report]
    if missing:
        failures.append("missing_section")
        detail["missing_section"] = missing

    leaks = [m for m in LEAK_MARKERS if m in report]
    if leaks:
        failures.append("thinking_leak")
        detail["thinking_leak"] = leaks

    hits: list[str] = []
    for pos, neg in CONTRADICTION_PAIRS:
        if re.search(pos, report) and (m := re.search(neg, report)):
            hits.append(m.group(0))
    if hits:
        failures.append("self_contradiction")
        detail["self_contradiction"] = hits

    stripped = report.strip()
    if stripped and stripped[-1] not in '.)]”"':
        failures.append("truncation")
        detail["truncation"] = [stripped[-60:]]

    return {"passed": not failures, "failures": failures, "detail": detail}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k gate`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/gate.py backend/tests/test_sheet_budget_suite.py
git commit -m "feat(sheet-budget): structural gate with bake-off contradiction pairs"
```

---

### Task 5: Ad-hoc v2.2 judge adapter

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/judge.py`
- Test: `backend/tests/test_sheet_budget_suite.py`

`quality_scoring.score_report()` (`quality_scoring.py:441`) needs a DB row, but `_assemble_case()` (`:313`) returns a plain dict. This adapter builds that dict directly so harness output can be judged with no database.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sheet_budget_suite.py`:

```python
from rapid_reports_ai import quality_scoring as qs
from rapid_reports_ai.scripts.sheet_budget import judge as J


def test_case_dict_matches_assemble_case_keys_exactly():
    """Guard against drift in _assemble_case's contract."""
    built = J.build_case(inputs="Scan type: CT head", skill_sheet="# Sheet", report="FINDINGS: ...")
    assert set(built) == {"pipeline", "inputs", "skill_sheet", "ai_output", "final_output"}
    assert built["pipeline"] == "quick"
    assert built["final_output"] is None


def test_case_text_renders_for_every_v22_dimension():
    built = J.build_case(inputs="Scan type: CT head", skill_sheet="# Sheet", report="FINDINGS: x")
    for dim in qs.DIMENSIONS_V22:
        text = qs._case_text_v2(dim, built)
        assert isinstance(text, str) and text.strip()


def test_score_case_uses_an_injected_judge_and_returns_all_dimensions():
    calls = []

    def fake_judge(prompt, case_text):
        calls.append(case_text)
        return qs.JudgeScore(score=4, rationale="fixture")

    scores = J.score_case(
        inputs="Scan type: CT head", skill_sheet="# Sheet",
        report="FINDINGS: x", judge=fake_judge,
    )
    assert set(scores) == set(qs.DIMENSIONS_V22)
    assert all(v["score"] == 4 for v in scores.values())
    assert len(calls) == len(qs.DIMENSIONS_V22)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "case_dict or case_text or score_case"`
Expected: FAIL with `ModuleNotFoundError: No module named '...judge'`

- [ ] **Step 3: Write the adapter**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/judge.py`:

```python
"""Score harness output on rubric v2.2 without a database row.

quality_scoring.score_report() requires an ORM Report; _assemble_case() does
not - it returns a plain dict. Building that dict directly lets the experiment
reuse the production rubric and judge model unchanged.
"""
from __future__ import annotations

from typing import Callable

from ... import quality_scoring as qs


def build_case(*, inputs: str, skill_sheet: str, report: str) -> dict:
    """Mirror _assemble_case()'s contract for the quick pipeline.

    final_output is None: the harness has no radiologist-edited final, so the
    judge assesses ai_output, which is what _case_text_v2 falls back to.
    """
    return {
        "pipeline": "quick",
        "inputs": inputs or "",
        "skill_sheet": skill_sheet or "",
        "ai_output": report or "",
        "final_output": None,
    }


def score_case(
    *,
    inputs: str,
    skill_sheet: str,
    report: str,
    judge: Callable[[str, str], "qs.JudgeScore"] | None = None,
) -> dict[str, dict]:
    """Score one report across all v2.2 dimensions.

    ``judge`` defaults to the production Sonnet judge. It is sync and calls
    asyncio.run() internally, so callers inside an event loop must dispatch
    this through asyncio.to_thread.
    """
    judge = judge or qs._default_judge
    case = build_case(inputs=inputs, skill_sheet=skill_sheet, report=report)
    out: dict[str, dict] = {}
    for dim in qs.DIMENSIONS_V22:
        prompt = qs._PROMPTS_V22[dim]
        result = judge(prompt, qs._case_text_v2(dim, case))
        out[dim] = {
            "score": result.score,
            "rationale": result.rationale,
            "issues": [i.model_dump() for i in result.issues],
        }
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "case_dict or case_text or score_case"`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/judge.py backend/tests/test_sheet_budget_suite.py
git commit -m "feat(sheet-budget): ad-hoc v2.2 judge adapter, no DB required"
```

---

### Task 6: Runner

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/runner.py`

The only module that performs network calls. Serialised throughout — the bake-off lost 4 of 20 cells to Groq 429s (OTPM 32,000) when four Qwen calls ran concurrently, and serialised re-runs passed cleanly.

- [ ] **Step 1: Write the runner**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/runner.py`:

```python
"""Sheet-budget experiment runner.

Usage:
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner --tier T1 --tier T2
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner --no-judge

Everything is serialised. Groq's OTPM ceiling (32,000 observed) kills
concurrent Qwen calls; the 2026-08-12 bake-off lost 4 of 20 cells that way.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parents[3]
CASES_PATH = BACKEND_ROOT / "test_cases" / "analyser_suite.json"
OUTPUT_ROOT = BACKEND_ROOT / "test_output"

ANALYSER_MODEL = "qwen/qwen3.6-27b"
GENERATOR_MODEL = "qwen/qwen3.6-27b"
SEED = 20260812


def _load_dotenv() -> None:
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if not os.environ.get(k.strip()):
            os.environ[k.strip()] = v.strip().strip("'\"")


_load_dotenv()

from rapid_reports_ai.quick_report_analyser import (  # noqa: E402
    generate_ephemeral_skill_sheet,
    new_run_id,
)
from rapid_reports_ai.quick_report_api import _run_one_generator  # noqa: E402
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402

from . import compliance, gate, judge, report as report_mod, tiers  # noqa: E402


async def _with_backoff(coro_factory, *, what: str, attempts: int = 3):
    """Retry on Groq 429s. Serialisation is the primary defence; this is the net."""
    last = None
    for i in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if "429" not in str(exc) or i == attempts - 1:
                raise
            wait = 20.0 * (i + 1)
            print(f"    429 on {what}; backing off {wait:.0f}s")
            await asyncio.sleep(wait)
    raise last


async def run_one(case: dict, tier: dict, tm: TemplateManager) -> dict[str, Any]:
    directive = tiers.render_directive(tier)
    label = f"{tier['id']}/{case['name']}"
    print(f"  [{label}] analysing...")

    t0 = time.time()
    sheet_result = await _with_backoff(
        lambda: generate_ephemeral_skill_sheet(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            api_key="",  # groq path resolves GROQ_API_KEY itself
            model_override=ANALYSER_MODEL,
            budget_directive=directive,
        ),
        what=f"{label} analyser",
    )
    sheet = sheet_result["skill_sheet"]
    print(f"  [{label}] sheet {len(sheet):,} chars in {sheet_result['latency_ms']/1000:.1f}s")

    template_config = {
        "generation_mode": "skill_sheet_guided",
        "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + sheet,
        "scan_type": case["scan_type"],
    }
    user_inputs = {"FINDINGS": case["findings"], "CLINICAL_HISTORY": case["clinical_history"]}

    candidate = await _with_backoff(
        lambda: _run_one_generator(
            tm=tm,
            template_config=template_config,
            user_inputs=user_inputs,
            model_name=GENERATOR_MODEL,
            run_id=f"budget-{tier['id']}-{case['name']}-{new_run_id()}",
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            skill_sheet_markdown=sheet,
        ),
        what=f"{label} generator",
    )

    return {
        "tier": tier["id"],
        "cuts": tier.get("cuts"),
        "case": case["name"],
        "sheet_chars": len(sheet),
        "sheet_tokens_est": len(sheet) // 4,
        "analyser_latency_ms": sheet_result["latency_ms"],
        "generator_latency_ms": candidate.get("latency_ms"),
        "report": candidate.get("content") or "",
        "report_chars": len(candidate.get("content") or ""),
        "generator_error": candidate.get("error"),
        "compliance": compliance.check(sheet, tier),
        "gate": gate.run_gate(candidate.get("content") or ""),
        "skill_sheet": sheet,
        "total_wall_s": round(time.time() - t0, 1),
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qwen sheet-budget experiment")
    p.add_argument("--tier", action="append", default=None,
                   help="Filter to tier id(s). Repeatable. Default: all.")
    p.add_argument("--case", action="append", default=None,
                   help="Filter to case name(s). Repeatable. Default: all.")
    p.add_argument("--no-judge", action="store_true",
                   help="Skip the paid v2.2 judge; gate only.")
    p.add_argument("--output-dir", default=None)
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    all_tiers = tiers.load_tiers()
    tiers.validate_tiers(all_tiers)
    if args.tier:
        all_tiers = [t for t in all_tiers if t["id"] in set(args.tier)]
    cases = json.loads(CASES_PATH.read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.output_dir) if args.output_dir else OUTPUT_ROOT / f"budget_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"tiers: {[t['id'] for t in all_tiers]}\ncases: {[c['name'] for c in cases]}\nout:   {out_dir}")

    tm = TemplateManager()
    runs: list[dict] = []
    for tier in all_tiers:
        for case in cases:
            try:
                runs.append(await run_one(case, tier, tm))
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {tier['id']}/{case['name']} failed: {exc}")
                runs.append({"tier": tier["id"], "case": case["name"], "error": str(exc)})
        _report_compliance(tier, runs)

    if not args.no_judge:
        for run in runs:
            if run.get("error") or not run.get("gate", {}).get("passed"):
                continue
            case = next(c for c in cases if c["name"] == run["case"])
            inputs = f"Scan type: {case['scan_type']}\nClinical history: {case['clinical_history']}"
            run["judge"] = await asyncio.to_thread(
                judge.score_case,
                inputs=inputs,
                skill_sheet=run["skill_sheet"],
                report=run["report"],
            )
            print(f"  judged {run['tier']}/{run['case']}")

    (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))
    report_mod.write_curve_csv(runs, out_dir / "curve.csv")
    report_mod.write_artifact_html(runs, out_dir / "curve.html")
    print(f"\n✅ {len(runs)} runs → {out_dir}")
    return 0


def _report_compliance(tier: dict, runs: list[dict]) -> None:
    """Abort signal: per spec §8, check compliance after T2, not after all 25."""
    rows = [r for r in runs if r.get("tier") == tier["id"] and "compliance" in r]
    if not rows:
        return
    bad = {
        f: [(r["case"], r["compliance"][f]["got"], r["compliance"][f]["want"])
            for r in rows if not r["compliance"][f]["ok"]]
        for f in tiers.BUDGETED_INTS
    }
    bad = {f: v for f, v in bad.items() if v}
    if bad and tier["id"] != "T1":
        print(f"  ⚠ {tier['id']} COMPLIANCE MISS — the model is not honouring the budget:")
        for f, misses in bad.items():
            print(f"      {f}: {misses}")
        print("      If this persists, stop and switch to hard section ablation (spec §8).")
    else:
        print(f"  ✓ {tier['id']} compliant")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Verify it imports and the CLI parses**

Run: `cd backend && poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner --help`
Expected: argparse help text listing `--tier`, `--case`, `--no-judge`, `--output-dir`

- [ ] **Step 3: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/runner.py
git commit -m "feat(sheet-budget): serialised runner with 429 backoff and compliance abort signal"
```

---

### Task 7: Curve output — CSV and artifact

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/report.py`
- Test: `backend/tests/test_sheet_budget_suite.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_sheet_budget_suite.py`:

```python
from rapid_reports_ai.scripts.sheet_budget import report as R

RUNS_FIXTURE = [
    {"tier": "T1", "case": "a", "sheet_tokens_est": 3400, "sheet_chars": 13600,
     "analyser_latency_ms": 24800, "generator_latency_ms": 12700, "report_chars": 1800,
     "gate": {"passed": True, "failures": []},
     "judge": {"output_adherence": {"score": 5}, "dictation_fidelity": {"score": 4},
               "normal_fill_appropriateness": {"score": 5}, "unwarranted_assertion": {"score": 4}}},
    {"tier": "T5", "case": "a", "sheet_tokens_est": 700, "sheet_chars": 2800,
     "analyser_latency_ms": 9000, "generator_latency_ms": 6000, "report_chars": 1200,
     "gate": {"passed": False, "failures": ["self_contradiction"]}},
]


def test_curve_csv_has_a_row_per_run_and_mean_score(tmp_path):
    path = tmp_path / "curve.csv"
    R.write_curve_csv(RUNS_FIXTURE, path)
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3  # header + 2 runs
    assert "mean_score" in lines[0]
    assert "4.5" in lines[1]  # (5+4+5+4)/4
    assert "gate_failures" in lines[0]


def test_artifact_html_is_self_contained_and_themed(tmp_path):
    path = tmp_path / "curve.html"
    R.write_artifact_html(RUNS_FIXTURE, path)
    html = path.read_text()
    assert "<title>" in html
    assert "prefers-color-scheme" in html
    assert "http://" not in html and "https://" not in html  # no external assets
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "curve or artifact"`
Expected: FAIL with `ModuleNotFoundError: No module named '...report'`

- [ ] **Step 3: Write the emitter**

Create `backend/src/rapid_reports_ai/scripts/sheet_budget/report.py`:

```python
"""Emit the quality-vs-tokens curve as CSV and as a self-contained HTML page.

Latency projections cover the self-hosted target band (100/115/130 tok/s
decode). Total output tokens are estimated from report chars plus measured
generator latency at the Groq rate; where usage data is absent the projection
uses the visible-token estimate only and is marked as a floor.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

DIMS = ("output_adherence", "dictation_fidelity",
        "normal_fill_appropriateness", "unwarranted_assertion")
THROUGHPUTS = (100, 115, 130)


def _mean_score(run: dict) -> float | None:
    j = run.get("judge")
    if not j:
        return None
    scores = [j[d]["score"] for d in DIMS if d in j]
    return round(sum(scores) / len(scores), 2) if scores else None


def write_curve_csv(runs: list[dict], path: Path) -> None:
    fields = ["tier", "case", "sheet_chars", "sheet_tokens_est", "report_chars",
              "analyser_latency_ms", "generator_latency_ms", "gate_passed",
              "gate_failures", "mean_score", *DIMS]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in runs:
            row = {k: r.get(k) for k in fields}
            g = r.get("gate") or {}
            row["gate_passed"] = g.get("passed")
            row["gate_failures"] = "|".join(g.get("failures", []))
            row["mean_score"] = _mean_score(r)
            for d in DIMS:
                row[d] = (r.get("judge") or {}).get(d, {}).get("score")
            w.writerow(row)


def write_artifact_html(runs: list[dict], path: Path) -> None:
    points = [
        {"tier": r["tier"], "case": r.get("case"), "x": r.get("sheet_tokens_est"),
         "y": _mean_score(r), "gate": (r.get("gate") or {}).get("passed"),
         "gen_ms": r.get("generator_latency_ms")}
        for r in runs if r.get("sheet_tokens_est") is not None
    ]
    path.write_text(_HTML.replace("{{DATA}}", json.dumps(points))
                         .replace("{{THROUGHPUTS}}", json.dumps(list(THROUGHPUTS))))


_HTML = """<title>Qwen sheet-budget — quality vs tokens</title>
<style>
  :root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --grid:#e5e5e5; --pass:#2563eb; --fail:#dc2626; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
    --bg:#111; --fg:#eee; --muted:#999; --grid:#333; --pass:#60a5fa; --fail:#f87171; } }
  :root[data-theme="dark"] { --bg:#111; --fg:#eee; --muted:#999; --grid:#333; --pass:#60a5fa; --fail:#f87171; }
  body { background:var(--bg); color:var(--fg); font:15px/1.55 ui-sans-serif,system-ui,sans-serif;
         margin:0; padding:2rem; }
  .wrap { max-width:900px; margin:0 auto; }
  table { border-collapse:collapse; width:100%; font-size:14px; }
  th,td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--grid); }
  .scroll { overflow-x:auto; }
  .fail { color:var(--fail); font-weight:600; }
  .pass { color:var(--pass); }
  p.note { color:var(--muted); }
</style>
<div class="wrap">
<h1>Qwen 3.6 27B — sheet budget vs report quality</h1>
<p class="note">Mean v2.2 judge score against achieved skill-sheet size. Gate failures are
plotted in red and excluded from the quality reading.</p>
<svg id="chart" viewBox="0 0 720 380" width="100%" role="img" aria-label="Quality versus sheet tokens"></svg>
<div class="scroll"><table id="tbl"><thead><tr>
<th>Tier</th><th>Case</th><th>Sheet tok</th><th>Mean score</th><th>Gen latency</th><th>Gate</th>
</tr></thead><tbody></tbody></table></div>
<h2>Projected self-hosted generate latency</h2>
<p class="note">Generator wall time rescaled from the measured Groq rate to the self-hosted
decode band. Treat as a floor: it assumes reasoning volume is unchanged at the same budget.</p>
<div class="scroll"><table id="proj"><thead><tr><th>Tier</th><th>@100 t/s</th><th>@115 t/s</th><th>@130 t/s</th></tr></thead><tbody></tbody></table></div>
</div>
<script>
const DATA = {{DATA}}, TP = {{THROUGHPUTS}}, GROQ = 450;
const tb = document.querySelector('#tbl tbody');
DATA.forEach(d => {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${d.tier}</td><td>${d.case}</td><td>${d.x?.toLocaleString() ?? '—'}</td>
    <td>${d.y ?? '—'}</td><td>${d.gen_ms ? (d.gen_ms/1000).toFixed(1)+'s' : '—'}</td>
    <td class="${d.gate ? 'pass' : 'fail'}">${d.gate ? 'pass' : 'FAIL'}</td>`;
  tb.appendChild(tr);
});
const byTier = {};
DATA.forEach(d => { if (d.gen_ms) (byTier[d.tier] ||= []).push(d.gen_ms); });
const pb = document.querySelector('#proj tbody');
Object.entries(byTier).forEach(([tier, arr]) => {
  const med = arr.sort((a,b)=>a-b)[Math.floor(arr.length/2)] / 1000;
  const tr = document.createElement('tr');
  tr.innerHTML = `<td>${tier}</td>` + TP.map(t =>
    `<td>${(med * GROQ / t).toFixed(1)}s</td>`).join('');
  pb.appendChild(tr);
});
const pts = DATA.filter(d => d.y != null && d.x != null);
const svg = document.getElementById('chart');
if (pts.length) {
  const P = {l:56,r:20,t:20,b:44}, W=720, H=380;
  const xs = pts.map(p=>p.x), xmin=0, xmax=Math.max(...xs)*1.05;
  const X = v => P.l + (v-xmin)/(xmax-xmin) * (W-P.l-P.r);
  const Y = v => H-P.b - (v-1)/4 * (H-P.t-P.b);
  let s = `<line x1="${P.l}" y1="${H-P.b}" x2="${W-P.r}" y2="${H-P.b}" stroke="var(--grid)"/>`;
  s += `<line x1="${P.l}" y1="${P.t}" x2="${P.l}" y2="${H-P.b}" stroke="var(--grid)"/>`;
  for (let v=1; v<=5; v++) s += `<text x="${P.l-10}" y="${Y(v)+4}" text-anchor="end"
    fill="var(--muted)" font-size="12">${v}</text>`;
  pts.forEach(p => { s += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="5"
    fill="${p.gate ? 'var(--pass)' : 'var(--fail)'}"><title>${p.tier} ${p.case}</title></circle>`; });
  s += `<text x="${(W)/2}" y="${H-8}" text-anchor="middle" fill="var(--muted)"
    font-size="12">achieved skill-sheet tokens</text>`;
  svg.innerHTML = s;
}
</script>
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v -k "curve or artifact"`
Expected: PASS, 2 passed

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && poetry run pytest tests/test_sheet_budget_suite.py -v`
Expected: PASS, 23 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report.py backend/tests/test_sheet_budget_suite.py
git commit -m "feat(sheet-budget): curve CSV and self-contained themed artifact"
```

---

### Task 8: T1+T2 smoke run and the compliance decision

Per spec §8 the mechanism must be validated before spending the full sweep. This task is the abort gate: **if T2 does not honour the budget, stop and re-plan rather than running T3–T5.**

- [ ] **Step 1: Run T1 and T2 only, gate-only (no judge spend)**

Run:
```bash
cd backend && poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner \
  --tier T1 --tier T2 --no-judge \
  --output-dir test_output/SMOKE_budget
```
Expected: 10 runs (2 tiers × 5 cases), each printing sheet size, then a `✓ T2 compliant` or `⚠ T2 COMPLIANCE MISS` line.

- [ ] **Step 2: Decide**

- `✓ T2 compliant` → the mechanism works. Proceed to Step 3.
- `⚠ T2 COMPLIANCE MISS` on `findings` or `variants_per_finding` → **stop**. The model is not honouring structural counts. Report the observed counts and switch to hard section ablation (physically removing sections from the prompt) before running anything further. Do not run T3–T5.

- [ ] **Step 3: Full sweep with judge**

Run:
```bash
cd backend && poetry run python -m rapid_reports_ai.scripts.sheet_budget.runner
```
Expected: 25 runs, judge calls on gate survivors, then `✅ 25 runs → backend/test_output/budget_<stamp>`

- [ ] **Step 4: Publish the artifact**

Publish `backend/test_output/budget_<stamp>/curve.html` via the Artifact tool so the curve is shareable, then report the knee position and which dimension degraded first.

- [ ] **Step 5: Commit the results**

```bash
git add backend/test_output/budget_*/curve.csv backend/test_output/budget_*/runs.json
git commit -m "test(sheet-budget): full sweep results, 5 tiers x 5 cases"
```

---

## Self-Review

**Spec coverage.** §4 tier ladder → Task 2. §4 shrink mechanism → Task 1 + Task 2. §4 measured-per-run → Task 6 `run_one`. §4 two-stage scoring → Tasks 4, 5, 6. §5 all four components → Tasks 2, 3, 6, 7. §6 error handling: 429 backoff → Task 6 `_with_backoff`; per-run exception isolation → Task 6 `main`; judge retry → inherited from `_default_judge`; truncation → Task 4. §7 all five tests → Tasks 1–7. §8 abort-after-T2 → Task 8 Step 2; partial compliance visible per-field → Task 3 `check`.

**Two spec items deliberately not implemented as written.** The separate `ANALYSER_SYSTEM_PROMPT_QWEN` constant (rationale at the top of this plan — the override-block approach makes T1 a byte-identical control, which is strictly better). And §4's "fixed seed": `GroqModelSettings` exposes `seed`, but neither `generate_ephemeral_skill_sheet` nor `generate_report_from_config` currently threads model settings from the caller, so wiring it would mean changing two production signatures for a determinism benefit that Groq does not guarantee anyway. `SEED` is defined in `runner.py` and left unused rather than silently dropped; if run-to-run variance proves to swamp tier differences, threading it becomes its own task.

**Placeholder scan.** No TBD/TODO. Every code step contains complete code. Every command has expected output.

**Type consistency.** `compliance.check()` returns `{field: {want, got, ok}}` — consumed with those exact keys in `runner._report_compliance` and asserted in Task 3's tests. `gate.run_gate()` returns `{passed, failures, detail}` — consumed as `.get("passed")` / `.get("failures", [])` in `report.py` and `runner.py`. `judge.score_case()` returns `{dim: {score, reason}}` — consumed as `[d]["score"]` in `report._mean_score`. `tiers.BUDGETED_INTS` is imported by both `compliance.py` and `runner.py`.
