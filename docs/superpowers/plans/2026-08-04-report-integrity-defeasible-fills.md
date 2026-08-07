# Report Integrity: Defeasible Normal-Fill, Volume Containment, Dictation Truncation Detection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the quick-report pipeline from emitting confident assertions the evidence does not support — specifically out-of-volume normals, normals that contradict a dictated positive, and reports generated from truncated dictation.

**Architecture:** No architectural change. The skill sheet stays authored blind to the dictation inside the free dictation window — that design is correct and preserves the latency model (critical path today is `dictation time + ~10s`; anchoring the sheet to findings would make it `dictation time + ~43s`). The fix moves *authority*, not information: the generator already sees the sheet and the dictation together, so it is granted a licence to override individual canonical default-normal lines when evidence contradicts them. This generalises the pattern already proven by Principle 11 (gender-specific structures), which lets the generator override a sheet-prescribed line when a required signal is absent. Coverage stays mandatory; individual assertions become defeasible. Separately, a pure deterministic detector flags truncated dictation before generation.

**Tech Stack:** Python 3.11+, FastAPI, pytest (`asyncio_mode=auto`, `pythonpath=["src"]`), Poetry. Prompt text lives as module-level string constants — no template engine.

---

## Background: what we are fixing

Two defects, both traced to the skill sheet in live smoke test `24e7f42f-2f3f-42c0-a1bb-dcf94e1137ff` (CT head non-contrast, Haiku analyser):

1. **Out-of-volume assertion.** The sheet declared `Imaged volume: Vertex to skull base` and then emitted `Secondary visible regions: … cervical spine → "The cervical spine alignment is normal with no acute fracture or subluxation"`. The cervical spine is not inside vertex-to-skull-base. The generator copied the line verbatim. The spec at `quick_report_analyser.py:245` gates this field on *phrasing distinctiveness*, never on anatomical containment.

2. **Contradicted normal-fill.** Dictation stated an 8 mm right convexity subdural with 3 mm midline shift. The report still said "The subarachnoid spaces and basal cisterns are clear." The sheet's own Companion Matrix listed *"effacement of subarachnoid spaces, compression of basal cisterns"* as companions of mass effect — but the Phase 6 silence rule (`quick_report_analyser.py:187`) fires on silence unconditionally and never consults it.

A third, higher-severity defect from the historical corpus: report `56f501c1` (CT lumbar, metastatic cord-compression workup) was generated from a dictation truncated mid-clause — *"…new destructive expansile osseous lesion in the"* — and the generator smoothed it into a complete-looking report with a location-less metastasis. Scored `quality_core` 2.33.

### Critical implementation note: the analyser prompt exists TWICE

`quick_report_analyser.py` holds two full prompt variants, dispatched by provider in `generate_ephemeral_skill_sheet` (line 699-700):

| Constant | Lines | Serves | Production share |
|---|---|---|---|
| `ANALYSER_SYSTEM_PROMPT_SONNET` | ~69–320 | Anthropic (Haiku BEST, Sonnet) | ~5% |
| `ANALYSER_SYSTEM_PROMPT_GLM` | ~321–620 | Cerebras GLM (FAST) | ~95% |

`QUICK_REPORT_ANALYZER_FAST` = `zai-glm-4.7` returns in ~9.5s and usually wins the race, so **the GLM prompt authors almost every production sheet.** Editing only the Sonnet variant would fix essentially nothing in production. Every prompt task below has two edit sites. The two variants' texts differ slightly, so each needs its own `old_string`.

### Side effect to expect (this is desirable)

`analyser_prompt_version(model_name)` (line 647) hashes the system prompt + user template. Editing either prompt changes that hash, and the new value is written to `ephemeral_skill_sheets.analyser_prompt_version`. This gives clean before/after cohorts in Metabase — current production value is `4f003721a4b3` (GLM) / `1a2c6c8d14c7` (Haiku). Record the new hashes in Task 6.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `backend/src/rapid_reports_ai/quick_report_analyser.py` | Both analyser prompts — how the sheet is authored | Modify (4 edit sites) |
| `backend/src/rapid_reports_ai/quick_report_hardening.py` | Generator preamble — how the sheet is consumed | Modify (append Principle 12) |
| `backend/src/rapid_reports_ai/dictation_integrity.py` | Deterministic dictation checks. Detection only, never rewrites. | **Create** |
| `backend/src/rapid_reports_ai/main.py` | Route wiring | Modify (add one endpoint) |
| `backend/tests/test_quick_report_prompts.py` | Prompt-content assertions | **Create** |
| `backend/tests/test_dictation_integrity.py` | Detector unit tests | **Create** |
| `backend/tests/test_dictation_check_route.py` | Endpoint tests via TestClient | **Create** |

`dictation_integrity.py` is a new standalone module rather than a function inside `quick_report_api.py` because it is a pure function with no I/O, needs no auth or DB, and will later be called from three places (the check endpoint, the generate path, and the offline quality harness).

---

