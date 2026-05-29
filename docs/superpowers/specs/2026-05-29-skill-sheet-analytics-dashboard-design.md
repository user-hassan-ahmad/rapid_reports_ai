# Skill-Sheet Report Analytics & Quality Dashboard — Design

- **Date:** 2026-05-29
- **Status:** Draft for review
- **Owner:** Hassan Ahmad

## 1. Purpose & scope

A native, admin-only in-app page for analysing the **performance and quality** of
the two **skill-sheet-driven** report pipelines across **organic** user activity:

- **Quick reports** — `reports.report_type='auto'` AND `generation_mode='quick_ephemeral'`.
- **Template reports** — `reports.report_type='templated'` AND `template_id` belongs to a `skill_sheet_guided` template.

It has three layers:
1. **Descriptive analytics** — volume, adoption, signal coverage, head-to-head, skill-sheet usage, audits, template refinement (reads existing data).
2. **Trace + objective quality** — per-report isolation of **input → skill sheet → output → final**, with the edit diff, audit results, and objective **edit-burden** metrics.
3. **LLM-judged quality scoring** — a model scores each report on **skill-sheet fit**, **output↔sheet adherence**, and **input faithfulness**; scores are stored and aggregated.

### In scope
- Both skill-sheet pipelines (legacy `auto/NULL` reports and legacy section-based templates excluded).
- **Organic users only:** exclude an internal-accounts allowlist (default: `hassan.ahmad.ucl@gmail.com`).
- Default window: skill-sheet era (from 2026-04-14), with from/to and pipeline filters.
- Current dataset: ~99 quick + ~63 template organic reports.

### Out of scope (explicit non-goals this batch)
- **Fixing/extending telemetry capture** (template edit events, quick copy events, ratings, `sections_modified`, timing). Separate batch; the Coverage panel tracks when those land.
- General report-QA re-scoring — **reuse** the existing `report_audits` system instead of duplicating it.
- Any write path to live report/feedback data (quality scores live in their own table).

## 2. Access model

