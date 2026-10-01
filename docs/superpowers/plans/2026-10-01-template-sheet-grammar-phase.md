# Phase G — template sheet grammar (plan addendum)

> Executed with superpowers:subagent-driven-development (Opus 5.5 for every subagent). Spec:
> `docs/superpowers/specs/2026-10-01-template-sheet-grammar-design.md`. Parent plan:
> `2026-09-30-template-pipeline-mirror.md` — Tasks 9/10 (E1) are done (fallback extractor, E1b);
> Task 11 (brief) is replaced by G3; Tasks 15–20 follow Phase G unchanged except where noted.

Conventions as the parent plan (TDD, `cd backend && uv run pytest -q`, commit trailer
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, never edit `global_style_guide.py`
without sign-off, prompts case-agnostic, no production sheet/report text committed — synthetic
fixtures only).

### G1 — Grammar parser, lint, schema extension
- Create `src/rapid_reports_ai/template_sheet_grammar.py`: `parse_sheet(sheet) -> GrammarResult(structure: SheetStructure, errors: List[LintError])`, `LintError(line: int, text: str, reason: str)`, plus `render_unit(...)` helpers used by tests.
- Extend `template_sheet_structure.py` schema per spec (Rule.effect values; `items`, `anchor`, `position`; `SheetStructure.source`). Existing extractor + `build_structure` keep working (`source="extracted"`); bump `STRUCTURE_VERSION` only if stored structures would mis-load (they won't if new fields default).
- `tss.fresh()` serves grammar structures identically.
- Tests (`tests/test_template_sheet_grammar.py`): one per keyword/effect (happy path), one per lint reason, a full synthetic sheet (all units) → usable structure with correct sections/paragraphs/conditions/sources; prose passthrough; old-syntax `IF [` → lint error; `WHEN` without subject → error; unit outside a paragraph; duplicate SECTION.

### G2 — Lab harness + analyser prompt (lab copy)
- `src/rapid_reports_ai/scripts/template_sheet_lab.py` + `src/rapid_reports_ai/template_sheet_lab_prompts.py` (lab-only prompt module; production `analyze_examples_to_skill_sheet` untouched). Reuse the production analyser's call shape (read it: `template_manager.py:analyze_examples_to_skill_sheet`) with an amended system prompt that emits the grammar; include the lint-repair call.
- Inputs: prod templated reports via Metabase `/api/dataset` (DB 2; creds in `backend/.env` METABASE_URL/METABASE_API_KEY; UA "curl/8") — 4–5 `report_content` per template for the 8 templates in the spec, plus 2 held-out reports' `input_data.variables` (FINDINGS, CLINICAL_HISTORY) per template for G3's cross-link check. Cache the pulled data in the scratchpad (never in the repo).
- Dev: ≤ 3 templates, ≤ 3 iterations. Then lab run 1 on all 8. Report parse rate (first pass / after repair), lint error classes, per-template hand read (rule kinds, subjects, voice), and the generated sheets' paths.

### G3 — Template brief (replaces Task 11)
- `template_brief.py` per parent plan Task 11 + spec §3, consuming `SheetStructure` from either source, plus the new effects (spec table): list_missing (Jev per item), insert_before, suppress_paragraph_negatives, suppress_section, suppress_headers, order. If-present ignored (off).
- In-place rendering: for grammar sheets each unit line is rewritten/removed where it sits (source_lines are the unit lines).
- Tests: one per decision row and per new effect, stubbed Jev/Qwen; failure → raw path.

### G4 — Lint-on-save hook
- Analyse/refine/save paths: when a sheet is in grammar form (has `## Report Structure`), parse; on errors one repair call; store grammar structure directly (no background extraction needed) — else fall back to `schedule_structure` (extractor). Behind `RR_SHEET_GRAMMAR` (default off until prompts are signed off).

### G5 — Refine prompt (lab) + round-trip
- Lab copy of `refine_skill_sheet` prompt preserving the grammar; 3 instructions × 8 lab sheets; report lint-clean rate.

### G6 — Conversion of the 26 stored sheets (lab)
- Lab conversion prompt + provenance check (reuse E1 verifier ideas: every quoted unit text grounded in the old sheet) + lint; report grounded/lint-clean rate per sheet. No writes to prod.

### G7 — Sign-off package + production wiring
- Present to Hassan: analyser prompt, refine prompt, conversion prompt, TEMPLATE_SHEET_HEADER_BRIEF label additions. On approval: wire into production paths behind `RR_SHEET_GRAMMAR`, then continue with parent Tasks 15–20 (pipeline, endpoint, E2 on grammar sheets + fallback sheets, rollout).
