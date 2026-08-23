# Skill Sheet v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a sheet-agnostic policy layer and a deterministic defect checklist, use them to run the experiment that two generations of prompts have never had — *does the sheet grammar actually matter?* — and only then build v3.

**Architecture:** Three artefacts instead of two. `report_v3_policy.py` holds everything scan-type-invariant **and names no sheet fields** (register, uncertainty lexicon, banned constructions, section format, COMPARISON rule). That property is the whole point: today's `GLOBAL_STYLE_GUIDE`, `QUICK_REPORT_HARDENING_PREAMBLE` and `VERIFICATION_CHECKLIST` all name v1 sheet fields — *style exemplars*, *impression exemplars*, *canonical line*, *mandatory negatives*, *fixed blocks* — so changing the sheet grammar necessarily breaks the layer above it. That coupling is why `report_v2.py` had to go self-contained, and why v2 has never once run inside the system scaffolding. A sheet-agnostic policy layer makes "change only the sheet" a coherent operation for the first time. `report_v3.py` holds the two prompts, the sheet validator and the callers. `report_checks.py` holds a version-agnostic report defect checklist usable on v1/v2/v3 output today. Nothing in production imports any of it — v3 is a parallel track, guarded by test, exactly as v2 is.

**Sequencing is load-bearing.** Tasks 1–7 build the policy layer and the instrument. Task 8 runs a three-arm experiment and **is a decision gate** — if the v2 sheet grammar shows no benefit once policy is held constant, the v3 analyser work in Tasks 9–15 is the wrong investment and should not start.

**Tech Stack:** Python 3.13, pytest, `_run_agent_with_model` from `enhancement_utils`, Qwen 3.6 27B on Groq.

**Spec:** `docs/superpowers/specs/2026-08-22-skill-sheet-v3-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/rapid_reports_ai/report_v3_policy.py` | **Create.** `POLICY_CORE` (register, lexicon, banned) sent to both stages; `POLICY_REPORT` (sections, COMPARISON) sent to the generator only; `BANNED_PATTERNS` as the machine-readable twin of the prose |
| `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py` | **Create.** Version-agnostic report checks driven by `BANNED_PATTERNS`. Works on any report, no sheet needed |
| `backend/src/rapid_reports_ai/report_v3.py` | **Create.** `ANALYSER_V3`, `GENERATOR_V3`, `validate_sheet_v3`, `check_report_against_sheet_v3`, `generate_sheet_v3`, `generate_report_v3` |
| `backend/src/rapid_reports_ai/scripts/sheet_budget/policy_ab.py` | **Create.** The three-arm experiment of Task 8 |
| `backend/src/rapid_reports_ai/scripts/sheet_budget/v3_run.py` | **Create.** Harness mirroring `v2_run.py`, with judge and checks wired in |
| `backend/tests/test_report_checks.py` | **Create.** Unit tests for the checklist |
| `backend/tests/test_report_v3.py` | **Create.** Prompt-content guards, validator tests, production-isolation guard |

Ordering: policy + instrument (Tasks 1–7) → **decision gate** (Task 8) → v3, only if the gate says so (Tasks 9–15).

**Why not just build v3.** `v2_run.py` calls `generate_sheet_v2`/`generate_report_v2`, which pass `ANALYSER_V2`/`GENERATOR_V2` bare — no `SYSTEM_PREAMBLE`, no `GLOBAL_STYLE_GUIDE`, no hardening preamble, no scaffolds. Every v1 harness (`runner.py`, `reasoning_matrix.py`, `encoding_matrix.py`, `sheet_encoding_ab.py`) goes through `template_manager` and inherits all of it. So v1 was measured at roughly 42 KB analyser + 33 KB generator context and v2 at roughly 8 KB + 13 KB. **The two generations were never measured on comparable footing**, and the sheet grammar changed in the same step as the entire policy stack. Task 8 separates them before anything else is built.

**Single source of truth:** the banned-phrase list exists once, in `report_v3_policy.BANNED_PATTERNS`. The prose in `POLICY_CORE` and the regexes in `report_checks.py` both derive from it. Do not duplicate the list.

---

## Task 1: Policy module — core constants

**Files:**
- Create: `backend/src/rapid_reports_ai/report_v3_policy.py`
- Test: `backend/tests/test_report_v3.py`

- [ ] **Step 1: Write the failing test**

```python
"""Guards for the v3 parallel pipeline."""
from __future__ import annotations

import re

from rapid_reports_ai import report_v3_policy as pol


def test_policy_core_carries_lexicon_and_banned_prose():
    p = pol.POLICY_CORE
    for phrase in ("diagnostic of", "probable", "may represent", "unlikely",
                   "not proof of absence"):
        assert phrase in p, f"lexicon row missing: {phrase}"
    assert "not fully characterised" in p          # qualifier preservation, L-30 defect
    assert "cannot be excluded" in p
    assert "no significant abnormality" in p
    assert "physiotherapy" in p                    # management trespass, L-24


def test_policy_report_carries_sections_and_comparison_branches():
    p = pol.POLICY_REPORT
    assert "COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION" in p
    assert "on its own line, terminated by a colon" in p
    assert "No prior imaging available for comparison." in p
    assert "Comparison made to previous imaging." in p
    assert "never inventing a scan type or a date" in p


def test_banned_patterns_are_compiled_and_named():
    assert pol.BANNED_PATTERNS, "banned list must not be empty"
    for name, rx in pol.BANNED_PATTERNS:
        assert isinstance(name, str) and name
        assert isinstance(rx, re.Pattern)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.report_v3_policy'`

- [ ] **Step 3: Write the implementation**

```python
"""Global report policy for the v3 pipeline.

Everything here is scan-type-invariant: the same bytes on every case. It is
prepended to the stage prompts rather than restated in the decision sheet
(spec R6 — if a rule is the same for every case, it never belongs in the sheet).

Supersedes, for v3 only, QUICK_REPORT_HARDENING_PREAMBLE and the quick path's
use of global_style_guide.GLOBAL_STYLE_GUIDE. Production still uses those; this
module is on the parallel track until a cutover is separately proposed.

Split in two because the analyser writes report-register templates (so it needs
the register, the lexicon and the banned list) but never writes a COMPARISON
section (so the output-format half would be dead tokens on the analyser call).
"""
from __future__ import annotations

import re

POLICY_CORE = """## REPORT POLICY — core

Applies to every study and every modality. Never restated in the decision sheet.

### Register
British English, UK/NHS practice. Impersonal, present tense for findings. Compressed
declaratives — a consultant states what is, at pace. Dates DD/MM/YYYY; mm and cm; consistent
units and sensible precision within a report, never false precision. Lead with the anatomical
subject or the imaging feature: existential openers ("there is", "there are") and padding verbs
("is noted", "is seen", "is demonstrated", "is appreciated") are filler. Direct copula plus
adjective ("the appendix is dilated") is not filler — it carries information.

Laterality and vertebral levels are checked, not assumed, and must agree between FINDINGS and
IMPRESSION. Laterality error is the classic radiology report defect.

### Calibrated uncertainty
Confidence is expressed with this lexicon and no other. Do not hedge outside it.

| phrase | confidence |
|---|---|
| diagnostic of / consistent with | above 90% |
| probable / likely represents | 70 to 90% |
| possible / may represent | 25 to 50% |
| unlikely | below 10% |
| no evidence of | below detection on this study — not proof of absence |

Uncertainty in the dictation is preserved, never resolved. A dictated hypodensity "not fully
characterised" is not a cyst. Naming an entity the dictation declined to name is fabrication,
however probable the entity. Where genuine uncertainty remains, name what would resolve it — a
specific test, a prior study, a clinical detail — rather than leaving it open.

### Banned constructions
- "cannot be excluded" without both a confidence term and a resolution path
- "clinical correlation recommended" standing alone, with nothing named to correlate
- "no significant abnormality" — significant to whom
- "stable" for a measurable lesion without the current value, the prior value and the prior's date
- management vocabulary: treatment, drugs, dosing, operative versus conservative choice, surgical
  technique, hardware, immobilisation, physiotherapy, rehabilitation. Naming the specialty that
  should review is in scope; naming what that specialty should then do is not.
"""

POLICY_REPORT = """## REPORT POLICY — output format

### Sections
Exactly these, in this order: COMPARISON, TECHNIQUE, FINDINGS, IMPRESSION. Each header uppercase,
on its own line, terminated by a colon; content begins on the next line; one blank line between
sections. Never place content on the header line, never use markdown, never add or omit a
section. One-line sections keep the same layout:

TECHNIQUE:
Non-contrast CT of the lumbar spine.

FINDINGS:
...

### COMPARISON
Always present, first. Reflect whether the reading involved comparison, judged from the dictation
as a whole — not merely whether a prior is named at the top:
1. the dictation identifies a prior → carry it as given, with its date where stated
2. no prior named and no comparison-dependent language in the findings → "No prior imaging
   available for comparison."
3. no prior named but the findings use comparison-dependent language — new, stable, improved,
   progressed, decreased, unchanged, resolved → acknowledge generically, "Comparison made to
   previous imaging.", never inventing a scan type or a date

Any lesion under surveillance carries its current measurement and the prior measurement with the
prior's date.

### TECHNIQUE
Strictly protocol description. Never carries assessment disclosures or limitation commentary.
"""

# Machine-readable twin of the "Banned constructions" prose above. The gate and
# the prompt must never drift: this tuple is the single source of truth and the
# prose is its description. Context-sensitive entries (cannot_be_excluded,
# stable_without_numbers) are matched here and refined in report_checks.py.
BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cannot_be_excluded", re.compile(r"cannot be excluded", re.I)),
    ("bare_clinical_correlation", re.compile(r"clinical correlation (?:is )?(?:recommended|advised|suggested)", re.I)),
    ("no_significant_abnormality", re.compile(r"no significant abnormalit", re.I)),
    ("management_trespass", re.compile(
        r"\b(?:physiotherapy|rehabilitation|immobilisation|analgesia|"
        r"conservative management|operative management|surgical technique|"
        r"commence|prescribe|dosing)\b", re.I)),
)

# Confidence terms from the lexicon, used to decide whether a hedge is calibrated.
LEXICON_TERMS: tuple[str, ...] = (
    "diagnostic of", "consistent with", "probable", "likely represents",
    "possible", "may represent", "unlikely",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3_policy.py backend/tests/test_report_v3.py
git commit -m "feat(v3): global policy layer - register, uncertainty lexicon, banned constructions"
```

