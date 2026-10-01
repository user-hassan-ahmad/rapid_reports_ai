# Template pipeline mirror — design

**Date:** 2026-09-30 · **Branch:** `feat/template-pipeline-mirror` · **Status:** design agreed in
brainstorm; §5 prompt package awaiting Hassan's explicit sign-off.
**Inputs:** `docs/superpowers/handover/2026-09-30-template-pipeline-mirror-handover.md`, the
"Brainstorm outcome" section of `2026-09-30-suggestions-panel-handover.md` (Review rail), memory
`project_report_path_split`.

## Goal

Templated reports (`skill_sheet_guided`) follow the same flow, machinery, model routing and safety
rules as quick reports:

```
skill sheet ─► brief (sheet reconciled with this dictation) ─► generate ─► post-generation check
           ─► options ─► persist GenerationArtifacts ─► audit + enhance (already shared) ─► Review rail
```

Only three things differ, all because a template sheet is a stored document in the radiologist's
voice rather than a sheet written fresh for each case:

1. **Where the items come from.** A save-time structuring pass turns the stored sheet into typed
   items once; the per-case engine then runs on those items exactly as quick does.
2. **What the brief touches.** Only conditional content is reconciled. Voice (fixed blocks,
   terminology, phrasing, paragraph patterns, examples) passes through verbatim.
3. **Sections.** Output sections come from the template's own headings, including an optional
   CLINICAL HISTORY section.

The lesson carried over from quick: the sheet had no awareness of this case's findings, so the
generator had to resolve a bloated, conditional instruction sheet against every possible case.
Here Jev resolves every condition against the dictation before generation, Qwen makes the
judgement calls it already makes on quick, and code owns every removal.

## Evidence that shaped the design (2026-09-30)

- **Q2 test on all 26 stored `skill_sheet_guided` sheets.** `quick_report_brief.parse_sheet` →
  `render` round-trips 26/26 byte-for-byte, but every quick extractor (mandatory negatives,
  normal-study path, differentials, recommendations, style exemplars, impression variants,
  measurements, If present) finds **0/26**. Template sheets use a different vocabulary: Fixed
  Blocks, Per-Section Construction Rules, Interpretive Clause Rules, Conditional Suppression
  Rules, Negative Finding Rules, Impression Construction Rules.
