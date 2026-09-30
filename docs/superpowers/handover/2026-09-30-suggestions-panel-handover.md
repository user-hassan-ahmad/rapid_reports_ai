# Handover: Suggestions panel (optional additions + audit fixes, per section)

**Date:** 2026-09-30 · **From:** the session that shipped finding-linked negatives, the
post-generation check and the impression guard (main `30af21d`, live in production).
**Status:** not started. Needs brainstorm → spec → plan → build.
**Applies to:** both sides, **quick** (which the code still calls "auto" in places: `AutoReportTab`,
`report_type: "auto"`) and **templated**. The panel, audit fixes *and* optional items must work
for both. Today the optional items and the post-generation check exist on quick only, so bringing
them to templated is part of this work (phase 2, see "Scope").

## The intent (Hassan's words, paraphrased)

- **"An upgraded optionality picker, per section."** A side panel with easy-to-read optional
  items, grouped by the report section they would go into, each one toggled in and out of the
  report.
- **"Fix with AI should lead to direct report repair injection toggle."** It replaces the current
  path: build a chat message, auto-send it, let the chat model decide, then implement.

These are **one feature**. Every item is a suggested edit tied to a section, applied and undone
in place. One panel and one edit path, not two.

| Source | Section | Edit |
|---|---|---|
| Offered finding negative (e.g. "No ascites.") | FINDINGS | insert next to its finding |
| Optional impression item / recommendation | IMPRESSION | insert (already a toggle today) |
| Audit "Apply fix" (criterion has `suggested_replacement` / `suggested_sentence`) | where its span lives | replace span / insert sentence |
| Audit "Fix with AI" (no instant fix) | where the fix lands | edits from the repair functions (below), no chat |

Chat stays for open-ended requests.

## Scope: both sides (checked 2026-09-30)

There are two sides: **quick** and **templated**. "Auto" is the old name for quick. The goal is
the full feature on both.

| Piece | Quick | Templated today | To reach templated |
|---|---|---|---|
| Viewer and editor `ReportResponseViewer` (options slot, unsaved bar) | ✓ via `IntelliDictateTab` / `AutoReportTab` | ✓ via `TemplateForm` | shared: build once |
| Audit panel `AuditBanner` in `ReportEnhancementSidebar` (Apply fix, Fix with AI) | ✓ | ✓ (prod, last 30 days: 2/2 templated reports audited) | shared: build once |
| Repair functions (`quick_report_quality.py`) | ✓ | — | generic (report text + `FINDINGS`; templated reports store `input_data.variables.FINDINGS`): move to a shared module, e.g. `report_repair.py` |
| Post-generation check (Jev + repair) | ✓ in `generate_quick_report` | ✗ | **easy:** call it after the template generator (`template_manager.generate_report_from_config`) |
| Optional impression items + recommendations (compiled brief, `quick_report_brief.py`) | ✓ | ✗ | **moderate:** 26/57 templates are `skill_sheet_guided`, so run the brief on their stored sheet (check the sheet format is compatible). The 31 legacy templates have no sheet: another source, or audit fixes only |
| Finding-linked negatives ("If present" list) | ✓ | ✗ | **moderate:** the template sheet analyser (`SKILL_SHEET_ANALYZER` role) needs the same directive, and the 26 stored template sheets need refreshing |
| Impression guard | ✓ (quick prompts) | ✗ | templated prompts live in `global_style_guide.py`. Quick and templated are deliberately separate (memory `project_report_path_split`): make the cross-change explicitly, with Hassan's sign-off |

**Suggested phasing:**
- **Phase 1:** the panel and audit fixes, shared by both sides; quick optional items move into
  the panel; the repair functions move to a shared module.
- **Phase 2:** templated sources. The post-generation check first, as it is cheap. Then the
  brief-driven options and finding negatives for `skill_sheet_guided` templates. Then decide what
  legacy templates get.

## What exists today

### Backend: the options payload (already section-scoped)
- `backend/src/rapid_reports_ai/quick_report_generator.py`, `_write_options`. Every option is
  `{id, kind, section, sentence, reason, source, finding?}`:
  - `kind` is `recommendation` | `impression` | `finding_negative`;
  - `section` is `"IMPRESSION"` or `"FINDINGS"`;
  - ids are `opt{i}` for written items and `fn{i}` for finding negatives, which pass through
    verbatim with no LLM.