---

## Task 2: Section splitter

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py`
- Test: `backend/tests/test_report_checks.py`

- [ ] **Step 1: Write the failing test**

```python
"""Version-agnostic report defect checks."""
from __future__ import annotations

from rapid_reports_ai.scripts.sheet_budget import report_checks as rc

REPORT = """COMPARISON:
CT abdomen 12/02/2026.

TECHNIQUE:
CT thorax, abdomen and pelvis, portal venous phase.

FINDINGS:
The left adrenal shows nodular thickening measuring 24 mm.
The liver is unremarkable.

IMPRESSION:
Left adrenal nodule; endocrine review recommended.
"""


def test_sections_splits_on_uppercase_colon_headers():
    s = rc.sections(REPORT)
    assert set(s) == {"COMPARISON", "TECHNIQUE", "FINDINGS", "IMPRESSION"}
    assert s["TECHNIQUE"] == "CT thorax, abdomen and pelvis, portal venous phase."
    assert "nodular thickening" in s["FINDINGS"]
    assert "endocrine review" in s["IMPRESSION"]


def test_sections_ignores_uppercase_words_inside_prose():
    s = rc.sections("FINDINGS:\nThe CT shows no MRI correlate.\n")
    assert set(s) == {"FINDINGS"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: FAIL with `ImportError: cannot import name 'report_checks'`

- [ ] **Step 3: Write the implementation**

```python
"""Deterministic report defect checks, independent of sheet version.

These run on a report alone and work on v1, v2 and v3 output identically. They
exist because rubric v2.2 scored 24/24 dimensions at 5.00 on six reports that a
manual read found four real defects in (ledger L-30), and because a hand-written
contradiction pair list only finds modes someone already thought of (L-28).

Screen, not gate: a false positive costs a glance, a false negative costs a
signed report. Never optimise a model against these scores (L-14).
"""
from __future__ import annotations

import re

from ...report_v3_policy import BANNED_PATTERNS, LEXICON_TERMS

# A header is uppercase, colon-terminated, and alone on its line. That is the
# format contract, so anything else is prose and must not split the report.
_HEADER = re.compile(r"^([A-Z][A-Z ]{2,}):[ \t]*$", re.M)


def sections(report: str) -> dict[str, str]:
    """Map header name -> section body."""
    marks = [(m.group(1).strip(), m.start(), m.end()) for m in _HEADER.finditer(report)]
    out: dict[str, str] = {}
    for i, (name, _start, end) in enumerate(marks):
        stop = marks[i + 1][1] if i + 1 < len(marks) else len(report)
        out[name] = report[end:stop].strip()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py backend/tests/test_report_checks.py
git commit -m "feat(v3): section splitter for report checks"
```

---

## Task 3: Banned-construction check

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py`
- Test: `backend/tests/test_report_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_checks.py`:

```python
def test_bare_cannot_be_excluded_flags_but_calibrated_one_does_not():
    bad = "FINDINGS:\nSubtle ischaemia cannot be excluded.\n"
    assert "cannot_be_excluded" in {n for n, _ in rc.check_banned(bad)}

    good = ("FINDINGS:\nEarly ischaemia is possible and cannot be excluded; "
            "MRI DWI would resolve this.\n")
    assert "cannot_be_excluded" not in {n for n, _ in rc.check_banned(good)}


def test_management_trespass_and_bare_correlation_flag():
    r = ("IMPRESSION:\nLikely represents degenerative change. "
         "Physiotherapy recommended. Clinical correlation is advised.\n")
    names = {n for n, _ in rc.check_banned(r)}
    assert "management_trespass" in names
    assert "bare_clinical_correlation" in names


def test_stable_without_numbers_flags_and_with_numbers_does_not():
    bad = "FINDINGS:\nThe right upper lobe nodule is stable.\n"
    assert rc.check_stable_without_numbers(bad)

    good = ("FINDINGS:\nThe right upper lobe nodule is stable at 6 mm, "
            "unchanged from 6 mm on 12/02/2026.\n")
    assert not rc.check_stable_without_numbers(good)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'check_banned'`

- [ ] **Step 3: Write the implementation**

Append to `report_checks.py`:

```python
_MEASURE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mm|cm|ml|%)\b", re.I)
_RESOLUTION = re.compile(
    r"\b(?:would resolve|recommend|advised|further|MRI|CT|ultrasound|"
    r"biopsy|follow[- ]up|interval|correlat)\w*", re.I)


def _sentence_at(text: str, pos: int) -> str:
    start = text.rfind(".", 0, pos) + 1
    stop = text.find(".", pos)
    return text[start: len(text) if stop < 0 else stop].strip()


def check_banned(report: str) -> list[tuple[str, str]]:
    """Return (check_name, offending_sentence) for each banned construction.

    `cannot be excluded` is context-sensitive: it is legitimate when the same
    sentence carries a confidence term from the lexicon AND names a resolution
    path. Everything else in BANNED_PATTERNS is unconditional.
    """
    hits: list[tuple[str, str]] = []
    for name, rx in BANNED_PATTERNS:
        for m in rx.finditer(report):
            sentence = _sentence_at(report, m.start())
            if name == "cannot_be_excluded":
                calibrated = any(t in sentence.lower() for t in LEXICON_TERMS)
                if calibrated and _RESOLUTION.search(sentence):
                    continue
            hits.append((name, sentence[:120]))
    return hits


def check_stable_without_numbers(report: str) -> list[str]:
    """`stable` on a measurable lesion needs both values and the prior's date."""
    out = []
    for m in re.finditer(r"\bstable\b", report, re.I):
        sentence = _sentence_at(report, m.start())
        if not _MEASURE.search(sentence):
            out.append(sentence[:120])
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py backend/tests/test_report_checks.py
git commit -m "feat(v3): banned-construction and stable-without-numbers checks"
```

---

## Task 4: Impression-vs-findings closure checks

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py`
- Test: `backend/tests/test_report_checks.py`

These catch two of L-30's four missed defects: a measurement appearing in the impression that the findings never stated, and a laterality in the impression absent from the body.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_checks.py`:

```python
def test_impression_measurement_absent_from_findings_flags():
    bad = ("FINDINGS:\nThe nodule is present in the right upper lobe.\n\n"
           "IMPRESSION:\nRight upper lobe nodule measuring 8 mm.\n")
    assert rc.check_impression_numbers(bad) == ["8mm"]

    good = ("FINDINGS:\nAn 8 mm nodule in the right upper lobe.\n\n"
            "IMPRESSION:\nRight upper lobe nodule measuring 8 mm.\n")
    assert rc.check_impression_numbers(good) == []


def test_impression_laterality_absent_from_findings_flags():
    bad = ("FINDINGS:\nThe adrenal shows nodular thickening.\n\n"
           "IMPRESSION:\nLeft adrenal nodule.\n")
    assert rc.check_impression_laterality(bad) == ["left"]

    good = ("FINDINGS:\nThe left adrenal shows nodular thickening.\n\n"
            "IMPRESSION:\nLeft adrenal nodule.\n")
    assert rc.check_impression_laterality(good) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'check_impression_numbers'`

- [ ] **Step 3: Write the implementation**

Append to `report_checks.py`:

```python
_LATERALITY = re.compile(r"\b(left|right)\b", re.I)


def _measures(text: str) -> set[str]:
    return {m.group(0).lower().replace(" ", "") for m in _MEASURE.finditer(text)}


def check_impression_numbers(report: str) -> list[str]:
    """Every measurement in IMPRESSION must already appear in FINDINGS."""
    s = sections(report)
    return sorted(_measures(s.get("IMPRESSION", "")) - _measures(s.get("FINDINGS", "")))


def check_impression_laterality(report: str) -> list[str]:
    """A laterality in IMPRESSION that FINDINGS never states."""
    s = sections(report)
    body = {m.group(1).lower() for m in _LATERALITY.finditer(s.get("FINDINGS", ""))}
    imp = {m.group(1).lower() for m in _LATERALITY.finditer(s.get("IMPRESSION", ""))}
    return sorted(imp - body)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py backend/tests/test_report_checks.py
git commit -m "feat(v3): impression-to-findings closure checks for numbers and laterality"
```

---

## Task 5: COMPARISON check

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py`
- Test: `backend/tests/test_report_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_checks.py`:

```python
def test_comparison_missing_or_contradicted_flags():
    missing = "FINDINGS:\nNormal study.\n\nIMPRESSION:\nNormal.\n"
    assert "comparison_absent" in rc.check_comparison(missing)

    contradicted = ("COMPARISON:\nNo prior imaging available for comparison.\n\n"
                    "FINDINGS:\nThe nodule is unchanged.\n")
    assert "comparative_language_without_prior" in rc.check_comparison(contradicted)

    ok = ("COMPARISON:\nCT abdomen 12/02/2026.\n\n"
          "FINDINGS:\nThe nodule is unchanged.\n")
    assert rc.check_comparison(ok) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'check_comparison'`

- [ ] **Step 3: Write the implementation**

Append to `report_checks.py`:

```python
_COMPARATIVE = re.compile(
    r"\b(?:new|stable|improved|progressed|decreased|unchanged|resolved|interval)\b", re.I)
_NO_PRIOR = re.compile(r"no prior|none available|not available", re.I)


