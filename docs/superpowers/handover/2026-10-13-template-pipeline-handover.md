# Handover: template pipeline for the scratchpad (2026-10-13)

Start here in the next session. Two workstreams remain: **(1) finish project 1 (phases D, E, F) and merge**, and
**(2) the architecture review follow-up** (separate, after or alongside).

## Where things are

- **Branch:** `feat/template-stack` in worktree `.claude/worktrees/hybrid-stack` (local, not pushed), on top of
  `feat/stack-tighten` and PR #31 `feat/hybrid-stack`. HEAD `34ea0c6f`. Full backend suite: 3765 passed, 1 skipped.
  Frontend `bun run check`: 1198 errors **pre-existing on main too** (old untyped JS) — judge by "0 new in touched files".
- **Spec:** `docs/superpowers/specs/2026-10-12-template-pipeline-design.md` (+ `…-template-requirements-design.md`).
- **Plan:** `docs/superpowers/plans/2026-10-12-template-pipeline.md` (phases A–F). Plan errata below override it.
- **Production data (never in the repo):** `~/Code/rr-template-conversion-private/` = private GitHub repo
  `user-hassan-ahmad/rr-template-conversion-private`. Holds the 31 hand-fixed converted sheets (`final/*.final.md`),
  hand reads, e2e cases, FALLBACK.md, writer/RESULT.md, SUMMARY.md (template decisions + sheet defects), `apply_prod.py`,
  `e2e.py`, `lint.py`. Delete both copies after the upgrade ships.
- **Local live testing:** `local/test-combined` (local only, never push); backend :8000 from the local-combined worktree,
  frontend :4173 from the hybrid-stack worktree.

## Done (all independently reviewed and approved)

| Phase | What | Commits |
|---|---|---|
| A | Scratchpad fixes: 16 normals/region; subject-less normals labelled for Jev only; context RULEs stop their normals; dropped normals returned with reasons; region-scoped "covered" (contradiction still whole dictation; global-normal stub removed); writer rules (FIXED lines kept unless contradicted; examples are wording only; TERM only on report wording; scores/grades/time windows only when dictated); undictated-number flags (not yet shown in UI) | fefac61…9227e3d |
| A5 | Fallback lab: today's path on converted sheets 33 errors vs 43 on old → no change needed | lab only |
| B | One save function `template_sheet_save.vet_sheet` for create/PUT/creator save/restore; save-time unit checks (abnormal-as-normal, placeholders; multi-structure check OFF — no clean Jev gap); coverage from the parse; pre-upgrade restore refused; empty/mode-switch guarded | 222a702…b1fbc65 |
| C | Preview through the scratchpad path (`template_preview.py`); writer = **D** (direct grammar analyser, ~11 s/1 call) via `template_writer.write_sheet`; labelled `Opening (<state>):` lines; strict lint kept, a voice line is dropped (never the sheet) on automatic writes; exemplars slot values and `{diagnosis}`; chat-to-edit writes the grammar; vet judges only what a write adds/changes; refine asks when an instruction may not fit the scan | d818b80…34ea0c6f |

Stroke sheet edited in the private repo (time-window instruction removed, ASPECTS slotted, grades conditional, dictated
MRV kept).

## Remaining for project 1 (before merge)

Run with superpowers:subagent-driven-development (implementer + spec review + code review per task). Plan task text is
in the plan file; apply the errata.

- **D — evidence** (D1 migration `20261013090000`: template_examples, template_chat_turns, reports.generation_stamp,
  dictation_stack_logs.template_id/stamp; D2 stamps (write_sheet already returns `analyser_version`); D3 gate
  offered/dropped (server already returns `dropped`); D4 de-identified examples + creator notice (D-arm writer has the
  examples); D5 chat turns; D6 copy capture scoped to the report + template final = latest ReportVersion; D7 quality
  scoring against the stamped sheet + path).