- **Content of the 26:** 0 `{{parameters}}` (the handover's premise was wrong); 176 IF lines, all
  26 sheets; 124 in `IF [cond] THEN …` form, 50 irregular (bold, `IF x: "…"`, compound OR,
  context style switches); 62 `[NEEDS VERIFICATION]`; 51 per-paragraph Mandatory negatives
  blocks; 99 Normal patterns; no L-45 If-present list. Curly-brace slots are common in Abnormal
  patterns (`"The {structure} is {abnormality} measuring {measurement}…"`).
- **Usage:** 26 guided (all active, 133 uses, 2 reports in the last 60 days); legacy 16 active +
  15 inactive (1 report in 60 days).
- **Template endpoint today:** `POST /api/templates/{id}/generate` returns one JSON response,
  saves via `create_report(report_type="templated")` with no `candidate_reports`, and carries a
  dormant validate-and-fix pass behind `ENABLE_TEMPLATE_STRUCTURE_VALIDATION`. The template
  prompt stack has no hardening preamble (quick's label semantics live in hardening principle 12).
- Only 2/26 sheets define a history section in their Structural Pattern.

## Decisions (brainstorm)

| # | Question | Decision |
|---|---|---|
| Q1 | Share or copy the pathway-neutral logic | **Shared engine, per-side extractors.** Neutral mechanics move to shared modules both sides import; each side keeps its extractor, compiler and prompts. |
| Q2 | Can the brief read template sheets | No: new extractor. **Save-time Qwen/gpt-oss structuring pass** into a codified structure, verified by code, refreshed on every sheet change. Regex alone cannot handle the variability. |
| — | Structuring model | Run **Qwen and gpt-oss** on the 26 (memory `project_model_routing`: nested structured output → gpt-oss); pick on evidence. |
| Q3 | Legacy templates (no sheet) | **Retire:** hidden from the picker and creation; generate refuses them with a clear message; reports and History untouched; no rows deleted. |
| Q4 | Finding-linked negatives (L-45) | **Derived into the structure**; the user's sheet is never rewritten. Refreshing the 26 = re-running structuring. |
| Q5 | Streaming | Single JSON response plus an `artifacts` field; no SSE (adds ~1–2 s). |
| Q6 / L-36 | Clinical history | Never written into the report **except** in a dedicated CLINICAL HISTORY section the sheet defines (radiologist preference). That section restates the platform's clinical-history input tersely: no new content, no inference, nothing in any other section. Written by a separate small call; placed by code. |
| — | Lean pass | Port quick's `03cea37` mechanism: originals untouched for the fallback, `_BRIEF` variants built with asserted `_swaps` (§5). |

## §1 Architecture

**Flow for `skill_sheet_guided` templates, behind `RR_TEMPLATE_MIRROR` (Railway kill switch):**

```
SAVE TIME (skill-sheet save / template update when skill_sheet changes / refine save → background task)
  stored sheet ─► structuring pass (model chosen in E1)
               ─► code verification (verbatim spans, coverage gate, atomic normals, …)
               ─► template_config.sheet_structure

REQUEST TIME (POST /api/templates/{id}/generate)
  flag on AND structure fresh AND structure usable?
     no ──► today's path, byte-identical (raw sheet, original prompts)
     yes
      ├─► template brief: shared reconcile engine (Jev + Qwen + plan + fallback, parallel)  ┐
      ├─► history section: small Qwen call (only if the sheet defines one)                 ┘ parallel
      ├─► generate (TEMPLATE_REPORT_GENERATOR, reads brief, _BRIEF prompts)
      ├─► code inserts the CLINICAL HISTORY section
      ├─► options written (template style) ─► post-generation check (sections from structure)
      └─► persist candidate_reports[0] ─► JSON response incl. artifacts
```

**Modules.**

| Module | Role |
|---|---|
| `report_reconcile.py` (new, shared) | Jev/Qwen calls, negative classification (contradicted / expected / keep), `route_finding`, bundled split with word provenance, impression plan (new optional `inclusion_logic` input), unanticipated-finding fallback, KEEP/OMIT/DO NOT ASSERT routing. Moved out of `quick_report_brief.py`. |
| `report_review.py` (new, shared; name agreed with the rail branch) | `check`, `repair_report`, `insert_findings`, `remove_negative_clause`, `edit_allowed`, `run_quality_check`, taking `sections` and protected spans instead of the FINDINGS/IMPRESSION regex. Moved out of `quick_report_quality.py`. |
| `generation_artifacts.py` (new, shared) | The `GenerationArtifacts` pydantic model; emitted by both sides. |
| `quick_report_brief.py` / `quick_report_quality.py` | Keep the quick extractor and compile; public API unchanged; thin over the shared modules. |
| `template_sheet_structure.py` (new) | Structuring prompt, schema, verification, coverage gate, staleness hash, background trigger. |
| `template_brief.py` (new) | Structure → items → shared reconcile → in-place brief text + decisions. |
| `template_pipeline.py` (new) | Orchestration mirroring `generate_quick_report`. |
| `template_manager.py` | `_generate_report_skill_sheet_guided(brief=…)` selects the `_BRIEF` prompts and brief header; without a brief, today's code path exactly. |

Shared modules import neither pathway. Neither pathway imports the other's prompts or generator.
Quick output must stay byte-identical through the refactor (golden tests, §6).

## §2 The sheet structure (save time)

**Schema** (`template_config.sheet_structure`):

```
sheet_structure {
  version, sheet_hash, model, created_at, usable: bool
  sections[]      {name, role: history|technique|comparison|findings|impression|other,
                   header: "as written in reports" | null (implicit), order}
  paragraphs[]    {id, section, name}                 internal groupings; never output headers
  rules[]         {id, section, paragraph, condition, condition_source: findings|history|context,
                   effect: suppress|replace|append|use, target, then_text, source_lines[]}
  negatives[]     {id, section, paragraph, text, condition | null, source_lines[]}
  normals[]       {id, section, paragraph, structure, text, source_line}     atomic, one structure each
  fixed_blocks[]  {id, section, text}
  terminology     {preferred[], suppressed[]}
  if_present[]    {finding, section, paragraph, negatives[{text, tag: core|contextual}]}
  coverage        {if_lines, if_covered, negative_lines, negative_covered, uncovered[],
                   verbatim_failures[]}
}
```

- `sections[]` holds output headings only, in order, implicit ones included (`header: null`).
  This is the `sections[]` the rail reads.
- `condition` is phrased as a statement Jev can answer ("The dictated findings report
  pneumoperitoneum"). `source_lines` keep the original wording for traceability and in-place
  rewriting.
- A negative that appears in several places (a paragraph's Mandatory negatives and Negative
  Finding Rules) is **one item with every `source_line`**.
- Normal patterns are split into **atomic normals**, one structure each, so a finding in one
  organ flags only that organ's normal.
- `if_present[]` is the only generated content: the L-45 directive, phrased in the sheet's own
  negative style. Everything else is extracted.

**Code verification**, run after the model and before storing:

1. **Verbatim:** `text`, `target`, `then_text`, `source_lines`, fixed blocks and terminology are
   spans of the sheet (after whitespace/quote normalisation). An item that fails is dropped and
   logged. The model cannot invent a negative, rule, normal or fixed block.
2. **Atomic normals:** every word of an atomic normal comes from its source line (the word
   provenance check used for bundled negatives).
3. **Coverage gate:** every sheet line holding a conditional maps to a rule, and every quoted
   negative line in a negative section maps to a negative item. `usable = true` only when both
   are complete. The lean `_BRIEF` prompts drop the instructions that handled unlabelled
   conditionals, so they must only ever meet a fully labelled sheet. A sheet that fails the gate
   generates down today's raw path with the original prompts.
4. **Sections** exist in the sheet's Structural Pattern.
5. **if_present:** each entry is a negative (`is_negative`), has a valid tag, and does not
   duplicate a sheet negative.

**Staleness and triggers.** `sheet_hash` = sha256 of the sheet. A missing or stale structure, an
old `version`, or `usable = false` means the raw path, and a stale or missing structure queues
a restructure. Triggers: skill-sheet save, template update when `skill_sheet` changes, refine
save (background task; `flag_modified` on the JSON column). `extract_coverage_sections` is left
alone.

**Prompt rule:** case-agnostic, structural examples only (`IF [condition] THEN suppress
"[negative]"`), per memory `feedback_case_agnostic_prompts`.

`[NEEDS VERIFICATION]` markers pass through untouched.

## §3 The template brief (at generation time)

**Inputs:** fresh, usable structure; scan type; dictated findings; clinical history.
**Output:** `Brief {text, decisions, reconcile_ms}`, the type quick uses.

**Reconcile, in parallel (~0.5–1 s):**

- **Jev, findings state** (scan type + dictated findings, as quick): rules whose
  `condition_source` is findings, normals affected, If-present findings present. This is the
  default for every rule not explicitly tagged history/context.
- **Jev, context state** (findings + clinical history): only rules tagged history or context
  ("oncology context", "prior surgery"). History is read here, never written.
- **Qwen classifier** (shared, unchanged): each surviving negative → contradicted / expected /
  keep; second opinion on affected normals.
- **Impression plan** (shared) with the sheet's *Inclusion logic* text as optional input so the
  plan respects the radiologist's promotion preferences. Quick passes nothing, unchanged.
- **Fallback** for unanticipated findings (shared; offered, never stated).
- **History-section call**, only if the sheet defines one.

**Decisions** (quick's thresholds; condition met = Jev ≥ 0.5):

| Item | Met | Not met |
|---|---|---|
| Rule `suppress` / `replace` | target → `OMIT: "…" — the dictation reports: …`, plus `INSTEAD: "then_text"` for replace | rule lines removed; the target negative stands |
| Rule `append` (interpretive clause) | `APPLY: "then_text"` | removed |
| Rule `use` (style switch) | `USE: "then_text"` | removed |
| Negative with a condition | to the classifier | removed |
| Negative (unconditional or met) | classifier → `KEEP` / `OMIT` / `DO NOT ASSERT` | — |
| Atomic normal | unaffected → kept verbatim | affected → "do not assert as normal", never deleted |
| If-present negatives | `route_finding` → stated (KEEP) / offered / do not assert / dropped; cap 4 | — |
| Normal-study impression block | dropped by code when any positive dictated item exists | kept |

**Rendering in place.** The brief is the stored sheet with every covered line rewritten where it
sits: each rule's source lines become the resolution or disappear; every copy of a negative
becomes its labelled line inside its own block; atomic normals are re-rendered per paragraph;
stated If-present negatives are added to their paragraph. An Impression Plan section is appended
as in quick. Voice passes through verbatim.

**Options** use quick's payload `{id, kind, section, sentence, reason, source, finding?}`:
finding negatives take the output heading of their paragraph's section; impression items take
the section whose role is impression (IMPRESSION, CONCLUSION, …). No recommendation options:
template sheets carry recommendation phrasing, not a recommendation scope. The option-sentence
writer is shared logic but receives the sheet's impression quoted examples and terminology as
style on the template side.

**Decisions log:** quick's dict plus `rules[]` `{id, condition, met, score, action}`.

**Failure:** brief error or timeout → raw sheet with the original prompts, `brief_used: false`.
History call failure → section omitted, logged. Never blocks a report.

## §4 Generation, history section, check, persistence

**Generation.** `_generate_report_skill_sheet_guided(brief=…)` reads `brief.text` with the §5
`_BRIEF` constants and the brief header. Model role `TEMPLATE_REPORT_GENERATOR` and fallback
behaviour unchanged. When the sheet defines a CLINICAL HISTORY section, the generator is told it
is supplied separately and does not write it.

**CLINICAL HISTORY section.** A reasoning-off Qwen call restates the input in terse referral form
(age and sex abbreviated, facts as noun phrases, question last). Code checks every content word
comes from the input; on failure the section is omitted and logged. Code inserts it under the
sheet's header at its `sections[].order` position.

**Post-generation check, section-generic (`report_review.py`).**
- `check` / `run_quality_check` take `sections` (name, header, role) and protected spans. Quick
  passes what its regex yields today → byte-identical.
- The report is split on the structure's headers; an implicit header covers text up to the next
  known one.
- Contradiction: clauses from findings, impression and other sections. History, technique and
  comparison are skipped (protocol text and prior-study names are not dictated findings).
- Omission: against the report with the history section removed.
- Repairs unchanged (L-47: negatives removed only in code, never turned into findings), plus
  `edit_allowed` rejects edits that touch the history span or a fixed-block span, or that
  introduce a suppressed term. A contradiction inside a fixed block becomes a flag for the rail,
  not an automatic repair.

**Persistence and response.** `create_report(report_type="templated")` gains
`candidate_reports=[record]` with quick's fields (`options`, `options_applied: []`, brief
decisions/text/`brief_used`/`reconcile_ms`, `quality_check`) plus `sections`. The response gains:

```
GenerationArtifacts {
  report              final report text
  dictated_findings   input_data.variables.FINDINGS
  sections[]          ordered output headings (history included; carries no options)
  options[]           {id, kind, section, sentence, reason, source, finding?}, section ∈ sections
  brief.decisions     routing rows
  quality_check       post-generation telemetry
}
```

The quick response emits the same model, and a test pins both sides to it.

**Flag and A/B.** `RR_TEMPLATE_MIRROR` (default off until E2 passes). The request accepts
`pipeline: "mirror" | "current"`, honoured for admin users only, so old and new can run on the
same dictation through the real endpoint. The dormant `ENABLE_TEMPLATE_STRUCTURE_VALIDATION`
pass is not run on the mirror path.

**UI.** None beyond legacy retirement. If the existing options panel reads `candidate_reports`
without caring about pathway, templated options appear; otherwise they wait for the rail. The
plan checks which and records it.

**Legacy retirement.** Legacy templates filtered from the picker; legacy creation path removed;
generate returns "re-create this template as a skill sheet"; History and old reports untouched;
no rows deleted.

## §5 `global_style_guide.py` sign-off package

Mechanism as quick's lean pass (`03cea37`): originals stay byte-identical except T0; four new
constants built with asserted `_swaps`; each gets its own hash pin in
`tests/test_report_path_split.py`. **Every item needs Hassan's explicit sign-off before it is
written.**

**T0 — original, fallback path (moves the `GLOBAL_STYLE_GUIDE` pin):**
- Output Structure: "It is never reproduced — not as a section, and not as content in any
  section" → "It is never reproduced outside a CLINICAL HISTORY section the skill sheet defines
  — not as content in any other section".
- Terse-referral paragraph kept, plus "restate the clinical history input only; add nothing".

**`TEMPLATE_SHEET_HEADER_BRIEF`** (system prompt, so both providers see it; replaces the inline
header in `template_manager.py` on the brief path):

> The following skill sheet defines this radiologist's reporting conventions, reconciled with
> this dictation. Before you received it, every conditional item was checked against the
> dictated findings; items that do not apply were removed. Act on its labels exactly; do not
> re-derive them and do not reintroduce removed items.
> – **KEEP**: state the negative as written. **OMIT**: the dictation reports this finding;
> describe it as dictated and never state the negative, in any section. **DO NOT ASSERT**: a
> dictated finding is expected to cause this; do not state it as absent.
> – **INSTEAD**: in place of the omitted text, write what this rule prescribes, from the
> dictation. **APPLY**: append this interpretive clause where the rule places it. **USE**: this
> phrasing variant applies to this case.
> – **Do not assert as normal**: a dictated finding acts on these structures; describe them only
> as the dictation does.
> – **Impression plan**: address every Carry forward finding in the impression; Findings only
> items stay out of it. The plan is a minimum: add the synthesis the evidence supports.
> Coverage is obligatory, assertion is earned: every structure the sheet's paragraphs visit is
> still covered, and what is said about it is only what the dictation and the labels support.
> The skill sheet inherits the Global Style Guide; where they conflict, the skill sheet takes
> precedence.

**`GLOBAL_STYLE_GUIDE_BRIEF`:**

| # | Passage | Becomes |
|---|---|---|
| S1 | Conditional Style Application, whole section (incl. history paragraph) | "The skill sheet governs structure; do not fabricate sections it does not define. If the skill sheet defines a CLINICAL HISTORY section, it is supplied separately and inserted after writing: do not write it." |
| S2 | Output Structure: "It is never reproduced — not as a section, and not as content in any section" | "It is never reproduced in any section you write" |
| S3 | Conditional Awareness, whole section | removed |
| S4 | Missing Data Handling, "But the skill sheet's mandatory negatives and systems review statements exist independently…" → "…explicit normal statement." | "Silence about a structure the sheet's paragraphs visit means it was assessed and normal: state its Normal pattern where the sheet gives one, unless it is listed under Do not assert as normal." |
| S5 | "The principle: generate everything the skill sheet says must always be present." | "The principle: generate every KEEP line and every Normal pattern the dictation leaves unaddressed." |
| S6 | Parameter Placeholders, whole section | "Curly-brace slots in a sheet's patterns (`{measurement}`, `{structure}`) are shapes: fill them from the dictation or leave the clause out. A slot is never written as text." |
| S7 | Fixed Blocks: "verify that the factual condition it encodes matches the clinical history and findings input" | "verify that the factual condition it encodes matches the findings input" |

**`PRE_WRITING_ANALYSIS_BRIEF`:**

| # | Passage | Becomes |
|---|---|---|
| P1 | Step 1, "Cross-reference against the skill sheet's mandatory negatives … (or omit entirely)." | "Apply each reconciliation label: KEEP, OMIT, DO NOT ASSERT, INSTEAD." |
| P2 | "Clinical history as checklist" block | quick's "Clinical history as focus" block, verbatim |
| P3 | Step 4, "Scan the skill sheet for conditional fields triggered by these findings. Verify all IF/THEN interpretive clauses that apply." | "Place each APPLY clause and USE variant." |

**`VERIFICATION_CHECKLIST_BRIEF`:**

| # | Passage | Becomes |
|---|---|---|
| V1 | "Every mandatory negative … exact phrasing" + "Every triggered Conditional Suppression Rule …" | "Every KEEP negative is present; no OMIT negative and no DO NOT ASSERT statement appears anywhere, impression included" + "Every INSTEAD, APPLY and USE is applied" |
| V2 | "All triggered interpretive clauses are appended" | removed |
| V3 | new lines | "No structure listed under Do not assert as normal is stated to be normal" · "Every Carry forward finding is addressed in the impression; no Findings only item appears there" · L-48+ line · "No curly-brace slot appears as text" |
| V4 | "No clinical history item … is restated anywhere in the report" | "…is written anywhere; the CLINICAL HISTORY section, if defined, is supplied separately" |

**L-48+ (V3):** "The impression contains at most one negative — the answer to the clinical
question when no positive finding answers it, or one clause that changes the next step — or one
cluster of negatives bearing on the index finding's next step (staging, resectability,
complication). It never lists unrelated or excluded alternatives." No deterministic trim (memory
`feedback_impression_negatives`).

**Kept on the template side** (quick removed these because its brief never carries the
material; template sheets do): Reference Values qualifier rule, `header: none` labels,
impression format, demonstrated-style precedence, fixed references, Consolidation,
`[NEEDS VERIFICATION]` handling, Recommendations.

## §6 Testing, evaluation, rollout

**Tests (TDD).**
- *Refactor safety first:* golden fixtures with recorded Jev/Qwen responses pin `compile_brief`
  and `run_quality_check` output byte-identical before and after the move to shared modules.
- *Split test:* shared modules import neither pathway; template modules import no
  `quick_report_*`; pins for the four `_BRIEF` constants and the signed-off T0 pin.
- *Unit:* structure verification (verbatim, coverage gate, atomic normals, duplicate source
  lines, fixed blocks, terminology, staleness); one brief test per §3 decision row with stubbed
  models, in-place rendering, all copies relabelled, gate failure → raw path; history word check
  and placement; section-generic splitting with implicit headers; `edit_allowed` guards
  (history span, fixed blocks, suppressed terms); option sections; `GenerationArtifacts` from
  both sides; flag, kill switch, admin-only override; legacy refusal.
- *Integration:* endpoint with stubbed models persists `candidate_reports[0]` in quick's shape.

**Evaluation** (memory `feedback_eval_economy`: ≤ 2 runs, reuse outputs, hand read; pid in
output filenames). Logged as the next L-entry in `docs/model-migration/parameter-ledger.md`.
- **E1 — structuring.** Run 1: Qwen and gpt-oss on the 26; code metrics (schema valid, verbatim
  failures, coverage, gate pass, sections match) + hand read of every failure, every
  history/context-tagged rule, and 6 varied sheets (polytrauma, CMR, lumbar spine, aorta, CT
  abdomen/pelvis, knee). Iterate the prompt on the winner's failures. Run 2: winner only, doubles
  as consistency check. Bar: 26/26 schema-valid; gate pass ≥ 24/26 (the rest take the raw path
  safely); no fabricated item surviving verification; no findings condition tagged
  history/context.
- **E2 — old vs new on the same dictations.** The 2 recent real guided reports plus existing
  quick-report dictations whose scan type matches a template, from prod: ~10 pairs across ~8
  templates, including the CLINICAL HISTORY template. Run 1: current and mirror once each via the
  admin override. Run 2: mirror only, if run 1 prompts a fix. Code metrics: residual Jev
  contradictions, KEEP present / OMIT absent, slot leaks, history outside its section, suppressed
  terms, sections match, added latency. Hand read side by side for voice and safety. Bar: no
  serious error where the old report had none; voice holds on every pair; median added latency
  ≤ ~2.5 s.

**Rollout.**
1. Merge with `RR_TEMPLATE_MIRROR` off. Structures build lazily; a backfill script structures
   all 26 against prod (Hassan authorised direct prod reads and writes, 2026-09-30, via the
   Railway CLI): dry run first, then writes **only** `template_config.sheet_structure`, never
   `skill_sheet`.
2. E1 and E2 against prod; hand read.
3. Hassan's sign-off → `RR_TEMPLATE_MIRROR=1` on Railway (same switch is the kill switch).
4. Live check in Chrome on at least one `skill_sheet_guided` template, ideally the one with a
   CLINICAL HISTORY section: report, persisted artifacts, options on reopen.
5. Legacy retirement ships in the same deploy, independent of the flag.

**Coordination.** This branch creates `report_review.py`, `report_reconcile.py` and
`generation_artifacts.py`. `feat/review-rail` has no code yet; it rebases onto this branch and
reads `GenerationArtifacts` as defined here. A line to that effect is added to the rail handover.

## Safety rules carried over unchanged

- Repairs never turn a negative into a finding (L-47); negatives are removed only in code.
- Impression negatives are never trimmed deterministically (`feedback_impression_negatives`).
- Policy-1 silence rules apply (`project_silence_policy_1`).
- Clinical history is never emitted outside its dedicated, sheet-defined section (L-36 as
  refined above).
- Analyser and structuring prompts stay case-agnostic.
- Qwen writes, Jev/gpt-oss check; settings through `normalise_model_settings`.

## Accepted risk

`condition_source` is classified at save time. A misrouted findings condition could be answered
from history (breaking "a history finding is not a finding on this study"). Mitigations: the
findings-only state is the default; E1 hand-reads every history/context-tagged rule; the E1 bar
requires none misrouted.

## Out of scope

Review rail UI; SSE for templates; migrating legacy templates; rewriting stored sheets;
`[NEEDS VERIFICATION]` handling; recommendation-scope reconciliation on templates.
