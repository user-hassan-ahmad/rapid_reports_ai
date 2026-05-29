# Skill-Sheet Quality Engine + Metabase SQL Pack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build an LLM quality-scoring engine that writes per-report scores (`sheet_fit`, `output_adherence`, `input_faithfulness`, objective `edit_burden`) into a new `report_quality_scores` table, plus a repeatable Metabase SQL pack for descriptive analytics + the per-report trace. Metabase does all visualisation.

**Architecture:** New table (via Alembic, using `JSONBType` so tests run on the existing SQLite harness). A pure `compute_edit_burden`. A `score_report` that calls a judge (`MODEL_CONFIG["QUALITY_JUDGE"]`, default `claude-haiku-4-5-20251001`) on three case-agnostic rubric prompts and upserts a score row. A batch CLI to score in-scope reports. SQL files in `docs/analytics/metabase/` for Metabase questions.

**Tech Stack:** SQLAlchemy, Alembic, pydantic-ai (`_run_agent_with_model`), pytest, Metabase (SQL).

---

## File structure

- Modify `backend/src/rapid_reports_ai/database/models.py` — add `ReportQualityScore`.
- Create `backend/migrations/versions/<rev>_add_report_quality_scores.py` — Alembic migration.
- Modify `backend/src/rapid_reports_ai/enhancement_utils.py` — add `QUALITY_JUDGE` to `MODEL_CONFIG`.
- Create `backend/src/rapid_reports_ai/quality_scoring.py` — `compute_edit_burden`, prompts, `score_report`, `upsert_score`.
- Create `backend/scripts/score_report_quality.py` — batch CLI.
- Create `backend/tests/test_quality_scoring.py` — unit tests (judge mocked).
- Create `docs/analytics/metabase/*.sql` — Metabase SQL pack.

---

## Task 1: `ReportQualityScore` model + migration

**Files:**
- Modify: `backend/src/rapid_reports_ai/database/models.py`
- Create: `backend/migrations/versions/<rev>_add_report_quality_scores.py`

- [ ] **Step 1: Add the model** (after `ReportFeedback`)

```python
class ReportQualityScore(Base):
    """LLM + objective quality scores for a skill-sheet-driven report."""
    __tablename__ = "report_quality_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    pipeline = Column(String(16), nullable=False)          # "quick" | "template"
    sheet_fit = Column(Integer, nullable=True)             # 1–5
    output_adherence = Column(Integer, nullable=True)      # 1–5
    input_faithfulness = Column(Integer, nullable=True)    # 1–5
    edit_burden = Column(Float, nullable=True)             # 0–1 objective; null if no final
    dimensions_json = Column(JSONBType(), nullable=True)   # {dim:{score,rationale,issues:[...]}}
    judge_model = Column(String(100), nullable=False)
    rubric_version = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint("report_id", "rubric_version", name="uq_report_quality_rubric"),
    )
```

- [ ] **Step 2: Generate the migration**

Run: `cd backend && poetry run alembic revision -m "add report_quality_scores"`
Then edit the new file's `upgrade()`/`downgrade()` to create/drop the table (mirror the columns above; use `sa.dialects.postgresql.JSONB` for `dimensions_json`, `postgresql.UUID` for ids).

- [ ] **Step 3: Apply locally against a scratch DB to verify it runs**

Run: `cd backend && DATABASE_URL="$SCRATCH_PG_URL" poetry run alembic upgrade head`
Expected: no error; `report_quality_scores` exists. (Use a scratch Postgres, NOT prod.)

- [ ] **Step 4: Commit**

```bash
git add backend/src/rapid_reports_ai/database/models.py backend/migrations/versions/
git commit -m "feat(db): report_quality_scores table + migration"
```

---

## Task 2: `compute_edit_burden` (pure, objective)