- **E — clean-up:** E1 no Phase 1/options on the stack path **and make the template stack always take the lean
  generator + post-generation + number check regardless of `RR_TEMPLATE_MIRROR`** (today, in prod, template scratchpad
  reports get NO post-generation check — main.py ~1904 `use_mirror`); E2 fallback reads sections/terms from the parse.
  **Capped rows vanish on templates once options are skipped — show them in the scratchpad.**
- **F — ship:** F2 apply Hassan's template-content decisions (SUMMARY.md) and fix sheet defects: `{value}` slots in
  NORMALs (cardiac_mr_2 ×7, cmr_non_stress), FIXED lines asserting patient state (oncology staging "No adverse interval
  changes", cmr_non_stress "No previous CMR available", HRCT "No contrast"); re-lint every sheet via `vet_sheet`
  (none left unusable). F3 move `apply_prod.py` into `backend/src/rapid_reports_ai/scripts/template_upgrade_apply.py`
  (old sheet kept as a pre-upgrade TemplateVersion + JSON backup; skip stale/refused; soft-delete 16 active legacy
  templates; dry run default). F4 banner C ("Your templates have been upgraded to the new workflow. If a template doesn't
  feel right, you can create a fresh one from a few example reports."). F5 remove `RR_STACK_DEBUG` trace; independent
  whole-branch review; live smoke on local/test-combined; merge/push **only on Hassan's go-ahead**; prod write via
  `railway run` dry run → his yes → apply.

## Plan errata (override the plan text)

1. Grammar fixtures parse `usable` only with pipe sections + an impression section, e.g.
   `SECTION FINDINGS | header: "Findings:" | role: findings` and `SECTION CONCLUSION | header: "Conclusion:" | role: impression`.
2. Hybrid-stack routes are under `/api/canvas/stack/...`; route tests use the `authed` fixture.
3. Shared fixtures: `from tests.template_sheet_fixtures import GOOD, BAD_UNIT`. `check_units` fakes take `(st, sheet="")`.
4. `model_call` lives in `template_sheet_model.py`. `vet_sheet(sheet, origin, previous="") -> VetOutcome(status, sheet,
   message, dropped, coverage_sections)`; PUT/refine/restore return `notice` on ADJUSTED.
5. Ad-hoc scripts: run from `backend/` with `PYTHONPATH=src .venv/bin/python` (else the venv resolves another worktree).

## Follow-ups (after merge unless noted)

- Undictated-number flags: surface in the review rail; first tighten the bare-value rule (mask list markers/identifiers/
  dates; require a label or measurement word) and add NORMAL/NEGATIVE text to reference limits.
- Writer variance seen in the C4 smoke: one multi-structure NORMAL despite the rule; duplicate normal across overlapping
  paragraphs; thin normals where all examples were abnormal (by design — encourage mixed examples).
- Letter codes (ASPECTS-style) aren't caught by the number flag. Thorax comparison-line drop (writer variance) isn't caught
  by the omission check.
- Learning loop (project 2, own spec): evidence ranking, style-not-content, recurrence threshold, proposals approved by the
  radiologist, replay scored by edit rate.

## Architecture review (separate session)

Findings and ranked changes for the NEW pipeline are in memory `project_scratchpad_architecture_review.md`. Headline
items: Generate still waits on the full quick analyser; dropped normals invisible and Jev failure silent; template stack
quality tied to `RR_TEMPLATE_MIRROR` (overlaps E1); two brief builders + findings block built in TS and Python; contrast
facet re-asked per session; `/assumed` uncached. Verify claims in code before acting (an earlier review overstated the
"subtraction" point for the quick path with a slim sheet).

## Working notes

- Auto mode: `~/.claude/settings.json` has `autoMode.allow` rules so Agent launches (implement/review/test in this repo,
  reading the scratchpad and the private data copy) pass the classifier. Backup: `settings.json.bak-automode`.
- Hassan's philosophy: root cause over narrow patches; simple, lean, adaptable; verify claims in code; sample before
  committing to a direction (labs of ~5 first).
