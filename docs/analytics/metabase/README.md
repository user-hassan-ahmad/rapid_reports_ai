# Metabase SQL pack — skill-sheet report analytics

These queries power the analytics in **Metabase** (no app code/UI). Each delimited
block in the `.sql` files is meant to become **one Metabase Question**; group the
Questions onto a Dashboard.

## Files

- **`descriptive.sql`** — runnable today against the app DB. Volume & adoption,
  signal coverage, quick-vs-template, skill-sheet quality (analyser model/latency,
  scan-type clusters), audit summary, template refinement.
- **`trace_and_quality.sql`** — the per-report trace + LLM quality scores.
  **Requires** the `report_quality_scores` migration applied *and* the batch scorer
  run (`backend/scripts/score_report_quality.py`); until then the score columns are NULL.

## Scope (baked into every query)

- **Organic users only** — internal accounts excluded via the email list in each
  query (default `hassan.ahmad.ucl@gmail.com`). Add emails to every block's list, or
  better, replace the literal with a Metabase variable.
- **Skill-sheet pipelines only** — quick (`report_type='auto'` AND
  `generation_mode='quick_ephemeral'`) and template (`report_type='templated'` AND the
  template's `template_config->>'generation_mode' = 'skill_sheet_guided'`). Legacy
  reports are excluded. This mirrors `backend/src/rapid_reports_ai/analytics_scope.py`
  so the dashboards and the batch scorer agree on what counts.

## Setup

1. **Confirm the data source:** Metabase → Admin → Databases → the app DB
   (the pgVector-Railway Postgres). Add it if absent (host/port/db/user from the
   Railway connection vars).
2. **Create Questions:** New → SQL query → paste a block → Save. Repeat per block.
3. **Display tips:**
   - Trace (Q8): Table; enable row drill-through to read the skill sheet / outputs /
     `dimensions_json` rationale.
   - Scores (Q9): conditional-format `sheet_fit` / `output_adherence` /
     `input_faithfulness` on a 1–5 colour scale; Q9c as a scatter (edit_burden x score).
4. **Quality columns** only populate after: `alembic upgrade head` (creates
   `report_quality_scores`) and a run of the batch scorer.

## Conventions

- Postgres dialect (Metabase runs these against the app DB).
- `edit_burden`: 0 = unchanged draft … 1 = fully rewritten (objective signal).
- Scores `sheet_fit` / `output_adherence` / `input_faithfulness`: 1 (poor) – 5 (excellent), LLM-judged.
