# Template Pipeline Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Templated (`skill_sheet_guided`) reports run the same sheet → brief → generate → post-generation check → options flow as quick reports, emitting the same `GenerationArtifacts`, behind the `RR_TEMPLATE_MIRROR` kill switch.

**Architecture:** The pathway-neutral logic moves out of `quick_report_brief.py` / `quick_report_quality.py` into shared `report_reconcile.py` and `report_review.py` (quick output byte-identical, pinned by golden tests). A save-time structuring pass turns each stored template sheet into a verified, coverage-gated `sheet_structure`. At generation time `template_brief.py` reconciles that structure with the dictation through the shared engine and rewrites the sheet in place; `template_pipeline.py` orchestrates generation, the code-placed CLINICAL HISTORY section, the section-generic post-generation check and persistence.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (JSON column `templates.template_config`), pydantic v2, pydantic-ai via `enhancement_utils._run_agent_with_model`, Jev (`typesafe/jev-1.13` on OpenRouter), Qwen 3.8 27B / gpt-oss-120b on Cerebras, pytest (`asyncio_mode = "auto"`), SvelteKit frontend (one small change).

**Spec:** `docs/superpowers/specs/2026-09-30-template-pipeline-mirror-design.md` (approved 2026-09-30, including the §5 prompt package).

**Conventions for every task**
- Run tests from `backend/`: `uv run pytest -q <paths>`. Full suite: `uv run pytest -q`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Source lives in `backend/src/rapid_reports_ai/`; tests in `backend/tests/`. Paths below are relative to `backend/`.
- Never edit `global_style_guide.py` outside Task 13 (signed-off package).
- Prompts written here stay case-agnostic (structural examples only).

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/rapid_reports_ai/report_reconcile.py` | create | Shared reconcile engine: Jev/Qwen calls, negative classifier, bundled split, impression plan, fallback, routing, `Brief`, option-sentence writer |
| `src/rapid_reports_ai/report_review.py` | create | Shared post-generation check and repairs, section-generic, protected spans, suppressed-term guard |
| `src/rapid_reports_ai/generation_artifacts.py` | create | `GenerationArtifacts` model + `from_candidate` |
| `src/rapid_reports_ai/template_sheet_structure.py` | create | Structure schema, structuring prompt/call, verification, coverage gate, staleness, background store |
| `src/rapid_reports_ai/template_brief.py` | create | Template brief: structure + dictation → in-place brief + decisions + options |
| `src/rapid_reports_ai/template_history.py` | create | CLINICAL HISTORY section: write (Qwen), provenance check, insertion |
| `src/rapid_reports_ai/template_pipeline.py` | create | Template orchestration, flag, override, candidate record |
| `src/rapid_reports_ai/quick_report_brief.py` | modify | Keeps quick extractor + `compile_brief`; imports engine names from `report_reconcile` |
| `src/rapid_reports_ai/quick_report_quality.py` | modify | Becomes a re-export shim over `report_review` (scripts import it) |
| `src/rapid_reports_ai/quick_report_generator.py` | modify | `_write_options` delegates to `report_reconcile.write_options` |
| `src/rapid_reports_ai/quick_report_api.py` | modify | Candidate record gains `sections` |
| `src/rapid_reports_ai/global_style_guide.py` | modify | T0 + four `_BRIEF` constants (signed off) |
| `src/rapid_reports_ai/template_manager.py` | modify | `_generate_report_skill_sheet_guided(brief_text=…, history_supplied=…)` |
| `src/rapid_reports_ai/database/crud.py` | modify | `create_report(..., candidate_reports=None)` |
| `src/rapid_reports_ai/main.py` | modify | Generate endpoint (mirror, override, persistence, legacy refusal), structure triggers, list filter |
| `src/rapid_reports_ai/scripts/template_structure_eval.py` | create | E1 + backfill |
| `src/rapid_reports_ai/scripts/template_mirror_eval.py` | create | E2 old-vs-new |
| `frontend/src/routes/components/TemplatedReportTab.svelte` | modify | Remove the legacy banner |
| `tests/test_golden_quick_pipeline.py` + `tests/fixtures/golden_quick.json` | create | Byte-identity pins for the refactor |
| `tests/test_report_review.py`, `tests/test_template_sheet_structure.py`, `tests/test_template_brief.py`, `tests/test_template_history.py`, `tests/test_template_prompts.py`, `tests/test_template_pipeline.py`, `tests/test_generation_artifacts.py` | create | New behaviour |
| `tests/fixtures/template_sheet.md` | create | Synthetic template sheet fixture in the stored-sheet format |
| `tests/test_report_path_split.py`, `tests/test_quick_report_quality.py`, `tests/conftest.py` | modify | New import rules/pins; retarget patches; quality-check exemption list |

---

## Phase A — Shared engine, quick output unchanged

### Task 1: Golden pins for the quick brief and quality check

**Files:**
- Create: `tests/test_golden_quick_pipeline.py`
- Create: `tests/fixtures/golden_quick.json` (generated)

- [ ] **Step 1: Write the golden test**

```python
"""Byte-identity pins for the quick path while its engine moves to shared modules
(spec 2026-09-30-template-pipeline-mirror-design §1). Regenerate only on an intended change:
UPDATE_GOLDEN=1 uv run pytest tests/test_golden_quick_pipeline.py"""
from __future__ import annotations

import json
import os
import pathlib

from rapid_reports_ai import quick_report_brief as qb
from rapid_reports_ai import quick_report_quality as qq

from test_quick_report_brief import JEV, QWEN, SHEET, _stub

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "golden_quick.json"
FINDINGS = "8 mm right subdural haematoma. 3 mm midline shift."
REPORT = """FINDINGS:
An 8 mm right subdural haematoma. No skull fracture. No hydrocephalus, no herniation, and no intraventricular extension.

IMPRESSION:
Acute right subdural haematoma with 3 mm midline shift.

Dr A"""


async def _snapshot(monkeypatch) -> dict:
    _stub(monkeypatch, JEV, QWEN)
    brief = await qb.compile_brief(SHEET, "CT head", FINDINGS, "fall")

    async def fake_jev(state, qs):
        return {k: {"noul": 0.9 if k in ("c1", "r1") else 0.1} for k in qs}
    target = qq.rc if hasattr(qq, "rc") else qq.qb
    monkeypatch.setattr(target, "_jev", fake_jev)
    res = await qq.check(REPORT, FINDINGS, "CT head", [])
    fnd, imp = qq.report_sections(REPORT)
    return {"brief_text": brief.text, "decisions": brief.decisions,
            "clauses": qq.clauses(fnd) + qq.clauses(imp),
            "check": res.model_dump(),
            "removed": qq.remove_negative_clause(REPORT, "No herniation")}


async def test_quick_pipeline_matches_golden(monkeypatch):
    snap = json.loads(json.dumps(await _snapshot(monkeypatch)))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=1, sort_keys=True))
    assert snap == json.loads(GOLDEN.read_text())
```

The `hasattr(qq, "rc")` line lets the same test run before (quality module holds `qb`) and after Task 3 (`report_review` holds `rc`).

- [ ] **Step 2: Generate the golden file on the current code**

Run: `UPDATE_GOLDEN=1 uv run pytest -q tests/test_golden_quick_pipeline.py`
Expected: `1 passed`; `tests/fixtures/golden_quick.json` exists and contains `brief_text`, `decisions`, `clauses`, `check`, `removed`.

- [ ] **Step 3: Verify it passes without the flag**

Run: `uv run pytest -q tests/test_golden_quick_pipeline.py`
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_golden_quick_pipeline.py tests/fixtures/golden_quick.json
git commit -m "test(quick): golden pins for brief and quality check before the engine moves"
```

### Task 2: Extract `report_reconcile.py`

**Files:**
- Create: `src/rapid_reports_ai/report_reconcile.py`
- Modify: `src/rapid_reports_ai/quick_report_brief.py`
- Modify: `tests/test_report_path_split.py`

- [ ] **Step 1: Add the failing import-rule test**

Append to `tests/test_report_path_split.py`:

```python
SHARED_MODULES = ("report_reconcile.py", "report_review.py", "generation_artifacts.py")
PATHWAY_MODULES = {"quick_report_brief", "quick_report_quality", "quick_report_generator", "quick_report_prompts",
                   "quick_report_hardening", "quick_report_api", "quick_report_analyser", "template_manager",
                   "global_style_guide", "template_brief", "template_pipeline", "template_sheet_structure",
                   "template_history"}


def test_shared_modules_import_neither_pathway():
    for f in SHARED_MODULES:
        path = SRC / f
        assert path.exists(), f
        assert not (_imports(path) & PATHWAY_MODULES), f
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest -q tests/test_report_path_split.py::test_shared_modules_import_neither_pathway`
Expected: FAIL, `AssertionError: report_reconcile.py`.

- [ ] **Step 3: Create `report_reconcile.py` by moving code verbatim**

Create the module with this header:

```python
"""Shared reconcile engine: the pathway-neutral half of the compiled brief.

Both report pathways (quick, templated) reconcile a skill sheet with one dictation through these
calls; each keeps its own extractor, compiler and prompts (spec
2026-09-30-template-pipeline-mirror-design §1). Moved verbatim from quick_report_brief.py.

    Jev   yes/no on stated text (conditions, affected normals, findings present)
    Qwen  negatives: contradicted / expected / keep; bundled split; impression plan; fallback
    code  routing (route_finding), caps, labels
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import List, Literal, Optional

import httpx
from pydantic import BaseModel, field_validator

from .enhancement_utils import _run_agent_with_model

logger = logging.getLogger(__name__)
```

Then **cut** these definitions from `quick_report_brief.py` and paste them, unchanged and in this order, into `report_reconcile.py`:

1. `JEV_URL`, `JEV_MODEL`, `QWEN`, `JEV_TIMEOUT_S`, `QWEN_TIMEOUT_S` (brief lines 43–47)
2. `_quoted`, `_is_bundled` (lines 113–118)
3. The block from the `# Policy 1 for dictated findings` comment through `route_finding` (lines 156–211): `PRESENT_LOW`, `PRESENT_HIGH`, `MAX_FINDING_OPTIONS`, `Q_FINDING`, `FindingNegative`, `route_finding`. **Leave** `_CONFIRMED`, `_CONFIRMED_BRANCH`, `_CONFIRMED_NEG`, `_tag`, `parse_if_present`, `distinct_keys` in the quick module (quick sheet format).
4. `_MEASUREMENT` (line 214)
5. The whole `# ── reconcile ──` section (lines 217–405): `Q_AFFECTED`, `Q_PRESENT`, `Q_REC_UNMET`, `Q_STYLE_MATCH`, `NegativeDecision`, `_unstring`, `QwenDecisions`, `Split`, `RecDecision`, `ImpressionPlan`, `PLAN_SYS`, `PLAN_TIMEOUT_S`, `MAX_OPTIONS`, `_BAR_KINDS`, `QWEN_SYS`, `_words`, `_split_bundled`, `_jev`, `_qwen`, `FallbackItem`, `FallbackNegatives`, `FALLBACK_SYS`, `FALLBACK_TIMEOUT_S`, `_fallback`, `split_findings`, `_plan`
6. The `Brief` dataclass (lines 411–415)

Then change `_plan` to accept the template side's inclusion preferences (quick passes nothing, so its prompt is byte-identical):

```python
async def _plan(scan_type: str, clinical_history: str, items: List[str], recs: List[str],
                inclusion_logic: str = "") -> ImpressionPlan:
    user = (f"SCAN TYPE: {scan_type}\nCLINICAL QUESTION (context only): {clinical_history or '(not given)'}\n\n"
            "DICTATED FINDINGS:\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(items))
            + "\n\nCANDIDATE RECOMMENDATIONS:\n" + ("\n".join(f"{i}. {t}" for i, t in enumerate(recs)) or "(none)"))
    if inclusion_logic:
        user += "\n\nTHE REPORTER'S OWN INCLUSION PREFERENCES (follow them where they apply):\n" + inclusion_logic
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=QWEN, output_type=ImpressionPlan, system_prompt=PLAN_SYS,
        user_prompt=user, api_key="",
        model_settings={"temperature": 0, "max_tokens": 8000, "reasoning_effort": "low"}), PLAN_TIMEOUT_S)
    return r.output
```

- [ ] **Step 4: Re-import the moved names into `quick_report_brief.py`**

Replace the brief's imports block (from `import asyncio` through `from .enhancement_utils import _run_agent_with_model`) and the removed constants with:

```python
import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .report_reconcile import (  # noqa: F401 — re-exported; tests patch these names on this module
    JEV_MODEL, JEV_TIMEOUT_S, JEV_URL, MAX_FINDING_OPTIONS, MAX_OPTIONS, PLAN_SYS, PLAN_TIMEOUT_S,
    PRESENT_HIGH, PRESENT_LOW, Q_AFFECTED, Q_FINDING, Q_PRESENT, Q_REC_UNMET, Q_STYLE_MATCH, QWEN,
    QWEN_SYS, QWEN_TIMEOUT_S, FALLBACK_SYS, FALLBACK_TIMEOUT_S, _BAR_KINDS, _MEASUREMENT, Brief,
    FallbackItem, FallbackNegatives, FindingNegative, ImpressionPlan, NegativeDecision, QwenDecisions,
    RecDecision, Split, _fallback, _is_bundled, _jev, _plan, _quoted, _qwen, _split_bundled, _unstring,
    _words, route_finding, split_findings,
)

logger = logging.getLogger(__name__)
```

`compile_brief` keeps calling the bare names (`_jev`, `_qwen`, `_plan`, `_fallback`, `_split_bundled`), which resolve through this module's globals, so `monkeypatch.setattr(qb, "_jev", …)` in the existing tests still takes effect. Remove the now-unused `json`, `os`, `httpx`, `Literal`, `BaseModel`, `field_validator` imports from the brief if nothing left in it uses them (check with `uv run ruff check src/rapid_reports_ai/quick_report_brief.py` if ruff is available, else `python -m pyflakes`).

- [ ] **Step 5: Run the quick suites and the golden pin**

Run: `uv run pytest -q tests/test_quick_report_brief.py tests/test_confirmed_negatives.py tests/test_impression_negatives.py tests/test_golden_quick_pipeline.py tests/test_report_path_split.py -k "not report_review and not generation_artifacts"`
Expected: all pass except `test_shared_modules_import_neither_pathway`, which still fails on `report_review.py` (created in Task 3).

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/report_reconcile.py src/rapid_reports_ai/quick_report_brief.py tests/test_report_path_split.py
git commit -m "refactor(brief): move the pathway-neutral reconcile engine to report_reconcile"
```

### Task 3: Extract `report_review.py`

**Files:**
- Create: `src/rapid_reports_ai/report_review.py`
- Modify: `src/rapid_reports_ai/quick_report_quality.py`
- Modify: `tests/test_quick_report_quality.py`, `tests/test_golden_quick_pipeline.py` (no change needed; it detects `rc`), `tests/conftest.py`

- [ ] **Step 1: Move the module**

```bash
git mv src/rapid_reports_ai/quick_report_quality.py src/rapid_reports_ai/report_review.py
```

In `report_review.py`:
- Replace the docstring's first line with `"""Shared post-generation check: Jev flags contradictions and omissions, focal repairs fix them.` and add a line `Used by both pathways (spec 2026-09-30-template-pipeline-mirror-design §4).` after it.
- Replace `from . import quick_report_brief as qb` with `from . import report_reconcile as rc`.
- Replace every `qb.` with `rc.` (`qb.QWEN`, `qb.split_findings`, `qb._jev`, `qb._unstring` — four sites).

- [ ] **Step 2: Create the quick shim**

Create `src/rapid_reports_ai/quick_report_quality.py`:

```python
"""Quick-report post-generation check. The engine is shared with templated reports and lives in
report_review; this module keeps the quick path's import name (scripts and the generator use it)."""
from .report_review import *  # noqa: F401,F403
from .report_review import (  # noqa: F401 — private helpers the eval scripts read
    _HEADER, _NEGATION, _diff_edits, _problem, _restates, _sentences,
)
```

- [ ] **Step 3: Retarget the quality tests**

In `tests/test_quick_report_quality.py`:
- `from rapid_reports_ai import quick_report_quality as qq` → `from rapid_reports_ai import report_review as qq`
- every `qq.qb` → `qq.rc` (the `_stub_jev` helper and the Jev-failure test).

In `tests/conftest.py`, replace the fixture body so new review/template modules also run the live-check code path under their own stubs:

```python
_QUALITY_MODULES = ("test_quick_report_quality", "test_report_review", "test_template_pipeline",
                    "test_golden_quick_pipeline")


@pytest.fixture(autouse=True)
def _no_live_quality_check(request, monkeypatch):
    """The post-generation check calls Jev over the network; unit tests outside the modules that
    stub it run the generators with it switched off."""
    if request.module.__name__.endswith(_QUALITY_MODULES):
        return
    monkeypatch.setenv("RR_QUALITY_CHECK", "0")