def check_comparison(report: str) -> list[str]:
    """COMPARISON must exist and must not contradict the body's own language."""
    s = sections(report)
    comp = s.get("COMPARISON", "")
    if not comp.strip():
        return ["comparison_absent"]
    if _NO_PRIOR.search(comp) and _COMPARATIVE.search(s.get("FINDINGS", "")):
        return ["comparative_language_without_prior"]
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py backend/tests/test_report_checks.py
git commit -m "feat(v3): COMPARISON presence and consistency check"
```

---

## Task 6: Aggregator and CLI

**Files:**
- Modify: `backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py`
- Test: `backend/tests/test_report_checks.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_checks.py`:

```python
def test_run_report_checks_aggregates_and_passes_clean_report():
    clean = ("COMPARISON:\nNo prior imaging available for comparison.\n\n"
             "TECHNIQUE:\nCT head without contrast.\n\n"
             "FINDINGS:\nNo intracranial haemorrhage. The ventricles are normal.\n\n"
             "IMPRESSION:\nNo acute intracranial abnormality.\n")
    out = rc.run_report_checks(clean)
    assert out["passed"] is True
    assert out["failures"] == []

    dirty = clean.replace("No acute intracranial abnormality.",
                          "No significant abnormality. Physiotherapy recommended.")
    out = rc.run_report_checks(dirty)
    assert out["passed"] is False
    assert "banned_construction" in out["failures"]
    assert out["detail"]["banned_construction"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'run_report_checks'`

- [ ] **Step 3: Write the implementation**

Append to `report_checks.py`:

```python
def run_report_checks(report: str) -> dict:
    """Return {passed, failures, detail}. Failures are check names."""
    results = {
        "banned_construction": check_banned(report),
        "stable_without_numbers": check_stable_without_numbers(report),
        "impression_number_not_in_findings": check_impression_numbers(report),
        "impression_laterality_not_in_findings": check_impression_laterality(report),
        "comparison": check_comparison(report),
    }
    failures = [name for name, hits in results.items() if hits]
    return {
        "passed": not failures,
        "failures": failures,
        "detail": {name: hits for name, hits in results.items() if hits},
    }


def main() -> None:
    """Run the checklist over every report in a runs.json produced by a harness.

    Usage: python -m rapid_reports_ai.scripts.sheet_budget.report_checks <path>
    """
    import json
    import sys

    path = sys.argv[1]
    runs = json.loads(open(path).read())
    rows = runs if isinstance(runs, list) else runs.get("runs", [])
    total = flagged = 0
    for row in rows:
        report = row.get("report") or ""
        if not report:
            continue
        total += 1
        out = run_report_checks(report)
        if not out["passed"]:
            flagged += 1
            print(f"{row.get('case', '?')}: {', '.join(out['failures'])}")
            for name, hits in out["detail"].items():
                for hit in hits[:3]:
                    print(f"    {name}: {hit}")
    print(f"\n{flagged}/{total} reports flagged")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_checks.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/report_checks.py backend/tests/test_report_checks.py
git commit -m "feat(v3): report-checks aggregator and corpus CLI"
```

---

## Task 7: Calibrate the instrument against the existing corpus

The checks are only useful if their false-positive rate is known. This task produces a number, not code.

**Files:**
- Create: `backend/test_output/CHECKS_CALIBRATION.md` (gitignored output; paste the summary into the ledger)

- [ ] **Step 1: Run the checklist over the encoding A/B corpus**

```bash
cd backend
poetry run python -m rapid_reports_ai.scripts.sheet_budget.report_checks \
  test_output/ENCODING_AB_20260822T012941/runs.json
```

Expected: a flagged/total line plus per-case detail. L-30 recorded four real defects across those six reports — a silently dropped finding, a must-appear violation, a "renal cysts" overcall, and stripped "not fully characterised" qualifiers.

- [ ] **Step 2: Run it over the v2 corpus**

```bash
poetry run python -m rapid_reports_ai.scripts.sheet_budget.report_checks \
  test_output/V2_FULL/runs.json
```

- [ ] **Step 3: Hand-adjudicate every flag**

For each flag, record in `test_output/CHECKS_CALIBRATION.md`: case, check name, the offending sentence, and **true positive or false positive**. Do not tune a check before its rate is written down — L-30's method note, "write predictions down before the run".

- [ ] **Step 4: Tune only checks whose false-positive rate exceeds 30%**

If `management_trespass` fires on legitimate referral language, narrow the pattern in `report_v3_policy.BANNED_PATTERNS` — never in `report_checks.py`, which must stay a consumer of the single source of truth. Re-run Steps 1–2 after any change.

- [ ] **Step 5: Commit the calibration note**

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): L-33 deterministic report checks, calibration on 23 reports"
```

Append to `docs/model-migration/parameter-ledger.md` as **L-33**, recording: number of reports scanned, flags raised, true/false positive split per check, and which of L-30's four manual-read defects the checklist caught unaided.

---

## Task 8: The three-arm policy experiment — DECISION GATE

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/policy_ab.py`

**This task is a gate, not a step.** Its result decides whether Tasks 9–15 happen at all.

### What it settles

A sheet and the generator that consumes it are a matched pair — a sheet is only meaningful to a generator that knows its field names, so the sheet grammar cannot be A/B'd on its own. What *can* be isolated is the policy layer, precisely because `POLICY_CORE` names no sheet fields. Three arms:

| arm | composition | what it is |
|---|---|---|
| **A** | v1 sheet + v1 generator + full legacy stack | production exactly as shipped — the true baseline |
| **B** | v2 sheet + `GENERATOR_V2`, bare | reproduces the existing `V2_FULL` artifacts |
| **C** | v2 sheet + `GENERATOR_V2` + `POLICY_CORE` | **v2 as it was actually intended** — has never been run |

- **C vs B** answers the question that prompted this plan: did v2 lose something real by dropping the policy stack, or was the stack dead weight?
- **C vs A** is the first fair comparison of the two pipelines, with policy held constant.

`POLICY_CORE` only — not `POLICY_REPORT`. `GENERATOR_V2` §0 already owns section format, so adding `POLICY_REPORT` would double-state it. `POLICY_CORE` carries the register, uncertainty lexicon and banned constructions, which v2 has **no** equivalent of — and which are exactly what L-30's manual-read defects were about (stripped qualifiers, characterisation overcall).

Sheets are generated **once per case and reused across arms**, so sheet stochasticity cannot confound the generator comparison. This is L-30's method, which caught what a naive design would have missed.

- [ ] **Step 1: Write the experiment harness**

```python
"""Three-arm policy experiment. See plan Task 8.

Isolates the policy layer, which is the only separable variable: a sheet and
its generator are a matched pair, but POLICY_CORE names no sheet fields.

    poetry run python -m rapid_reports_ai.scripts.sheet_budget.policy_ab \\
        --reps 3 --output-dir test_output/POLICY_AB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from rapid_reports_ai.quick_report_analyser import (  # noqa: E402
    generate_ephemeral_skill_sheet,
)
from rapid_reports_ai.report_v2 import (  # noqa: E402
    GENERATOR_V2, V2_MODEL, generate_sheet_v2,
)
from rapid_reports_ai.report_v3_policy import POLICY_CORE  # noqa: E402
from rapid_reports_ai.template_manager import TemplateManager  # noqa: E402
from rapid_reports_ai.quick_report_hardening import (  # noqa: E402
    QUICK_REPORT_HARDENING_PREAMBLE,
)
from rapid_reports_ai.scripts.sheet_budget import gate  # noqa: E402
from rapid_reports_ai.scripts.sheet_budget.report_checks import (  # noqa: E402
    run_report_checks,
)

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]


async def _v2_generator(sheet: str, case: dict, *, policy: bool) -> dict:
    """Arms B and C: GENERATOR_V2, with or without POLICY_CORE prepended."""
    from rapid_reports_ai.enhancement_utils import (
        _get_api_key_for_provider, _get_model_provider, _run_agent_with_model,
    )
    system = f"{POLICY_CORE}\n\n{GENERATOR_V2}" if policy else GENERATOR_V2
    user = (f"## DECISION SHEET\n{sheet}\n\n## STUDY METADATA\n"
            f"SCAN TYPE: {case['scan_type']}\n"
            f"CLINICAL HISTORY: {case['clinical_history']}\n\n"
            f"## DICTATION\n{case['findings']}\n\nWrite the report.")
    t0 = time.time()
    result = await _run_agent_with_model(
        model_name=V2_MODEL, output_type=str,
        system_prompt=system, user_prompt=user,
        api_key=_get_api_key_for_provider(_get_model_provider(V2_MODEL)),
        use_thinking=True,
        model_settings={"temperature": 0.6, "top_p": 0.95, "max_tokens": 16384},
    )
    report = result.output if hasattr(result, "output") else str(result)
    return {"report": report, "latency_ms": int((time.time() - t0) * 1000)}


async def _v1_generator(sheet: str, case: dict) -> dict:
    """Arm A: the production composition, unchanged."""
    tm = TemplateManager()
    t0 = time.time()
    res = await tm.generate_report_from_config(
        template_config={
            "generation_mode": "skill_sheet_guided",
            "skill_sheet": QUICK_REPORT_HARDENING_PREAMBLE + sheet,
            "scan_type": case["scan_type"],
        },
        user_inputs={"FINDINGS": case["findings"],
                     "CLINICAL_HISTORY": case["clinical_history"]},
        model_override=V2_MODEL,
    )
    return {"report": res.get("report_content", "") or "",
            "latency_ms": int((time.time() - t0) * 1000)}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--cases-file",
                    default=str(BACKEND_ROOT / "test_cases/analyser_suite.json"))
    args = ap.parse_args()

    cases = json.loads(pathlib.Path(args.cases_file).read_text())
    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for case in cases:
        # One sheet per grammar per case, reused across every arm and rep.
        v1_sheet = (await generate_ephemeral_skill_sheet(
            scan_type=case["scan_type"],
            clinical_history=case["clinical_history"],
            api_key="",
        ))["skill_sheet"]
        v2_sheet = (await generate_sheet_v2(
            case["scan_type"], case["clinical_history"]))["sheet"]
        print(f"{case['name']}: v1 sheet {len(v1_sheet):,}ch  "
              f"v2 sheet {len(v2_sheet):,}ch")

        # Interleave arms so provider load drifts across all three equally.
        for rep in range(args.reps):
            for arm, coro in (
                ("A_v1_full", _v1_generator(v1_sheet, case)),
                ("B_v2_bare", _v2_generator(v2_sheet, case, policy=False)),
                ("C_v2_policy", _v2_generator(v2_sheet, case, policy=True)),
            ):
                res = await coro
                report = res["report"]
                row = {
                    "arm": arm, "case": case["name"], "rep": rep,
                    "sheet": v1_sheet if arm.startswith("A") else v2_sheet,
                    "report": report, "report_chars": len(report),
                    "generator_latency_ms": res["latency_ms"],
                    "gate": gate.run_gate(report),
                    "report_checks": run_report_checks(report),
                }
                runs.append(row)
                flags = ",".join(row["report_checks"]["failures"]) or "clean"
                print(f"  {arm:12} rep{rep} {len(report):,}ch "
                      f"{res['latency_ms']/1000:.1f}s gate="
                      f"{'pass' if row['gate']['passed'] else 'FAIL'} {flags}")
                (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke-test on one case, one rep**

```bash
cd backend
poetry run python -m rapid_reports_ai.scripts.sheet_budget.policy_ab \
  --reps 1 --output-dir test_output/POLICY_AB_SMOKE
```

Expected: two sheet lines and three arm lines. If arm A errors, the production composition is broken for `qwen3.6-27b` and that is itself the finding — stop and investigate before running the full matrix.

- [ ] **Step 3: Run the full matrix**

```bash
poetry run python -m rapid_reports_ai.scripts.sheet_budget.policy_ab \
  --reps 3 --output-dir test_output/POLICY_AB
```

5 cases × 3 arms × 3 reps = 45 generator calls plus 10 sheet calls. Serialised — concurrency at this org's Groq OTPM limit loses cells.

- [ ] **Step 4: Summarise by arm**

```bash
poetry run python -c "
import json, collections
runs = json.load(open('test_output/POLICY_AB/runs.json'))
by = collections.defaultdict(list)
for r in runs: by[r['arm']].append(r)
for arm in sorted(by):
    rs = by[arm]
    n = len(rs)
    chars = sum(r['report_chars'] for r in rs)/n
    lat = sum(r['generator_latency_ms'] for r in rs)/n/1000
    gate_ok = sum(r['gate']['passed'] for r in rs)
    clean = sum(r['report_checks']['passed'] for r in rs)
    flags = collections.Counter(
        f for r in rs for f in r['report_checks']['failures'])
    print(f'{arm:12} n={n} chars={chars:6.0f} lat={lat:5.1f}s '
          f'gate={gate_ok}/{n} clean={clean}/{n} {dict(flags)}')
"
```

- [ ] **Step 5: Score with the judge**

```bash
poetry run python -c "
import json, asyncio
from rapid_reports_ai.scripts.sheet_budget import judge
runs = json.load(open('test_output/POLICY_AB/runs.json'))
for r in runs:
    inputs = judge.format_inputs(scan_type=r.get('scan_type',''),
                                 clinical_history=r.get('clinical_history',''),
                                 findings=r.get('findings',''))
    r['judge'] = judge.score_case(inputs=inputs, skill_sheet=r['sheet'],
                                  report=r['report'])
json.dump(runs, open('test_output/POLICY_AB/runs_judged.json','w'), indent=2)
"
```

Note L-30: rubric v2.2 saturated at 5.00 across 24 dimensions on reports containing four real defects. Treat judge scores as a floor check, not a discriminator — the arm comparison rests on Step 4's deterministic flags and Step 6's manual read.

- [ ] **Step 6: Hand-adjudicate ten reports, blind to arm**

Strip the arm label, read ten reports drawn evenly across arms, and score each for: dropped dictated findings, stripped qualifiers, characterisation overcall, self-contradiction, must-appear omissions, management trespass. Record in `test_output/POLICY_AB/MANUAL.md` and only then unblind.

L-13 and L-14 both say the same thing: the judge cannot see editorial quality, and an automatable proxy encodes the wrong objective. This step is the measurement.

- [ ] **Step 7: Record and decide**

Append to the ledger as **L-34**, stating the prediction before the numbers (L-30's method note). Then apply the gate:

| outcome | decision |
|---|---|
| **C ≫ B** | The policy layer was load-bearing and v2's deficit was never about the sheet. Proceed to Tasks 9–15, but the win is policy, not grammar — say so in the ledger |
| **C ≈ B, both ≥ A** | The v2 sheet grammar carries its own weight. Proceed to Tasks 9–15 with confidence |
| **C ≈ B ≈ A** | The sheet grammar is not the lever. **Do not build v3.** Return to L-15's open question — inclusion/exclusion policy — with the radiologist |
| **A ≫ C** | v1's stack is doing something neither v2 arm reproduces. Stop and find out what before writing another prompt |

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): L-34 three-arm policy experiment - v2 as intended"
```

---

## Task 9: `report_v3.py` and the analyser prompt

> **Gated on Task 8.** Do not start until the three-arm result is recorded and Task 8 Step 7's
> decision table says proceed. If the arms come out flat, the sheet grammar is not the lever and
> everything from here is misdirected effort — go back to L-15 with the radiologist instead.

**Files:**
- Create: `backend/src/rapid_reports_ai/report_v3.py`
- Test: `backend/tests/test_report_v3.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_v3.py`:

```python
from rapid_reports_ai import report_v3 as v3


def test_analyser_v3_forbids_assertion_and_declares_the_typed_contract():
    p = v3.ANALYSER_V3
    assert "may not assert any finding" in p
    for section in ("## CASE", "## FLOW", "## LIMITS", "## OBLIGATIONS",
                    "## VERDICT", "## MEASURE"):
        assert section in p, f"missing sheet section: {section}"
    assert "QUESTION or COMPLETENESS" in p
    assert "T-NEG" in p and "T-IND" in p
    # No RECOMMEND: urgency and service depend on what was dictated, so the
    # writer decides them; the remit boundary is a standing policy rule.
    # No CARRY: a manifest of items to mention gets discharged, not distilled.
    assert "## RECOMMEND" not in p
    assert "CARRY:" not in p


def test_analyser_v3_flow_declares_topology_and_breadth_separately():
    flat = " ".join(v3.ANALYSER_V3.split())
    for token in ("TOPOLOGY:", "BREADTH:", "ORDER:", "FLAT", "COMPARTMENTS",
                  "UNITS", "FOCUSED", "BROAD"):
        assert token in flat, f"FLOW token missing: {token}"
    assert "from topology, not from habit" in flat
    assert "needs the dictation and is not yours" in flat


def test_analyser_v3_expect_governs_t_neg_and_history_is_resolved_here():
    flat = " ".join(v3.ANALYSER_V3.split())
    assert "EXPECT:" in flat
    assert "may not negate any class named in its own EXPECT" in flat
    assert "omit T-NEG" in flat
    # the conditional the generator can no longer be asked to execute
    assert "SUPPRESS-IF-HISTORY" not in v3.ANALYSER_V3


def test_analyser_v3_states_a_verdict_without_building_a_manifest():
    flat = " ".join(v3.ANALYSER_V3.split())
    assert "## VERDICT" in v3.ANALYSER_V3
    assert "CONFIRMED" in flat and "EXCLUDED" in flat and "INDETERMINATE" in flat
    assert "never what must be mentioned" in flat
    assert "would read as an inventory" in flat


def test_analyser_v3_puts_conditioning_history_in_bearing():
    """History that changes what the gate turns on qualifies the QUESTION; it
    does not become a checklist the impression discharges."""
    flat = " ".join(v3.ANALYSER_V3.split())
    assert "BEARING:" in flat
    assert "how it moves that gate or conditions the reading" in flat
    assert "a list gets filled rather than distilled" in flat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rapid_reports_ai.report_v3'`

- [ ] **Step 3: Write the implementation**

```python
"""Report pipeline v3 — policy layer, typed sheet, one generator conditional.

Parallel to production and to v2. Nothing live imports this module (guarded by
test). Design: docs/superpowers/specs/2026-08-22-skill-sheet-v3-design.md

What changed from v2, and why:
  - EXPECT governs T-NEG, so a negative the question makes likely is never
    written (L-32's root cause, removed at source rather than suppressed later)
  - SUPPRESS-IF-HISTORY is gone; the analyser holds the history and resolves it
    (one fewer generator conditional — every conditional is where reasoning-off
    breaks, L-31)
  - the sheet's only word on the impression is a one-line VERDICT; history that
    conditions the question sits in CASE/BEARING. A manifest gets discharged
    rather than distilled — v2's generator already had to say RECOMMEND is
    "not a quota to spend". The coverage CHECK survives in
    check_report_against_sheet_v3; only the slot is gone
  - no RECOMMEND: urgency and service depend on the dictation, so the writer
    decides them; the remit boundary is a standing rule in the policy layer
  - VOLUME and STRUCTURE merge into FLOW, with density derived from the volume
  - MEASURE carries thresholds, closing v2's contract hole
  - invariant policy is hoisted into report_v3_policy (spec R6)
"""
from __future__ import annotations

import re
import time
from typing import Any

from .report_v3_policy import POLICY_CORE, POLICY_REPORT

ANALYSER_V3 = """You are a senior consultant radiologist preparing a DECISION SHEET for one study.
You know the scan type and the clinical history. You have NOT seen the images and you have NOT
seen the radiologist's dictation.

Because you have not seen them, you may not assert any finding — no presence, no absence, no
normality, no stability, no measurement. What you produce instead is the set of questions this
study must answer, and for each one a resolution procedure the report writer applies once the
dictation arrives. The sheet is an internal instrument: nothing in it is report text, except the
sentence templates marked T-NEG and T-IND, which the writer emits.

The report policy above governs register, calibrated uncertainty and banned constructions. Do not
restate it. This sheet carries only what is specific to this study and this clinical question.

## What the history is for

The history is your only case-specific input and it does four jobs:

1. It sets the QUESTION — what clinical decision this imaging gates.
2. It tiers the obligations — the same negative is load-bearing on one history and hygiene on
   another. You decide which, here, once; the writer never re-derives it.
3. It resolves suppressions HERE. Disease the history already establishes must not be
   contradicted by a routine normal line. You hold the history, so you settle this now: where the
   history voids a normal line, you do not write that line. Never write a normal line together
   with a rule telling the writer to suppress it — a conditional you were able to resolve
   yourself is a conditional the writer may fail to execute.
4. It conditions the question. Some history changes what the gate turns on — a prior event the
   decision hinges on, a comorbidity that shifts urgency, a value that sits against a threshold.
   Record those in BEARING, where they qualify the question itself. Do not build a list of things
   the impression must mention: a list gets filled rather than distilled.

## Output — exactly this structure

# DECISION SHEET

## CASE
- MODALITY: <modality and technique>
- QUESTION: <primary clinical question, decomposed> => GATES: <the management decision it gates>
- BEARING: <a datum from this history> => <how it moves that gate or conditions the reading>
  (one line each, typically 0 to 4; omit the field entirely when the history conditions nothing)
- SECONDARY: <further questions, comma-separated, or "none">

## FLOW

The report's structure, computed here so the writer never re-derives it. Three declarations.

- TOPOLOGY: one of
  FLAT — a single field of assessment. The default; most studies.
  COMPARTMENTS: <name> => <its stations> ; <name> => <stations> — the study spans anatomically
    disjoint fields, each effectively its own examination.
  UNITS: GLOBAL => <observations true of the whole structure, stated once> ; PER-UNIT => <the
    criteria applied to each serial unit> — the same checklist repeats across serial units.
  Choose from topology, not from habit: COMPARTMENTS only if a clinician would treat the regions
  as separate examinations, UNITS only if the same checklist genuinely repeats per unit.
  Otherwise FLAT.

- BREADTH: FOCUSED or BROAD, derived from the imaged volume.
  FOCUSED — the volume covers one organ system; the silent-case sweep is one or two groups.
  BROAD — the volume spans several organ systems a consultant would comment on systematically
    even when unaffected; the silent-case sweep visits each in turn.
  Judge this from what the volume contains, not from the modality's reputation. Breadth sets the
  granularity of ORDER.

- ORDER: the groups the report will render, in render order, each naming its stations.
  This is the skeleton for the case where the dictation is silent throughout. A station the
  dictation makes positive breaks out into its own paragraph — that decision needs the dictation
  and is not yours.
  - COMPARTMENTS follow anatomical convention — cranio-caudal, appendicular and soft tissue last.
    Priority lives in the impression, never in block order.
  - FLAT order is question-directed: the stations the clinical question implicates lead;
    peripheral stations are terminal. Generic anatomical order only when the question gives no
    directional cue.
  - FOCUSED names one or two groups. BROAD names one group per organ system, ending with a
    terminal group for soft tissues and true incidentals.

Coverage is total: everything the scan images belongs to exactly one group. Structures running
continuously through several compartments — the vertebral column on any body protocol above all —
are their own compartment at their anatomical position, never entries in a terminal group.

- OUT: <structure> => <alternative test> (one line each; only structures the question might
  implicate). Scope OUT only what this study genuinely cannot demonstrate, never a region another
  modality would merely show better.

## LIMITS
- <what this modality cannot show that bears on the question> — <why> (one line each; these are
  facts about physics, the only assertions you are permitted)

## OBLIGATIONS

One block per station. Coverage is obligatory: every station named in FLOW/ORDER carries at least
one obligation whose T-NEG is that station's canonical normal statement. This is the systems
review, and a station without an obligation vanishes silently from the report. Add QUESTION
obligations on top. Typically 10 to 18 total.

- OB<n> | <QUESTION or COMPLETENESS> | <station>
  OBSERVES: <the specific observation this obligation rests on>
  EXPECT: <the finding classes THIS clinical question makes plausible at THIS station, or "none">
  T-NEG: "<the sentence the writer emits when the dictation is silent AND the observation was
  assessable>" (omitted entirely where the history voids it — see below)
  UNASSESSABLE-IF: <dictated finding classes that make OBSERVES unreadable> ; NOT: <near-miss
  terms that do NOT qualify> (opt — only where a real obscurant exists)
  T-IND: "<indeterminate sentence naming {obscurant}>" (required whenever UNASSESSABLE-IF present)

Rules for obligations:
- TIER is your clinical judgement from the history. QUESTION marks what the study exists to
  answer; COMPLETENESS means systematic coverage.
- OBSERVES names one observation, concretely — an interface, a margin, a lumen, a signal — so the
  writer can judge whether a dictated finding obscures it.
- EXPECT governs T-NEG. Name what this question makes likely here, not everything possible. A
  T-NEG may not negate any class named in its own EXPECT. Where the question makes a class
  plausible, negate the discriminating neighbours instead: a study asking about bowel ischaemia
  does not carry "No intramural gas" as its bowel normal, because intramural gas is what it is
  looking for. It carries the narrower negative that stays informative if the expected finding is
  present. A negative the dictation is likely to contradict is a defect the writer cannot repair.
- Where the history already voids a normal line, omit T-NEG. Emit the obligation with OBSERVES
  and, where useful, a contingent T-IND — never an assertion the history contradicts. A patient
  with known liver metastases has no "liver unremarkable" line.
- Templates are complete sentences in final report register, with {braced} blanks only where the
  filler is case data.
- Where OBSERVES depends on reading an interface, margin, line or plane, remember what routinely
  renders such reads impossible: adjacent oedema or haemorrhage, collapse or volume loss,
  artefact, overlying material. Enumerate the classes plausible for THIS study in
  UNASSESSABLE-IF. An obligation whose observation can be obscured but which carries no
  UNASSESSABLE-IF is incomplete.

## VERDICT
- <the CASE question, restated as the thing to be answered> => FORMS: CONFIRMED | EXCLUDED |
  INDETERMINATE (<which LIMIT leaves it open, and what would resolve it>)

One line, and the only thing this sheet says about the impression. It states what must be
resolved — never what must be mentioned, never how to compose it. The impression is a distillation
of the findings, not a set of slots: a manifest of items would be discharged one by one and the
result would read as an inventory. What the history contributes is already in CASE/BEARING, where
it qualifies the question rather than sitting on a list.

## MEASURE (opt)
- <finding type>: <dimensions, units, when required> (only where the question turns on it)
  THRESHOLD: <value> => <what crossing it means for management> (opt — this sheet is the only
  source of thresholds the writer may cite; a threshold not stated here may not be used)
  PRIOR: <value> (<date>) (opt — only where the history states a prior measurement)

There is no RECOMMEND section. Whether an action is warranted, which service, and how urgently all
depend on what was dictated, so the writer decides them with the findings in hand. The boundary of
radiological remit is a standing rule in the policy layer, not a per-case list.

Before emitting, check: every FLOW/ORDER station has an obligation; no T-NEG negates a class named
in its own EXPECT; no T-NEG asserts what the history contradicts; every UNASSESSABLE-IF has a
T-IND. Keep the sheet under about 160 lines. Precision within each obligation beats prose around
it — never buy brevity by dropping a station's coverage."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3.py backend/tests/test_report_v3.py
git commit -m "feat(v3): analyser prompt - FLOW, EXPECT-governed negatives, impression obligations"
```

---

## Task 10: The generator prompt

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_v3.py`
- Test: `backend/tests/test_report_v3.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_v3.py`:

```python
def test_generator_v3_authority_rules_are_present_and_absolute():
    flat = " ".join(v3.GENERATOR_V3.split())
    assert "Qualifiers are content" in flat
    assert "is NOT completed" in flat                    # syntactic truncation
    assert "Never silently harmonise" in flat            # laterality conflict
    assert "never delete a dictated finding" in flat
    assert "not in the sheet's MEASURE" in flat          # threshold authority


def test_generator_v3_has_three_branches_and_one_real_conditional():
    flat = " ".join(v3.GENERATOR_V3.split())
    assert "DICTATED" in flat and "UNASSESSABLE" in flat and "SILENT" in flat
    assert "HISTORY-SUPPRESSED" not in v3.GENERATOR_V3   # resolved in the sheet now
    assert "exactly one branch fires" in flat
    assert "you do not reconstruct one" in flat          # no T-NEG means silence


def test_generator_v3_impression_fixes_coverage_and_frees_composition():
    flat = " ".join(v3.GENERATOR_V3.split())
    assert "The sheet fixes what must be resolved; composition is yours" in flat
    assert "not a list to acknowledge" in flat
    assert "Integrated prose" in flat and "not a numbered list" in flat
    assert "an argument, not an inventory" in flat
    assert "Your domain ends at understanding" in flat


def test_prompt_budget_holds():
    """v3 buys a policy layer, not instruction bulk. v1 was 42k + 33k."""
    assert len(v3.ANALYSER_V3) < 13000, f"analyser v3 at {len(v3.ANALYSER_V3)}"
    assert len(v3.GENERATOR_V3) < 11000, f"generator v3 at {len(v3.GENERATOR_V3)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `AttributeError: module 'rapid_reports_ai.report_v3' has no attribute 'GENERATOR_V3'`

- [ ] **Step 3: Write the implementation**

Append to `report_v3.py`:

```python
GENERATOR_V3 = """You are a senior consultant radiologist writing the final report for one study.
You have the radiologist's dictation and a DECISION SHEET prepared before the dictation existed.
The dictation is evidence; the sheet is procedure. You are the only component that sees both.

Sheet-internal notation — OB numbers, tier names, field names, braces — never appears in the
report.

## 1 · Authority

The dictation is semantically untouchable: every value, laterality, qualifier, presence and
absence it states is reported exactly as stated. You may harmonise register. You may not alter,
grade, or extend content.

- Qualifiers are content. "Not fully characterised", "probable", "small volume" survive into the
  report unchanged. Stripping a qualifier alters the finding.
- No graded classification — Grade I to III, Weber, any named tier — unless the dictation states
  it or the sheet's MEASURE maps dictated features to it. Otherwise report the dictated feature.
- No reference value or threshold that is not in the sheet's MEASURE.
- A dictated statement that terminates mid-clause — syntactically incomplete, stopping before its
  object or qualifier — is NOT completed. Do not emit the broken fragment and do not guess the
  missing element: recast the sentence so it states only what was dictated, and add at the end of
  FINDINGS: "The dictated description of {finding} is incomplete; {missing element} is not
  stated." A fabricated completion is a fabricated finding — location above all. This fires on
  syntactic truncation only; terse dictation that merely omits detail is not truncation.
- A dictated finding matching no obligation or station is still reported in FINDINGS at its
  natural anatomical position — inside the nearest group, or as its own paragraph when none fits.
  The sheet scopes expectations, never dictated content: a mis-scoped sheet can never delete a
  dictated finding.
- Where dictated laterality or site conflicts with the study metadata, preserve the dictated
  content unchanged and add: "The dictation states {dictated}; the study is registered as
  {metadata}. Reported as dictated; correlation advised." Never silently harmonise either way.

## 2 · Resolving each obligation

Take the sheet's obligations in FLOW order. For each, exactly one branch fires:

| branch | condition | emit |
|---|---|---|
| DICTATED | the dictation addresses OBSERVES | the dictated content, section 1 governing |
| UNASSESSABLE | the dictation is silent on OBSERVES AND a dictated finding matches an UNASSESSABLE-IF class | T-IND, {obscurant} filled from that finding |
| SILENT | neither of the above | T-NEG exactly, blanks filled |

Matching for UNASSESSABLE is strict: the dictated finding must name or be equivalent to the listed
class. Any term on the NOT list, and any related-but-different structure, does not fire it.

An obligation carrying no T-NEG resolves silently on the SILENT branch. The analyser omitted it
deliberately because the history voids it, and you do not reconstruct one. Never emit a T-NEG
whose branch did not fire, never emit both a positive and its unfired T-NEG, and an unfilled
{brace} anywhere is an error.

## 3 · FINDINGS

Render the sheet's FLOW. The groups and their order are computed there; you never re-derive them.

- The index paragraph opens the section: the principal dictated abnormality with its direct
  consequences — the findings sharing one pathological story, even across regions. A report never
  opens on a peripheral normal.
- Then the sheet's groups in their declared order. A group whose stations all resolve silently
  renders as one consolidated paragraph. A station the dictation makes positive breaks out into
  its own paragraph — that is the one grouping decision the sheet could not make, because it needs
  the dictation.
- COMPARTMENTS render as named blocks: the compartment name on its own line followed by a colon,
  content beneath, one blank line between blocks. Within a block the dominant dictated finding
  leads and the remaining stations follow as the systems review.
- UNITS render the GLOBAL observations as one opening paragraph, stated once and never repeated
  per unit; then one line per unit the dictation addresses, in anatomical order; then units the
  dictation is silent on consolidated into a single remainder sentence. Never enumerate normal
  units individually.

Every station in FLOW/ORDER appears. The systems review is visibly complete: a station resolving
entirely to normals still appears, consolidated with its neighbours rather than dropped. Never one
paragraph per station, never one solid block. Every paragraph reads correctly in isolation.

## 4 · IMPRESSION

Your reading of what the findings mean, distilled for the clinician who asked — written the way a
consultant hands over: fifteen seconds of a colleague's attention, and nothing that does not carry
weight. Integrated prose, not a numbered list.

The sheet fixes what must be resolved; composition is yours.

Required: the sheet's VERDICT is answered explicitly in one of its FORMS. Where CASE names BEARING
items, your answer engages them — they are what the gate turns on, not a list to acknowledge, and
a sentence that merely notes one has done no work. An INDETERMINATE verdict names why — the LIMIT
that leaves it open — and what would resolve it.

Free: everything else. Order, sentence count, grouping, emphasis, and what earns a place are
yours. Compose by answering, in your reasoning, the questions a consultant answers before
speaking, then write only the answers that matter for this case: what do we now know that we did
not; what is the best formulation, at what confidence; do the findings account for the
presentation — "no cause identified" is a complete answer, not a failure; is anything here
unexpected but consequential; does the imaging itself warrant a next step, and how urgently.

Open at the diagnosis. The first sentence is the unifying diagnostic statement — the conclusion
this study establishes, never a recap of findings. FINDINGS owns descriptive detail: measurements,
locations and specifics are not restated here, and a value or site appears only when it is itself
a determinant the next decision turns on. A sentence that merely re-lists what FINDINGS states is
deleted, not compressed.

The impression is an argument, not an inventory. Each fact admitted appears exactly once, in the
sentence where it earns its conclusion — evidence stands beside what it proves, never in an
opening list a later sentence repeats. If the diagnostic opening names a finding, no later
sentence reintroduces it.

Most consequential answer first; findings sharing an aetiology share a sentence; recommendations
reel into one or two sentences grouped by destination and urgency, joined to their findings as
semicolon clauses. Where the imaging warrants an action, name it with the dictation in hand — the
investigation that would resolve what remains open, the specialty that should review, and how
urgently. Recommend nothing by default: a complete answer with no recommendation is a strong
impression, and only the findings earn one. Your domain
ends at understanding: what the team does about that understanding — treatment, procedures,
monitoring — is theirs, never yours. Every fact traces to the dictation or a resolved obligation;
new facts are fabrication. Sheet notation and thresholds are never cited.

## 5 · Before output

Headers exactly as the policy specifies, uppercase and colon-terminated, content on the next line
· every station in FLOW/ORDER present in FINDINGS · every emitted template's branch actually fired
· no braces, no tags, no sheet notation · dictated values, laterality and qualifiers verbatim ·
the VERDICT answered in one of its forms · every BEARING item engaged where one is named · every
impression sentence carries an answer the referrer needs, or is deleted · no fact stated twice in
the impression.

Output the report only."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3.py backend/tests/test_report_v3.py
git commit -m "feat(v3): generator prompt - three branches, fixed coverage and free composition"
```

---

## Task 11: `validate_sheet_v3`

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_v3.py`
- Test: `backend/tests/test_report_v3.py`

Closes v2's blind spot: `validate_sheet_v2` never checked for `## STRUCTURE`, and it was absent from 17 of 17 sheets.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_v3.py`:

```python
GOOD_SHEET = """# DECISION SHEET

## CASE
- MODALITY: CT head, non-contrast
- QUESTION: Acute intracranial haemorrhage => GATES: thrombolysis
- BEARING: anticoagulated on warfarin => raises the haemorrhage prior and gates reversal
- SECONDARY: none

## FLOW
- TOPOLOGY: FLAT
- BREADTH: FOCUSED
- ORDER: brain parenchyma (cortex, deep grey, white matter) ; ventricles and cisterns ;
  terminal: skull and scalp soft tissues
- OUT: cervical vessels => CT angiography

## LIMITS
- Hyperacute ischaemia under six hours — frequently invisible without diffusion imaging

## OBLIGATIONS
- OB1 | QUESTION | brain parenchyma
  OBSERVES: parenchymal attenuation and grey-white differentiation
  EXPECT: intraparenchymal haemorrhage, established infarct
  T-NEG: "Grey-white differentiation is preserved throughout."
  UNASSESSABLE-IF: extensive motion artefact ; NOT: mild beam hardening
  T-IND: "Parenchymal assessment is limited by {obscurant}."
- OB2 | COMPLETENESS | ventricles and cisterns
  OBSERVES: ventricular calibre and basal cistern patency
  EXPECT: none
  T-NEG: "The ventricles and basal cisterns are normal in calibre."
- OB3 | COMPLETENESS | terminal: skull and scalp soft tissues
  OBSERVES: cortical continuity and scalp soft tissue contour
  EXPECT: none
  T-NEG: "The skull vault and scalp soft tissues are intact."

## VERDICT
- Acute intracranial haemorrhage => FORMS: CONFIRMED | EXCLUDED | INDETERMINATE (hyperacute ischaemia limit; MRI DWI resolves)
"""


def test_validator_accepts_a_well_formed_sheet():
    v = v3.validate_sheet_v3(GOOD_SHEET)
    assert v["ok"], v
    assert v["obligations"] == 3
    assert v["question_tier"] == 1
    assert v["expect_fields"] == 3
    assert v["verdict"] == 1
    assert v["bearing"] == 1
    assert v["flow_ok"] is True


def test_validator_accepts_a_sheet_with_no_bearing_lines():
    """Most histories condition nothing. BEARING is counted, never required —
    a minimum would make the analyser manufacture entries."""
    no_bearing = "\n".join(
        l for l in GOOD_SHEET.splitlines() if not l.startswith("- BEARING:"))
    v = v3.validate_sheet_v3(no_bearing)
    assert v["ok"], v
    assert v["bearing"] == 0


def test_validator_rejects_a_missing_flow_block():
    bad = GOOD_SHEET.replace("- TOPOLOGY: FLAT", "")
    v = v3.validate_sheet_v3(bad)
    assert not v["ok"]
    assert v["flow_ok"] is False


def test_validator_rejects_a_t_neg_that_negates_its_own_expect():
    bad = GOOD_SHEET.replace(
        'T-NEG: "Grey-white differentiation is preserved throughout."',
        'T-NEG: "No intraparenchymal haemorrhage is identified."')
    v = v3.validate_sheet_v3(bad)
    assert not v["ok"]
    assert any("intraparenchymal haemorrhage" in x for x in v["expect_violations"])


def test_validator_rejects_obligations_missing_expect():
    bad = GOOD_SHEET.replace("  EXPECT: none\n", "", 1)
    v = v3.validate_sheet_v3(bad)
    assert not v["ok"]
    assert v["expect_fields"] < v["obligations"]


def test_validator_flags_emittable_prose_outside_templates():
    bad = GOOD_SHEET + '\n- NOTE: "The brain parenchyma is entirely normal in this patient."\n'
    assert v3.validate_sheet_v3(bad)["stray_prose"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'validate_sheet_v3'`

- [ ] **Step 3: Write the implementation**

Append to `report_v3.py`:

```python
_OB = re.compile(r"^-\s*OB\d+\s*\|\s*(QUESTION|COMPLETENESS)\s*\|\s*(.+)$", re.M)
_TNEG = re.compile(r'^\s*T-NEG:\s*"(.*)"\s*$', re.M)
_TIND = re.compile(r"^\s*T-IND:", re.M)
_UNASS = re.compile(r"^\s*UNASSESSABLE-IF:", re.M)
_EXPECT = re.compile(r"^\s*EXPECT:\s*(.+)$", re.M)
_BEARING = re.compile(r"^-\s*BEARING:\s*(.+)$", re.M)
_FORMS = re.compile(r"^-\s*(.+?)\s*=>\s*FORMS:\s*(.+)$", re.M)
_QUOTED = re.compile(r'"[^"]{25,}"')
_STOPWORDS = {"none", "and", "the", "or", "with", "without"}


def _ob_blocks(sheet: str) -> list[str]:
    """Split the sheet into per-obligation blocks."""
    parts = re.split(r"(?=^-\s*OB\d+\s*\|)", sheet, flags=re.M)
    return [p for p in parts if _OB.match(p)]


def _expect_terms(block: str) -> list[str]:
    m = _EXPECT.search(block)
    if not m:
        return []
    out = []
    for raw in re.split(r"[;,]", m.group(1)):
        term = raw.strip().lower().split(" (")[0].strip()
        if len(term) > 3 and term not in _STOPWORDS:
            out.append(term)
    return out


def _expect_violations(sheet: str) -> list[str]:
    """A T-NEG may not negate a class named in its own EXPECT.

    This is L-32's root cause checked mechanically: the reasoning-on analyser
    wrote "No pneumoperitoneum", leaving room for the mural gas its question
    made likely; the reasoning-off analyser wrote "No pneumatosis" blind to the
    collision. Countable, so it no longer needs reasoning to get right.
    """
    out = []
    for block in _ob_blocks(sheet):
        tneg = _TNEG.search(block)
        if not tneg:
            continue
        negative = tneg.group(1).lower()
        for term in _expect_terms(block):
            if term in negative:
                out.append(f"T-NEG negates its own EXPECT class: {term!r}")
    return out


def _flow_ok(sheet: str) -> bool:
    if "## FLOW" not in sheet:
        return False
    has_topology = re.search(r"^-\s*TOPOLOGY:\s*(FLAT|COMPARTMENTS|UNITS)", sheet, re.M)
    has_breadth = re.search(r"^-\s*BREADTH:\s*(FOCUSED|BROAD)\s*$", sheet, re.M)
    has_order = re.search(r"^-\s*ORDER:\s*\S", sheet, re.M)
    return bool(has_topology and has_breadth and has_order)


def flow_stations(sheet: str) -> list[str]:
    """The stations named in FLOW/ORDER, in render order."""
    m = re.search(r"^-\s*ORDER:\s*(.+?)(?=^-\s*OUT:|^##\s)", sheet, re.M | re.S)
    if not m:
        return []
    body = re.sub(r"\s+", " ", m.group(1))
    out = []
    for group in body.split(";"):
        name = group.split("(")[0].strip().rstrip(",").strip()
        if name:
            out.append(name)
    return out


def validate_sheet_v3(sheet: str) -> dict[str, Any]:
    """Structural checks on a v3 sheet. All countable; no model in the loop."""
    blocks = _ob_blocks(sheet)
    tiers = [_OB.match(b).group(1) for b in blocks]
    n_unass, n_ind = len(_UNASS.findall(sheet)), len(_TIND.findall(sheet))
    expect_fields = sum(1 for b in blocks if _EXPECT.search(b))
    violations = _expect_violations(sheet)

    # Emittable prose may only sit on a template line (spec R5). Anything else
    # quoted and sentence-length is prose the generator can imitate verbatim.
    stray = [
        m.group(0)[:70] for m in _QUOTED.finditer(sheet)
        if not re.match(r"^\s*T-(NEG|IND):",
                        sheet[sheet.rfind("\n", 0, m.start()) + 1: m.start()])
    ]

    flow_ok = _flow_ok(sheet)
    return {
        "obligations": len(blocks),
        "question_tier": sum(1 for t in tiers if t == "QUESTION"),
        "expect_fields": expect_fields,
        "expect_violations": violations,
        "t_neg": len(_TNEG.findall(sheet)),
        "unassessable": n_unass,
        "t_ind": n_ind,
        "ind_paired": n_ind >= n_unass,
        # BEARING is optional — many histories condition nothing. Counted, never
        # required: a minimum would push the analyser to manufacture entries,
        # which is the manifest failure the design removes.
        "bearing": len(_BEARING.findall(sheet)),
        "verdict": len(_FORMS.findall(sheet)),
        "flow_ok": flow_ok,
        "flow_stations": flow_stations(sheet),
        "stray_prose": stray,
        "history_suppress_leaked": "SUPPRESS-IF-HISTORY" in sheet,
        "ok": (
            3 <= len(blocks) <= 20
            and any(t == "QUESTION" for t in tiers)
            and expect_fields == len(blocks)
            and not violations
            and n_ind >= n_unass
            and flow_ok
            and len(_FORMS.findall(sheet)) >= 1
            and not stray
            and "SUPPRESS-IF-HISTORY" not in sheet
        ),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: PASS, 16 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3.py backend/tests/test_report_v3.py
git commit -m "feat(v3): sheet validator - FLOW presence, EXPECT coverage, collision check"
```

---

## Task 12: `check_report_against_sheet_v3`

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_v3.py`
- Test: `backend/tests/test_report_v3.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_v3.py`:

```python
def test_report_check_flags_a_missing_station_and_unengaged_bearing():
    report = ("COMPARISON:\nNo prior imaging available for comparison.\n\n"
              "TECHNIQUE:\nCT head without contrast.\n\n"
              "FINDINGS:\nGrey-white differentiation is preserved throughout. "
              "The ventricles and basal cisterns are normal in calibre.\n\n"
              "IMPRESSION:\nNo acute intracranial haemorrhage.\n")
    out = v3.check_report_against_sheet_v3(report, GOOD_SHEET)
    assert not out["passed"]
    assert any("skull" in s for s in out["detail"]["stations_missing"])
    assert out["detail"]["bearing_missing"] == ["anticoagulated on warfarin"]


def test_report_check_passes_when_stations_and_bearing_are_present():
    report = ("COMPARISON:\nNo prior imaging available for comparison.\n\n"
              "TECHNIQUE:\nCT head without contrast.\n\n"
              "FINDINGS:\nGrey-white differentiation is preserved throughout. "
              "The ventricles and basal cisterns are normal in calibre. "
              "The skull vault and scalp soft tissues are intact.\n\n"
              "IMPRESSION:\nNo acute intracranial haemorrhage. The patient is "
              "anticoagulated on warfarin; no reversal is indicated on imaging grounds.\n")
    out = v3.check_report_against_sheet_v3(report, GOOD_SHEET)
    assert out["passed"], out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'check_report_against_sheet_v3'`

- [ ] **Step 3: Write the implementation**

Append to `report_v3.py`:

```python
def _content_words(phrase: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{5,}", phrase.lower()) if w not in _STOPWORDS]


def _mentioned(phrase: str, text: str) -> bool:
    """A phrase counts as present when any of its content words appears.

    Deliberately loose: this is a screen for a station or hook that vanished
    entirely, not a paraphrase detector. A false positive costs a glance.
    """
    words = _content_words(phrase)
    return any(w in text for w in words) if words else True


def check_report_against_sheet_v3(report: str, sheet: str) -> dict[str, Any]:
    """Coverage checks that need both artefacts.

    Two things the sheet promised and only the pair can verify: that every
    FLOW/ORDER station reached FINDINGS (L-16 — a station with nowhere to go
    vanishes silently), and that every BEARING item reached IMPRESSION (L-31/L-32
    — must-appear erosion was the residual failure of every reasoning-off cell).

    Note the asymmetry that makes this safe: BEARING is checked here but never
    presented to the generator as a list to discharge. The sheet frames it as
    what the question turns on; the check verifies the outcome. Keeping the
    check while removing the slot is the whole point.
    """
    from .scripts.sheet_budget.report_checks import sections

    parts = sections(report)
    findings = parts.get("FINDINGS", "").lower()
    impression = parts.get("IMPRESSION", "").lower()

    stations_missing = [
        s for s in flow_stations(sheet)
        if not _mentioned(re.sub(r"^terminal:\s*", "", s), findings)
    ]
    hooks = [m.group(1).split("=>")[0].strip() for m in _BEARING.finditer(sheet)]
    bearing_missing = [
        h for h in hooks
        if h.lower() != "none" and not _mentioned(h, impression)
    ]

    detail = {k: v for k, v in {
        "stations_missing": stations_missing,
        "bearing_missing": bearing_missing,
    }.items() if v}
    return {"passed": not detail, "failures": sorted(detail), "detail": detail}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3.py backend/tests/test_report_v3.py
git commit -m "feat(v3): sheet-to-report coverage checks for stations and BEARING items"
```

---

## Task 13: Callers and the production-isolation guard

**Files:**
- Modify: `backend/src/rapid_reports_ai/report_v3.py`
- Test: `backend/tests/test_report_v3.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_v3.py`:

```python
import pathlib


def test_production_does_not_import_v3():
    """v3 is a parallel development track; nothing live may depend on it
    until the deliberate swap."""
    src = pathlib.Path(v3.__file__).parent
    offenders = []
    for f in src.rglob("*.py"):
        if f.name in {"report_v3.py", "report_v3_policy.py"}:
            continue
        if "scripts" in f.parts or "test" in f.name:
            continue
        if "report_v3" in f.read_text(errors="replace"):
            offenders.append(f.name)
    assert not offenders, f"production modules import report_v3: {offenders}"


def test_stage_prompts_compose_the_policy_layer():
    """The analyser gets the core policy; the generator gets core plus format.
    Sending the output-format half to the analyser would be dead tokens — it
    never writes a COMPARISON section."""
    assert v3.analyser_system_prompt().startswith(v3.POLICY_CORE)
    assert v3.POLICY_REPORT not in v3.analyser_system_prompt()
    gen = v3.generator_system_prompt()
    assert v3.POLICY_CORE in gen and v3.POLICY_REPORT in gen
    assert gen.endswith(v3.GENERATOR_V3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && poetry run pytest tests/test_report_v3.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'analyser_system_prompt'`

- [ ] **Step 3: Write the implementation**

Append to `report_v3.py`:

```python
V3_MODEL = "qwen/qwen3.6-27b"


def analyser_system_prompt() -> str:
    """Core policy plus the sheet contract. No output-format half: the analyser
    writes report-register templates but never writes report sections."""
    return f"{POLICY_CORE}\n\n{ANALYSER_V3}"


def generator_system_prompt() -> str:
    return f"{POLICY_CORE}\n\n{POLICY_REPORT}\n\n{GENERATOR_V3}"


async def generate_sheet_v3(scan_type: str, clinical_history: str,
                            model: str = V3_MODEL,
                            reasoning: bool = True) -> dict[str, Any]:
    from .enhancement_utils import (
        _get_api_key_for_provider, _get_model_provider, _run_agent_with_model,
    )
    t0 = time.time()
    user = (f"SCAN TYPE: {scan_type}\nCLINICAL HISTORY: {clinical_history}\n\n"
            "Produce the decision sheet.")
    result = await _run_agent_with_model(
        model_name=model, output_type=str,
        system_prompt=analyser_system_prompt(), user_prompt=user,
        api_key=_get_api_key_for_provider(_get_model_provider(model)),
        use_thinking=reasoning,
        model_settings={"temperature": 0.5, "top_p": 0.95, "max_tokens": 16000},
    )
    sheet = result.output if hasattr(result, "output") else str(result)
    return {"sheet": sheet, "latency_ms": int((time.time() - t0) * 1000),
            "model": model, "reasoning": reasoning}


async def generate_report_v3(sheet: str, scan_type: str, clinical_history: str,
                             findings: str, model: str = V3_MODEL,
                             reasoning: bool = True) -> dict[str, Any]:
    from .enhancement_utils import (
        _get_api_key_for_provider, _get_model_provider, _run_agent_with_model,
    )
    t0 = time.time()
    user = (f"## DECISION SHEET\n{sheet}\n\n## STUDY METADATA\nSCAN TYPE: {scan_type}\n"
            f"CLINICAL HISTORY: {clinical_history}\n\n## DICTATION\n{findings}\n\n"
            "Write the report.")
    result = await _run_agent_with_model(
        model_name=model, output_type=str,
        system_prompt=generator_system_prompt(), user_prompt=user,
        api_key=_get_api_key_for_provider(_get_model_provider(model)),
        use_thinking=reasoning,
        model_settings={"temperature": 0.6, "top_p": 0.95, "max_tokens": 16384},
    )
    report = result.output if hasattr(result, "output") else str(result)
    return {"report": report, "latency_ms": int((time.time() - t0) * 1000),
            "model": model, "reasoning": reasoning}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && poetry run pytest tests/test_report_v3.py tests/test_report_checks.py -v`
Expected: PASS, 20 + 9 tests

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/report_v3.py backend/tests/test_report_v3.py
git commit -m "feat(v3): stage callers with composed policy and per-stage reasoning flags"
```

---

## Task 14: The v3 harness

**Files:**
- Create: `backend/src/rapid_reports_ai/scripts/sheet_budget/v3_run.py`

- [ ] **Step 1: Write the harness**

```python
"""Run the v3 pipeline over the case suite.

    poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \\
        --output-dir test_output/V3_FULL

    # reasoning cells: analyser off, generator on (L-32's closest cell)
    poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \\
        --analyser-reasoning off --output-dir test_output/V3_OFF_ON

Serialised against Groq: concurrency at this org's OTPM limit loses cells
(ledger method note).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from rapid_reports_ai.report_v3 import (  # noqa: E402
    generate_sheet_v3, generate_report_v3, validate_sheet_v3,
    check_report_against_sheet_v3,
)
from rapid_reports_ai.scripts.sheet_budget.gate import run_gate  # noqa: E402
from rapid_reports_ai.scripts.sheet_budget.report_checks import (  # noqa: E402
    run_report_checks,
)

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]


async def _one(case: dict, args) -> dict:
    sheet_out = await generate_sheet_v3(
        case["scan_type"], case["clinical_history"],
        **({"model": args.model} if args.model else {}),
        reasoning=(args.analyser_reasoning == "on"),
    )
    sheet = sheet_out["sheet"]
    validation = validate_sheet_v3(sheet)

    report_out = await generate_report_v3(
        sheet, case["scan_type"], case["clinical_history"], case["findings"],
        **({"model": args.model} if args.model else {}),
        reasoning=(args.generator_reasoning == "on"),
    )
    report = report_out["report"]

    return {
        "case": case["name"],
        "skill_sheet": sheet,
        "sheet_chars": len(sheet),
        "sheet_validation": validation,
        "analyser_latency_ms": sheet_out["latency_ms"],
        "report": report,
        "report_chars": len(report),
        "generator_latency_ms": report_out["latency_ms"],
        "gate": run_gate(report),
        "report_checks": run_report_checks(report),
        "coverage": check_report_against_sheet_v3(report, sheet),
        "cell": f"{args.analyser_reasoning}_{args.generator_reasoning}",
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    # Same default as v2_run.py, so the v3 cells cover the same 17 cases the
    # V2 artifacts used and the comparison in Task 15 is like-for-like. Narrow with
    # --cases-file test_cases/analyser_suite.json (5 cases) when iterating.
    ap.add_argument("--cases-file",
                    default=str(BACKEND_ROOT / "test_cases/broad_suite.json"))
    ap.add_argument("--case", action="append", help="case name; repeatable")
    ap.add_argument("--model", help="override V3_MODEL for both stages")
    ap.add_argument("--analyser-reasoning", choices=["on", "off"], default="on")
    ap.add_argument("--generator-reasoning", choices=["on", "off"], default="on")
    args = ap.parse_args()

    cases = json.loads(pathlib.Path(args.cases_file).read_text())
    if args.case:
        cases = [c for c in cases if c["name"] in set(args.case)]

    out_dir = pathlib.Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for case in cases:
        row = await _one(case, args)
        runs.append(row)
        flags = ",".join(row["report_checks"]["failures"]) or "clean"
        print(f"{row['case']}: sheet={row['sheet_chars']} "
              f"valid={row['sheet_validation']['ok']} "
              f"gate={row['gate']['passed']} checks={flags}")
        (out_dir / "runs.json").write_text(json.dumps(runs, indent=2))

    ok = sum(r["sheet_validation"]["ok"] for r in runs)
    clean = sum(r["report_checks"]["passed"] for r in runs)
    print(f"\n{ok}/{len(runs)} sheets valid, {clean}/{len(runs)} reports clean")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke-test on one case**

Run:
```bash
cd backend
poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \
  --case clean_ct_head --output-dir test_output/V3SMOKE
```
Expected: one line printed, `runs.json` written, `valid=True`.

- [ ] **Step 3: Inspect the sheet by eye**

```bash
poetry run python -c "
import json
print(json.load(open('test_output/V3SMOKE/runs.json'))[0]['skill_sheet'])
"
```

Confirm by reading: `## FLOW` present with all three declarations; every obligation has `EXPECT`; no `SUPPRESS-IF-HISTORY`; a one-line `## VERDICT`; no `## RECOMMEND`. `BEARING` may legitimately be absent — check the history actually conditions nothing before treating that as a fault.

- [ ] **Step 4: Commit**

```bash
git add backend/src/rapid_reports_ai/scripts/sheet_budget/v3_run.py
git commit -m "feat(v3): run harness with per-stage reasoning cells and coverage checks"
```

---

## Task 15: Full run and comparison

- [ ] **Step 1: Run the full suite, analyser on**

```bash
cd backend
poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \
  --output-dir test_output/V3_ON_ON
```

- [ ] **Step 2: Run the analyser-off cell — the primary success criterion**

```bash
poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \
  --analyser-reasoning off --output-dir test_output/V3_OFF_ON
```

- [ ] **Step 3: Run the generator-off cell — the stretch target**

```bash
poetry run python -m rapid_reports_ai.scripts.sheet_budget.v3_run \
  --analyser-reasoning off --generator-reasoning off \
  --output-dir test_output/V3_OFF_OFF
```

- [ ] **Step 4: Compare against Task 8's arms**

Task 8's arm A (production as shipped) and whichever v2 arm won are the numbers to beat. Read them from `test_output/POLICY_AB/runs.json` alongside the v3 cells below.

```bash
poetry run python -c "
import json, pathlib
for d in ['V3_ON_ON','V3_OFF_ON','V3_OFF_OFF']:
    p = pathlib.Path('test_output')/d/'runs.json'
    if not p.exists():
        continue
    runs = json.loads(p.read_text())
    lat = sum(r['analyser_latency_ms']+r['generator_latency_ms'] for r in runs)/len(runs)/1000
    gate = sum(r['gate']['passed'] for r in runs)
    checks = sum(r.get('report_checks',{}).get('passed', True) for r in runs)
    print(f'{d:16} n={len(runs)} e2e={lat:5.1f}s gate={gate}/{len(runs)} checks_clean={checks}/{len(runs)}')
"
```

- [ ] **Step 5: Record the result and stop for review**

Append to the ledger as **L-35**: per cell, sheet chars, analyser and generator latency and tokens, validator pass rate, gate pass rate, report-checks flags, and coverage misses.

**Do not flip any production default on this data.** Per spec §10, a generator-off flip produces a report roughly a tenth the length of the one the consultant reviewed in L-13 — it needs its own clinical review, not a passing gate. Hand `V3_OFF_ON` and `V3_ON_ON` to the radiologist side by side before deciding anything.

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): L-35 v3 cells against the v2 re-baseline"
```

---

## Self-Review

**Spec coverage.** §4.1 policy layer → Task 1. §5.2 FLOW → Tasks 9, 11. §5.4 EXPECT and the deletion of `SUPPRESS-IF-HISTORY` → Tasks 9, 11. §5.5 impression → Tasks 9, 10, 12, **revised**: the sheet carries a one-line `## VERDICT` and nothing else, with history's contribution moved to `CASE/BEARING`. §5.6 MEASURE thresholds → Task 9 (prompt only, no validator check — a threshold is optional and its absence is not a defect). §5.7 RECOMMEND → **deleted**, see below. §6 generator restructure → Task 10. §7 gate checks → Tasks 2–6 (report-only) and 11–12 (sheet-coupled); the "no unfilled braces" row is already covered by `gate.py`'s leak markers. §9 sequencing → Tasks 7–8 before 9, with Task 8 as a hard gate. §10 risks → Task 15 Step 5.

**Deliberate departures from the spec as written**, both settled in review and to be back-ported when the spec is next touched:

1. **`## IMPRESSION` with `VERDICT` + `CARRY` → `## VERDICT` alone, plus `CASE/BEARING`.** A manifest of items gets discharged rather than distilled — the same mechanism that made v2's generator say `RECOMMEND` is "not a quota to spend", and the mechanism v1's own prompt already documents ("the generator copies them verbatim and the impression bloats"). `BEARING` frames the history as what the question turns on, so engaging it is entailed rather than enumerated. The coverage **check** is unchanged: `check_report_against_sheet_v3` still verifies every `BEARING` item reached the impression. Keep the check, remove the slot.
2. **`## RECOMMEND` deleted.** Urgency and service choice both depend on what was dictated, so they fail §2's editing rule. The remit boundary — the only part the analyser could pre-decide — is invariant and now lives in `POLICY_CORE`'s banned-construction list, prepended directly to the generator, which is closer to the point of use than a sheet section was. Untested, so Task 15 must check `management_trespass` flags specifically: if trespass returns, the guardrail needs restoring somewhere.

**Not covered by design:** §12.2, the critical-finding communication placeholder, is a product decision awaiting sign-off and has no task. It must not be implemented silently.

**Type consistency.** `sections()` is defined in Task 2 and consumed in Tasks 4, 5, 6 and 12. `BANNED_PATTERNS` and `LEXICON_TERMS` are defined in Task 1 and consumed in Task 3 and Task 8. `POLICY_CORE` is defined in Task 1 and consumed in Tasks 8 and 13. `flow_stations()` is defined in Task 11 and consumed in Task 12. `_STOPWORDS`, `_BEARING`, `_TNEG`, `_EXPECT` are defined in Task 11 and reused in Task 12. `run_report_checks()` from Task 6 is consumed in Tasks 8 and 14; `check_report_against_sheet_v3()` from Task 12 is consumed in Task 14.