- The options travel on the SSE `candidate` event as `candidate.options` and are persisted in
  `reports.candidate_reports[0].options`.
- Ticks are saved as `candidate_reports[0].options_applied` via
  `PATCH /api/quick-report/reports/{id}/finalise` (`applied_option_ids`), in
  `quick_report_api.py` around line 564.
- Where they come from: `quick_report_brief.py` `compile_brief`, `decisions["options"]`:
  - impression/recommendation items, capped by `MAX_OPTIONS = 3`;
  - finding negatives, capped by `MAX_FINDING_OPTIONS = 4`. These are contextual negatives,
    negatives whose finding is only borderline, and fallback negatives for findings the sheet
    didn't anticipate. Every one has been screened by the post-generation contradiction check.
- `candidate_reports[0].brief.decisions` persists the routing (`finding_negatives` rows say why
  each item was stated, offered or dropped). `candidate_reports[0].quality_check` holds the
  post-generation telemetry.

### Backend: repair functions (built for Fix with AI to reuse)
`backend/src/rapid_reports_ai/quick_report_quality.py`, with tests in `tests/test_quick_report_quality.py`:
- **`repair_report(report, findings, problems, insert_only=False)`** — one focal Qwen call that
  returns verbatim `{find, replace}` edits. An edit is applied only when `edit_allowed` passes
  (**it never drops a negation**, and on insert-only it never rewrites) and `find` occurs exactly
  once.
- **`insert_findings(report, findings, items)`** — Qwen writes the sentence and picks an anchor;
  **code** inserts it, with a duplicate guard (`_restates`).
- **`remove_negative_clause(report, clause)`** — deterministic, no LLM.
- **`check(...)`** — Jev contradiction and omission.

For the panel these return a *new report string*. A toggle needs the *edit* (span + replacement)
so it can undo, so expose edits rather than applying them in place (`_diff_edits` shows one way
to do that).

### Backend: audit criteria
`backend/src/rapid_reports_ai/enhancement_models.py`, around line 620:
- `highlighted_spans` — verbatim report substrings;
- `recommendation`;
- `suggested_replacement` — `anatomical_accuracy` and `recommendations` only; a drop-in
  replacement for `highlighted_spans[0]`;
- `suggested_sentence` — `report_completeness` only; a sentence to insert;
- `characterisation_gaps`, `flags_identified`, and so on.

Phase 1 runs via `/api/audit` and Phase 2 via `/api/reports/{id}/enhance`; both run after the
report is shown.

### Frontend
- **`frontend/src/lib/utils/impressionOptions.ts`** (104 lines): `ReportOption`, `insertEdit`,
  `removeEdit`, `applyEdit`, `isApplied`, `appliedOptionIds`, and `panelOptions` (which **hides
  `finding_negative`** until this panel exists). These are pure text functions returning one
  `TextEdit`, and **insertion targets IMPRESSION only**. FINDINGS insertion is new work.
- **`frontend/src/routes/components/OptionalAdditions.svelte`** (48 lines): today's panel below
  the editor.
- **`frontend/src/routes/components/IntelliDictateTab.svelte`**: `reportOptions` is set from
  `cand.options` (around line 465, through `panelOptions`) and passed to the viewer; finalise
  sends `applied_option_ids`.
- **`frontend/src/routes/components/ReportResponseViewer.svelte`** (1219 lines): the editor
  (CodeMirror), the unsaved-changes bar, `handleSuggestFix` (the **chat route**: it builds a
  message and dispatches `openSidebar` with `autoSend`), `handleAcknowledge`, and
  `_tryPatchCriterion` (`resolution_method`: `manual` | `ai_assisted` | `dismissed`).
- **`frontend/src/routes/components/AuditBanner.svelte`** (1579 lines):
  - `handleApplyFix`, around line 247, dispatches `applyFix` with
    `{original: highlighted_spans[0], replacement, sentence}`. That is the existing instant fix,
    shown when a criterion carries a suggested replacement or sentence.
  - `handleSuggestFix` is "Fix with AI in chat", the button pair at around lines 758–815.