```

- [ ] **Step 4: Run everything touched**

Run: `uv run pytest -q tests/test_quick_report_quality.py tests/test_quick_report_brief.py tests/test_golden_quick_pipeline.py tests/test_report_path_split.py -k "not generation_artifacts"`
Expected: all pass except `test_shared_modules_import_neither_pathway` (now fails on `generation_artifacts.py`, Task 5).

Run: `uv run python -c "import rapid_reports_ai.scripts.quality_check_eval"` from `backend/` with `PYTHONPATH=src`.
Expected: no ImportError.

- [ ] **Step 5: Commit**

```bash
git add -A src/rapid_reports_ai/report_review.py src/rapid_reports_ai/quick_report_quality.py tests/test_quick_report_quality.py tests/conftest.py
git commit -m "refactor(quality): move the post-generation check to shared report_review"
```

### Task 4: Section-generic check, protected spans, suppressed-term guard

**Files:**
- Modify: `src/rapid_reports_ai/report_review.py`
- Create: `tests/test_report_review.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Section-generic review (spec §4): template headings, implicit sections, protected spans."""
from __future__ import annotations

from rapid_reports_ai import report_review as rr

SECTIONS = [rr.ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            rr.ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"),
            rr.ReportSection(name="FINDINGS", header=None, role="findings"),
            rr.ReportSection(name="IMPRESSION", header="Impression", role="impression")]
REPORT = """CLINICAL HISTORY
67F. Abdominal pain. ?Appendicitis.

TECHNIQUE
Portal venous phase CT.

The appendix is dilated measuring 11 mm. No pneumoperitoneum. Unremarkable appearances of the spleen.

Impression
Acute appendicitis."""


def test_section_spans_cover_headed_and_implicit_sections():
    spans = {s.name: REPORT[a:b].strip() for s, a, b in rr.section_spans(REPORT, SECTIONS)}
    assert spans["CLINICAL HISTORY"] == "67F. Abdominal pain. ?Appendicitis."
    assert spans["TECHNIQUE"].startswith("Portal venous phase CT.")
    assert spans["IMPRESSION"] == "Acute appendicitis."


def test_implicit_first_section_runs_to_the_first_header():
    secs = [rr.ReportSection(name="FINDINGS", header=None, role="findings"),
            rr.ReportSection(name="CONCLUSION", header="Conclusion:", role="impression")]
    text = "Liver normal. No ascites.\n\nConclusion:\nNormal study."
    spans = {s.name: text[a:b].strip() for s, a, b in rr.section_spans(text, secs)}
    assert spans == {"FINDINGS": "Liver normal. No ascites.", "CONCLUSION": "Normal study."}


def test_checked_clauses_skip_history_technique_and_comparison():
    cls = rr.checked_clauses(REPORT, SECTIONS)
    assert "No pneumoperitoneum." in cls and "Acute appendicitis." in cls
    assert not any("Abdominal pain" in c or "Portal venous" in c for c in cls)


def test_quick_default_is_unchanged():
    quick = "FINDINGS:\nNo ascites, no collection.\n\nIMPRESSION:\nNormal.\n\nDr A"
    fnd, imp = rr.report_sections(quick)
    assert rr.checked_clauses(quick, None) == list(dict.fromkeys(rr.clauses(fnd) + rr.clauses(imp)))


def test_edit_guard_rejects_protected_spans_and_suppressed_terms():
    history = "67F. Abdominal pain. ?Appendicitis."
    assert not rr.edit_allowed(rr.Edit(find="Abdominal pain.", replace="Pain."), False, protected=[history])
    assert not rr.edit_allowed(rr.Edit(find="The spleen is unremarkable.", replace="The spleen is normal."),
                               False, suppressed=["normal"])
    assert rr.edit_allowed(rr.Edit(find="The appendix is dilated.", replace="The appendix is dilated to 11 mm."),
                           False, protected=[history], suppressed=["normal"])


def test_omission_state_drops_the_history_text():
    assert "Abdominal pain" not in rr.without(REPORT, ["67F. Abdominal pain. ?Appendicitis."])


async def test_check_with_sections_asks_only_checked_clauses(monkeypatch):
    seen = []

    async def fake_jev(state, qs):
        seen.append((state, [q["instructions"] for q in qs.values()]))
        return {k: {"noul": 0.1} for k in qs}
    monkeypatch.setattr(rr.rc, "_jev", fake_jev)
    res = await rr.check(REPORT, "11 mm appendix", "CT AP", [], sections=SECTIONS,
                         protected=["67F. Abdominal pain. ?Appendicitis."])
    contra = next(q for s, q in seen if s.startswith("SCAN TYPE"))
    omit_state = next(s for s, q in seen if s.startswith("REPORT"))
    assert not any("Portal venous" in x or "Abdominal pain" in x for x in contra)
    assert "Abdominal pain" not in omit_state and res.error is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_report_review.py`
Expected: FAIL, `AttributeError: module 'rapid_reports_ai.report_review' has no attribute 'ReportSection'`.

- [ ] **Step 3: Implement in `report_review.py`**

Add below `positive_items` (the `# ── units ──` section):

```python
class ReportSection(BaseModel):
    name: str
    header: Optional[str] = None      # as written in reports; None = implicit (no header line)
    role: str = "other"               # history|technique|comparison|findings|impression|other


CHECKED_ROLES = {"findings", "impression", "other"}


def section_spans(report: str, sections: List[ReportSection]) -> List[Tuple[ReportSection, int, int]]:
    """(section, start, end) for each section found, in sheet order. A headed section starts after
    its header line and ends at the next header found, or, when the next section is implicit, at
    its first paragraph break; an implicit section covers the text from the previous section's end
    (or the top) to the next header."""
    found: List[Tuple[ReportSection, Optional[int], Optional[int]]] = []
    pos = 0
    for sec in sections:
        if sec.header:
            pat = re.compile(rf"^[ \t]*{re.escape(sec.header.strip().rstrip(':'))}[ \t]*:?[ \t]*$", re.M | re.I)
            m = pat.search(report, pos)
            if not m:
                continue
            found.append((sec, m.start(), m.end()))
            pos = m.end()
        else:
            found.append((sec, None, None))
    header_starts = sorted(h for _, h, _ in found if h is not None)
    out: List[Tuple[ReportSection, int, int]] = []
    prev_end = 0
    for idx, (sec, h, c) in enumerate(found):
        start = c if c is not None else prev_end
        nxt = next((x for x in header_starts if x >= start and (h is None or x > h)), len(report))
        if c is not None and idx + 1 < len(found) and found[idx + 1][1] is None:
            body = re.search(r"\S", report[start:nxt])
            brk = re.search(r"\n[ \t]*\n", report[start + body.start():nxt]) if body else None
            if brk:
                nxt = start + body.start() + brk.start()
        out.append((sec, start, nxt))
        prev_end = nxt
    return out


def checked_clauses(report: str, sections: Optional[List[ReportSection]]) -> List[str]:
    """Clauses the contradiction check reads. Quick (no sections): FINDINGS + IMPRESSION as before.
    Templates: every section whose role carries dictated content."""
    if sections is None:
        fnd, imp = report_sections(report)
        return list(dict.fromkeys(clauses(fnd) + clauses(imp)))
    texts = [report[a:b] for s, a, b in section_spans(report, sections) if s.role in CHECKED_ROLES]
    return list(dict.fromkeys(c for t in texts for c in clauses(t.strip())))


def without(report: str, protected: List[str]) -> str:
    """The report with protected text (history section, fixed blocks) removed."""
    for p in protected:
        if p:
            report = report.replace(p, "")
    return report
```

Change `check`'s signature and first lines:

```python
async def check(report: str, findings: str, scan_type: str, options: List[dict],
                sections: Optional[List[ReportSection]] = None, protected: Optional[List[str]] = None) -> CheckResult:
    """Two Jev calls in parallel: every checked report clause and option against the dictation,
    every positive dictated item against the report (protected text removed)."""
    cls = checked_clauses(report, sections)
```

and in the `asyncio.gather`, replace `ask(f"REPORT:\n{report}", omit_qs)` with `ask(f"REPORT:\n{without(report, protected or [])}", omit_qs)`.

Replace `edit_allowed`:

```python
def edit_allowed(e: Edit, insert_only: bool, protected: Optional[List[str]] = None,
                 suppressed: Optional[List[str]] = None) -> bool:
    """A repair never turns a negated statement into an assertion (L-47), an insertion never
    rewrites text, protected text (history section, fixed blocks) is never edited, and a repair
    never introduces a term the sheet suppresses."""
    if not e.find or e.find == e.replace:
        return False
    if _NEGATION.search(e.find) and not _NEGATION.search(e.replace):
        return False
    if any(p and (e.find in p or p in e.find) for p in (protected or [])):
        return False
    for term in suppressed or []:
        pat = re.compile(rf"\b{re.escape(term)}\b", re.I)
        if pat.search(e.replace) and not pat.search(e.find):
            return False
    return not insert_only or e.find in e.replace
```

Thread `protected`/`suppressed` through the repair paths:
- `repair_report(report, findings, problems, insert_only=False, protected=None, suppressed=None)`: call `edit_allowed(e, insert_only, protected, suppressed)`.
- `insert_findings(report, findings, items, sections=None, protected=None, suppressed=None)`: skip a sentence that contains a suppressed term (`any(re.search(rf"\b{re.escape(t)}\b", sent, re.I) for t in suppressed or [])` → `skipped += 1; continue`); treat an `after` anchor inside protected text as not found (`it.after and out.count(it.after) == 1 and not any(it.after in p for p in protected or [])`); for the fallback first sentence use the first `findings`-role span when `sections` is given: `fnd = next((out[a:b] for s, a, b in section_spans(out, sections) if s.role == "findings"), "") if sections else report_sections(out)[0]`.
- `remove_negative_clause(report, clause, sections=None)`: build its sentence list from `checked_clauses`' source texts: `texts = [report[a:b] for s, a, b in section_spans(report, sections) if s.role in CHECKED_ROLES] if sections else list(report_sections(report))` then `for s in [x for t in texts for x in _sentences(t)]:`.
- `run_quality_check(report, findings, scan_type, options, sections=None, protected=None, suppressed=None)`: pass `sections`/`protected` to `check`; skip removing a flagged negative that lies inside protected text (`if f.kind == "contradiction" and is_negative(f.text) and not any(f.text.rstrip(".") in p for p in protected or []):`), call `remove_negative_clause(report, f.text, sections)`, and pass `protected, suppressed` to `repair_report` and `sections, protected, suppressed` to `insert_findings`. A contradiction flag inside protected text is left in `tel["flags"]` for the rail and excluded from `fix`.

Add a helper the quick record uses (Task 5):

```python
def header_names(report: str) -> List[str]:
    """Ordered section headings of a quick report (FINDINGS:, IMPRESSION:, …)."""
    return [m.group(1) for m in _HEADER.finditer(report)]
```

- [ ] **Step 4: Run review, quality and golden tests**

Run: `uv run pytest -q tests/test_report_review.py tests/test_quick_report_quality.py tests/test_golden_quick_pipeline.py`
Expected: all pass (golden unchanged proves quick defaults are byte-identical).

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/report_review.py tests/test_report_review.py
git commit -m "feat(review): section-generic check, protected spans and suppressed-term guard"
```

### Task 5: `GenerationArtifacts` and shared option writer

**Files:**
- Create: `src/rapid_reports_ai/generation_artifacts.py`, `tests/test_generation_artifacts.py`
- Modify: `src/rapid_reports_ai/report_reconcile.py`, `src/rapid_reports_ai/quick_report_generator.py`, `src/rapid_reports_ai/quick_report_api.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai.generation_artifacts import GenerationArtifacts


def test_from_candidate_reads_either_pathway_record():
    rec = {"content": "FINDINGS:\nX.\n\nIMPRESSION:\nY.", "options": [{"id": "fn0", "section": "FINDINGS"}],
           "quality_check": {"enabled": True}, "brief": {"text": "t", "decisions": {"rules": []}},
           "sections": ["FINDINGS", "IMPRESSION"]}
    a = GenerationArtifacts.from_candidate(rec, "dictated X")
    assert a.report.startswith("FINDINGS") and a.dictated_findings == "dictated X"
    assert a.sections == ["FINDINGS", "IMPRESSION"] and a.brief == {"decisions": {"rules": []}}
    assert a.options[0]["id"] == "fn0"


def test_option_section_must_be_a_listed_section():
    rec = {"content": "", "options": [{"id": "fn0", "section": "NOPE"}], "sections": ["FINDINGS"]}
    assert GenerationArtifacts.from_candidate(rec, "").options == []


async def test_write_options_uses_style_and_impression_section():
    seen = {}

    class R:
        class output:
            sentences = ["Written."]

    async def runner(**kw):
        seen.update(kw)
        return R
    opts = [{"kind": "impression", "text": "3 cm mass"},
            {"kind": "finding_negative", "section": "Solid organs", "text": "no liver lesion", "finding": "mass"}]
    out = await rc.write_options(opts, "f", "CT", model="m", runner=runner,
                                 style="Quoted: \"Uncomplicated appendicitis.\"", impression_section="CONCLUSION")
    assert out[0] == {"id": "opt0", "kind": "impression", "section": "CONCLUSION", "sentence": "Written.",
                      "reason": "", "source": "3 cm mass"}
    assert out[1]["section"] == "Solid organs" and out[1]["sentence"] == "No liver lesion."
    assert "Uncomplicated appendicitis" in seen["user_prompt"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_generation_artifacts.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'rapid_reports_ai.generation_artifacts'`.

- [ ] **Step 3: Implement `generation_artifacts.py`**

```python
"""The generation contract the Review rail reads, whichever pathway produced the report
(spec 2026-09-30-template-pipeline-mirror-design §4)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class GenerationArtifacts(BaseModel):
    report: str
    dictated_findings: str
    sections: List[str]                 # ordered output headings
    options: List[dict]                 # {id, kind, section, sentence, reason, source, finding?}
    brief: Optional[dict] = None        # {"decisions": {...}} — routing rows
    quality_check: Optional[dict] = None

    @classmethod
    def from_candidate(cls, record: dict, dictated_findings: str) -> "GenerationArtifacts":
        sections = list(record.get("sections") or [])
        brief = record.get("brief")
        return cls(report=record.get("content", ""), dictated_findings=dictated_findings, sections=sections,
                   options=[o for o in record.get("options") or [] if o.get("section") in sections],
                   brief={"decisions": brief.get("decisions")} if brief else None,
                   quality_check=record.get("quality_check"))
```

- [ ] **Step 4: Move the option writer into `report_reconcile.py`**

Add to `report_reconcile.py` (below `_plan`):

```python
class _OptionSentences(BaseModel):
    sentences: List[str]

    @field_validator("sentences", mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return json.loads(v) if isinstance(v, str) else v


OPTION_SYS = ("Write one sentence for the IMPRESSION of a radiology report for each numbered item, in order. "
              "A 'recommendation' item becomes a recommendation sentence naming the test or service and, where "
              "the item gives one, its urgency; drop any condition in brackets once it is met. An 'impression' "
              "item becomes a compressed statement of that dictated finding. Use only facts in the item and the "
              "findings. British English, consultant voice, no preamble. Return JSON {\"sentences\": [...]}.")


async def write_options(options: List[dict], findings: str, scan_type: str, *, model: str, runner,
                        style: str = "", impression_section: str = "IMPRESSION") -> List[dict]:
    """Reporter-choice items. Impression and recommendation items get one sentence each from a
    writer call beside the generator; finding-linked negatives are already in report form and
    pass through. On a writer failure only the written items are lost. `runner` is the caller's
    _run_agent_with_model (so each pathway's tests patch their own module); `style` carries a
    template sheet's impression examples and terminology."""
    direct = [o for o in options if o["kind"] == "finding_negative"]
    to_write = [o for o in options if o["kind"] != "finding_negative"]
    passed = [{"id": f"fn{i}", "kind": o["kind"], "section": o.get("section", "FINDINGS"),
               "sentence": o["text"][:1].upper() + o["text"][1:].rstrip(".") + ".", "reason": o.get("reason", ""), "source": o["text"],
               "finding": o.get("finding", "")}
              for i, o in enumerate(direct)]
    if not to_write:
        return passed
    try:
        items = "\n".join(f"{i}. [{o['kind']}] {o['text']}" for i, o in enumerate(to_write))
        user = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}\n\nITEMS:\n{items}"
        if style:
            user += f"\n\nWRITE IN THIS REPORTER'S STYLE:\n{style}"
        r = await asyncio.wait_for(runner(
            model_name=model, output_type=_OptionSentences, system_prompt=OPTION_SYS, user_prompt=user,
            api_key="", model_settings={"temperature": 0.2, "max_tokens": 2000, "reasoning_effort": "none"}), 10.0)
        sentences = r.output.sentences
    except Exception as e:
        logger.warning("option sentences failed (%s: %s); no written options offered", type(e).__name__, str(e)[:200])
        return passed
    written = [{"id": f"opt{i}", "kind": o["kind"], "section": impression_section, "sentence": s.strip(),
                "reason": o.get("reason", ""), "source": o["text"]}
               for i, (o, s) in enumerate(zip(to_write, sentences)) if s and s.strip()]
    return written + passed