**Files:**
- Create: `backend/src/rapid_reports_ai/quality_scoring.py`
- Test: `backend/tests/test_quality_scoring.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_quality_scoring.py
from rapid_reports_ai.quality_scoring import compute_edit_burden

def test_edit_burden_zero_when_identical():
    assert compute_edit_burden("LUNGS: clear.", "LUNGS: clear.") == 0.0

def test_edit_burden_one_when_no_overlap():
    assert compute_edit_burden("aaaa", "bbbb") == 1.0

def test_edit_burden_none_when_no_final():
    assert compute_edit_burden("anything", None) is None

def test_edit_burden_partial_between_0_and_1():
    v = compute_edit_burden("the quick brown fox", "the slow brown fox")
    assert 0.0 < v < 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && poetry run pytest tests/test_quality_scoring.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# backend/src/rapid_reports_ai/quality_scoring.py
"""Quality scoring for skill-sheet-driven reports (objective edit-burden + LLM judge)."""
from __future__ import annotations

import difflib
from typing import Optional


def compute_edit_burden(ai_text: str, final_text: Optional[str]) -> Optional[float]:
    """0.0 (identical) … 1.0 (fully rewritten). None if there is no final text."""
    if final_text is None or final_text == "":
        return None
    ratio = difflib.SequenceMatcher(None, ai_text or "", final_text).ratio()
    return round(1.0 - ratio, 4)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && poetry run pytest tests/test_quality_scoring.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/rapid_reports_ai/quality_scoring.py backend/tests/test_quality_scoring.py
git commit -m "feat(quality): objective edit_burden metric"
```

---

## Task 3: `QUALITY_JUDGE` model config + case-agnostic rubric prompts

**Files:**
- Modify: `backend/src/rapid_reports_ai/enhancement_utils.py` (`MODEL_CONFIG`)
- Modify: `backend/src/rapid_reports_ai/quality_scoring.py`

- [ ] **Step 1: Add the judge model**

In `MODEL_CONFIG` add:
```python
    "QUALITY_JUDGE": "claude-haiku-4-5-20251001",  # Quality scoring judge (Anthropic; ≠ generator family)
```
(`claude-haiku-4-5-20251001` is already in `MODEL_PROVIDERS` → anthropic.)

- [ ] **Step 2: Add the three rubric prompts** (case-agnostic — structural, no single-domain clinical examples)

```python
# append to quality_scoring.py
RUBRIC_VERSION = "v1"

_SCORE_INSTRUCTION = (
    "Score from 1 (poor) to 5 (excellent). Respond with the integer score, a one-sentence "
    "rationale, and a list of verbatim problem spans (may be empty). Judge only the dimension "
    "described; do not reward or penalise unrelated qualities."
)

SHEET_FIT_PROMPT = (
    "# Role\nYou assess whether a generated review guide ('skill sheet') is well-matched to the "
    "case it was produced for.\n\n# Dimension: skill-sheet fit\nGiven the case inputs (scan type "
    "and clinical context) and the skill sheet, judge whether the sheet covers the assessments "
    "that the inputs make relevant, in proportion, without irrelevant filler or items unsupported "
    "by the inputs. Breadth and specificity should track what the inputs justify — neither padded "
    "nor sparse.\n\n" + _SCORE_INSTRUCTION
)

OUTPUT_ADHERENCE_PROMPT = (
    "# Role\nYou assess whether a generated report addressed the points raised by its review guide.\n\n"
    "# Dimension: output↔sheet adherence\nGiven the skill sheet and the report, judge the degree to "
    "which the report substantively addresses the sheet's items — each item either resolved with a "
    "definite statement or appropriately acknowledged. Items the sheet raised but the report ignores "
    "lower the score.\n\n" + _SCORE_INSTRUCTION
)

INPUT_FAITHFULNESS_PROMPT = (
    "# Role\nYou assess whether a report is faithful to the case inputs it was generated from.\n\n"
    "# Dimension: input faithfulness\nGiven the inputs and the report, judge whether the report "
    "introduces no claim absent from or contradicting the inputs (fabrication), omits no input-stated "
    "finding (omission), and preserves laterality, quantities, and qualifiers exactly. List any "
    "violating spans. This is safety-critical; weight fabrication and laterality/quantity errors "
    "most heavily.\n\n" + _SCORE_INSTRUCTION
)
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/rapid_reports_ai/enhancement_utils.py backend/src/rapid_reports_ai/quality_scoring.py
git commit -m "feat(quality): QUALITY_JUDGE config + case-agnostic rubric prompts"
```

---

## Task 4: `score_report` + `upsert_score`

**Files:**
- Modify: `backend/src/rapid_reports_ai/quality_scoring.py`
- Test: `backend/tests/test_quality_scoring.py`

- [ ] **Step 1: Write the failing test (judge mocked, SQLite)**

