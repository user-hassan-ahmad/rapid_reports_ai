# Skill-Sheet Report Analytics & Quality — Design (Metabase + LLM scoring engine)

- **Date:** 2026-05-29 (revised after Metabase pivot)
- **Status:** Draft for review
- **Owner:** Hassan Ahmad

## 1. Purpose & scope

Analyse performance and quality of the two **skill-sheet-driven** report pipelines across **organic** user activity:

- **Quick** — `reports.report_type='auto'` AND `generation_mode='quick_ephemeral'`.
- **Template** — `reports.report_type='templated'` AND `template_id` ∈ `skill_sheet_guided` templates.

**Architecture decision (pivot):** descriptive analytics and all visualisation are delivered through **Metabase** (already running) via a repeatable, scoped **SQL pack**. We build only the thing Metabase can't: an **LLM quality-scoring engine** that writes per-report scores into a new table, which Metabase then reads and visualises like any other data.

### In scope
- **Metabase SQL pack** (authored in-repo, pasted into Metabase as questions/models): volume & adoption, signal coverage, quick-vs-template, skill-sheet quality/usage, audit summary, template refinement, the per-report **trace**, and quality-score views.
- **LLM quality-scoring engine** (app code): `report_quality_scores` table + migration, scoring module, batch CLI, judge prompts.
- Organic users only — exclude allowlist (default `hassan.ahmad.ucl@gmail.com`) **inside the SQL**.

### Out of scope (non-goals)
- **No custom dashboard UI, no `/admin/analytics` page, no `/overview` API, no `require_admin` gate** — Metabase owns viewing + access.
- **Inline flagged-span highlighting** inside report text (Metabase shows spans as a text list; a custom view is explicitly deferred).
- Telemetry capture fixes (edit/copy signals) — separate batch.
- Signed-embed-in-RadFlow — optional future add-on (§7), not built now.

## 2. How the analysis is viewed

- **All visuals live in the Metabase UI** by default (its own login). Questions + dashboards, sliced interactively there.
- **LLM scores surface natively** because they are stored as clean columns:
  - *Trace table* — a SQL join `reports → ephemeral_skill_sheets/templates → report_quality_scores`; each row shows input/sheet/output/final + diff alongside `sheet_fit`/`output_adherence`/`input_faithfulness` (1–5, conditional-formatted) + `edit_burden` + one-line rationale. Metabase row-detail shows full rationale + flagged spans from `dimensions_json`.
  - *Aggregate charts* — score distributions, averages by pipeline/scan-type, and a scores-vs-`edit_burden` scatter (validation).
- **Optional future:** signed embedding to surface a Metabase dashboard inside a RadFlow admin page under app auth (§7).

## 3. Data model — `report_quality_scores`

Alembic migration (`backend/migrations/versions`). Uses the project's `JSONBType` (JSON on SQLite) so unit tests run on the existing in-memory SQLite harness — **no Postgres test DB required**.

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `report_id` | UUID FK→reports (CASCADE), indexed | |
| `pipeline` | String | "quick" \| "template" (denormalised for Metabase filtering) |
| `sheet_fit` | Integer | 1–5 |
| `output_adherence` | Integer | 1–5 |
| `input_faithfulness` | Integer | 1–5 |
| `edit_burden` | Float | objective: normalised diff size 0–1; nullable when no final captured |
| `dimensions_json` | JSONBType | `{dim: {score, rationale, issues:[{span,note}]}}` for row-detail |
| `judge_model` | String | e.g. `claude-haiku-4-5-20251001` |
| `rubric_version` | String | bump to re-score |
| `created_at` | DateTime | |

Unique on (`report_id`, `rubric_version`) → re-runs upsert.

## 4. LLM quality-scoring engine (app code)

- **Module** `backend/src/rapid_reports_ai/quality_scoring.py`:
  - `compute_edit_burden(ai_text, final_text) -> float` — objective, pure (diff ratio via `difflib`); no model call.
  - `score_report(db, report) -> dict` — assembles input/skill-sheet/output/final, calls the judge for the three dimensions, returns scores + rationale + flagged spans; upserts a `report_quality_scores` row.
  - Judge via a new `MODEL_CONFIG["QUALITY_JUDGE"] = "claude-haiku-4-5-20251001"` (different family from the GLM generator → avoids self-preference bias) using the existing `_run_agent_with_model` path.
- **Prompts:** three judge prompts (sheet_fit, output_adherence, input_faithfulness), **case-agnostic** — structural/multi-domain framing, never single-domain clinical worked examples (house rule). Each returns a structured score (1–5) + rationale + verbatim flagged spans.
- **Reuse, don't duplicate:** general report QA stays in the existing `report_audits`; the judge only covers the skill-sheet chain + faithfulness.
- **Batch CLI** `backend/scripts/score_report_quality.py`: scope filters, `--dry-run`, re-runnable, idempotent by (`report_id`, `rubric_version`); logs per-report errors and continues; connects via `DATABASE_URL` like `create_user.py`.

## 5. Metabase SQL pack (authored in-repo)

Saved under `docs/analytics/metabase/` as `.sql` files (one per question), each encoding the scope once (organic exclusion + skill-sheet pipelines):
- `volume_adoption.sql`, `signal_coverage.sql`, `quick_vs_template.sql`, `skill_sheet_quality.sql`, `audit_summary.sql`, `template_refinement.sql`
- `report_trace.sql` — the per-report join including quality-score columns
- `quality_scores_overview.sql` — distributions / by-pipeline / scores-vs-edit-burden

The repo files are the source of truth; you paste them into Metabase as Questions (or SQL-backed Models) and arrange a dashboard.

## 6. Testing

- `compute_edit_burden` — pure unit tests (no DB).
- `score_report` — judge **mocked**; assert prompt assembly, score parsing, `dimensions_json` shape, and upsert-by-`rubric_version` (runs on the existing SQLite harness because the table uses `JSONBType`).
- SQL pack — validated by running each query against the app DB read-only during authoring; documented expected shape in each file's header comment.

## 7. Future (separate batches)

- Signed-embed a Metabase dashboard inside a RadFlow admin page (app-auth, native feel).
- Inline flagged-span highlighting in a small custom report view.
- Telemetry capture fixes (edit/copy on both pipelines).
- Optional human agree/disagree feedback on scores to tune the rubric.
