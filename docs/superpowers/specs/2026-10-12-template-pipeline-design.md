# Template pipeline for the scratchpad (project 1) — design

Date: 2026-10-12. Status: agreed with Hassan in brainstorming; two independent design reviews folded in. Builds on
`feat/template-stack` and the template requirements spec (`2026-10-12-template-requirements-design.md`). The
learning loop (project 2) gets its own spec; this design only captures the evidence it needs.

## Mission and decisions

The scratchpad becomes THE way templates are reported; today's template Generate is a fallback to be retired.
Every step of a template's life must therefore produce, keep and use a sheet in the grammar, in the leanest form.

Decided by Hassan:
- Scratchpad is the way; today's path is fallback (no second, free-form sheet is maintained).
- The sheet is never shown to users. Sheets are only written by prompts; requirements appear as report behaviour.
- Templates store the example reports the user pastes at creation.
- Post-generation options are skipped on the scratchpad path.
- Banner at ship: "Your templates have been upgraded to the new workflow. If a template doesn't feel right, you can
  create a fresh one from a few example reports." (dismissible, once per user)
- Existing skill-sheet templates get the hand-fixed converted sheets; legacy v1 templates are soft-deleted.

## Building blocks

### 1. One writer

The creator's analyser writes the grammar directly from the example reports, the scan type and the context notes
(production version of `template_sheet_lab_prompts.ANALYSER_SYSTEM_PROMPT`). It keeps returning the follow-up
`questions` the creator screen shows. The same call is the future rebuild (not built here). The conversion prompt
is kept only if the lab below shows the direct analyser loses.

Rules added to the writer prompts (analyser, refine, repair): one structure per NORMAL ("or group" removed); a
normal names its structure in its own text; exemplars use slots for every value, code, grade or time window and
carry no diagnosis; one sentence per NORMAL/NEGATIVE. Prompts stay case-agnostic.

**Lab (settles direct analyser vs analyser + conversion).** Material: the 31 production templates' real reports
(production data, scratchpad only). Hold one out: build the sheet from the other reports, test on the held-out
report's dictation through the preview function (block 3). Score: (a) unit checks — every normal is normal, one
structure per normal, no placeholders in normals, mandatory content of the hand-fixed sheet present, lint usable;
(b) the e2e hand read against the radiologist's own report; (c) region count vs the hand-fixed sheet. Gold: the
hand-fixed sheets. Two runs maximum per arm. Limitation: the reports are our template output edited by the
radiologist (latest version where one exists), not reports they wrote from scratch, so the lab favours today's voice.

### 2. One server save function

`save_template_sheet(template, new_config, origin)` is the only path that writes `skill_sheet`. Called by
`POST /api/templates`, `PUT /api/templates/{id}`, `POST /api/templates/skill-sheet/save` and version restore.
It runs only when the sheet changed (the existing equality check in `_carry_structure`).

1. Parse (template mode).
2. Save-time checks per NORMAL/NEGATIVE: code — no `{slot}` in the text; Jev yes/no — "states that something is
   normal or absent?" and "describes more than one structure?" (one Jev call per sheet, questions keyed per unit).
3. On any lint error or failed check: one repair call (`REPAIR_SYSTEM_PROMPT` with the failures listed).
4. Still failing:
   - a single NORMAL/NEGATIVE from the analyser or a repair → dropped, logged (template, unit, reason);
   - a unit the user asked for in chat → the edit is not applied: previous sheet kept, the user told "couldn't
     apply: <their instruction>";
   - the whole sheet unusable, or a guided template's sheet no longer in grammar form → refused: previous sheet
     kept (creator: the save fails with a plain message and the draft stays on screen);
   - a mandatory unit (one that backs "Every report will include/state") lost by an automatic write → refused.
5. Store the parse as today (`store_parsed`), stamp `analyser_version` and `grammar_version` on the structure.

Chat-to-edit (`refine_skill_sheet`) gets the grammar (as the conversion prompt carries it) and writes the grammar;
its reply stays framed as report behaviour. Version restore accepts only versions saved after the upgrade
(enforced in the endpoint; pre-upgrade versions stay in history as the backup).

### 3. One preview function

The lab harness (`scratchpad/convlab/e2e.py`) promoted to a server function:
`preview_report(sheet, scan_type, history, dictation, conclusion)` → regions, grouping, assumed normals (offered,
kept, dropped with reason), the findings block exactly as `regionState.buildFindingsBlock` builds it (Technique
first, regions with their assumed normals, other labels, General and unplaced sentences as said), and the template
stack report. Used by:
- the creator's test preview (today it previews today's path, so the radiologist approves something else);
  re-run on demand or after an accepted refine turn, not after every turn;