```python
import uuid
from rapid_reports_ai import quality_scoring as qs
from rapid_reports_ai.database.models import ReportQualityScore

def test_upsert_score_is_idempotent_by_rubric(db_session, monkeypatch):
    # requires ReportQualityScore in _TEST_TABLES (see Step 4)
    rid = uuid.uuid4()
    qs.upsert_score(db_session, report_id=rid, pipeline="quick",
                    scores={"sheet_fit": 4, "output_adherence": 5, "input_faithfulness": 5},
                    edit_burden=0.1, dimensions={"sheet_fit": {"score": 4, "rationale": "ok", "issues": []}},
                    judge_model="claude-haiku-4-5-20251001")
    qs.upsert_score(db_session, report_id=rid, pipeline="quick",
                    scores={"sheet_fit": 2, "output_adherence": 2, "input_faithfulness": 2},
                    edit_burden=0.5, dimensions={}, judge_model="claude-haiku-4-5-20251001")
    rows = db_session.query(ReportQualityScore).filter_by(report_id=rid).all()
    assert len(rows) == 1 and rows[0].sheet_fit == 2  # upserted, not duplicated
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && poetry run pytest tests/test_quality_scoring.py::test_upsert_score_is_idempotent_by_rubric -v`
Expected: FAIL — no `upsert_score`.

- [ ] **Step 3: Implement `upsert_score` and `score_report`**

```python
# append to quality_scoring.py
import uuid as _uuid
from sqlalchemy.orm import Session
from .database.models import ReportQualityScore

def upsert_score(db: Session, *, report_id, pipeline, scores: dict, edit_burden,
                 dimensions: dict, judge_model: str, rubric_version: str = RUBRIC_VERSION):
    row = (db.query(ReportQualityScore)
             .filter_by(report_id=report_id, rubric_version=rubric_version).one_or_none())
    if row is None:
        row = ReportQualityScore(id=_uuid.uuid4(), report_id=report_id,
                                 rubric_version=rubric_version)
        db.add(row)
    row.pipeline = pipeline
    row.sheet_fit = scores.get("sheet_fit")
    row.output_adherence = scores.get("output_adherence")
    row.input_faithfulness = scores.get("input_faithfulness")
    row.edit_burden = edit_burden
    row.dimensions_json = dimensions
    row.judge_model = judge_model
    db.commit()
    return row
```

For `score_report`: gather input/skill-sheet/output/final for the report (quick: ephemeral sheet + `final_report_content`; template: template config + `report_feedback.final_output`), call the judge per dimension via `_run_agent_with_model` with a small structured output type, then `upsert_score`. Test `score_report` with the judge function monkeypatched to return canned scores; assert it parses and upserts.

- [ ] **Step 4: Add `ReportQualityScore` to SQLite test tables**