- New SvelteKit route **`/admin/analytics`** — a **production admin feature**, not a dev/proto/eval route, so the `requireDevRoute` guard does **not** apply; gated by auth + email allowlist instead.
- Backend: endpoints under `/api/admin/analytics` depend on `get_current_user` **and** a new `require_admin` dependency checking `current_user.email` ∈ `ADMIN_EMAILS` (env var, comma-separated; seeded with the owner's admin email). `403` otherwise.
- Frontend: `/admin/analytics/+page.ts` guard redirects non-admins; page calls the API with the existing `Bearer` token.

## 3. Architecture

- **Backend**
  - `analytics_routes.py` under `/api/admin/analytics`; `require_admin` dependency in `auth.py`.
  - `analytics_queries.py` — pure functions (`Session` + filters → aggregates), unit-testable without FastAPI.
  - Endpoints:
    - `GET /overview?from=&to=&pipeline=` → all descriptive + quality aggregates in one JSON.
    - `GET /reports?pipeline=&…` → drill-down list.
    - `GET /reports/{id}` → full trace (input, skill sheet, output, final, diff, audits, quality scores).
  - **Quality scoring subsystem** (§6): `quality_scoring.py` (judge logic) + `scripts/score_report_quality.py` (batch CLI). Scores persist in a new `report_quality_scores` table.
- **Frontend** — `/admin/analytics` page; one component per panel; dependency-free SVG/CSS viz primitives in `$lib/components/analytics/` (`StackedBar`, `Histogram`, `Donut`, `Sparkline`, `StatTable`, `CoverageBar`, `ScoreBar`); a `ReportTrace` component for the drill-down.
- **No new runtime dependencies.** Charts are inline SVG/CSS.

## 4. Data model additions

New table **`report_quality_scores`** (Alembic migration, following the existing migration pattern):

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `report_id` | UUID FK→reports (CASCADE), indexed | |
| `pipeline` | String | "quick" \| "template" (denormalised for fast aggregation) |
| `sheet_fit` | Integer | 1–5 |
| `output_adherence` | Integer | 1–5 |
| `input_faithfulness` | Integer | 1–5 |
| `edit_burden` | Float | objective: normalised diff size (0=no change … 1=rewritten); nullable when no final captured |
| `dimensions_json` | JSONB | per-dimension rationale + flagged spans `{dim: {score, rationale, issues:[{span,note}]}}` |
| `judge_model` | String | e.g. `claude-haiku-4-5-20251001` |
| `rubric_version` | String | bump to invalidate/rescore |
| `created_at` | DateTime | |

Unique on (`report_id`, `rubric_version`) so re-runs upsert rather than duplicate.

## 5. Panels & data sources

Priority reflects the brainstorm: **Panel 4 (Skill-Sheet Quality) is top priority**; all panels in scope.

1. **Volume & Adoption** — reports by week × pipeline (stacked); per-user counts; scan-type mix.
2. **Signal Coverage (telemetry honesty)** — % of in-scope reports with each signal (skill sheet, final-edit, copy, edit_distance, rating, **quality score**). Makes gaps explicit.
3. **Quick vs Template head-to-head** — volume; % with skill sheet; % edited; median `edit_distance`; quick analyser latency; **mean quality scores per dimension**. Every cell shows its denominator.
4. **Skill-Sheet Quality & Usage** *(top priority)* — Ephemeral: count, `analyser_model`/`prompt_version` split, latency distribution, scan-type clusters. Template: `skill_sheet_guided` templates with `usage_count`, refinement count, `template_rating`. **Plus `sheet_fit` score distribution** by scan-type cluster.
5. **Report Trace & Quality (drill-down)** — per report: **input → skill sheet → AI output → final** side by side, with the diff highlighted, the existing audit result, and the three LLM scores + rationales/flagged spans. Subsumes the original "spot test" as a live, evidence-backed view.
6. **Quality Score Distributions** — histograms/box of `sheet_fit`, `output_adherence`, `input_faithfulness`, `edit_burden` across reports, sliced by pipeline and scan-type; **validation view**: scores vs edit-burden correlation (expect adherence/faithfulness to fall as edit-burden rises).
7. **QA / Audit** — existing `report_audits` status distribution, per-criterion breakdown, `prefetch_used` and reviewed rates (reused, not recomputed).
8. **Template Refinement Timeline** — `template_versions` over time per template, correlated with usage and quality.

## 6. Quality scoring subsystem

- **Rubric (per report, on the final/selected output):**
  - `sheet_fit` (1–5) — does the skill sheet cover the right assessments for the scan type + clinical history, with no irrelevant/hallucinated items?
  - `output_adherence` (1–5) — did the report address the sheet's points?
  - `input_faithfulness` (1–5) — no fabricated findings, nothing dropped, correct laterality/measurements (safety-critical); flagged spans for violations.
  - `edit_burden` (objective, 0–1) — normalised diff between AI output and final (`final_edit_diff`/`final_report_content` for quick; `ai_output`→`final_output` for template). Not LLM-derived; a cross-check on the judge.
- **Judge model:** a new `QUALITY_JUDGE` entry in `MODEL_CONFIG`, defaulting to **`claude-haiku-4-5-20251001`** — deliberately a *different model family* from the GLM generator to avoid self-preference bias; fast/cheap for ~162 reports. Configurable.
- **Prompts:** the three judge prompts MUST be **case-agnostic** — structural/multi-domain framing, never single-domain clinical worked examples (house rule). Each returns a structured score + rationale + verbatim flagged spans.
- **Runtime:** `scripts/score_report_quality.py` — batch, re-runnable, idempotent by (`report_id`, `rubric_version`); `--dry-run` and scope filters. Dashboard reads stored scores (no model calls on page view). Trace view offers an on-demand single-report rescore.
- **Reuse:** general report-QA comes from the existing `report_audits`; the judge only covers the skill-sheet chain + faithfulness.
- **Validation:** surface judge rationale in the trace view; show the scores-vs-edit-burden correlation in Panel 6 as a sanity check; `rubric_version` lets us re-score if prompts change.

## 7. Data flow

Page load → admin check → `GET /overview` (descriptive + stored quality aggregates) → render. Panel 5 list/detail on demand. Quality scores are produced **offline** by the batch script and read by the dashboard. All queries read-only, exclude the internal allowlist, respect filters.

## 8. Error handling & edge cases

- Non-admin → `403` / redirect.
- Empty ranges → explicit "no data" states.
- **Sparse signals:** denominators shown everywhere; reports without a captured final get `edit_burden=null` and are excluded from edit-based stats (not counted as zero).
- **Unscored reports:** Coverage panel shows quality-score coverage; aggregates compute over scored reports only, with the denominator visible.
- **Judge failures/cost:** batch script logs per-report errors, continues, and is resumable; bounded to in-scope reports.
- **PHI:** input/skill-sheet/report text appears only in the admin-gated Panel 5 trace, never in aggregates.

## 9. Testing

- **Backend:** unit tests for `analytics_queries.py` against a seeded test DB (quick + template, with/without each signal, an internal-allowlist user that must be excluded); assert exclusion, scoping, date filtering, coverage math.
- **Quality scoring:** `quality_scoring.py` tested with a stubbed/mocked judge (assert prompt assembly, score parsing, upsert by rubric_version, edit_burden computation); `require_admin` returns `403`/`200` correctly.
- **Frontend:** render tests for each viz primitive (empty + populated) and the `ReportTrace` component; page-guard redirect test.

## 10. Phasing (single batch, sequenced for reviewable value)

- **Phase 1 — Descriptive dashboard:** access gate, `/overview`, Panels 1–4, 7–8, viz primitives.
- **Phase 2 — Trace + objective quality:** `/reports` + `/reports/{id}`, `ReportTrace`, `edit_burden`, Panel 5.
- **Phase 3 — LLM scoring:** `report_quality_scores` migration, `quality_scoring.py`, batch script, judge prompts, Panel 6 + score surfacing in Panels 3–5.

## 11. Future (separate batches)

- Telemetry capture fixes: edit diffs + copy events on both pipelines (Coverage panel tracks arrival).
- Optional: ratings UI, `sections_modified`, decision-latency timing.
- Optional: human agree/disagree feedback on quality scores to tune the rubric.