```

In `quick_report_generator.py`, delete `_OptionSentences` and replace `_write_options` with:

```python
async def _write_options(options: List[dict], findings: str, scan_type: str) -> List[dict]:
    """Reporter-choice items; the writer is shared (report_reconcile.write_options)."""
    return await write_options(options, findings, scan_type, model=MODEL_CONFIG["QUICK_REPORT_GENERATOR"],
                               runner=_run_agent_with_model)
```

with `from .report_reconcile import write_options` added to its imports and the now-unused `json`, `BaseModel`, `field_validator` imports removed. `runner=_run_agent_with_model` is read from this module's globals at call time, so tests that patch `qrg._run_agent_with_model` still work, and the system/user prompt text is unchanged when `style` is empty.

- [ ] **Step 5: Add `sections` to the quick candidate record**

In `quick_report_api.py`, in the success record (around line 336), add after `"description": result.get("description"),`:

```python
            # Ordered output headings — the Review rail keys items by section (GenerationArtifacts).
            "sections": header_names(result.get("report_content", "")),
```

and import `from .report_review import header_names` at the top of the module.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest -q tests/test_generation_artifacts.py tests/test_quick_report_brief.py tests/test_confirmed_negatives.py tests/test_report_path_split.py tests/test_golden_quick_pipeline.py`
Expected: all pass, including `test_shared_modules_import_neither_pathway`.

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/generation_artifacts.py src/rapid_reports_ai/report_reconcile.py src/rapid_reports_ai/quick_report_generator.py src/rapid_reports_ai/quick_report_api.py tests/test_generation_artifacts.py
git commit -m "feat(artifacts): GenerationArtifacts contract; option writer shared; quick records sections"
```

- [ ] **Step 8: Full suite checkpoint**

Run: `uv run pytest -q`
Expected: all pass (baseline count + new tests). If anything outside the touched files fails, stop and fix before Phase B.

---

## Phase B — Save-time sheet structure

### Task 6: Structure schema and code verification

**Files:**
- Create: `src/rapid_reports_ai/template_sheet_structure.py`
- Create: `tests/fixtures/template_sheet.md`, `tests/test_template_sheet_structure.py`

- [ ] **Step 1: Create the fixture sheet** (synthetic, stored-sheet format)

`tests/fixtures/template_sheet.md`:

```markdown
# Skill Sheet: CT Abdomen and Pelvis

## Scan Context
- Modality: CT Abdomen and Pelvis

## Structural Pattern
- Sections included, in order:
  - CLINICAL HISTORY
  - FINDINGS (implicit header)
  - IMPRESSION
- For each section:
  - CLINICAL HISTORY: `header: "CLINICAL HISTORY"`
  - FINDINGS: always present, `header: none`
  - IMPRESSION: always present, `header: "Impression"`

## Fixed Blocks
None identified in provided examples.

## Per-Section Construction Rules

### Primary Pathology Paragraph
- **header**: `none`
- **Mandatory negatives**:
  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."
  - "No periappendiceal collection." (if appendicitis)
- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."

## Terminology Rules
- **Preferred terms**: "unremarkable", "size significant".
- **Suppressed terms**: "normal" (prefers "unremarkable").

## Interpretive Clause Rules
- IF [inflammatory morphology] THEN append "consistent with {diagnosis}."

## Conditional Suppression Rules
- IF [pneumoperitoneum is present] THEN suppress "No pneumoperitoneum." AND replace with "Free intra-abdominal air is present."
- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.

## Impression Construction Rules

### Quoted examples
1. "Uncomplicated acute appendicitis."

### Inclusion logic
- Promoted to Impression: primary pathology.

### Normal study impression
- "No acute intra-abdominal abnormality."

## Negative Finding Rules
- "No pneumoperitoneum."
```

- [ ] **Step 2: Write the failing verification tests**

```python
"""Save-time structure: verification and the coverage gate (spec §2)."""
from __future__ import annotations

import pathlib

from rapid_reports_ai import template_sheet_structure as tss

SHEET = (pathlib.Path(__file__).parent / "fixtures" / "template_sheet.md").read_text()
IF_SUPPRESS = '- IF [pneumoperitoneum is present] THEN suppress "No pneumoperitoneum." AND replace with "Free intra-abdominal air is present."'


def good_draft() -> tss.StructureDraft:
    return tss.StructureDraft(
        sections=[{"name": "CLINICAL HISTORY", "role": "history", "header": "CLINICAL HISTORY", "order": 0},
                  {"name": "FINDINGS", "role": "findings", "header": None, "order": 1},
                  {"name": "IMPRESSION", "role": "impression", "header": "Impression", "order": 2}],
        paragraphs=[{"id": "p0", "section": "FINDINGS", "name": "Primary Pathology Paragraph"}],
        rules=[{"id": "r0", "section": "FINDINGS", "paragraph": "p0", "condition": "The dictated findings report inflammatory morphology",
                "condition_source": "findings", "effect": "append", "then_text": "consistent with {diagnosis}.",
                "source_lines": ['- IF [inflammatory morphology] THEN append "consistent with {diagnosis}."']},
               {"id": "r1", "section": "FINDINGS", "paragraph": "p0", "condition": "The dictated findings report pneumoperitoneum",
                "condition_source": "findings", "effect": "replace", "target": "No pneumoperitoneum.",
                "then_text": "Free intra-abdominal air is present.", "source_lines": [IF_SUPPRESS]},
               {"id": "r2", "section": "FINDINGS", "paragraph": "", "condition": "The clinical context is oncology",
                "condition_source": "context", "effect": "use", "then_text": "no suspicious osseous lesion",
                "source_lines": ['- **IF [oncology context]** THEN use "no suspicious osseous lesion" for bones.']}],
        negatives=[{"id": "n0", "section": "FINDINGS", "paragraph": "p0", "text": "No pneumoperitoneum.",
                    "source_lines": ['  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."', '- "No pneumoperitoneum."']},
                   {"id": "n1", "section": "FINDINGS", "paragraph": "p0", "text": "No free intra-abdominal air or fluid.",
                    "source_lines": ['  - "No pneumoperitoneum." / "No free intra-abdominal air or fluid."']},
                   {"id": "n2", "section": "FINDINGS", "paragraph": "p0", "text": "No periappendiceal collection.",
                    "condition": "The dictated findings report appendicitis",
                    "source_lines": ['  - "No periappendiceal collection." (if appendicitis)']}],
        normals=[{"id": "m0", "section": "FINDINGS", "paragraph": "p0", "structure": "gallbladder",
                  "text": "Unremarkable appearances of the gallbladder.",
                  "source_line": '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'},
                 {"id": "m1", "section": "FINDINGS", "paragraph": "p0", "structure": "spleen",
                  "text": "Unremarkable appearances of the spleen.",
                  "source_line": '- **Normal pattern**: "Unremarkable appearances of the gallbladder, spleen and kidneys."'}],
        terminology={"preferred": ["unremarkable", "size significant"], "suppressed": ["normal"]},
        if_present=[{"finding": "appendicitis", "section": "FINDINGS", "paragraph": "p0",
                     "negatives": [{"text": "No appendicolith", "tag": "contextual"}]}])


def test_good_draft_is_usable_and_covered():
    s = tss.build_structure(SHEET, good_draft(), model="m")
    assert s.usable, s.coverage
    assert s.coverage.if_lines == 3 and s.coverage.if_covered == 3
    assert s.coverage.negative_lines == 3 and s.coverage.negative_covered == 3
    assert s.sheet_hash == tss.sheet_hash(SHEET)


def test_invented_negative_is_dropped_and_logged():
    d = good_draft()
    d.negatives.append(tss.Negative(id="n9", section="FINDINGS", text="No bowel obstruction.", source_lines=['- "No bowel obstruction."']))
    s = tss.build_structure(SHEET, d, model="m")
    assert all(n.id != "n9" for n in s.negatives)
    assert any("No bowel obstruction" in v for v in s.coverage.verbatim_failures)


def test_uncovered_if_line_fails_the_gate():
    d = good_draft()
    d.rules = [r for r in d.rules if r.id != "r2"]
    s = tss.build_structure(SHEET, d, model="m")
    assert not s.usable and any("oncology" in u for u in s.coverage.uncovered)


def test_uncovered_negative_line_fails_the_gate():
    d = good_draft()
    d.negatives = [n for n in d.negatives if n.id != "n2"]
    assert not tss.build_structure(SHEET, d, model="m").usable


def test_atomic_normal_must_come_from_its_source_line():
    d = good_draft()
    d.normals[0].text = "Unremarkable appearances of the pancreas."
    s = tss.build_structure(SHEET, d, model="m")
    assert [n.id for n in s.normals] == ["m1"]


def test_if_present_must_be_a_negative_and_not_a_sheet_duplicate():
    d = good_draft()
    d.if_present[0].negatives += [tss.IfPresentNeg(text="Appendix dilated", tag="core"),
                                  tss.IfPresentNeg(text="No pneumoperitoneum", tag="core")]
    s = tss.build_structure(SHEET, d, model="m")
    assert [n.text for n in s.if_present[0].negatives] == ["No appendicolith"]


def test_section_not_in_structural_pattern_is_dropped():
    d = good_draft()
    d.sections.append(tss.StructSection(name="LIMITATIONS", role="other", header="LIMITATIONS", order=3))
    assert [x.name for x in tss.build_structure(SHEET, d, model="m").sections] == ["CLINICAL HISTORY", "FINDINGS", "IMPRESSION"]


def test_fresh_needs_matching_hash_version_and_usable():
    s = tss.build_structure(SHEET, good_draft(), model="m")
    cfg = {"skill_sheet": SHEET, "sheet_structure": s.model_dump(mode="json")}
    assert tss.fresh(cfg) is not None
    assert tss.fresh({**cfg, "skill_sheet": SHEET + "\n- edited"}) is None
    assert tss.fresh({"skill_sheet": SHEET}) is None
    assert tss.needs_restructure({**cfg, "skill_sheet": SHEET + "x"}) and not tss.needs_restructure(cfg)
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_sheet_structure.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Implement the schema and verification**

`src/rapid_reports_ai/template_sheet_structure.py`:

```python
"""Save-time structure of a stored template skill sheet (spec 2026-09-30-template-pipeline-mirror §2).

A template sheet is the radiologist's voice with irregular conditionals. A model pass turns it into
typed items once; code keeps only what it can ground in the sheet, and marks the structure usable
only when every conditional line and every negative line is covered. The lean _BRIEF prompts only
ever meet a fully labelled sheet; anything else generates down the raw path.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

from .report_review import is_negative

logger = logging.getLogger(__name__)

STRUCTURE_VERSION = 1
Role = Literal["history", "technique", "comparison", "findings", "impression", "other"]


def _listify(v):
    return json.loads(v) if isinstance(v, str) else v


class StructSection(BaseModel):
    name: str
    role: Role
    header: Optional[str] = None
    order: int


class Paragraph(BaseModel):
    id: str
    section: str
    name: str


class Rule(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    condition: str
    condition_source: Literal["findings", "history", "context"] = "findings"
    effect: Literal["suppress", "replace", "append", "use"]
    target: str = ""
    then_text: str = ""
    source_lines: List[str]


class Negative(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    text: str
    condition: Optional[str] = None
    source_lines: List[str]


class Normal(BaseModel):
    id: str
    section: str
    paragraph: str = ""
    structure: str
    text: str
    source_line: str


class FixedBlock(BaseModel):
    id: str
    section: str
    text: str


class Terminology(BaseModel):
    preferred: List[str] = []
    suppressed: List[str] = []


class IfPresentNeg(BaseModel):
    text: str
    tag: Literal["core", "contextual"]


class IfPresent(BaseModel):
    finding: str
    section: str
    paragraph: str = ""
    negatives: List[IfPresentNeg]


class Coverage(BaseModel):
    if_lines: int = 0
    if_covered: int = 0
    negative_lines: int = 0
    negative_covered: int = 0
    uncovered: List[str] = []
    verbatim_failures: List[str] = []


class StructureDraft(BaseModel):
    """What the model returns; build_structure verifies it."""
    sections: List[StructSection]
    paragraphs: List[Paragraph] = []
    rules: List[Rule] = []
    negatives: List[Negative] = []
    normals: List[Normal] = []
    fixed_blocks: List[FixedBlock] = []
    terminology: Terminology = Terminology()
    if_present: List[IfPresent] = []

    @field_validator("sections", "paragraphs", "rules", "negatives", "normals", "fixed_blocks", "if_present",
                     mode="before")
    @classmethod
    def _parse_stringified(cls, v):
        return _listify(v)


class SheetStructure(StructureDraft):
    version: int = STRUCTURE_VERSION
    sheet_hash: str
    model: str
    created_at: str
    usable: bool = False
    coverage: Coverage = Coverage()


# ── verification ─────────────────────────────────────────────────────────────

def sheet_hash(sheet: str) -> str:
    return hashlib.sha256(sheet.encode()).hexdigest()


def _norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = s.replace("—", "-").replace("–", "-").replace("*", "").replace("`", "")
    s = re.sub(r"^\s*(?:-|\d+\.)\s+", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", _norm(s)))


def _covers(source_line: str, line: str) -> bool:
    a, b = _norm(source_line), _norm(line)
    return bool(a) and (a == b or (a in b and len(a) >= 0.6 * len(b)) or b in a)


def conditional_lines(sheet: str) -> List[str]:
    """Sheet lines that carry a conditional (an uppercase IF), outside headings."""
    return [ln for ln in sheet.splitlines() if re.search(r"\bIF\b", ln) and not ln.lstrip().startswith("#")]


def negative_lines(sheet: str) -> List[str]:
    """Quoted lines under a paragraph's Mandatory negatives bullet, and every quoted bullet under
    '## Negative Finding Rules'."""
    out, section, in_mand, mand_indent = [], "", False, 0
    for ln in sheet.splitlines():
        if ln.startswith("## "):
            section, in_mand = ln[3:].strip(), False
            continue
        if ln.startswith("#"):
            in_mand = False
            continue
        indent = len(ln) - len(ln.lstrip())
        if "Mandatory negatives" in ln:
            in_mand, mand_indent = True, indent
            continue
        if in_mand and ln.strip() and indent <= mand_indent:
            in_mand = False
        quoted = re.match(r'^\s*-\s+["“]', ln)
        if quoted and (in_mand or section == "Negative Finding Rules"):
            out.append(ln)
    return out


def _structural_pattern(sheet: str) -> str:
    m = re.search(r"^## Structural Pattern\n(.*?)(?=^## |\Z)", sheet, re.M | re.S)
    return m.group(1) if m else ""


def build_structure(sheet: str, draft: StructureDraft, model: str) -> SheetStructure:
    """Keep only what is grounded in the sheet, then gate on coverage."""
    ns = _norm(sheet)
    failures: List[str] = []

    def grounded(label: str, *texts: str) -> bool:
        bad = [t for t in texts if t and _norm(t) not in ns]
        failures.extend(f"{label}: {t}" for t in bad)
        return not bad

    pattern = _structural_pattern(sheet).lower()
    sections = [s for s in draft.sections if s.name.lower() in pattern]
    rules = [r for r in draft.rules if grounded(f"rule {r.id}", r.target, r.then_text, *r.source_lines)]
    negatives = [n for n in draft.negatives if grounded(f"negative {n.id}", n.text, *n.source_lines)]
    normals = [n for n in draft.normals
               if grounded(f"normal {n.id}", n.source_line) and _words(n.text) <= _words(n.source_line)
               or failures.append(f"normal {n.id}: {n.text}")]
    fixed = [b for b in draft.fixed_blocks if grounded(f"fixed {b.id}", b.text)]
    term = Terminology(preferred=[t for t in draft.terminology.preferred if grounded("preferred", t)],
                       suppressed=[t for t in draft.terminology.suppressed if grounded("suppressed", t)])
    sheet_negs = {_norm(n.text).rstrip(".") for n in negatives}
    if_present = []
    for ip in draft.if_present:
        keep = [x for x in ip.negatives if is_negative(x.text) and _norm(x.text).rstrip(".") not in sheet_negs]
        if keep:
            if_present.append(ip.model_copy(update={"negatives": keep}))

    ifs, negs = conditional_lines(sheet), negative_lines(sheet)
    rule_src = [sl for r in rules for sl in r.source_lines]
    neg_src = [sl for n in negatives for sl in n.source_lines]
    unc_if = [ln for ln in ifs if not any(_covers(sl, ln) for sl in rule_src)]
    unc_neg = [ln for ln in negs if not any(_covers(sl, ln) for sl in neg_src)]
    cov = Coverage(if_lines=len(ifs), if_covered=len(ifs) - len(unc_if), negative_lines=len(negs),
                   negative_covered=len(negs) - len(unc_neg), uncovered=[ln.strip() for ln in unc_if + unc_neg],
                   verbatim_failures=failures)
    return SheetStructure(
        sections=sections, paragraphs=draft.paragraphs, rules=rules, negatives=negatives, normals=normals,
        fixed_blocks=fixed, terminology=term, if_present=if_present, sheet_hash=sheet_hash(sheet), model=model,
        created_at=datetime.now(timezone.utc).isoformat(), coverage=cov,
        usable=bool(sections) and not unc_if and not unc_neg)


def _stored(config: dict) -> Optional[SheetStructure]:
    raw = (config or {}).get("sheet_structure")
    if not raw:
        return None
    try:
        return SheetStructure.model_validate(raw)
    except Exception:
        return None


def fresh(config: dict) -> Optional[SheetStructure]:
    """The stored structure if it matches this sheet, this version, and passed the gate."""
    s = _stored(config)
    sheet = (config or {}).get("skill_sheet", "")
    if s and s.version == STRUCTURE_VERSION and s.sheet_hash == sheet_hash(sheet) and s.usable:
        return s
    return None


def needs_restructure(config: dict) -> bool:
    """Missing, old or stale (an unusable but current structure is not rebuilt on every request)."""
    s = _stored(config)
    sheet = (config or {}).get("skill_sheet", "")
    return bool(sheet) and (s is None or s.version != STRUCTURE_VERSION or s.sheet_hash != sheet_hash(sheet))
```

Note the `normals` comprehension: `grounded(...) and provenance or failures.append(...)` — `failures.append` returns `None`, so a failing normal is logged and excluded.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q tests/test_template_sheet_structure.py`
Expected: 8 passed. If `test_good_draft_is_usable_and_covered` reports different line counts, print `tss.conditional_lines(SHEET)` / `tss.negative_lines(SHEET)` and fix the scanner, not the fixture.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/template_sheet_structure.py tests/fixtures/template_sheet.md tests/test_template_sheet_structure.py
git commit -m "feat(template): sheet structure schema, verification and coverage gate"
```

### Task 7: Structuring call, prompt and background store

**Files:**
- Modify: `src/rapid_reports_ai/template_sheet_structure.py`
- Modify: `tests/test_template_sheet_structure.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
from rapid_reports_ai.enhancement_utils import MODEL_CONFIG  # noqa: E402


async def test_structure_sheet_calls_the_model_and_verifies(monkeypatch):
    seen = {}

    class R:
        output = good_draft()

    async def fake_run(**kw):
        seen.update(kw)
        return R
    monkeypatch.setattr(tss, "_run_agent_with_model", fake_run)
    s = await tss.structure_sheet(SHEET, model="gpt-oss-120b")
    assert s.usable and s.model == "gpt-oss-120b"
    assert seen["user_prompt"].endswith(SHEET) and "IF [condition]" in seen["system_prompt"]
    for clinical in ("appendic", "pneumoperitoneum", "liver"):
        assert clinical not in tss.STRUCTURE_SYS.lower(), clinical


async def test_store_skips_when_the_sheet_changed_meanwhile(monkeypatch):
    s = tss.build_structure(SHEET, good_draft(), model="m")

    class T:
        template_config = {"skill_sheet": SHEET + "\nedited", "generation_mode": "skill_sheet_guided"}

    class DB:
        committed = False

        def query(self, *_):
            return self

        def filter(self, *_):
            return self

        def first(self):
            return T

        def commit(self):
            DB.committed = True

        def close(self):
            pass
    assert tss.store_structure(DB(), "00000000-0000-0000-0000-000000000000", s) is False
    assert DB.committed is False
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_sheet_structure.py -k "structure_sheet or store"`
Expected: FAIL, `AttributeError: ... 'structure_sheet'`.

- [ ] **Step 3: Implement**

Append to `template_sheet_structure.py`:

```python
import asyncio  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402

from .enhancement_utils import _run_agent_with_model  # noqa: E402

STRUCTURE_TIMEOUT_S = 120.0


def structure_model() -> str:
    """Chosen in E1 (ledger); overridable on Railway."""
    return os.environ.get("RR_STRUCTURE_MODEL", "gpt-oss-120b")


STRUCTURE_SYS = """You convert a radiology report skill sheet into typed items. The sheet is the reporter's own style guide; you do not change it, judge it or add to it, except for the if_present list. Copy text exactly as it appears in the sheet (same words, same punctuation) wherever a field says "verbatim". Return JSON only.

sections — the report's OUTPUT sections from the Structural Pattern, in order: name, role (history | technique | comparison | findings | impression | other), header exactly as reports write it (null when the sheet says the header is none or implicit), order (0-based). Paragraph groupings inside a section are not sections.

paragraphs — each "### <name>" block under Per-Section Construction Rules: id (p0, p1, …), the output section it belongs to, name.

rules — one per sheet line that holds a conditional, in any form: IF [condition] THEN suppress "[negative]", IF [condition] THEN append "[clause]", IF x: "[text]", bold **IF [..]**, compound OR conditions. id (r0, …); section and paragraph id where it applies; condition rewritten as one plain statement that can be judged true or false for a case ("The dictated findings report [X]" for an imaging condition; "The clinical history reports [Y]" or "The clinical context is [Z]" for a history or context condition); condition_source: findings | history | context; effect: suppress (drop the target text) | replace (drop the target text and write then_text) | append (add then_text, e.g. an interpretive clause) | use (a phrasing variant); target: the text it suppresses or replaces, verbatim, else ""; then_text: the text it adds, verbatim, else ""; source_lines: the whole sheet line(s), verbatim. Every conditional line in the sheet must appear in some rule's source_lines.

negatives — every quoted negative statement listed under a paragraph's Mandatory negatives and under Negative Finding Rules. One item per statement: a line holding two quoted statements gives two items with the same source line. The same statement listed in several places is ONE item whose source_lines lists every line it appears on. text verbatim (the quoted statement); condition: when the line attaches one ("(if [X])"), the plain statement "The dictated findings report [X]", else null; source_lines verbatim.

normals — split every Normal pattern into one item per structure it names: structure (the structure's name), text (a sentence for that structure alone, using only words from the pattern line: "Unremarkable appearances of the [A], [B] and [C]." gives "Unremarkable appearances of the [A]." and so on), source_line verbatim.

fixed_blocks — each fixed block's text, verbatim. Empty when the sheet says none were identified.

terminology — preferred and suppressed terms, verbatim, one term each.

if_present — the only list you write rather than copy. For the findings this scan commonly reports, give the finding (a short general name) and up to three negatives a consultant states once that finding is reported: the absence of each extension, spread or complication this technique shows and the next management step depends on. One finding per negative, starting "No", written in this sheet's own negative style. tag core when the next management step depends on it, contextual otherwise. Never repeat a negative the sheet already lists. Assign each to the section and paragraph where the finding is described."""


async def structure_sheet(sheet: str, model: Optional[str] = None) -> SheetStructure:
    model = model or structure_model()
    r = await asyncio.wait_for(_run_agent_with_model(
        model_name=model, output_type=StructureDraft, system_prompt=STRUCTURE_SYS,
        user_prompt=f"SKILL SHEET:\n\n{sheet}", api_key="",
        model_settings={"temperature": 0, "max_tokens": 32000, "reasoning_effort": "low"}), STRUCTURE_TIMEOUT_S)
    return build_structure(sheet, r.output, model)


def store_structure(db, template_id: str, structure: SheetStructure) -> bool:
    """Write the structure only if the template's sheet is still the one it was built from."""
    from sqlalchemy.orm.attributes import flag_modified
    from .database.models import Template
    tpl = db.query(Template).filter(Template.id == uuid.UUID(str(template_id))).first()
    if not tpl or sheet_hash((tpl.template_config or {}).get("skill_sheet", "")) != structure.sheet_hash:
        return False
    tpl.template_config = {**tpl.template_config, "sheet_structure": structure.model_dump(mode="json")}
    flag_modified(tpl, "template_config")
    db.commit()
    return True


_inflight: set = set()


def schedule_structure(template_id: str, sheet: str) -> None:
    """Background: structure the sheet and store it. Never raises; one task per (template, sheet)."""
    key = (str(template_id), sheet_hash(sheet))
    if key in _inflight:
        return
    _inflight.add(key)

    async def run():
        from .database import SessionLocal
        try:
            s = await structure_sheet(sheet)
            db = SessionLocal()
            try:
                ok = store_structure(db, template_id, s)
            finally:
                db.close()
            logger.info("sheet structure %s: stored=%s usable=%s coverage=%s", template_id, ok, s.usable,
                        s.coverage.model_dump())
        except Exception as e:
            logger.warning("sheet structure %s failed (%s: %s)", template_id, type(e).__name__, str(e)[:200])
        finally:
            _inflight.discard(key)
    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        _inflight.discard(key)
```

Move the new imports to the top of the module with the others (they are shown inline here only for readability).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_template_sheet_structure.py`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_sheet_structure.py tests/test_template_sheet_structure.py
git commit -m "feat(template): structuring call, case-agnostic prompt, guarded background store"
```

### Task 8: Structure triggers on save and update

**Files:**
- Modify: `src/rapid_reports_ai/main.py` (`skill_sheet_save_endpoint` ~2505, `update_template_endpoint` ~1656)
- Create: `tests/test_template_structure_triggers.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Every sheet write queues a restructure; an unchanged sheet keeps its structure (spec §2)."""
from __future__ import annotations

from rapid_reports_ai import main
from rapid_reports_ai import template_sheet_structure as tss


def test_carry_structure_keeps_a_fresh_structure_the_client_dropped():
    old = {"skill_sheet": "S", "sheet_structure": {"sheet_hash": tss.sheet_hash("S")}}
    assert main._carry_structure({"skill_sheet": "S"}, old)["sheet_structure"] == old["sheet_structure"]
    assert "sheet_structure" not in main._carry_structure({"skill_sheet": "S2"}, old)


def test_save_and_update_schedule_structuring(monkeypatch):
    calls = []
    monkeypatch.setattr(tss, "schedule_structure", lambda tid, sheet: calls.append((tid, sheet)))
    main._queue_structure("t1", {"generation_mode": "skill_sheet_guided", "skill_sheet": "S"})
    main._queue_structure("t2", {"generation_mode": "legacy"})
    assert calls == [("t1", "S")]
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_structure_triggers.py`
Expected: FAIL, `AttributeError: module 'rapid_reports_ai.main' has no attribute '_carry_structure'`.

- [ ] **Step 3: Implement in `main.py`**

Add near the template endpoints:

```python
from . import template_sheet_structure as tss


def _carry_structure(new_config: dict, old_config: dict) -> dict:
    """PUT replaces template_config wholesale; keep the stored structure when the sheet is unchanged."""
    old = old_config or {}
    if (new_config.get("skill_sheet") and "sheet_structure" not in new_config
            and old.get("skill_sheet") == new_config.get("skill_sheet") and old.get("sheet_structure")):
        return {**new_config, "sheet_structure": old["sheet_structure"]}
    return new_config


def _queue_structure(template_id: str, config: dict) -> None:
    if (config or {}).get("generation_mode") == "skill_sheet_guided" and tss.needs_restructure(config):
        tss.schedule_structure(template_id, config["skill_sheet"])
```

In `skill_sheet_save_endpoint`, after `template = create_template(...)`: `_queue_structure(str(template.id), template_config)`.

In `update_template_endpoint`, before `update_template(...)`:

```python
        if template_config:
            existing = get_template(db, template_id, user_id=str(current_user.id))
            template_config = _carry_structure(template_config, existing.template_config if existing else {})
```

and after `if not updated_template: ...`: `_queue_structure(template_id, updated_template.template_config)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_template_structure_triggers.py`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/main.py tests/test_template_structure_triggers.py
git commit -m "feat(template): queue sheet structuring on save and update"
```

### Task 9: E1 script (structuring evaluation + backfill)

**Files:**
- Create: `src/rapid_reports_ai/scripts/template_structure_eval.py`

- [ ] **Step 1: Write the script**

```python
"""E1 (spec §6): structure the stored skill_sheet_guided sheets with one model, score in code,
write per-sheet outputs for the hand read; --write stores usable structures (backfill).

  railway run --service <backend> -- uv run python -m rapid_reports_ai.scripts.template_structure_eval \
      --model gpt-oss-120b --out test_output/template_structure_e1_gptoss_$$
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import time

from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import SessionLocal
from rapid_reports_ai.database.models import Template


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--write", action="store_true", help="store usable structures (backfill)")
    ap.add_argument("--only", default="", help="comma-separated template ids")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    rows = [t for t in db.query(Template).filter(Template.is_active.is_(True)).all()
            if (t.template_config or {}).get("generation_mode") == "skill_sheet_guided"
            and (not a.only or str(t.id) in a.only.split(","))]
    sem = asyncio.Semaphore(4)

    async def one(t):
        async with sem:
            t0 = time.time()
            try:
                s = await tss.structure_sheet(t.template_config["skill_sheet"], model=a.model)
                err = None
            except Exception as e:
                s, err = None, f"{type(e).__name__}: {str(e)[:300]}"
            rec = {"id": str(t.id), "name": t.name, "ms": int((time.time() - t0) * 1000), "error": err,
                   "usable": bool(s and s.usable), "coverage": s.coverage.model_dump() if s else None,
                   "n": {k: len(getattr(s, k)) for k in ("sections", "rules", "negatives", "normals", "if_present")} if s else None,
                   "context_rules": [r.model_dump() for r in s.rules if r.condition_source != "findings"] if s else []}
            (out / f"{t.id}.json").write_text(json.dumps({"summary": rec, "structure": s.model_dump(mode="json") if s else None}, indent=1))
            if a.write and s and s.usable:
                rec["stored"] = tss.store_structure(db, str(t.id), s)
            return rec
    recs = await asyncio.gather(*(one(t) for t in rows))
    summary = {"model": a.model, "pid": os.getpid(), "n": len(recs), "usable": sum(r["usable"] for r in recs),
               "errors": sum(bool(r["error"]) for r in recs),
               "if_cov": sum((r["coverage"] or {}).get("if_covered", 0) for r in recs),
               "if_lines": sum((r["coverage"] or {}).get("if_lines", 0) for r in recs),
               "verbatim_failures": sum(len((r["coverage"] or {}).get("verbatim_failures", [])) for r in recs),
               "rows": recs}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke-import it**

Run: `PYTHONPATH=src uv run python -c "import rapid_reports_ai.scripts.template_structure_eval"`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/rapid_reports_ai/scripts/template_structure_eval.py
git commit -m "feat(eval): E1 structuring evaluation and backfill script"
```

### Task 10: Run E1 against prod (evaluation, no code)

Hassan authorised direct prod reads and writes (2026-09-30). Reads only in this task.

- [ ] **Step 1: Find the backend service name and confirm DB access**

Run: `railway status` and `railway service` (list); then
`railway run --service <backend-service> -- uv run python -c "from rapid_reports_ai.database import SessionLocal; from rapid_reports_ai.database.models import Template; db=SessionLocal(); print(db.query(Template).count())"`
Expected: a template count (57). If `DATABASE_URL` is the private Railway hostname and unreachable locally, use the Postgres service's `DATABASE_PUBLIC_URL`: `railway variables --service Postgres-78CY --kv | grep DATABASE_PUBLIC_URL` and run with `DATABASE_URL=<that>` exported for the command only.

- [ ] **Step 2: Run 1, both arms**

```bash
cd backend
railway run --service <backend-service> -- uv run python -m rapid_reports_ai.scripts.template_structure_eval --model gpt-oss-120b --out test_output/template_structure_e1_gptoss_$$
railway run --service <backend-service> -- uv run python -m rapid_reports_ai.scripts.template_structure_eval --model qwen-3.8-27b --out test_output/template_structure_e1_qwen_$$
```

Expected: two summaries; record n, usable, errors, if_cov/if_lines, verbatim_failures.

- [ ] **Step 3: Hand read**

Read, for the better arm (and the worse arm's failures): every sheet with `usable: false` (its `uncovered` and `verbatim_failures`), every `context_rules` entry (none may be an imaging condition answered from history — the accepted risk), and 6 varied sheets end to end (polytrauma, CMR, lumbar spine, aorta, CT abdomen/pelvis, knee): sections match the Structural Pattern, rules resolve the right target, atomic normals read naturally, if_present negatives are pertinent and in the sheet's voice.

- [ ] **Step 4: Fix the prompt on the winner's failures, then run 2 (winner only)**

Edit only `STRUCTURE_SYS` (case-agnostic wording) and/or the scanners if a failure is a scanner artefact (add a unit test for the artefact first). Rerun the winner once to a new `_$$` directory; compare item-level agreement with run 1 (same rule/negative ids per sheet).

- [ ] **Step 5: Bar and decision**

Bar: 26/26 schema-valid; usable ≥ 24/26; no fabricated item surviving verification in the hand read; no findings condition tagged history/context. Set `structure_model()`'s default to the winner if it is not gpt-oss, commit, and note the numbers for the ledger entry (Task 20).

```bash
git add src/rapid_reports_ai/template_sheet_structure.py tests/
git commit -m "tune(template): structuring prompt after E1; <winner> as default"
```

---

## Phase C — Template brief

### Task 11: Template brief — reconcile and decide

**Files:**
- Create: `src/rapid_reports_ai/template_brief.py`, `tests/test_template_brief.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Template brief (spec §3): one test per decision row, rendering in place, gate fallback."""
from __future__ import annotations

import pathlib

import pytest

from rapid_reports_ai import report_reconcile as rc
from rapid_reports_ai import template_brief as tb
from rapid_reports_ai import template_sheet_structure as tss

from test_template_sheet_structure import SHEET, good_draft

STRUCT = tss.build_structure(SHEET, good_draft(), model="m")


def stub(monkeypatch, jev_f: dict, jev_c: dict | None = None, qwen: rc.QwenDecisions | None = None,
         plan: rc.ImpressionPlan | None = None):
    states = []

    async def fake_jev(state, qs):
        states.append((state, set(qs)))
        src = jev_c if "CLINICAL HISTORY" in state and jev_c is not None else jev_f
        return {k: src.get(k, {"noul": 0.1}) for k in qs}

    async def fake_qwen(state, negs, normals, measurements):
        return qwen or rc.QwenDecisions(negatives=[], affected_normals=[], applicable_measurements=[])

    async def no_split(negs):
        return [[n] for n in negs]

    async def fake_plan(scan_type, history, items, recs, inclusion_logic=""):
        if plan is None:
            raise RuntimeError("no plan")
        return plan

    async def no_fallback(state, items, keys):
        return None
    for name, fn in (("_jev", fake_jev), ("_qwen", fake_qwen), ("_split_bundled", no_split),
                     ("_plan", fake_plan), ("_fallback", no_fallback)):
        monkeypatch.setattr(tb.rc, name, fn)
    return states


async def compile_(findings="Dilated appendix 11 mm with fat stranding.", history="?appendicitis"):
    return await tb.compile_template_brief(SHEET, STRUCT, "CT AP", findings, history)


async def test_met_replace_rule_names_omit_and_instead(monkeypatch):
    stub(monkeypatch, {"r1": {"noul": 0.9}})
    b = await compile_(findings="Free air under the diaphragm.")
    assert 'OMIT: "No pneumoperitoneum."' in b.text and 'INSTEAD: "Free intra-abdominal air is present."' in b.text
    assert "IF [pneumoperitoneum is present]" not in b.text
    assert {"id": "r1", "met": True} .items() <= next(r for r in b.decisions["rules"] if r["id"] == "r1").items()


async def test_unmet_rule_line_is_removed_and_target_negative_stands(monkeypatch):
    stub(monkeypatch, {"r1": {"noul": 0.1}})
    b = await compile_()
    assert "IF [pneumoperitoneum is present]" not in b.text
    assert 'KEEP: "No pneumoperitoneum."' in b.text


async def test_append_and_use_rules(monkeypatch):
    stub(monkeypatch, {"r0": {"noul": 0.9}}, jev_c={"r2": {"noul": 0.1}})
    b = await compile_()
    assert 'APPLY: "consistent with {diagnosis}."' in b.text
    assert "no suspicious osseous lesion" not in b.text


async def test_context_rules_go_to_the_history_state_only(monkeypatch):
    states = stub(monkeypatch, {}, jev_c={"r2": {"noul": 0.9}})
    b = await compile_()
    assert 'USE: "no suspicious osseous lesion"' in b.text
    ctx = [qs for s, qs in states if "CLINICAL HISTORY" in s]
    plain = [qs for s, qs in states if "CLINICAL HISTORY" not in s]
    assert ctx == [{"r2"}] and "r2" not in plain[0] and "r1" in plain[0]


async def test_conditional_negative_unmet_is_removed(monkeypatch):
    stub(monkeypatch, {"c2": {"noul": 0.1}})
    b = await compile_(findings="Simple renal cyst.")
    assert "periappendiceal" not in b.text


async def test_classifier_labels_every_copy_of_a_negative(monkeypatch):
    q = rc.QwenDecisions(negatives=[rc.NegativeDecision(index=0, action="contradicted", dictated_finding="free air")],
                         affected_normals=[], applicable_measurements=[])
    stub(monkeypatch, {}, qwen=q)
    b = await compile_(findings="Free air.")
    assert b.text.count('OMIT: "No pneumoperitoneum."') == 2          # paragraph block and Negative Finding Rules
    assert '- "No pneumoperitoneum."' not in b.text


async def test_affected_atomic_normal_flags_only_its_structure(monkeypatch):
    stub(monkeypatch, {"n1": {"noul": 0.9}})
    b = await compile_(findings="Splenomegaly 16 cm.")
    assert '"Unremarkable appearances of the gallbladder."' in b.text
    assert "Do not assert as normal" in b.text and "Unremarkable appearances of the spleen." in b.text.split("Do not assert as normal")[1]


async def test_if_present_offered_goes_to_its_section(monkeypatch):
    q = rc.QwenDecisions(negatives=[rc.NegativeDecision(index=3, action="keep")], affected_normals=[], applicable_measurements=[])
    stub(monkeypatch, {"f0": {"noul": 0.9}}, qwen=q)
    b = await compile_()
    opt = next(o for o in b.decisions["options"] if o["kind"] == "finding_negative")
    assert opt["section"] == "FINDINGS" and opt["text"] == "No appendicolith" and opt["paragraph"] == "Primary Pathology Paragraph"


async def test_normal_study_impression_dropped_when_anything_is_positive(monkeypatch):
    stub(monkeypatch, {})
    assert "No acute intra-abdominal abnormality" not in (await compile_()).text
    assert "No acute intra-abdominal abnormality" in (await compile_(findings="No abnormality.")).text


async def test_voice_passes_through_verbatim(monkeypatch):
    stub(monkeypatch, {})
    b = await compile_()
    for line in ('- **Preferred terms**: "unremarkable", "size significant".', '1. "Uncomplicated acute appendicitis."'):
        assert line in b.text


async def test_impression_plan_uses_the_sheets_inclusion_logic(monkeypatch):
    seen = {}
    stub(monkeypatch, {})

    async def fake_plan(scan_type, history, items, recs, inclusion_logic=""):
        seen["inc"] = inclusion_logic
        return rc.ImpressionPlan(recommendations=[], impression=[0])
    monkeypatch.setattr(tb.rc, "_plan", fake_plan)
    b = await compile_()
    assert "Promoted to Impression" in seen["inc"] and "Carry forward" in b.text
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_brief.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'rapid_reports_ai.template_brief'`.

- [ ] **Step 3: Implement `template_brief.py`**

```python
"""Template brief (spec 2026-09-30-template-pipeline-mirror §3): the stored sheet reconciled with one
dictation through the shared engine and rewritten in place. Voice passes through verbatim; only
covered conditional content is rewritten. Question keys: r<i> rules, c<i> conditional negatives,
n<i> atomic normals, f<i> If-present findings."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict, List, Optional

from . import report_reconcile as rc
from .report_review import positive_items
from .template_sheet_structure import SheetStructure, _covers

logger = logging.getLogger(__name__)

Q_CONDITION = "This statement is true for this case: "
MET = 0.5


def _block(sheet: str, heading: str) -> str:
    """Text of a '### heading' block (to the next heading)."""
    m = re.search(rf"^###\s+{re.escape(heading)}\s*\n(.*?)(?=^#|\Z)", sheet, re.M | re.S)
    return m.group(1).strip() if m else ""


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _line_index(lines: List[str], source_line: str) -> Optional[int]:
    return next((i for i, ln in enumerate(lines) if _covers(source_line, ln)), None)


async def compile_template_brief(sheet: str, s: SheetStructure, scan_type: str, findings: str,
                                 clinical_history: str = "") -> rc.Brief:
    t0 = time.time()
    state = f"SCAN TYPE: {scan_type}\nDICTATED FINDINGS:\n{findings}"
    ctx_state = f"{state}\nCLINICAL HISTORY:\n{clinical_history or '(not given)'}"
    items = rc.split_findings(findings)
    para_name = {p.id: p.name for p in s.paragraphs}
    imp_section = next((x.name for x in s.sections if x.role == "impression"), "IMPRESSION")

    q_f: Dict[str, dict] = {}
    q_c: Dict[str, dict] = {}
    for i, r in enumerate(s.rules):
        (q_c if r.condition_source in ("history", "context") else q_f)[f"r{i}"] = {
            "type": "noul", "instructions": Q_CONDITION + r.condition}
    for i, n in enumerate(s.negatives):
        if n.condition:
            q_f[f"c{i}"] = {"type": "noul", "instructions": Q_CONDITION + n.condition}
    for i, n in enumerate(s.normals):
        q_f[f"n{i}"] = {"type": "noul", "instructions": rc.Q_AFFECTED + n.text}
    for i, ip in enumerate(s.if_present):
        q_f[f"f{i}"] = {"type": "noul", "instructions": rc.Q_FINDING + ip.finding}

    ip_negs = [(ip, x) for ip in s.if_present for x in ip.negatives]
    raw_negs = [n.text.rstrip(".") for n in s.negatives] + [x.text.rstrip(".") for _, x in ip_negs]
    split = await rc._split_bundled(raw_negs)
    flat = [(k, part) for k, parts in enumerate(split) for part in parts]

    async def plan_or_none():
        try:
            return await rc._plan(scan_type, clinical_history, items, [], _block(sheet, "Inclusion logic"))
        except Exception as e:
            logger.warning("template impression plan failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    async def fallback_or_none():
        try:
            return await rc._fallback(state, items, [ip.finding for ip in s.if_present]) if items and s.if_present else None
        except Exception as e:
            logger.warning("template fallback failed (%s: %s)", type(e).__name__, str(e)[:200])
            return None

    jev_f, jev_c, qw, plan, fb = await asyncio.gather(
        rc._jev(state, q_f) if q_f else asyncio.sleep(0, {}),
        rc._jev(ctx_state, q_c) if q_c else asyncio.sleep(0, {}),
        rc._qwen(state, [p for _, p in flat], [n.text for n in s.normals], []),
        plan_or_none(), fallback_or_none())
    score = lambda ans, k: float(ans[k]["noul"]) if k in ans else 0.0
    qneg = {d.index: d for d in qw.negatives}

    lines = sheet.splitlines()
    edits: Dict[int, List[str]] = {}          # line index -> replacement lines ([] = delete)

    def put(source_line: str, new: List[str]):
        i = _line_index(lines, source_line)
        if i is None:
            return
        edits.setdefault(i, []).extend(_indent(lines[i]) + x for x in new)

    def _q(t: str) -> str:
        return t.strip().rstrip(".") + "."

    decisions: dict = {"rules": [], "negatives": [], "normals": [], "finding_negatives": [], "options": [],
                       "impression_plan": None}

    # Rules. A met suppress/replace forces its target negative to OMIT.
    forced_omit: Dict[str, str] = {}
    for i, r in enumerate(s.rules):
        p = score(jev_c if f"r{i}" in q_c else jev_f, f"r{i}")
        met = p >= MET
        new: List[str] = []
        if met and r.effect in ("suppress", "replace"):
            if r.target:
                forced_omit[r.target.rstrip(".").lower()] = r.condition
                new.append(f'- OMIT: "{r.target}" — {r.condition}')
            if r.effect == "replace" and r.then_text:
                new.append(f'- INSTEAD: "{r.then_text}"')
        elif met and r.effect == "append":
            new.append(f'- APPLY: "{r.then_text}"')
        elif met and r.effect == "use":
            new.append(f'- USE: "{r.then_text}"')
        for sl in r.source_lines:
            put(sl, new if sl == r.source_lines[0] else [])
        decisions["rules"].append({"id": r.id, "condition": r.condition, "met": met, "score": round(p, 3),
                                   "action": ("applied" if met else "removed")})

    # Sheet negatives: conditional ones first need their condition; then the classifier label.
    for k, n in enumerate(s.negatives):
        parts = [(j, part) for j, (kk, part) in enumerate(flat) if kk == k]
        if n.condition and score(jev_f, f"c{k}") < MET:
            new, action = [], "removed"
        else:
            new = []
            for j, part in parts:
                d = qneg.get(j)
                why = forced_omit.get(part.rstrip(".").lower()) or forced_omit.get(n.text.rstrip(".").lower())
                if why:
                    new.append(f'- OMIT: "{_q(part)}" — {why}')
                elif d and d.action == "contradicted":
                    new.append(f'- OMIT: "{_q(part)}" — the dictation reports: {d.dictated_finding}')
                elif d and d.action == "expected":
                    new.append(f'- DO NOT ASSERT: "{_q(part)}" — expected consequence of: {d.dictated_finding}')
                else:
                    new.append(f'- KEEP: "{_q(part)}"')
            action = "labelled"
        for sl in n.source_lines:
            put(sl, new)
        decisions["negatives"].append({"id": n.id, "text": n.text, "action": action, "lines": new})

    # Atomic normals: kept verbatim, or listed as not assertable (never deleted).
    by_line: Dict[str, List[tuple]] = {}
    for i, n in enumerate(s.normals):
        flagged = score(jev_f, f"n{i}") >= MET or i in set(qw.affected_normals)
        by_line.setdefault(n.source_line, []).append((n, flagged))
        decisions["normals"].append({"id": n.id, "structure": n.structure, "action": "do_not_assert" if flagged else "keep"})
    for sl, group in by_line.items():
        keep = [n.text for n, f in group if not f]
        flag = [n.text for n, f in group if f]
        new = ["- **Normal pattern**: " + " ".join(f'"{t}"' for t in keep)] if keep else []
        if flag:
            new.append("- **Do not assert as normal (a dictated finding acts on these):** " + " ".join(f'"{t}"' for t in flag))
        put(sl, new)

    # If-present negatives (policy 1): stated, do-not-assert, offered or dropped.
    stated, n_offered = [], 0
    base = len(s.negatives)
    for m, (ip, x) in enumerate(ip_negs):
        fi = s.if_present.index(ip)
        p = score(jev_f, f"f{fi}")
        for j, (kk, part) in enumerate(flat):
            if kk != base + m:
                continue
            d = qneg.get(j)
            label = d.action if d else "keep"
            outcome = rc.route_finding(label, p, x.tag)
            if outcome == "offered":
                if n_offered >= rc.MAX_FINDING_OPTIONS:
                    outcome = "dropped"
                else:
                    n_offered += 1
                    decisions["options"].append({"kind": "finding_negative", "section": ip.section, "text": part,
                                                 "finding": ip.finding, "paragraph": para_name.get(ip.paragraph, ip.paragraph),
                                                 "reason": "contextual" if p >= rc.PRESENT_HIGH else f"finding borderline (p={p:.2f})"})
            if outcome == "stated":
                stated.append(f'- KEEP: "{_q(part)}" (finding: {ip.finding}; place in: {para_name.get(ip.paragraph, ip.section)})')
            elif outcome == "do_not_assert":
                stated.append(f'- DO NOT ASSERT: "{_q(part)}" — expected consequence of: {d.dictated_finding if d else ip.finding}')
            decisions["finding_negatives"].append({"finding": ip.finding, "text": part, "tag": x.tag, "qwen": label,
                                                   "present": round(p, 3), "outcome": outcome})

    # Unanticipated carried findings: offered only (shared fallback).
    if plan and fb:
        seen = {o["text"] for o in decisions["options"]}
        for it in fb.items:
            if it.covered or it.index not in plan.impression or not (0 <= it.index < len(items)):
                continue
            for neg in it.negatives[:3]:
                neg = neg.strip().rstrip(".")
                if neg and neg not in seen and n_offered < rc.MAX_FINDING_OPTIONS:
                    seen.add(neg)
                    n_offered += 1
                    decisions["options"].append({"kind": "finding_negative",
                                                 "section": next((x.name for x in s.sections if x.role == "findings"), "FINDINGS"),
                                                 "text": neg, "finding": items[it.index], "reason": "unanticipated finding"})

    out: List[str] = []
    for i, ln in enumerate(lines):
        out.extend(edits[i] if i in edits else [ln])
    text = "\n".join(out)

    # Normal-study impression: dropped when anything positive is dictated.
    if positive_items(findings):
        text = re.sub(r"^###\s+Normal study (?:impression|conclusion)\s*\n.*?(?=^#|\Z)", "", text, flags=re.M | re.S | re.I)

    if stated:
        text += "\n\n## Finding-Linked Negatives (reconciled with this dictation)\n" + "\n".join(stated)

    if plan and items:
        pick = lambda idx: [items[i] for i in dict.fromkeys(idx) if 0 <= i < len(items)]
        carry, only = pick(plan.impression), pick(plan.findings_only)
        opt = [t for t in pick(plan.optional_impression) if t not in carry]
        room = rc.MAX_OPTIONS - len([o for o in decisions["options"] if o["kind"] != "finding_negative"])
        decisions["options"].extend({"kind": "impression", "section": imp_section, "text": t, "reason": ""} for t in opt[:room])
        decisions["impression_plan"] = {"carry": carry, "findings_only": only, "optional": opt[:room]}
        plan_lines = []
        if carry:
            plan_lines.append("- **Carry forward (the impression addresses each):** " + " ".join(f'"{t}"' for t in carry))
        if only:
            plan_lines.append("- **Findings only (not in the impression):** " + " ".join(f'"{t}"' for t in only))
        if plan_lines:
            text += "\n\n## Impression Plan\n" + "\n".join(plan_lines)

    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return rc.Brief(text=text, decisions=decisions, reconcile_ms=int((time.time() - t0) * 1000))
```

Notes for the implementer:
- A rule with several `source_lines` writes its resolution on the first line and deletes the others.
- A sheet line shared by two negatives (the `/` line) receives both negatives' labels in order, because `put` appends to an already-touched line.
- The Qwen classifier's indices follow the flat list: the sheet negatives' parts first, then If-present parts. With `no_split` in the fixture, 0–2 are sheet negatives and 3 is `No appendicolith`.
- Labels always quote the negative with one trailing full stop (`_q`), whatever the split returned.

- [ ] **Step 4: Run and iterate until green**

Run: `uv run pytest -q tests/test_template_brief.py`
Expected: 11 passed. The Jev key for a conditional negative is `c<index in s.negatives>` (`c2` in the fixture); for atomic normals `n<index>` (`n1` = spleen).

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_brief.py tests/test_template_brief.py
git commit -m "feat(template): template brief — shared reconcile, in-place labels, options by section"
```

### Task 12: CLINICAL HISTORY section

**Files:**
- Create: `src/rapid_reports_ai/template_history.py`, `tests/test_template_history.py`

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from rapid_reports_ai import template_history as th
from rapid_reports_ai.report_review import ReportSection

SECTIONS = [ReportSection(name="CLINICAL HISTORY", header="CLINICAL HISTORY", role="history"),
            ReportSection(name="FINDINGS", header=None, role="findings"),
            ReportSection(name="IMPRESSION", header="Impression", role="impression")]
HISTORY = "67 year old female with right iliac fossa pain, raised CRP. Query appendicitis."


def test_provenance_accepts_a_terse_restatement():
    assert th.grounded("67F. Right iliac fossa pain. Raised CRP. ?Appendicitis.", HISTORY)


def test_provenance_rejects_added_facts():
    assert not th.grounded("67F. Right iliac fossa pain. Raised CRP. Previous appendicectomy.", HISTORY)
    assert not th.grounded("72F. Right iliac fossa pain.", HISTORY)


def test_insert_puts_the_section_first_when_findings_are_implicit():
    report = "The appendix is dilated.\n\nImpression\nAppendicitis."
    out = th.insert_history(report, "67F. ?Appendicitis.", SECTIONS)
    assert out.startswith("CLINICAL HISTORY\n67F. ?Appendicitis.\n\nThe appendix is dilated.")


def test_insert_goes_before_the_next_present_header():
    secs = [ReportSection(name="TECHNIQUE", header="TECHNIQUE", role="technique"), SECTIONS[0],
            ReportSection(name="FINDINGS", header="FINDINGS", role="findings")]
    report = "TECHNIQUE\nCT.\n\nFINDINGS\nX."
    assert th.insert_history(report, "67F.", secs) == "TECHNIQUE\nCT.\n\nCLINICAL HISTORY\n67F.\n\nFINDINGS\nX."


async def test_write_history_returns_none_when_ungrounded(monkeypatch):
    class R:
        class output:
            text = "67F. Previous appendicectomy."

    async def fake(**kw):
        return R
    monkeypatch.setattr(th, "_run_agent_with_model", fake)
    assert await th.write_history(HISTORY) is None
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_history.py`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""CLINICAL HISTORY section for templates whose sheet defines one (spec §4, L-36 as refined
2026-09-30): a terse restatement of the platform's clinical-history input, written by a small call,
checked for provenance in code, placed by code. Nothing from the history goes anywhere else."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List, Optional

from pydantic import BaseModel

from . import report_reconcile as rc
from .enhancement_utils import _run_agent_with_model
from .report_review import ReportSection

logger = logging.getLogger(__name__)

HISTORY_SYS = ("Restate a referral's clinical history for the CLINICAL HISTORY section of a radiology report, in terse "
               "referral format: age and sex abbreviated (e.g. 61M, 52F), key clinical facts as noun phrases separated "
               "by full stops, no connective prose, the clinical question last (prefixed '?'). Use only facts in the "
               "input and add nothing. Return JSON {\"text\": \"...\"}.")
_ALLOWED = {"query", "known", "history", "previous", "prior", "with", "and", "for", "the", "of", "on", "in", "no"}
_SEX = {"m": ("male", "man", "m", "boy"), "f": ("female", "woman", "f", "girl", "lady")}


class _History(BaseModel):
    text: str


def grounded(text: str, history: str) -> bool:
    """Every word and number in `text` comes from `history`; '67F' needs 67 and a female word."""
    src = history.lower()
    src_words = set(re.findall(r"[a-z]+", src))
    src_nums = set(re.findall(r"\d+(?:\.\d+)?", src))
    for tok in re.findall(r"\d+(?:\.\d+)?[mf]?\b|[a-z]+", text.lower()):
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([mf])?", tok)
        if m:
            if m.group(1) not in src_nums or (m.group(2) and not (set(_SEX[m.group(2)]) & src_words)):
                return False
        elif len(tok) >= 3 and tok not in src_words and tok not in _ALLOWED:
            return False
    return True


async def write_history(history: str) -> Optional[str]:
    if not history.strip():
        return None
    try:
        r = await asyncio.wait_for(_run_agent_with_model(
            model_name=rc.QWEN, output_type=_History, system_prompt=HISTORY_SYS, user_prompt=history, api_key="",
            model_settings={"temperature": 0, "max_tokens": 400, "reasoning_effort": "none"}), rc.QWEN_TIMEOUT_S)
        text = r.output.text.strip()
    except Exception as e:
        logger.warning("history section failed (%s: %s); omitted", type(e).__name__, str(e)[:200])
        return None
    if not grounded(text, history):
        logger.warning("history section not grounded in the input; omitted: %r", text[:200])
        return None
    return text


def insert_history(report: str, text: str, sections: List[ReportSection]) -> str:
    """Place the section under its header, before the next section (in sheet order) whose header is
    in the report; at the top when the next section is implicit or absent."""
    hist = next(s for s in sections if s.role == "history")
    block = f"{hist.header or hist.name}\n{text}\n\n"
    after = sections[sections.index(hist) + 1:]
    for s in after:
        if s.header is None:
            break
        m = re.search(rf"^[ \t]*{re.escape(s.header.strip().rstrip(':'))}[ \t]*:?[ \t]*$", report, re.M | re.I)
        if m:
            return report[:m.start()] + block + report[m.start():]
    before = sections[:sections.index(hist)]
    if before and all(s.header for s in before):
        return report.rstrip() + "\n\n" + block.rstrip() + "\n"
    return block + report
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_template_history.py`
Expected: 5 passed. (`test_insert_puts_the_section_first…`: the next section is implicit → top.)

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_history.py tests/test_template_history.py
git commit -m "feat(template): CLINICAL HISTORY section — grounded restatement, placed by code"
```

---

## Phase D — Signed-off prompt package

### Task 13: `global_style_guide.py` T0 and `_BRIEF` constants

**Files:**
- Modify: `src/rapid_reports_ai/global_style_guide.py`
- Modify: `tests/test_report_path_split.py`
- Create: `tests/test_template_prompts.py`

- [ ] **Step 1: Write the failing prompt tests**

```python
"""Signed-off §5 package: brief variants carry the labels and none of the duplicated rules."""
from __future__ import annotations

from rapid_reports_ai import global_style_guide as g


def test_t0_allows_only_a_sheet_defined_history_section():
    assert "never reproduced outside a\nCLINICAL HISTORY section the skill sheet defines" in g.GLOBAL_STYLE_GUIDE
    assert "Restate the clinical history input only; add nothing." in g.GLOBAL_STYLE_GUIDE


def test_brief_variants_drop_what_the_brief_resolves():
    brief = g.GLOBAL_STYLE_GUIDE_BRIEF + g.PRE_WRITING_ANALYSIS_BRIEF + g.VERIFICATION_CHECKLIST_BRIEF
    for gone in ("### Conditional Awareness", "### Conditional Style Application", "### Parameter Placeholders",
                 "Clinical history as checklist", "Conditional Suppression Rule", "All triggered interpretive clauses",
                 "Verify all IF/THEN"):
        assert gone not in brief, gone
    for kept in ("Reference Values table", "header: none", "Impression format matches skill sheet",
                 "demonstrated style always takes precedence", "### Consolidation", "[NEEDS VERIFICATION]"):
        assert kept in brief, kept


def test_brief_header_defines_every_label():
    for label in ("KEEP", "OMIT", "DO NOT ASSERT", "INSTEAD", "APPLY", "USE", "Do not assert as normal",
                  "Carry forward", "Coverage is obligatory, assertion is earned"):
        assert label in g.TEMPLATE_SHEET_HEADER_BRIEF, label


def test_checklist_carries_the_l48_plus_line_and_slot_rule():
    v = g.VERIFICATION_CHECKLIST_BRIEF
    assert "or one cluster of negatives bearing on the index finding's next step" in v
    assert "No curly-brace slot appears as text" in v
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_prompts.py`
Expected: FAIL, `AttributeError: ... 'GLOBAL_STYLE_GUIDE_BRIEF'` (and the T0 test fails).

- [ ] **Step 3: Apply T0 to the original constant**

In `GLOBAL_STYLE_GUIDE`, replace:

```
history from the input is used for reasoning only. It is never reproduced — not as a
section, and not as content in any section: no demographics, presenting symptoms,
```

with:

```
history from the input is used for reasoning only. It is never reproduced outside a
CLINICAL HISTORY section the skill sheet defines — not as content in any other section:
no demographics, presenting symptoms,
```

and replace `last. Never long-form prose.` with `last. Never long-form prose. Restate the clinical history input only; add nothing.`

- [ ] **Step 4: Append the brief constants to `global_style_guide.py`**

```python
# ── Brief variants (signed off 2026-09-30, spec template-pipeline-mirror §5) ────────────────
# Used only when the generator reads a reconciled template brief. Built by exact passage swaps so a
# drift in the originals fails at import; the originals stay the raw-sheet fallback.

def _swap(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"passage not found exactly once: {old[:60]!r}"
    return text.replace(old, new)


def _swaps(text: str, *pairs: tuple) -> str:
    for old, new in pairs:
        text = _swap(text, old, new)
    return text


def _between(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


TEMPLATE_SHEET_HEADER_BRIEF = """## TEMPLATE SKILL SHEET

The following skill sheet defines this radiologist's reporting conventions, reconciled with this
dictation. Before you received it, every conditional item was checked against the dictated
findings; items that do not apply were removed. Act on its labels exactly; do not re-derive them
and do not reintroduce removed items.

- **KEEP**: state the negative as written. **OMIT**: the dictation reports this finding; describe
  it as dictated and never state the negative, in any section. **DO NOT ASSERT**: a dictated
  finding is expected to cause this; do not state it as absent.
- **INSTEAD**: in place of the omitted text, write what this rule prescribes, from the dictation.
  **APPLY**: append this interpretive clause where the rule places it. **USE**: this phrasing
  variant applies to this case.
- **Do not assert as normal**: a dictated finding acts on these structures; describe them only as
  the dictation does.
- **Impression plan**: address every Carry forward finding in the impression; Findings only items
  stay out of it. The plan is a minimum: add the synthesis the evidence supports.

Coverage is obligatory, assertion is earned: every structure the sheet's paragraphs visit is still
covered, and what is said about it is only what the dictation and the labels support.

The skill sheet inherits the Global Style Guide; where they conflict, the skill sheet takes
precedence."""

GLOBAL_STYLE_GUIDE_BRIEF = _swaps(
    GLOBAL_STYLE_GUIDE,
    # S2
    ("It is never reproduced outside a\nCLINICAL HISTORY section the skill sheet defines — not as content in any other section:",
     "It is never reproduced in any section you write:"),
    # S1
    (_between(GLOBAL_STYLE_GUIDE, "### Conditional Style Application", "### Findings Discipline"),
     "### Structure\n\nThe skill sheet governs structure; do not fabricate sections it does not define. If the skill\n"
     "sheet defines a CLINICAL HISTORY section, it is supplied separately and inserted after\n"
     "writing: do not write it.\n\n"),
    # S3
    (_between(GLOBAL_STYLE_GUIDE, "### Conditional Awareness", "### Missing Data Handling"), ""),
    # S4
    ("""But the skill sheet's
mandatory negatives and systems review statements exist independently of the
dictation. A radiologist does not dictate "no pleural effusion" — the reporting
convention requires it to be stated. The absence of a structure from the
dictation does not mean it was not assessed; it means it was normal and the
convention expects an explicit normal statement.""",
     """Silence about a structure the sheet's paragraphs visit means it was assessed
and normal: state its Normal pattern where the sheet gives one, unless it is
listed under Do not assert as normal."""),
    # S5
    ("The principle: generate everything the skill sheet says must always be present.",
     "The principle: generate every KEEP line and every Normal pattern the dictation leaves unaddressed."),
    # S6
    (_between(GLOBAL_STYLE_GUIDE, "### Parameter Placeholders", "### Output Consistency"),
     "### Pattern Slots\n\nCurly-brace slots in a sheet's patterns (`{measurement}`, `{structure}`) are shapes: fill\n"
     "them from the dictation or leave the clause out. A slot is never written as text.\n\n"),
    # S7
    ("matches the clinical history and\nfindings input", "matches the findings input"),
)

PRE_WRITING_ANALYSIS_BRIEF = _swaps(
    PRE_WRITING_ANALYSIS,
    # P1
    ("""Cross-reference against the skill sheet's mandatory negatives
   — any mandatory negative not addressed by the dictation must still appear.
   Check each mandatory negative against the skill sheet's Conditional Suppression
   Rules: if the current finding state triggers a suppression condition, suppress
   the negative and apply the replacement phrase (or omit entirely).""",
     """Apply each reconciliation label:
   KEEP, OMIT, DO NOT ASSERT, INSTEAD."""),
    # P2
    (_between(PRE_WRITING_ANALYSIS, "   **Clinical history as checklist**", "2. **Impression plan**"),
     """   **Clinical history as focus**: Use prior events, diagnoses and procedures in the
   history to decide which dictated findings the report must address and emphasise.
   The history never creates a field to fill: a structure, measurement or negative the
   dictation does not mention is not added because the history makes it relevant.

"""),
    # P3
    ("""Scan the skill sheet for conditional fields
   triggered by these findings. Verify all IF/THEN interpretive clauses that
   apply.""", "Place each APPLY clause and USE variant."),
)

VERIFICATION_CHECKLIST_BRIEF = _swaps(
    VERIFICATION_CHECKLIST,
    # V1 + V3
    ("""- Every mandatory negative from the skill sheet is present with exact phrasing
- Every triggered Conditional Suppression Rule has been applied — suppressed phrase removed, replacement phrase inserted
""",
     """- Every KEEP negative is present; no OMIT negative and no DO NOT ASSERT statement appears anywhere, impression included
- Every INSTEAD, APPLY and USE is applied
- No structure listed under "Do not assert as normal" is stated to be normal
- Every Carry forward finding is addressed in the impression; no Findings only item appears there
- The impression contains at most one negative — the answer to the clinical question when no positive finding answers it, or one clause that changes the next step — or one cluster of negatives bearing on the index finding's next step (staging, resectability, complication). It never lists unrelated or excluded alternatives
- No curly-brace slot appears as text
"""),
    # V2
    ("- All triggered interpretive clauses are appended\n", ""),
    # V4
    ("- No clinical history item (demographic, symptom, medication, laboratory value, prior diagnosis, referral wording) is restated anywhere in the report",
     "- No clinical history item (demographic, symptom, medication, laboratory value, prior diagnosis, referral wording) is written anywhere; the CLINICAL HISTORY section, if defined, is supplied separately"),
)
```

- [ ] **Step 5: Run the prompt tests**

Run: `uv run pytest -q tests/test_template_prompts.py`
Expected: 4 passed. An `AssertionError: passage not found exactly once` names the passage to re-copy from the file.

- [ ] **Step 6: Update the pins (T0 moves `GLOBAL_STYLE_GUIDE`; four new pins)**

Run: `PYTHONPATH=src uv run python -c "import hashlib; from rapid_reports_ai import global_style_guide as g; [print(n, hashlib.sha256(getattr(g,n).encode()).hexdigest()[:8]) for n in ('GLOBAL_STYLE_GUIDE','GLOBAL_STYLE_GUIDE_BRIEF','PRE_WRITING_ANALYSIS_BRIEF','VERIFICATION_CHECKLIST_BRIEF','TEMPLATE_SHEET_HEADER_BRIEF')]"`

In `tests/test_report_path_split.py`, set `TEMPLATE_PROMPTS["GLOBAL_STYLE_GUIDE"]` to the new digest (T0, signed off 2026-09-30) and add the four new names with their digests. `PRE_WRITING_ANALYSIS` and `VERIFICATION_CHECKLIST` pins must be unchanged.

Run: `uv run pytest -q tests/test_report_path_split.py tests/test_template_prompts.py`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/rapid_reports_ai/global_style_guide.py tests/test_report_path_split.py tests/test_template_prompts.py
git commit -m "feat(template-prompts): signed-off brief package — T0 history rule, lean _BRIEF variants, label header"
```

---

## Phase E — Generation and pipeline

### Task 14: Template generator reads the brief

**Files:**
- Modify: `src/rapid_reports_ai/template_manager.py:2517-2676`
- Create: `tests/test_template_pipeline.py` (first tests)

- [ ] **Step 1: Write the failing tests**

```python
"""Template pipeline (spec §4)."""
from __future__ import annotations

import pytest

from rapid_reports_ai import enhancement_utils as eu
from rapid_reports_ai import global_style_guide as g
from rapid_reports_ai.template_manager import TemplateManager


@pytest.fixture
def capture(monkeypatch):
    seen = []

    class R:
        output = "FINDINGS\nX."

    async def fake(**kw):
        seen.append(kw)
        return R
    monkeypatch.setattr(eu, "_run_agent_with_model", fake)
    monkeypatch.setattr(eu, "_get_api_key_for_provider", lambda p, fallback_api_key=None: "k")
    monkeypatch.setattr(eu, "_get_model_provider", lambda m: "cerebras")
    return seen


async def test_brief_path_uses_brief_prompts_and_history_note(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(
        cfg, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, brief_text="BRIEF TEXT", history_supplied=True)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "BRIEF TEXT" in gen["system_prompt"] and "RAW SHEET" not in gen["system_prompt"]
    assert g.TEMPLATE_SHEET_HEADER_BRIEF in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE_BRIEF in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS_BRIEF in gen["user_prompt"]
    assert "The CLINICAL HISTORY section is supplied separately; do not write it." in gen["user_prompt"]


async def test_raw_path_is_unchanged(capture):
    cfg = {"generation_mode": "skill_sheet_guided", "skill_sheet": "RAW SHEET", "scan_type": "CT"}
    await TemplateManager()._generate_report_skill_sheet_guided(cfg, {"FINDINGS": "f"}, None)
    gen = next(k for k in capture if k["output_type"] is str)
    assert "RAW SHEET" in gen["system_prompt"] and g.GLOBAL_STYLE_GUIDE in gen["system_prompt"]
    assert g.PRE_WRITING_ANALYSIS in gen["user_prompt"] and "supplied separately" not in gen["user_prompt"]
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_pipeline.py`
Expected: FAIL, `TypeError: ... unexpected keyword argument 'brief_text'`.

- [ ] **Step 3: Implement**

Change the signature:

```python
    async def _generate_report_skill_sheet_guided(
        self,
        template_config: dict,
        user_inputs: dict,
        user_signature: str = None,
        model_override: str = None,
        brief_text: str | None = None,
        history_supplied: bool = False,
    ) -> dict:
```

Replace the `global_style_guide` import and the `system_prompt = f"""{SYSTEM_PREAMBLE}...` assignment with:

```python
        from .global_style_guide import (
            SYSTEM_PREAMBLE, GLOBAL_STYLE_GUIDE, PRE_WRITING_ANALYSIS, VERIFICATION_CHECKLIST,
            GLOBAL_STYLE_GUIDE_BRIEF, PRE_WRITING_ANALYSIS_BRIEF, VERIFICATION_CHECKLIST_BRIEF,
            TEMPLATE_SHEET_HEADER_BRIEF,
        )

        skill_sheet = template_config.get("skill_sheet", "")
        scan_type = template_config.get("scan_type", "")
        findings_input = user_inputs.get("FINDINGS", "")
        clinical_history = user_inputs.get("CLINICAL_HISTORY", "")

        if brief_text is not None:
            # Mirror path (spec template-pipeline-mirror §5): the sheet reconciled with this dictation.
            style, pre, ver = GLOBAL_STYLE_GUIDE_BRIEF, PRE_WRITING_ANALYSIS_BRIEF, VERIFICATION_CHECKLIST_BRIEF
            system_prompt = f"{SYSTEM_PREAMBLE}\n\n{style}\n\n{TEMPLATE_SHEET_HEADER_BRIEF}\n\n{brief_text}"
        else:
            style, pre, ver = GLOBAL_STYLE_GUIDE, PRE_WRITING_ANALYSIS, VERIFICATION_CHECKLIST
            system_prompt = f"""{SYSTEM_PREAMBLE}

{GLOBAL_STYLE_GUIDE}

## TEMPLATE SKILL SHEET

The following skill sheet defines scan-specific reporting conventions for this template.
It inherits all rules from the Global Style Guide above. Where a skill sheet rule
conflicts with a global rule, the skill sheet takes precedence.

{skill_sheet}"""
        history_note = ("\n\nThe CLINICAL HISTORY section is supplied separately; do not write it."
                        if history_supplied else "")
```

In both `user_prompt` f-strings: append `{history_note}` directly after the `Findings: {findings_input}` line, and in the non-Anthropic one replace `{PRE_WRITING_ANALYSIS}` / `{VERIFICATION_CHECKLIST}` with `{pre}` / `{ver}`. With `brief_text=None` and `history_supplied=False` every string is byte-identical to today's.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q tests/test_template_pipeline.py tests/test_report_path_split.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_manager.py tests/test_template_pipeline.py
git commit -m "feat(template): generator reads the reconciled brief with the brief prompt package"
```

### Task 15: `template_pipeline.py` orchestration

**Files:**
- Create: `src/rapid_reports_ai/template_pipeline.py`
- Modify: `tests/test_template_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
from rapid_reports_ai import report_reconcile as rc  # noqa: E402
from rapid_reports_ai import template_pipeline as tp  # noqa: E402
from rapid_reports_ai import template_sheet_structure as tss  # noqa: E402

from test_template_sheet_structure import SHEET, good_draft  # noqa: E402

STRUCT = tss.build_structure(SHEET, good_draft(), model="m")
CFG = {"generation_mode": "skill_sheet_guided", "skill_sheet": SHEET, "scan_type": "CT AP"}


def _pipeline_stubs(monkeypatch, brief_ok=True):
    calls = {}

    async def fake_brief(sheet, s, scan, findings, history):
        if not brief_ok:
            raise RuntimeError("boom")
        return rc.Brief(text="BRIEF", decisions={"options": [{"kind": "finding_negative", "section": "FINDINGS",
                                                              "text": "No appendicolith", "finding": "appendicitis"}]},
                        reconcile_ms=5)

    async def fake_gen(self, cfg, inputs, sig, model_override=None, brief_text=None, history_supplied=False):
        calls["gen"] = {"brief_text": brief_text, "history_supplied": history_supplied, "sig": sig}
        return {"report_content": "The appendix is dilated.\n\nImpression\nAppendicitis.", "description": "d",
                "scan_type": "CT AP", "model_used": "q", "fallback_from": None}

    async def fake_history(h):
        return "67F. ?Appendicitis."

    async def fake_check(report, findings, scan, options, sections=None, protected=None, suppressed=None):
        calls["check"] = {"sections": [s.name for s in sections], "protected": protected, "suppressed": suppressed,
                          "report": report}
        return report, options, {"enabled": True}
    monkeypatch.setattr(tp, "compile_template_brief", fake_brief)
    monkeypatch.setattr(tp.TemplateManager, "_generate_report_skill_sheet_guided", fake_gen)
    monkeypatch.setattr(tp, "write_history", fake_history)
    monkeypatch.setattr(tp, "run_quality_check", fake_check)
    return calls


async def test_mirror_inserts_history_checks_by_section_and_signs_last(monkeypatch):
    calls = _pipeline_stubs(monkeypatch)
    out = await tp.generate_template_report(CFG, {"FINDINGS": "11 mm appendix", "CLINICAL_HISTORY": "67 female ?appendicitis"},
                                            "Dr A", STRUCT)
    assert calls["gen"] == {"brief_text": "BRIEF", "history_supplied": True, "sig": None}
    assert out["report_content"].startswith("CLINICAL HISTORY\n67F. ?Appendicitis.")
    assert out["report_content"].endswith("\n\nDr A")
    assert calls["check"]["sections"] == ["CLINICAL HISTORY", "FINDINGS", "IMPRESSION"]
    assert "67F. ?Appendicitis." in calls["check"]["protected"] and calls["check"]["suppressed"] == ["normal"]
    assert out["brief_used"] and out["sections"] == ["CLINICAL HISTORY", "FINDINGS", "IMPRESSION"]
    assert out["brief_options"][0]["id"] == "fn0" and out["brief_options"][0]["section"] == "FINDINGS"


async def test_brief_failure_falls_back_to_the_raw_sheet_and_generator_writes_history(monkeypatch):
    calls = _pipeline_stubs(monkeypatch, brief_ok=False)
    out = await tp.generate_template_report(CFG, {"FINDINGS": "f", "CLINICAL_HISTORY": "h"}, None, STRUCT)
    assert calls["gen"]["brief_text"] is None and calls["gen"]["history_supplied"] is False
    assert not out["brief_used"] and not out["report_content"].startswith("CLINICAL HISTORY")


def test_choose_pipeline_respects_flag_and_allowlist(monkeypatch):
    monkeypatch.delenv("RR_TEMPLATE_MIRROR", raising=False)
    monkeypatch.setenv("RR_PIPELINE_OVERRIDE_USERS", "a@x.com")
    assert tp.choose_mirror(None, "b@x.com") is False
    assert tp.choose_mirror("mirror", "b@x.com") is False        # not on the allowlist
    assert tp.choose_mirror("mirror", "a@x.com") is True
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    assert tp.choose_mirror(None, "b@x.com") is True
    assert tp.choose_mirror("current", "a@x.com") is False


def test_candidate_record_has_quick_fields_plus_sections():
    rec = tp.candidate_record({"report_content": "r", "model_used": "q", "description": "d", "brief_options": [],
                               "quality_check": {}, "brief_used": True, "brief_text": "t", "brief_decisions": {},
                               "sections": ["FINDINGS"]}, 1200)
    assert set(rec) >= {"model", "content", "latency_ms", "generated_at", "error", "description", "options",
                        "options_applied", "quality_check", "brief", "sections"}
    assert rec["options_applied"] == [] and rec["brief"] == {"text": "t", "decisions": {}}
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_pipeline.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'rapid_reports_ai.template_pipeline'`.

- [ ] **Step 3: Implement**

```python
"""Templated reports, mirror of the quick flow (spec 2026-09-30-template-pipeline-mirror):
structure → brief → generate → CLINICAL HISTORY by code → options → post-generation check → persist.
Only generation differs from quick; the engine is shared (report_reconcile, report_review)."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from .enhancement_utils import MODEL_CONFIG, _run_agent_with_model
from .report_reconcile import write_options
from .report_review import ReportSection, run_quality_check
from .template_brief import compile_template_brief
from .template_history import insert_history, write_history
from .template_manager import TemplateManager
from .template_sheet_structure import SheetStructure

logger = logging.getLogger(__name__)


def enabled() -> bool:
    """Kill switch: RR_TEMPLATE_MIRROR=1 turns the mirror on (default off until E2 passes)."""
    return os.environ.get("RR_TEMPLATE_MIRROR", "0").strip().lower() in ("1", "true", "on")


def choose_mirror(requested: Optional[str], email: Optional[str]) -> bool:
    """An explicit pipeline choice is honoured only for allowlisted users (evaluation A/B)."""
    allow = {e.strip().lower() for e in os.environ.get("RR_PIPELINE_OVERRIDE_USERS", "").split(",") if e.strip()}
    if requested in ("mirror", "current") and (email or "").lower() in allow:
        return requested == "mirror"
    return enabled()


def _style(sheet: str, s: SheetStructure) -> str:
    m = re.search(r"^###\s+Quoted examples\s*\n(.*?)(?=^#|\Z)", sheet, re.M | re.S)
    terms = ", ".join(s.terminology.preferred)
    return ((m.group(1).strip() + "\n") if m else "") + (f"Preferred terms: {terms}" if terms else "")


async def generate_template_report(template_config: dict, user_inputs: dict, user_signature: Optional[str],
                                   structure: SheetStructure) -> dict:
    sheet = template_config.get("skill_sheet", "")
    scan_type = template_config.get("scan_type", "")
    findings = user_inputs.get("FINDINGS", "")
    history = user_inputs.get("CLINICAL_HISTORY", "")
    sections = [ReportSection(name=x.name, header=x.header, role=x.role)
                for x in sorted(structure.sections, key=lambda x: x.order)]
    defines_history = any(x.role == "history" for x in sections)
    imp_section = next((x.name for x in sections if x.role == "impression"), "IMPRESSION")

    async def brief_or_none():
        try:
            return await compile_template_brief(sheet, structure, scan_type, findings, history)
        except Exception as e:
            logger.warning("template brief failed (%s: %s); generating from the raw sheet", type(e).__name__, str(e)[:200])
            return None

    async def history_or_none():
        return await write_history(history) if defines_history else None

    brief, history_text = await asyncio.gather(brief_or_none(), history_or_none())
    use_history = bool(brief and history_text)
    gen, options = await asyncio.gather(
        TemplateManager()._generate_report_skill_sheet_guided(
            template_config, user_inputs, None, brief_text=brief.text if brief else None,
            history_supplied=bool(brief) and defines_history),
        write_options(brief.decisions.get("options", []) if brief else [], findings, scan_type,
                      model=MODEL_CONFIG["TEMPLATE_REPORT_GENERATOR"], runner=_run_agent_with_model,
                      style=_style(sheet, structure), impression_section=imp_section))
    report = gen["report_content"]
    if use_history:
        report = insert_history(report, history_text, sections)
    protected = ([history_text] if use_history else []) + [b.text for b in structure.fixed_blocks]
    report, options, quality = await run_quality_check(report, findings, scan_type, options, sections=sections,
                                                       protected=protected, suppressed=structure.terminology.suppressed)
    if user_signature:
        report = report.rstrip() + "\n\n" + user_signature
    return {**gen, "report_content": report, "brief_used": brief is not None,
            "brief_reconcile_ms": brief.reconcile_ms if brief else None,
            "brief_decisions": brief.decisions if brief else None, "brief_text": brief.text if brief else None,
            "brief_options": options, "quality_check": quality, "sections": [x.name for x in sections],
            "history_inserted": use_history}


def candidate_record(result: dict, latency_ms: int) -> dict:
    """Same fields as the quick candidate record (quick_report_api), plus sections."""
    return {"model": result.get("model_used", "unknown"), "content": result.get("report_content", ""),
            "latency_ms": latency_ms, "generated_at": datetime.now(timezone.utc).isoformat(), "error": None,
            "description": result.get("description"), "options": result.get("brief_options") or [],
            "options_applied": [], "quality_check": result.get("quality_check"),
            "brief": ({"text": result.get("brief_text"), "decisions": result.get("brief_decisions")}
                      if result.get("brief_used") else None),
            "sections": result.get("sections") or []}
```

- [ ] **Step 4: Run the tests and the split test**

Run: `uv run pytest -q tests/test_template_pipeline.py tests/test_report_path_split.py`
Expected: all pass. Add to `tests/test_report_path_split.py`:

```python
def test_template_modules_do_not_import_quick_modules():
    for f in ("template_brief.py", "template_pipeline.py", "template_sheet_structure.py", "template_history.py",
              "template_manager.py"):
        assert not any(i.startswith("quick_report") for i in _imports(SRC / f)), f
```

and rerun: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rapid_reports_ai/template_pipeline.py tests/test_template_pipeline.py tests/test_report_path_split.py
git commit -m "feat(template): mirror orchestration — brief, history by code, section-generic check"
```

### Task 16: Generate endpoint — flag, override, persistence, artifacts, legacy refusal

**Files:**
- Modify: `src/rapid_reports_ai/database/crud.py:717-738`
- Modify: `src/rapid_reports_ai/main.py` (`TemplateGenerateRequest` ~658, `generate_report_from_template` ~1707)
- Create: `tests/test_template_generate_endpoint.py`

- [ ] **Step 1: Write the failing tests** (uses the existing `client` fixture in `tests/conftest.py`; check its name and how it authenticates — adapt the two helper lines if they differ)

```python
"""Generate endpoint (spec §4): mirror when on and the structure is fresh; legacy refused."""
from __future__ import annotations

from rapid_reports_ai import main
from rapid_reports_ai import template_pipeline as tp
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import crud

from test_template_sheet_structure import SHEET, good_draft

STRUCT = tss.build_structure(SHEET, good_draft(), model="m")


def test_create_report_stores_candidate_reports(db_session, test_user):
    r = crud.create_report(db_session, str(test_user.id), "templated", "text", "q", candidate_reports=[{"x": 1}])
    assert r.candidate_reports == [{"x": 1}]


def test_legacy_template_is_refused(client, auth_headers, legacy_template):
    r = client.post(f"/api/templates/{legacy_template.id}/generate", json={"user_inputs": {"FINDINGS": "f"}},
                    headers=auth_headers).json()
    assert r["success"] is False and "skill sheet" in r["error"].lower()


def test_mirror_persists_artifacts(client, auth_headers, guided_template, monkeypatch):
    monkeypatch.setenv("RR_TEMPLATE_MIRROR", "1")
    monkeypatch.setattr(main.tss, "fresh", lambda cfg: STRUCT)

    async def fake(cfg, inputs, sig, s):
        return {"report_content": "FINDINGS\nX.", "description": "d", "scan_type": "CT", "model_used": "q",
                "fallback_from": None, "brief_used": True, "brief_text": "t", "brief_decisions": {},
                "brief_options": [], "quality_check": {"enabled": True}, "sections": ["FINDINGS"]}
    monkeypatch.setattr(tp, "generate_template_report", fake)
    r = client.post(f"/api/templates/{guided_template.id}/generate", json={"user_inputs": {"FINDINGS": "f"}},
                    headers=auth_headers).json()
    assert r["success"] and r["artifacts"]["sections"] == ["FINDINGS"] and r["pipeline"] == "mirror"
```

If `tests/conftest.py` has no `db_session`/`test_user`/`auth_headers`/`legacy_template`/`guided_template` fixtures, add them there following the existing client fixture's pattern (create a user, sign a JWT with the test `SECRET_KEY`, create two `Template` rows: one with `{"generation_mode": "skill_sheet_guided", "skill_sheet": SHEET, "scan_type": "CT"}`, one with `{"sections": []}`).

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_generate_endpoint.py`
Expected: FAIL (`create_report() got an unexpected keyword argument 'candidate_reports'`, and no `artifacts` in the response).

- [ ] **Step 3: Implement `crud.create_report`**

Add `candidate_reports: Optional[list] = None,` to the signature (after `description`) and `candidate_reports=candidate_reports,` to the `Report(...)` constructor.

- [ ] **Step 4: Implement the endpoint changes in `main.py`**

`TemplateGenerateRequest` gains `pipeline: Optional[str] = None  # "mirror" | "current"; allowlisted users only`.

Add near the other template helpers:

```python
from . import template_pipeline as tp
from .generation_artifacts import GenerationArtifacts

LEGACY_RETIRED = ("This template uses the retired template format. Re-create it as a skill-sheet template "
                  "(New template → from example reports).")
```

In `generate_report_from_template`, right after the `if not template.template_config:` block:

```python
        cfg = template.template_config
        if cfg.get("generation_mode") != "skill_sheet_guided":
            return {"success": False, "error": LEGACY_RETIRED}
        structure = tss.fresh(cfg)
        if tss.needs_restructure(cfg):
            tss.schedule_structure(str(template.id), cfg.get("skill_sheet", ""))
        use_mirror = bool(structure) and tp.choose_mirror(request.pipeline, current_user.email)
```

Replace the `report_output_dict = await tm.generate_report_from_config(...)` call with:

```python
        if use_mirror:
            report_output_dict = await tp.generate_template_report(
                cfg, user_inputs, current_user.signature, structure)
        else:
            report_output_dict = await tm.generate_report_from_config(
                template_config=cfg, user_inputs=user_inputs, user_signature=current_user.signature)
        _tpl_latency_ms = int((time.perf_counter() - _tpl_gen_t0) * 1000)
```

Change `if ENABLE_TEMPLATE_STRUCTURE_VALIDATION:` to `if ENABLE_TEMPLATE_STRUCTURE_VALIDATION and not use_mirror:`.

In the save block, build the record and pass it:

```python
                candidate = tp.candidate_record(report_output_dict, _tpl_latency_ms) if use_mirror else None
                saved_report = create_report(
                    db=db,
                    user_id=str(current_user.id),
                    report_type="templated",
                    report_content=report_output.report_content,
                    model_used=model_to_store,
                    input_data=input_data_to_save,
                    template_id=str(template.id),
                    description=context_title,
                    candidate_reports=[candidate] if candidate else None,
                )
```

(declare `candidate = None` before `if should_auto_save(current_user):` so it exists when auto-save is off). In the final response dict add:

```python
            "pipeline": "mirror" if use_mirror else "current",
            "artifacts": (GenerationArtifacts.from_candidate(
                candidate or tp.candidate_record(report_output_dict, _tpl_latency_ms),
                (user_inputs or {}).get("FINDINGS", "")).model_dump() if use_mirror else None),
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest -q tests/test_template_generate_endpoint.py tests/test_template_pipeline.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/database/crud.py src/rapid_reports_ai/main.py tests/test_template_generate_endpoint.py tests/conftest.py
git commit -m "feat(template): generate endpoint runs the mirror behind RR_TEMPLATE_MIRROR and persists artifacts"
```

### Task 17: Legacy retirement (list + banner) and options-panel check

**Files:**
- Modify: `src/rapid_reports_ai/main.py` (`list_templates` ~1434)
- Modify: `frontend/src/routes/components/TemplatedReportTab.svelte:492-494` and the banner markup that uses `showLegacyBanner`
- Modify: `tests/test_template_generate_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
def test_list_hides_legacy_templates(client, auth_headers, legacy_template, guided_template):
    ids = {t["id"] for t in client.get("/api/templates", headers=auth_headers).json()["templates"]}
    assert str(guided_template.id) in ids and str(legacy_template.id) not in ids
```

(Adapt the `["templates"]` key to the endpoint's actual response shape.)

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest -q tests/test_template_generate_endpoint.py::test_list_hides_legacy_templates`
Expected: FAIL (legacy id present).

- [ ] **Step 3: Implement**

In `list_templates`, after `templates = get_templates(...)`:

```python
        # Legacy (non skill-sheet) templates are retired: hidden, never deleted (spec §4).
        templates = [t for t in templates if (t.template_config or {}).get("generation_mode") == "skill_sheet_guided"]
```

In `TemplatedReportTab.svelte`, delete the `hasLegacyTemplates` / `showLegacyBanner` reactive lines and the `{#if showLegacyBanner}…{/if}` block (and `legacyHintDismissed` state if only the banner used it). Leave `hasSmartTemplates` if other markup uses it.

- [ ] **Step 4: Check whether the existing options panel lights up for templated reports**

Run: `grep -rn "candidate_reports\|brief_options\|OptionalAdditions" frontend/src | head -20`
Record in the task notes (and the final summary): whether `OptionalAdditions` reads options from a pathway-agnostic source (the report's `candidate_reports[0].options` or the generate response) or only from the quick SSE `candidate` event. No UI change in this branch either way (spec: the rail consumes artifacts).

- [ ] **Step 5: Run backend tests and the frontend type check**

Run: `uv run pytest -q tests/test_template_generate_endpoint.py` → all pass.
Run: `cd ../frontend && npm run check 2>&1 | tail -5` → no new errors in `TemplatedReportTab.svelte`.

- [ ] **Step 6: Commit**

```bash
git add src/rapid_reports_ai/main.py tests/test_template_generate_endpoint.py ../frontend/src/routes/components/TemplatedReportTab.svelte
git commit -m "feat(template): retire legacy templates — hidden from the list, banner removed"
```

- [ ] **Step 7: Full suite**

Run: `uv run pytest -q`
Expected: all pass.

---

## Phase F — Evaluation, ledger, rollout

### Task 18: E2 script (old vs new on the same dictations)

**Files:**
- Create: `src/rapid_reports_ai/scripts/template_mirror_eval.py`

- [ ] **Step 1: Write the script**

```python
"""E2 (spec §6): current vs mirror on the same dictations, in process against prod data.

Cases: JSON list [{"template_id", "findings", "clinical_history", "source"}] built in Task 19.
  railway run --service <backend> -- uv run python -m rapid_reports_ai.scripts.template_mirror_eval \
      --cases test_output/e2_cases.json --out test_output/template_mirror_e2_$$ [--arms current,mirror]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import time

from rapid_reports_ai import template_pipeline as tp
from rapid_reports_ai import template_sheet_structure as tss
from rapid_reports_ai.database import SessionLocal
from rapid_reports_ai.database.models import Template
from rapid_reports_ai.report_review import ReportSection, section_spans
from rapid_reports_ai.template_manager import TemplateManager

SLOT = re.compile(r"\{[a-z_ ]+\}")


def metrics(report: str, s: tss.SheetStructure, history: str) -> dict:
    secs = [ReportSection(name=x.name, header=x.header, role=x.role) for x in s.sections]
    spans = section_spans(report, secs)
    hist_words = {w for w in re.findall(r"[a-z]{5,}", history.lower())}
    outside = " ".join(report[a:b] for x, a, b in spans if x.role != "history").lower()
    return {"slot_leaks": SLOT.findall(report),
            "history_words_outside": sorted(w for w in hist_words if w in outside),
            "suppressed_terms": [t for t in s.terminology.suppressed if re.search(rf"\b{re.escape(t)}\b", report, re.I)],
            "sections_found": [x.name for x, _, _ in spans]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", default="current,mirror")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads(pathlib.Path(a.cases).read_text())
    db = SessionLocal()
    rows = []
    for i, c in enumerate(cases):
        t = db.query(Template).filter(Template.id == c["template_id"]).first()
        cfg = t.template_config
        s = tss.fresh(cfg)
        inputs = {"FINDINGS": c["findings"], "CLINICAL_HISTORY": c.get("clinical_history", "")}
        row = {"i": i, "template": t.name, "source": c.get("source"), "structure_usable": bool(s)}
        for arm in a.arms.split(","):
            t0 = time.time()
            try:
                if arm == "mirror":
                    if not s:
                        row[arm] = {"error": "no fresh usable structure"}
                        continue
                    r = await tp.generate_template_report(cfg, inputs, None, s)
                else:
                    r = await TemplateManager().generate_report_from_config(cfg, inputs, None)
                row[arm] = {"ms": int((time.time() - t0) * 1000), "report": r["report_content"],
                            "quality_check": r.get("quality_check"), "options": r.get("brief_options"),
                            "decisions": r.get("brief_decisions"),
                            "metrics": metrics(r["report_content"], s, inputs["CLINICAL_HISTORY"]) if s else None}
            except Exception as e:
                row[arm] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
        rows.append(row)
        (out / f"case_{i:02d}.json").write_text(json.dumps(row, indent=1))
    (out / "summary.json").write_text(json.dumps({"pid": os.getpid(), "rows": rows}, indent=1))
    print(f"{len(rows)} cases -> {out}")
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke-import and commit**

Run: `PYTHONPATH=src uv run python -c "import rapid_reports_ai.scripts.template_mirror_eval"` → exit 0.

```bash
git add src/rapid_reports_ai/scripts/template_mirror_eval.py
git commit -m "feat(eval): E2 current-vs-mirror script for templated reports"
```

### Task 19: Backfill structures, build E2 cases, run E2 (evaluation, prod)

Hassan authorised direct prod reads and writes (2026-09-30). Writes in this task touch **only** `template_config.sheet_structure`.

- [ ] **Step 1: Deploy the branch code needed for the backfill?** Not needed: the backfill runs locally through `railway run` against the prod DB. Confirm `git status` is clean.

- [ ] **Step 2: Backfill (dry run, then write)**

```bash
railway run --service <backend> -- uv run python -m rapid_reports_ai.scripts.template_structure_eval --model <E1 winner> --out test_output/template_structure_backfill_dry_$$
railway run --service <backend> -- uv run python -m rapid_reports_ai.scripts.template_structure_eval --model <E1 winner> --out test_output/template_structure_backfill_$$ --write
```

Expected: `usable` ≥ 24, and in the second run `stored: true` on every usable row. Verify one row read-only: `railway run ... -- uv run python -c "…print(Template.template_config['sheet_structure']['usable'])"`.

- [ ] **Step 3: Build ~10 E2 cases (reuse, don't write new dictations)**

Read-only SQL (via `railway run` + SQLAlchemy, or Metabase `/api/dataset`, DB 2):
- the 2 recent guided templated reports: `select r.template_id, r.input_data from reports r join templates t on t.id=r.template_id where t.template_config::jsonb->>'generation_mode'='skill_sheet_guided' order by r.created_at desc limit 5`;
- quick-report dictations whose scan type matches a template's `scan_type` (CT abdomen/pelvis, CTPA, MRI knee, MRI lumbar, CMR, polytrauma, aorta, and the CLINICAL HISTORY template "CT Abdomen and Pelvis (Portal Venous)"): `select findings_dictation, clinical_history, scan_type from reports where generation_mode='quick_ephemeral' and scan_type ilike '%<term>%' order by created_at desc limit 3`.
Write `test_output/e2_cases.json` as `[{"template_id", "findings", "clinical_history", "source"}]`, ~10 pairs across ~8 templates.

- [ ] **Step 3b: Run 1 (both arms)**

```bash
railway run --service <backend> -- uv run python -m rapid_reports_ai.scripts.template_mirror_eval --cases test_output/e2_cases.json --out test_output/template_mirror_e2_$$
```

- [ ] **Step 4: Hand read side by side**

For every case read `current.report` beside `mirror.report` with the dictation: serious errors (contradiction, fabricated finding, negative denying a dictated finding, history outside its section), KEEP negatives present / OMIT absent (from `mirror.decisions`), voice preserved (phrasing, headers, terminology), impression quality. Tabulate the code metrics (`slot_leaks`, `history_words_outside`, `suppressed_terms`, residual `quality_check.flags` after repair) and latency (median `mirror.ms − current.ms`).

- [ ] **Step 5: Run 2 only if run 1 prompts a fix**

Fix at the instruction site (brief rendering, `TEMPLATE_SHEET_HEADER_BRIEF` needs Hassan's sign-off again, structure prompt), add a unit test for the fixed behaviour, rerun `--arms mirror` only.

- [ ] **Step 6: Bar**

No serious error where the current report had none; voice holds on every pair; median added latency ≤ ~2.5 s. If the bar fails, stop and report to Hassan with the table.

### Task 20: Ledger entry, merge, flip, live check

- [ ] **Step 1: Ledger**

Append the next L-entry to `docs/model-migration/parameter-ledger.md` (read the last entry for the number and format): title `Template pipeline mirror — structure (E1) and old vs new (E2)`, verdict line with confidence, E1 table (arm, usable, IF coverage, verbatim failures, errors, hand-read notes, winner), E2 table (case, template, serious errors current/mirror, metrics, latency), watch list, output directories (with pids).

```bash
git add docs/model-migration/parameter-ledger.md
git commit -m "docs(ledger): L-<n> template pipeline mirror — E1 structuring, E2 old vs new"
```

- [ ] **Step 2: Merge and deploy with the flag off**

Use superpowers:finishing-a-development-branch. Railway: confirm `RR_TEMPLATE_MIRROR` is unset or `0`; set `RR_PIPELINE_OVERRIDE_USERS=hass.ahmad.95@gmail.com` (the account used for the live check); set `RR_STRUCTURE_MODEL` if the winner is not gpt-oss. Verify the deploy with `curl -s https://api.rad-flow.uk/health` (memory `reference_railway_deploy_architecture`: verify with curl, not deploy state) and that the served commit matches.

- [ ] **Step 3: Hassan's sign-off, then flip**

Present the ledger entry; on approval set `RR_TEMPLATE_MIRROR=1` on Railway (the same variable is the kill switch). Update the handover `2026-09-30-template-pipeline-mirror-handover.md` status line and memory `project_report_path_split`.

- [ ] **Step 4: Live check in Chrome**

Load the Chrome tools in one ToolSearch call (`tabs_context_mcp, tabs_create_mcp, navigate, computer, read_page, javascript_tool, read_network_requests`). On a `skill_sheet_guided` template (prefer "CT Abdomen and Pelvis (Portal Venous)", which defines CLINICAL HISTORY): generate a report from a reused dictation; confirm in the network response `pipeline: "mirror"`, `artifacts.sections`, options with template section names, `quality_check.enabled`; confirm the CLINICAL HISTORY section is present and restates only the input; reopen the report from History and confirm `candidate_reports[0]` carries the same options/brief/quality fields (fetch `/api/reports/<id>` from page context with the stored token). Record a short GIF (`template_mirror_live_check.gif`).

- [ ] **Step 5: Report**

Summarise to Hassan: what shipped, E1/E2 numbers, the live-check result, the options-panel finding from Task 17 Step 4, and anything on the watch list.

---

## Self-review (done while writing)

- **Spec coverage:** §1 modules → Tasks 2–5, 11, 12, 15; §2 schema/verification/gate/atomic normals/duplicates/fixed blocks/terminology/staleness/triggers → Tasks 6–8; model choice + E1 → Tasks 9–10; §3 decision table, context state, inclusion logic, options by section, template-style option writer, failure fallback → Tasks 2 (`_plan`), 5 (`write_options`), 11, 15; §4 generation, history section, section-generic check, protected spans, suppressed terms, persistence, artifacts, flag, override, dormant validation off, legacy retirement, options-panel check → Tasks 4, 12, 14–17; §5 package → Task 13; §6 tests/E1/E2/rollout/ledger/live check → Tasks 1, 10, 18–20; coordination note → already committed with the spec.
- **Deviation from the spec, deliberate:** stated If-present negatives are rendered in one appended "Finding-Linked Negatives" block with a `place in: <paragraph>` hint rather than spliced into each paragraph block (deterministic, testable; same information to the generator). Options carry a `paragraph` field in addition to `section`.
- **Type consistency:** `ReportSection(name, header, role)` (Task 4) is used by Tasks 12, 15, 18; `SheetStructure` fields (Task 6) match their uses in Tasks 11, 15, 16; `rc.write_options(..., model=, runner=, style=, impression_section=)` (Task 5) matches Task 15; `_generate_report_skill_sheet_guided(..., brief_text=, history_supplied=)` (Task 14) matches Task 15's stub and call; `tss.fresh(config)` / `needs_restructure(config)` / `schedule_structure(id, sheet)` match Tasks 8 and 16.