- **`frontend/src/lib/stores/audit.ts`**: criteria state, `acknowledgeLocal`.
- **Tests:** `src/lib/utils/impressionOptions.test.ts` (vitest) and
  `ReportResponseViewer.options.svelte.test.ts` (vitest-browser; Playwright must be
  chromium-1194). A pre-existing failure, `page.svelte.spec.js` "should render h1", is not ours.

## Decisions already made (don't reopen without cause)
- **Finding negatives are section `FINDINGS`**, their own kind, and not the impression options.
- **Impression line:** a staging-relevant negative cluster tied to the finding is fine in the
  impression. Lists of unrelated or excluded alternatives are not. Don't trim impression
  negatives in code (memory: `feedback_impression_negatives`).
- **Repairs never turn a negative into a finding** (L-47). Any LLM-proposed edit that drops a
  negation is rejected; negatives are removed only in code.
- **Both sides get the feature.** The panel and audit fixes are built once in shared components.
  Bringing optional items and the post-generation check to templated is phase 2. Quick and
  templated prompts are deliberately separate, so any prompt change crossing to templated
  (e.g. the impression guard in `global_style_guide.py`) is made explicitly, with Hassan's
  sign-off.
- **New dev or test frontend routes** ship with the `requireDevRoute` guard from the first
  commit.

## Open questions for the brainstorm
1. **Where does a FINDINGS insertion go?** Beside its finding's paragraph (a `finding` key
   exists for finding negatives, and a key or dictated item for fallback ones) or at the end of
   FINDINGS? Negatives in the same paragraph read best, but anchoring is harder.
2. **Panel placement:** a side panel beside the editor or below it; behaviour on narrow screens.
3. **Which audit criteria get Fix with AI**, and with what input:
   - `characterisation_gap` needs a **negative the dictation doesn't state**. That's policy-1
     territory, so should it insert as a finding negative?
   - `recommendations` needs new text; `report_completeness` needs an insertion.
   - Everything must obey the no-fabrication rule, and `repair_report` only uses facts from the
     dictation.
4. **The endpoint:** something like `POST /api/reports/{id}/repair` with `{criterion}` →
   `{edits:[{find, replace}]}`, reusing `repair_report` / `insert_findings`. It is synchronous,
   targeting under 1.5 s.
5. **Recording:**
   - `options_applied` for options;
   - `resolution_method: "ai_assisted"` plus the applied edit for audit fixes;
   - whether to log dismissals as feedback for retuning the optional tier.
6. **Undo after further edits:** today's option toggles re-find their sentence (`isApplied`).
   Replacements need the same idea: store `{find, replace}` and undo only if `replace` is still
   present verbatim.
7. **Does the audit re-run after fixes?** The re-audit exists (`handleReaudit`).

## Suggested process
1. `superpowers:brainstorming`, with the **visual companion** early (it's a layout question).
2. Write the spec to `docs/superpowers/specs/2026-09-30-suggestions-panel-design.md`, then
   `superpowers:writing-plans`.
3. Backend first, test-driven: the repair endpoint returns edits (no report mutation), plus
   FINDINGS anchoring for options. Then the frontend panel, then the audit wiring.
4. **Check it works:** take a live report (e.g. `de42a105`, the pancreatic head mass, which has
   2 offered FINDINGS negatives plus audit flags), then toggle each item in, undo, finalise, and
   check the database. Drive it in the Chrome session (memory: `reference_prod_smoke_testing`;
   make sure the tab is visible, since the "stuck unsaved bar" earlier came from a hidden tab).

## Context worth reading first
- Ledger `docs/model-migration/parameter-ledger.md`: L-45 (finding negatives), L-46 (what Jev
  can and can't check), L-47 (post-generation check and its safety fixes), L-48 (impression
  guard).
- Specs `docs/superpowers/specs/2026-09-29-policy1-confirmed-branch-negatives-design.md`
  (rev 2) and `2026-09-30-post-generation-check-design.md`. Its "Hand-off to the UI spec"
  section lists the payload fields.
- Memory: `project_finding_negatives`, `project_post_generation_check`,
  `feedback_impression_negatives`, `project_compiled_brief` (naming primes; plans are floors).