In `backend/tests/conftest.py`, append `ReportQualityScore.__table__` to `_TEST_TABLES` (all its columns are SQLite-compatible via `JSONBType`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && poetry run pytest tests/test_quality_scoring.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/rapid_reports_ai/quality_scoring.py backend/tests/test_quality_scoring.py backend/tests/conftest.py
git commit -m "feat(quality): score_report + idempotent upsert"
```

---

## Task 5: Batch CLI `score_report_quality.py`

**Files:**
- Create: `backend/scripts/score_report_quality.py`

- [ ] **Step 1: Implement the CLI** (mirror `create_user.py` conventions: `sys.path.insert` to `src`, set `DATABASE_URL` before importing app modules, `--dry-run` default off via `--commit` is not needed here since scoring writes only to the new table; use `--limit`, `--pipeline`, `--rescore`).

```python
#!/usr/bin/env python3
"""Batch-score skill-sheet reports into report_quality_scores. Re-runnable/idempotent.

Usage:
  DATABASE_URL="$DATABASE_PUBLIC_URL" poetry run python scripts/score_report_quality.py --limit 20
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pipeline", choices=["quick", "template", "both"], default="both")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--rescore", action="store_true", help="re-score even if a row exists")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not os.getenv("DATABASE_URL"):
        print("ERROR: set DATABASE_URL (e.g. $DATABASE_PUBLIC_URL)"); sys.exit(1)

    from rapid_reports_ai.database.connection import SessionLocal
    from rapid_reports_ai import quality_scoring as qs
    from rapid_reports_ai.analytics_scope import in_scope_reports  # small shared scope helper

    db = SessionLocal()
    try:
        reports = in_scope_reports(db, args.pipeline).all()
        if args.limit:
            reports = reports[: args.limit]
        ok = err = 0
        for r in reports:
            try:
                if args.dry_run:
                    print(f"[dry-run] would score {r.id}"); continue
                qs.score_report(db, r, rescore=args.rescore)
                ok += 1
            except Exception as e:  # continue on per-report failure
                err += 1; print(f"  ! {r.id}: {type(e).__name__}: {e}")
        print(f"done: scored={ok} errors={err} total={len(reports)}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
```

> `in_scope_reports` (organic exclusion + skill-sheet pipelines) is the same scope used by the Metabase SQL. Put it in a tiny `backend/src/rapid_reports_ai/analytics_scope.py` so the batch scorer and the SQL pack stay in sync conceptually. Add a unit test on the SQLite `reports` table.

- [ ] **Step 2: Smoke test dry-run against a scratch/seeded DB**

Run: `cd backend && DATABASE_URL="$SCRATCH_PG_URL" poetry run python scripts/score_report_quality.py --dry-run --limit 3`
Expected: prints up to 3 "would score …" lines, no writes.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/score_report_quality.py backend/src/rapid_reports_ai/analytics_scope.py
git commit -m "feat(quality): batch scoring CLI + shared in-scope helper"
```

---

## Task 6: Metabase SQL pack

**Files:**
- Create: `docs/analytics/metabase/*.sql`

- [ ] **Step 1: Author each query** with a header comment (purpose + expected columns), encoding scope once. Example `report_trace.sql`:

```sql
-- report_trace.sql — per-report trace + LLM quality scores (paste into Metabase as a Question)
-- Scope: organic users, skill-sheet pipelines. Columns: report_id, pipeline, created_at,
--   scan_type, clinical_history, skill_sheet, ai_output, final_output, edit_burden,
--   sheet_fit, output_adherence, input_faithfulness, rationale_json
WITH excluded AS (SELECT lower(email) e FROM users WHERE email IN ('hassan.ahmad.ucl@gmail.com'))
SELECT r.id AS report_id,
       CASE WHEN r.report_type='auto' THEN 'quick' ELSE 'template' END AS pipeline,
       r.created_at,
       ess.scan_type, ess.clinical_history,
       COALESCE(ess.skill_sheet_markdown, t.template_config->>'skill_sheet') AS skill_sheet,
       r.report_content AS ai_output,
       COALESCE(r.final_report_content, rf.final_output) AS final_output,
       q.edit_burden, q.sheet_fit, q.output_adherence, q.input_faithfulness,
       q.dimensions_json AS rationale_json
FROM reports r
JOIN users u ON u.id = r.user_id AND lower(u.email) NOT IN (SELECT e FROM excluded)
LEFT JOIN ephemeral_skill_sheets ess ON ess.id = r.ephemeral_skill_sheet_id
LEFT JOIN templates t ON t.id = r.template_id
LEFT JOIN report_feedback rf ON rf.report_id = r.id
LEFT JOIN report_quality_scores q ON q.report_id = r.id
WHERE (r.report_type='auto' AND r.generation_mode='quick_ephemeral')
   OR (r.report_type='templated' AND t.template_config->>'generation_mode'='skill_sheet_guided');
```

Author the remaining files the same way: `volume_adoption.sql`, `signal_coverage.sql`, `quick_vs_template.sql`, `skill_sheet_quality.sql`, `audit_summary.sql`, `template_refinement.sql`, `quality_scores_overview.sql`. Each begins with the same `excluded` CTE + pipeline scoping.

- [ ] **Step 2: Validate each query read-only against the app DB**

Run each via: `DATABASE_PUBLIC_URL` read-only connection (psql or a Python one-off). Confirm it returns rows and the documented columns. Fix any column/JSON-path mismatches.

- [ ] **Step 3: Commit**

```bash
git add docs/analytics/metabase/
git commit -m "docs(analytics): Metabase SQL pack (descriptive + trace + quality views)"
```

---

## Self-review notes

- **Spec coverage:** table+migration (T1), edit_burden (T2), judge+prompts (T3), score_report+upsert (T4), batch CLI (T5), Metabase SQL incl. trace + quality (T6). No custom UI/endpoint (correct — Metabase owns it).
- **Test-DB:** everything unit-testable on existing SQLite (`JSONBType`, pure functions, mocked judge). Migration + SQL validated against a scratch/real Postgres, never prod for writes.
- **House rules:** judge prompts are case-agnostic (structural, no single-domain examples); reuse existing audits for general QA; scope (organic + skill-sheet) defined once and shared between the batch scorer and the SQL pack.
- **Type consistency:** `compute_edit_burden`, `upsert_score`, `score_report`, `in_scope_reports`, `ReportQualityScore`, `RUBRIC_VERSION`, `QUALITY_JUDGE` used consistently across tasks.
```