- the lab;
- later, the rebuild regression gate.

### 4. One evidence record

- **Example reports:** stored with the template (new table `template_examples`: template_id, text, sha256,
  created_at, source="pasted"). De-identified at paste: a code backstop (dates of birth, NHS/MRN/accession-shaped
  numbers, "Name:" fields) plus a Jev "contains a patient identifier?" check; flagged spans are removed before
  storage. A one-line notice in the creator. Deleted with the template; never used across users.
- **Chat turns:** each refine instruction stored raw (template_id, instruction, version before/after). The change
  it caused is the TemplateVersion diff; nothing new is computed now.
- **Version stamps** on every report (`reports`) and every scratchpad session log (`dictation_stack_logs`, new
  `template_id` column, one migration): template_id, sheet_hash, grammar_version, analyser_version, path
  (`scratchpad` | `fallback`).
- **Session record (gate):** adds the normals offered, the normals the Jev check dropped and why (covered / hedged /
  contradicted). The dictated finding related to a removal is deferred (it needs its own call).
- **Template edit capture fixed.** Copy capture can record text from a different report against a template report
  (`quality_scoring._assemble_case` documents it), so template reports have no trustworthy final today. Capture is
  tied to the report it came from; the stored text is named for what it is (copy-time text), and an untouched
  report is never treated as approved.

## Integration clean-up

- Scratchpad path skips `/prepare` (Phase 1) and the post-generation options; the fallback keeps them behind the
  existing flag, reading section names and terminology from the parsed structure (no hard-coded FINDINGS /
  IMPRESSION, no free-form block names).
- `coverage_sections` derived from the parsed structure in the save function; `/api/templates/skill-sheet/
  extract-coverage` and the refine panel's call to it removed together.
- Quality scoring judges a report against the sheet it was written from (by sheet_hash) and groups by path in the
  rubric and the Metabase dashboard.
- Today's path runs in shadow on a sample of scratchpad sessions (the quick path's `RR_STACK_SHADOW_RATE`
  pattern), not on every Generate.

## Ship steps (with the scratchpad merge)

1. The one-off write script: dry run, then apply. It writes the 31 converted sheets (skip any edited since the
   pull or not usable), snapshots the pre-upgrade state as a TemplateVersion first, writes a JSON backup, and
   soft-deletes the active legacy templates. The 31 hand-fixed sheets carry Hassan's template-content decisions
   (lab `SUMMARY.md`).
2. `template_examples` starts empty for the 31: their generated reports stay in `reports` and are not copied as
   examples (they are our output). Their first examples arrive when edit capture produces trustworthy
   finals or the user re-creates the template.
3. The banner.

## Out of scope here (tracked)

- Runtime scratchpad bugs from the e2e lab: 8-normals-per-region cap; context RULEs not stopping assumed normals;
  FIXED lines inside findings paragraphs not printed on the scratchpad path; the writer lifting exemplar
  specifics; TERM AVOID/PREFER rewriting dictated words (apply TERM only to sheet-originated text). Pre-merge, own
  tasks.
- Fallback comparison: today's path on old vs converted sheets (pre-merge).
- Running rebuilds; Jev re-verification of standing instructions; the learning loop (project 2: rank evidence,
  learn style never clinical content, classify edits, recurrence threshold, proposals approved by the radiologist,
  replay scored by edit rate, change control).
- v1 template endpoints (dead code) — separate cleanup.

## Failure behaviour

- Jev or repair call fails at save → the automatic write is refused (previous sheet kept, logged); a user edit
  reports "couldn't apply". Creation shows a retry.
- De-identification check fails → the example is not stored (the template is still created from it); logged.
- Preview fails → the creator shows the error; saving is not blocked by a failed preview.
- Version stamps missing (older rows) → treated as unknown; never backfilled by guessing.

## Testing

- Save function: each origin × each failure branch (dropped unit logged, user edit refused with message, unusable
  sheet refused, grammar→free-form refused, mandatory unit loss refused, unchanged sheet skipped); restore rejects
  pre-upgrade versions; coverage_sections derived.
- Writer prompts: the lab above; refine round trip — three instructions per template keep lint clean.
- Preview function: parity with the lab harness on the 31 e2e cases (same findings block).
- Evidence: stamps written on report and log rows; gate record fields; examples stored de-identified and deleted
  with the template; edit capture tied to its own report (regression test for the cross-report case).
- Scratchpad path: no `/prepare` call and no options job when stack is set.