### Task 1: Make canonical default-normal lines defeasible (analyser prompts)

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py:187` (Sonnet Phase 6)
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py:476` (GLM Phase 6)
- Test: `backend/tests/test_quick_report_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_quick_report_prompts.py`:

```python
"""Prompt-content tests for the quick-report analyser prompts and the
generator hardening preamble.

These are pure string constants — no fixtures, no DB, no LLM call. We assert
that the doctrine we depend on is actually present in BOTH analyser variants.
The GLM variant serves ~95% of production sheets; a rule present only in the
Sonnet variant is effectively absent from production.

See docs/superpowers/plans/2026-08-04-report-integrity-defeasible-fills.md
"""
from __future__ import annotations

import pytest

from rapid_reports_ai.quick_report_analyser import (
    ANALYSER_SYSTEM_PROMPT_GLM,
    ANALYSER_SYSTEM_PROMPT_SONNET,
)

BOTH_ANALYSER_PROMPTS = [
    pytest.param(ANALYSER_SYSTEM_PROMPT_SONNET, id="sonnet"),
    pytest.param(ANALYSER_SYSTEM_PROMPT_GLM, id="glm"),
]


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_default_normal_lines_are_declared_defeasible(prompt: str):
    """A canonical default-normal is a proposal, not a mandate."""
    assert "defeasible" in prompt.lower()


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_defeasibility_is_scoped_to_companion_contradiction(prompt: str):
    """The override trigger must name the Companion Matrix, not be vague."""
    assert "Companion Matrix" in prompt


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_coverage_obligation_survives_defeasibility(prompt: str):
    """Dropping an assertion must not license dropping the structure.

    Regression guard: the fix must not swing the pendulum into under-coverage.
    """
    assert "Coverage of the structure remains obligatory" in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -v
```

Expected: 6 failures (3 tests × 2 variants), all `AssertionError`.

- [ ] **Step 3: Edit the Sonnet variant (line 187)**

In `backend/src/rapid_reports_ai/quick_report_analyser.py`, find the Phase 6 bullet that begins `- If dictation is silent about an in-scope structure` and ends `...that triggers LIMITATIONS inclusion and the position reflects the limitation.` — this is the **Sonnet** one (note the `and the position reflects the limitation` tail). Replace that whole bullet with:

```
- If dictation is silent about an in-scope structure the sweep order visits, render the structure's canonical default-normal line at its sweep position. Silence is not omission in the report — it is the default rendering. This applies to every in-scope system on broad-coverage scans, not only to secondary visible regions. If dictation specifies a positive finding, replace the canonical line; if dictation flags a technical limitation, that triggers LIMITATIONS inclusion and the position reflects the limitation. **The default rendering is defeasible.** A canonical default-normal line is a proposal the dictation may override, not a mandate the generator must satisfy. Where a dictated positive implicates the structure as a companion — the Companion Matrix names it as a secondary effect, complication, or paired-territory consequence of that positive — asserting the canonical normal would state as verified something the dictated finding puts in question. In that case the line is dropped, or rendered in a contingent form that does not assert. Coverage of the structure remains obligatory; the specific normal assertion does not. Silence about a structure whose companion finding was dictated is not the same kind of silence as silence on an unremarkable study, and must not be rendered as though it were.
```

- [ ] **Step 4: Edit the GLM variant (line 476)**

Find the second occurrence — the **GLM** one, ending `...that triggers LIMITATIONS inclusion.` (no `and the position reflects` tail). Replace that whole bullet with:

```
- If dictation is silent about an in-scope structure the sweep order visits, render the structure's canonical default-normal line at its sweep position. Silence is not omission in the report — it is the default rendering. This applies to every in-scope system on broad-coverage scans, not only to secondary visible regions. If dictation specifies a positive finding, replace the canonical line; if dictation flags a technical limitation, that triggers LIMITATIONS inclusion. **The default rendering is defeasible.** A canonical default-normal line is a proposal the dictation may override, not a mandate the generator must satisfy. Where a dictated positive implicates the structure as a companion — the Companion Matrix names it as a secondary effect, complication, or paired-territory consequence of that positive — asserting the canonical normal would state as verified something the dictated finding puts in question. In that case the line is dropped, or rendered in a contingent form that does not assert. Coverage of the structure remains obligatory; the specific normal assertion does not. Silence about a structure whose companion finding was dictated is not the same kind of silence as silence on an unremarkable study, and must not be rendered as though it were.
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Verify no other prompt assertions regressed**

```bash
cd backend && poetry run pytest tests/ -v
```

Expected: all pass. No existing test asserts on these prompt strings, so this should be green; if anything fails, it is a real regression — stop and investigate.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/quick_report_analyser.py backend/tests/test_quick_report_prompts.py
git commit -m "harden(quick-report): default-normal lines are defeasible when a companion is dictated

Both analyser variants (Sonnet + GLM). A canonical default-normal is now a
proposal the dictation may override, not a mandate. Coverage stays obligatory.

Fixes the class of defect where a report asserted clear basal cisterns
alongside a dictated 8mm subdural with 3mm midline shift."
```

---

### Task 2: Require imaged-volume containment for secondary visible regions

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py:245` (Sonnet Scan Context template)
- Modify: `backend/src/rapid_reports_ai/quick_report_analyser.py:556-557` (GLM Scan Context template)
- Test: `backend/tests/test_quick_report_prompts.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_quick_report_prompts.py`:

```python
@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_secondary_regions_must_lie_inside_imaged_volume(prompt: str):
    """A region outside the declared imaged volume cannot carry a normal line."""
    assert "must lie within the declared Imaged volume" in prompt


@pytest.mark.parametrize("prompt", BOTH_ANALYSER_PROMPTS)
def test_co_acquisition_is_not_visibility(prompt: str):
    """Guards the exact failure seen: trauma co-ordering made the analyser
    emit a cervical-spine normal on a vertex-to-skull-base head CT."""
    assert "Co-acquisition convention" in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -k "volume or acquisition" -v
```

Expected: 4 failures, `AssertionError`.

- [ ] **Step 3: Edit the Sonnet Scan Context template (line 245)**

Replace the single line beginning `- **Secondary visible regions:** <region> → "<canonical default-normal line>"  (emit a line ONLY when...` with:

```
- **Secondary visible regions:** <region> → "<canonical default-normal line>"  (emit a line ONLY when the phrasing is case-specific — a region that would default to "unremarkable" is omitted; the generator already carries that default. Emit when the region has a canonical radiological phrasing that differs from "unremarkable", e.g. "The visualised lung bases are clear". CONTAINMENT: every region named here must lie within the declared Imaged volume. A region outside that volume is not a secondary visible region — it belongs in Out of scope, with no canonical line. Co-acquisition convention is not visibility: regions commonly scanned in the same sitting as this study, or implied by the clinical context, are not visible in this study's volume unless the volume contains them. Emitting a canonical normal for a region outside the imaged volume produces a confident assertion about anatomy the study cannot evaluate.)
```

- [ ] **Step 4: Edit the GLM Scan Context template (lines 556-557)**

The GLM template is a terser two-line form. Replace:

```
- **Secondary visible regions:**
  - <region> → "<canonical default-normal line>"
```

with:

```
- **Secondary visible regions:**  (CONTAINMENT: every region named here must lie within the declared Imaged volume. A region outside that volume is not a secondary visible region — it belongs in Out of scope, with no canonical line. Co-acquisition convention is not visibility: regions commonly scanned in the same sitting as this study, or implied by the clinical context, are not visible in this study's volume unless the volume contains them. Emitting a canonical normal for a region outside the imaged volume produces a confident assertion about anatomy the study cannot evaluate.)
  - <region> → "<canonical default-normal line>"
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -v
```

Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/quick_report_analyser.py backend/tests/test_quick_report_prompts.py
git commit -m "harden(quick-report): secondary visible regions must lie inside the imaged volume

Both analyser variants. Co-acquisition convention is explicitly not visibility.

Fixes the defect where a vertex-to-skull-base head CT emitted
'The cervical spine alignment is normal with no acute fracture or subluxation'."
```

---

### Task 3: Add the generator-side override licence (Principle 12)

Task 1 changes how the *sheet* is authored. This task changes how the *generator* is permitted to treat it — necessary because the generator is instructed elsewhere that the normal-study path is a "load-bearing scaffold" it "does not invent" but "consumes" (`quick_report_analyser.py:137`). Without an explicit override licence, the generator will keep obeying stale sheets, including every sheet already cached in `ephemeral_skill_sheets`.

Model the wording on Principle 11, which already establishes this exact override shape for gender signals.

**Files:**
- Modify: `backend/src/rapid_reports_ai/quick_report_hardening.py` (append after Principle 11, before the closing `"---\n"`)
- Test: `backend/tests/test_quick_report_prompts.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_quick_report_prompts.py`:

```python
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE


def test_preamble_has_evidence_override_principle():
    assert "**12. A canonical line from the skill sheet is a proposal" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )


def test_principle_12_names_both_override_conditions():
    """Out-of-volume and companion-contradiction are the two triggers."""
    assert "outside the declared imaged volume" in QUICK_REPORT_HARDENING_PREAMBLE
    assert "companion of a dictated positive" in QUICK_REPORT_HARDENING_PREAMBLE


def test_principle_12_preserves_coverage():
    assert "Dropping an assertion is not dropping the structure" in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )


def test_principle_11_gender_rule_not_clobbered():
    """Regression guard — Principle 12 is appended, not substituted."""
    assert "**11. Gender-specific structures require an explicit gender " in (
        QUICK_REPORT_HARDENING_PREAMBLE
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -k principle -v
```

Expected: 3 failures (`test_principle_11_gender_rule_not_clobbered` passes already).

- [ ] **Step 3: Append Principle 12**

In `backend/src/rapid_reports_ai/quick_report_hardening.py`, the constant ends with Principle 11's final line `"incorrect).\n"` followed by `"\n"`, `"---\n"`, `"\n"`, `)`. Insert the new principle between `"incorrect).\n"` and the `"\n"` `"---\n"` closing lines:

```python
    "\n"
    "**12. A canonical line from the skill sheet is a proposal, not a "
    "warrant.**\n"
    "\n"
    "The skill sheet is authored from scan type and clinical history "
    "alone, before any dictation exists. Its canonical default-normal "
    "lines are therefore written without knowledge of what was found. "
    "They are the right default for a silent study and they carry the "
    "sweep's systematic coverage — but they are not evidence, and you "
    "are the only component that sees the sheet and the dictation "
    "together. Where the two conflict, the dictation governs.\n"
    "\n"
    "Override a canonical line in exactly two situations:\n"
    "\n"
    "- **The region lies outside the declared imaged volume.** Check "
    "each canonical line against the sheet's own Imaged volume "
    "declaration. A sheet may name a region that the stated volume "
    "does not contain — commonly a region conventionally co-acquired "
    "with this study, or one suggested by the clinical context. Do "
    "not render its line. A normal statement about anatomy the study "
    "did not cover is a fabrication with a citation.\n"
    "- **The region is a companion of a dictated positive.** Where "
    "the dictation reports a finding and the sheet's Companion Matrix "
    "names this region among that finding's secondary effects, "
    "complications, or paired-territory consequences, the canonical "
    "normal asserts as verified something the dictated finding puts "
    "in question. Drop the line, or render it contingently without "
    "asserting. A report that states a structure is clear while "
    "reporting a finding that would be expected to alter it is "
    "internally inconsistent, and the inconsistency is invisible to "
    "the radiologist skim-reading their own dictation back.\n"
    "\n"
    "Dropping an assertion is not dropping the structure. The sweep "
    "still visits it and the paragraph still covers it; what changes "
    "is that an unsupported claim is not made about it. Coverage is "
    "obligatory, assertion is earned. Where you are unsure whether a "
    "canonical line is contradicted, prefer the contingent rendering "
    "over the confident one — an under-asserted report costs the "
    "radiologist a glance, an over-asserted one costs them a "
    "correction they may not notice they need to make.\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && poetry run pytest tests/test_quick_report_prompts.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Sanity-check the preamble still composes**

```bash
cd backend && poetry run python -c "
from rapid_reports_ai.quick_report_hardening import QUICK_REPORT_HARDENING_PREAMBLE as P
print('chars:', len(P))
print('principles:', sum(1 for i in range(1, 13) if f'**{i}.' in P))
assert P.rstrip().endswith('---'), 'preamble must still end with the --- separator'
print('OK')
"
```

Expected: `principles: 12` and `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/quick_report_hardening.py backend/tests/test_quick_report_prompts.py
git commit -m "harden(quick-report): Principle 12 — generator may override unsupported canonical lines

Grants the generator an explicit licence to drop a sheet-prescribed
default-normal when the region is outside the imaged volume or is a companion
of a dictated positive. Generalises the override pattern already established
by Principle 11 for gender signals.

Also repairs sheets already cached in ephemeral_skill_sheets, which the
analyser-side fixes alone cannot reach."
```

---

### Task 4: Deterministic dictation integrity detector

**Files:**
- Create: `backend/src/rapid_reports_ai/dictation_integrity.py`
- Test: `backend/tests/test_dictation_integrity.py`

Design constraint: **detection only, never repair.** The existing contextual pass rewrites (strips fillers); a rewriting pass that encounters `"...lesion in the"` will tidy it into fluent prose, which reproduces the exact failure this is meant to prevent. This module returns flags and mutates nothing.

Second constraint: **precision over recall.** Radiologists dictate in fragments and bullet lists with no terminal punctuation. Missing punctuation alone must never flag, or the feature becomes noise and gets ignored. Only a trailing function word — a word that cannot legitimately end a clinical statement — flags.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_dictation_integrity.py`:

```python
"""Unit tests for the deterministic dictation integrity checks.

Pure function, no I/O. The corpus cases below are real:
- the truncation case is report 56f501c1 (CT lumbar, metastatic workup,
  quality_core 2.33) whose dictation ended '...osseous lesion in the'
- the benign-fragment cases are drawn from reports that scored 5.0 and must
  NOT flag, or the feature becomes noise.
"""
from __future__ import annotations

from rapid_reports_ai.dictation_integrity import IntegrityFlag, check_dictation


def test_clean_dictation_returns_no_flags():
    text = "- lungs are clear\n- no pleural effusion"
    assert check_dictation(text) == []


def test_truncation_mid_clause_is_flagged():
    """The real 56f501c1 failure: dictation cut off after a preposition."""
    text = (
        "- Comparison made to previous study dated 23/01/2026\n"
        "- There is a new destructive expansile osseous lesion in the"
    )
    flags = check_dictation(text)
    assert len(flags) == 1
    assert flags[0].kind == "truncation"
    assert flags[0].severity == "high"


def test_truncation_after_measuring_is_flagged():
    flags = check_dictation("There is a lesion measuring")
    assert len(flags) == 1
    assert flags[0].kind == "truncation"


def test_dangling_measurement_is_flagged():
    flags = check_dictation("Large high-density focus measuring up to 46 x")
    assert len(flags) == 1
    assert flags[0].kind == "dangling_measurement"
    assert flags[0].severity == "high"


def test_complete_measurement_is_not_flagged():
    text = "Focus measuring up to 46 x 36 mm axially and 29 mm CC"
    assert check_dictation(text) == []


def test_terminal_punctuation_suppresses_the_flag():
    """The TAVI 5.0 case contained the fragment 'The left lung.' — benign,
    because it terminates. Must not flag."""
    assert check_dictation("The left lung.") == []


def test_bullet_fragments_without_punctuation_do_not_flag():
    """Radiologists dictate in unpunctuated fragments. Precision matters more
    than recall here — a noisy check gets ignored."""
    text = (
        "- acute subdural haematoma along the right cerebral convexity\n"
        "- no skull vault fracture\n"
        "- age-related involutional change"
    )
    assert check_dictation(text) == []


def test_empty_and_whitespace_are_clean():
    assert check_dictation("") == []
    assert check_dictation("   \n  \n ") == []
    assert check_dictation(None) == []


def test_trailing_blank_lines_do_not_mask_truncation():
    flags = check_dictation("There is a mass in the\n\n   \n")
    assert len(flags) == 1
    assert flags[0].kind == "truncation"


def test_flag_carries_an_excerpt_for_the_ui():
    flags = check_dictation("There is a new destructive lesion in the")
    assert flags[0].excerpt
    assert flags[0].excerpt in "There is a new destructive lesion in the"


def test_flag_is_immutable():
    import pytest
    flag = IntegrityFlag(kind="truncation", severity="high", excerpt="x", message="y")
    with pytest.raises(Exception):
        flag.kind = "other"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && poetry run pytest tests/test_dictation_integrity.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'rapid_reports_ai.dictation_integrity'`.

- [ ] **Step 3: Write the implementation**

Create `backend/src/rapid_reports_ai/dictation_integrity.py`:

```python
"""Deterministic integrity checks on raw dictation, run before generation.

Detection only — this module never rewrites the dictation. A pass that
"repairs" a truncation reproduces the failure it exists to prevent: the
generator smoothing an incomplete statement into a confident, complete-looking
report. Flags are surfaced to the radiologist, who decides.

Precision is deliberately favoured over recall. Radiologists dictate in
unpunctuated fragments and bullet lists; a check that fires on every missing
full stop is noise and will be ignored, which is worse than no check. Only a
trailing function word — one that cannot legitimately end a clinical
statement — raises a flag.

These are cheap regex/token rules with no LLM call, so they can run on every
keystroke-idle without cost. Semantic checks (laterality contradiction,
measurement/descriptor mismatch) belong in a separate LLM-backed pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Words that cannot legitimately end a dictated clinical statement. A dictation
# ending here is mid-clause, whatever the punctuation suggests.
_DANGLING_TAIL = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with",
        "from", "into", "by", "for", "is", "are", "was", "were", "no", "there",
        "within", "without", "measuring", "showing", "demonstrating",
        "which", "that", "than", "but", "between", "adjacent", "overlying",
    }
)

_TERMINAL_PUNCTUATION = ".!?:;"

# "46 x", "4 ×" — a measurement whose next dimension never arrived.
_DANGLING_MEASUREMENT = re.compile(r"\d+\s*(?:x|×)\s*$", re.IGNORECASE)

_TRAILING_NON_WORD = re.compile(r"[^\w-]+$")

_EXCERPT_CHARS = 60


@dataclass(frozen=True)
class IntegrityFlag:
    """One detected problem. ``kind`` drives UI treatment, ``severity``
    drives whether generation is gated."""

    kind: str  # "truncation" | "dangling_measurement"
    severity: str  # "high" | "medium"
    excerpt: str
    message: str


def _last_content_line(text: str) -> str:
    """The last line with any content — trailing blank lines must not mask a
    truncation on the line above."""
    for line in reversed(text.strip().splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_dictation(text: str | None) -> list[IntegrityFlag]:
    """Return integrity flags for a dictation. An empty list means clean.

    Only the final content line is examined: truncation is an end-of-input
    phenomenon. Mid-text fragments are normal dictation style, not defects.
    """
    if not text or not text.strip():
        return []

    line = _last_content_line(text)
    if not line:
        return []

    if _DANGLING_MEASUREMENT.search(line):
        return [
            IntegrityFlag(
                kind="dangling_measurement",
                severity="high",
                excerpt=line[-_EXCERPT_CHARS:],
                message=(
                    "This measurement looks incomplete — a dimension may be "
                    "missing. Confirm before generating."
                ),
            )
        ]

    if line[-1] in _TERMINAL_PUNCTUATION:
        return []

    tokens = line.split()
    if not tokens:
        return []

    last_word = _TRAILING_NON_WORD.sub("", tokens[-1]).lower()
    if last_word in _DANGLING_TAIL:
        return [
            IntegrityFlag(
                kind="truncation",
                severity="high",
                excerpt=line[-_EXCERPT_CHARS:],
                message=(
                    f'The dictation appears to end mid-sentence ("…{last_word}"). '
                    "Generating from an incomplete statement can produce a "
                    "confident report with a missing detail. Confirm or complete "
                    "the dictation."
                ),
            )
        ]

    return []
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && poetry run pytest tests/test_dictation_integrity.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/dictation_integrity.py backend/tests/test_dictation_integrity.py
git commit -m "feat(quick-report): deterministic dictation integrity detector

Flags truncation mid-clause and dangling measurements. Detection only — never
rewrites, because a repairing pass reproduces the failure it prevents.

Precision-first: unpunctuated bullet fragments (normal dictation) do not flag;
only a trailing function word does. Catches the 56f501c1 class of failure."
```

---

### Task 5: Expose the detector as an endpoint

**Files:**
- Modify: `backend/src/rapid_reports_ai/main.py` (add request model near the other `BaseModel` declarations around line 745-758; add route near the quick-report routes around line 2570)
- Test: `backend/tests/test_dictation_check_route.py`

- [ ] **Step 1: Write the failing test**

**Auth note — read before writing this file.** `tests/conftest.py` provides `db_engine`, `db_session`, and `client`, but **no auth fixture**, and no existing test authenticates a protected route (`get_current_user` is never overridden anywhere in the suite). This is the first one that needs it, so the fixture is defined locally here. Override the dependency rather than minting real JWTs — `main.py` imports `get_current_user` from `.auth` at line 68, so that exact function object is the override key.

Create `backend/tests/test_dictation_check_route.py`:

```python
"""Route tests for POST /api/dictation/check.

Uses the shared SQLite TestClient harness from conftest.py. conftest provides
no auth fixture and no prior test authenticates a protected route, so the
authed_client fixture below is defined locally. It overrides the
get_current_user dependency rather than minting a JWT — the route's behaviour
under test is the integrity check, not token validation.
"""
from __future__ import annotations

import uuid

import pytest

from rapid_reports_ai.auth import get_current_user
from rapid_reports_ai.database.models import User
from rapid_reports_ai.main import app


@pytest.fixture
def authed_client(client, db_session):
    """TestClient whose requests resolve to a real persisted user."""
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@nhs.net",
        password_hash="x",
        full_name="Test Radiologist",
        is_active=True,
        is_verified=True,
        is_approved=True,
    )
    db_session.add(user)
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def test_clean_dictation_reports_ok(authed_client):
    r = authed_client.post(
        "/api/dictation/check",
        json={"findings": "- lungs clear\n- no effusion"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["flags"] == []
    assert body["should_gate"] is False


def test_truncated_dictation_reports_a_gating_flag(authed_client):
    r = authed_client.post(
        "/api/dictation/check",
        json={"findings": "There is a new destructive osseous lesion in the"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert len(body["flags"]) == 1
    assert body["flags"][0]["kind"] == "truncation"
    assert body["flags"][0]["message"]
    assert body["should_gate"] is True


def test_empty_findings_is_clean(authed_client):
    r = authed_client.post("/api/dictation/check", json={"findings": ""})
    assert r.status_code == 200
    assert r.json()["flags"] == []


def test_route_requires_authentication(client):
    """Plain `client` — no dependency override, so real JWT validation runs."""
    r = client.post("/api/dictation/check", json={"findings": "anything"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && poetry run pytest tests/test_dictation_check_route.py -v
```

Expected: 4 failures, all `assert 404 == 200` (route not registered) except the auth test.

- [ ] **Step 3: Add the request model**

In `backend/src/rapid_reports_ai/main.py`, immediately after the `QuickReportProtoGenerateRequest` class (around line 758), add:

```python
class DictationCheckRequest(BaseModel):
    findings: str
```

- [ ] **Step 4: Add the route**

In `backend/src/rapid_reports_ai/main.py`, immediately before `@app.post("/api/quick-report-proto/analyse")` (around line 2570), add:

```python
@app.post("/api/dictation/check")
async def dictation_check_endpoint(
    request: DictationCheckRequest,
    current_user: User = Depends(get_current_user),
):
    """Deterministic integrity check on raw dictation, before generation.

    Cheap (regex only, no LLM) so the frontend can call it on idle. Returns
    ``should_gate`` when a high-severity flag means the radiologist should
    confirm before a report is generated from this dictation.
    """
    from .dictation_integrity import check_dictation

    flags = check_dictation(request.findings)
    return {
        "success": True,
        "flags": [
            {
                "kind": f.kind,
                "severity": f.severity,
                "excerpt": f.excerpt,
                "message": f.message,
            }
            for f in flags
        ],
        "should_gate": any(f.severity == "high" for f in flags),
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && poetry run pytest tests/test_dictation_check_route.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run the whole suite**

```bash
cd backend && poetry run pytest tests/ -v
```

Expected: all pass. Watch specifically for cross-test pollution — `authed_client` mutates `app.dependency_overrides`, so if any *other* test starts failing only when the full suite runs, the override teardown is the first suspect.

- [ ] **Step 7: Commit**

```bash
git add backend/src/rapid_reports_ai/main.py backend/tests/test_dictation_check_route.py
git commit -m "feat(api): POST /api/dictation/check for pre-generation integrity flags

Thin authenticated route over dictation_integrity.check_dictation. Returns
should_gate for high-severity flags so the frontend can require confirmation
before generating from a truncated dictation."
```

---

### Task 6: Behavioural verification against the two known-bad cases

Prompt edits are not verified by unit tests — those only prove the words are present. This task proves the words changed the behaviour. It requires live API keys and makes real LLM calls.

**Files:**
- Create: `backend/test_cases/integrity_regression.json`

- [ ] **Step 1: Record the pre-change prompt versions**

```bash
cd backend && poetry run python -c "
from rapid_reports_ai.quick_report_analyser import analyser_prompt_version
print('glm  :', analyser_prompt_version('zai-glm-4.7'))
print('haiku:', analyser_prompt_version('claude-haiku-4-5-20251001'))
"
```

Expected: values differing from the pre-change production values `4f003721a4b3` (GLM) and `1a2c6c8d14c7` (Haiku). If they match, the prompt edits did not land — stop and re-check Tasks 1 and 2.

Write both new hashes into the commit message in Step 5.

- [ ] **Step 2: Create the regression case file**

Create `backend/test_cases/integrity_regression.json`:

```json
[
  {
    "name": "ct_head_out_of_volume_and_companion_contradiction",
    "scan_type": "CT head non-contrast",
    "clinical_history": "Elderly fall on anticoagulation, reduced GCS. Query intracranial haemorrhage.",
    "findings": "- acute subdural haematoma along the right cerebral convexity, maximal thickness 8 mm, with 3 mm of midline shift to the left\n- no skull vault fracture\n- age-related involutional change"
  },
  {
    "name": "ct_lumbar_truncated_dictation",
    "scan_type": "CT lumbar",
    "clinical_history": "Metastatic colonic cancer, mets to lung liver and bone, new onset reduced mobility and inability to walk, to rule out metastatic encroachment into the spinal canal",
    "findings": "- Comparison made to previous study dated 23/01/2026\n- There is a new destructive expansile osseous lesion in the"
  }
]
```

- [ ] **Step 3: Run the analyser suite over both cases**

```bash
cd backend && ./scripts/quick-eval.sh --cases-file test_cases/integrity_regression.json
```

Output lands in `backend/test_output/<timestamp>/summary.md`. Runs ~2 minutes.

- [ ] **Step 4: Inspect the output against these acceptance criteria**

Open `backend/test_output/<timestamp>/summary.md` and check, for the **ct_head** case:

| Check | Pass condition |
|---|---|
| Out-of-volume | The sheet's Scan Context does **not** list cervical spine under Secondary visible regions (or lists it under Out of scope) |
| Volume consistency | Nothing in the normal-study path asserts a normal for a region outside the stated Imaged volume |
| Companion contradiction | The generated report does **not** assert "the subarachnoid spaces and basal cisterns are clear" alongside the dictated midline shift |
| Coverage preserved | The report still sweeps the subarachnoid/cisternal region — dropped assertion, not dropped structure |

For the **ct_lumbar** case, confirm the detector independently:

```bash
cd backend && poetry run python -c "
import json
from rapid_reports_ai.dictation_integrity import check_dictation
cases = json.load(open('test_cases/integrity_regression.json'))
for c in cases:
    print(c['name'], '->', [f.kind for f in check_dictation(c['findings'])])
"
```

Expected:
```
ct_head_out_of_volume_and_companion_contradiction -> []
ct_lumbar_truncated_dictation -> ['truncation']
```

- [ ] **Step 5: Commit the case file**

```bash
git add backend/test_cases/integrity_regression.json
git commit -m "test(quick-report): integrity regression basket

Two corpus cases that previously failed: the CT head sheet that asserted a
cervical-spine normal outside its vertex-to-skull-base volume and clear basal
cisterns alongside 3mm midline shift, and the truncated CT lumbar dictation.

New analyser prompt versions: glm <HASH>, haiku <HASH>."
```

> Replace `<HASH>` with the values recorded in Step 1. These identify the post-fix cohort in `ephemeral_skill_sheets.analyser_prompt_version` for Metabase before/after comparison.

- [ ] **Step 6: If the ct_head case still fails**

Do not weaken the acceptance criteria. The likely causes, in order:

1. Only one analyser variant was edited — confirm with `grep -c "defeasible" backend/src/rapid_reports_ai/quick_report_analyser.py`, which must return `2`.
2. The eval ran the GLM analyser while you only verified the Sonnet output, or vice versa — check which variant the summary reports.
3. The rule is present but losing to the "load-bearing scaffold" language at line 137. If so, that line needs the defeasibility caveat too: append to it *"Individual canonical lines within this scaffold are defeasible under Phase 6 — the scaffold guarantees coverage, not the truth of any specific normal assertion."* Then re-run.

---

---

## Execution outcome (completed 2026-08-04, branch `harden/report-integrity-defeasible-fills`)

All six tasks executed inline. Final suite: **95 passed**.

**Prompt versions:** glm `4f003721a4b3` → `8bf051046bff`; haiku `1a2c6c8d14c7` → `9e891655c47e`. Use these to cut before/after cohorts in Metabase on `ephemeral_skill_sheets.analyser_prompt_version`.

**Task 6 found a real over-fire that unit tests could not.** The first version of Principle 12 keyed the override on *"the Companion Matrix names this region"*. That matrix holds **both** in-scope companions **and** mandatory negatives, so the rule licensed dropping mandatory negatives — and both analyser variants immediately did, on a study indicated for query haemorrhage:

| Run | GLM | Haiku |
|---|---|---|
| BEFORE (original prompts) | 801ch, cistern coverage present | 903ch, four-compartment haemorrhage negative present |
| AFTER-1 (first fix) | 696ch, **cistern coverage lost**, c-spine appeared | 878ch, **haemorrhage negative lost** |
| AFTER-2 (mandatory-negative exemption) | 861ch, coverage restored, no c-spine | 745ch, SAH negative restored, no c-spine |

AFTER-2 passes all four acceptance criteria on both variants. GLM now emits the contingent rendering the principle asked for — *"The extra-axial spaces are **otherwise** unremarkable"* — rather than flatly contradicting the dictated subdural, while retaining the hydrocephalus and basal-cistern negatives.

**Lesson worth carrying:** a prompt rule that names a sheet section as its trigger inherits everything in that section. Scope the trigger to the specific construct (canonical default-normal lines), not the container.

**Bonus finding from Task 4.** The detector was validated against 400 real production dictations: 2 flagged, **both genuine truncations, zero false positives**. One was previously unknown — report `fd47e6a2` (CT abdomen/pelvis) ended on *"No suspicious bony lesion was"* and the generator completed it into the flat assertion *"No suspicious bone lesions."* That report carries no quality score at all, so no existing metric would ever have surfaced it.

**Caveat on the behavioural evidence:** one run per variant per condition against a stochastic system. The direction is consistent across both variants and the mechanism is understood, but these are not statistically robust samples. Re-run `./scripts/quick-eval.sh --cases-file test_cases/integrity_regression.json` after any further prompt edit.

**Incidental fix:** `tests/test_quality_scoring.py` asserted `rubric_version == "v2"` while the engine emits `"v2.1"` — a stale assertion from the v2.1 work (db660f6) that left the suite red on main. Rebound to `qs.RUBRIC_VERSION_V2`, committed separately (`19bcf7a`).

---

## Follow-on plans (out of scope here — separate plans)

This plan deliberately covers one subsystem: assertions the evidence does not support. Three related pieces from the same analysis need their own plans, because each touches a different subsystem and ships independently.

**Plan B — Dictation integrity UX.** Surfaces `/api/dictation/check` in `DictationScratchpad.svelte`: inline underlines on idle, and a confirm-before-generate gate when `should_gate` is true. Includes carrying an acknowledged flag through to generation so the generator renders `[dictation incomplete — location not specified]` rather than smoothing. Frontend-only plus one field on the generate request.

**Plan C — Provenance tagging.** Generator marks each sentence as dictation-derived or default-fill; the UI renders fills at lower visual weight so the radiologist's eye lands on what they are certifying but did not say. Gives a free deterministic quality metric (fill ratio per report) needing no LLM judge, and converts an invisible risk into a visible one.

**Plan D — Reading-window contradiction pass.** Reuses the existing idle `STRUCTURE_VALIDATOR` slot (`gpt-oss-120b`) to check the drafted report for default-fills contradicting dictated positives, run *after* the report renders so it costs no critical-path latency — the same free-window trick the dictation phase already exploits. Also splits the judge rubric's `normal_fill_appropriateness` into "appropriate fill" vs "asserted unverified", which currently sits at a misleading 4.92/5.0 ceiling.

---

## Self-review notes

- **Spec coverage:** defeasible fills (Tasks 1, 3), volume containment (Task 2), truncation detection (Tasks 4, 5), behavioural proof (Task 6). Provenance tagging, contradiction pass, rubric split, and frontend UX are explicitly deferred above rather than silently dropped.
- **Both prompt variants** are edited in every prompt task; Task 6 Step 6 makes the "only edited one" failure mode the first thing to check.
- **Cached-sheet coverage:** Task 3 is what repairs the ~150 sheets already in `ephemeral_skill_sheets`, which Tasks 1–2 cannot reach.
- **Type consistency:** `IntegrityFlag(kind, severity, excerpt, message)` and `check_dictation(text) -> list[IntegrityFlag]` are used identically in Tasks 4, 5, and 6.
- **Auth fixture verified, not assumed:** `tests/conftest.py` provides only `db_engine`, `db_session`, and `client`. There is no `auth_headers` fixture and no existing test authenticates a protected route, so Task 5 defines `authed_client` locally and overrides `get_current_user` (imported in `main.py:68` from `.auth`, which is the correct override key).
- **Known soft spot:** Task 6 is the only task requiring live API keys and real LLM calls, and its acceptance criteria are judgement-based rather than assertable. It is deliberately last so Tasks 1–5 can be merged on unit tests alone if Task 6 needs to wait for credentials.
