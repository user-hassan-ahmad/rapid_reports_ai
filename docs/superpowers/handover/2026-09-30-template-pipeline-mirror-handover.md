# Handover: rebuild the templated pipeline to mirror quick reports

**Date:** 2026-09-30 · **From:** the brainstorm session for the Review rail (suggestions panel + copilot
restructure). **Status:** not started. Brainstorm → spec → plan → build, on its **own branch**
(suggested: `feat/template-pipeline-mirror`).
**Why now:** the Review rail (being specced separately, see "Coordination") reads one generation
contract. Quick reports already produce nearly all of it; templated reports don't. The earlier plan
to bolt quick-report pieces onto today's template generator ("templated phase 2" in
`2026-09-30-suggestions-panel-handover.md`) is **superseded** by this rebuild. Don't do that stopgap.

## The intent (Hassan, 2026-09-30)

> Everything scoped for quick reports (skill sheet generator, bridge/brief, analysis, audit) should
> apply holistically to the template side. Both generation pathways mirror the same logic and flow;
> only their generation pipeline itself may vary.

Read that alongside memory `project_report_path_split`: **separate code and prompts, same flow**.
"Separate" was never meant as "different logic".

## Target flow (both sides)

```
skill sheet ─► brief (reconcile sheet with this dictation) ─► generate ─► post-generation check
           ─► options (impression items, recommendations, finding negatives) ─► persist
           ─► audit + enhance (already shared) ─► Review rail
```

| Stage | Quick today | Templated today | To do |
|---|---|---|---|
| **Skill sheet** | Made fresh for each dictation: `quick_report_analyser.generate_ephemeral_skill_sheet` (`prune_v1`, L-35; history out, L-36) | **Stored** per template: `TemplateManager.analyze_examples_to_skill_sheet`. It emits fixed blocks, `[NEEDS VERIFICATION]`, `{{parameters}}` and IF-THEN clauses. 26/57 templates are `skill_sheet_guided`; 31 are legacy with no sheet. | Add the finding-linked "If present" negatives directive (L-45) to the template analyser, and refresh the 26 stored sheets. Decide what legacy templates get (see open questions). |
| **Brief** | `quick_report_brief.compile_brief(sheet, scan_type, findings, history)` returns `Brief {text, decisions, reconcile_ms}`. Its `parse_sheet` expects the **quick sheet format**. | none | Check whether template sheets parse. They carry fixed blocks, parameters and IF-THEN clauses, which quick sheets never have. Either extend the parser or add a template-sheet adapter. |
| **Generate** | `quick_report_generator.generate_quick_report`, with prompts in `quick_report_prompts.py` and `quick_report_hardening.py`; model role `QUICK_REPORT_GENERATOR` (+ `_FALLBACK`). Reads `brief.text`. | `TemplateManager._generate_report_skill_sheet_guided` (template_manager.py ~2517) reached through `generate_report_from_config` (~2678), with prompts from `global_style_guide.py`; model role `TEMPLATE_REPORT_GENERATOR`. Reads the raw sheet. | Make the template generator read the brief. **Any change to `global_style_guide.py` needs Hassan's sign-off.** It is pinned by hash in `tests/test_report_path_split.py`. |
| **Options** | `_write_options` (quick_report_generator.py:102), fed by `brief.decisions["options"]`. Every option is `{id, kind, section, sentence, reason, source, finding?}`. Ids are `opt{i}` for written items and `fn{i}` for finding negatives. Caps: `MAX_OPTIONS=3`, `MAX_FINDING_OPTIONS=4`. | none | Same payload, with `section` set to the **template's own heading names**. |
| **Post-generation check** | `quick_report_quality.run_quality_check` (Jev contradiction and omission, plus safe focal repair; L-46/47). Kill switch `RR_QUALITY_CHECK=0`. | none | Run it after template generation. The Review rail branch moves the repair functions into a shared `report_review.py` (see "Coordination"), so the template path can import them from there without breaking the split test. |
| **Impression guard** | In the quick prompts (L-48) | none | Port to `global_style_guide.py`, with sign-off. The L-36 CLINICAL HISTORY contradiction in the template style guide is **still open**; decide on it in the same sign-off. |
| **Persist and stream** | SSE `candidate` event; `reports.candidate_reports[0]` holds `options`, `options_applied`, `brief.decisions` and `quality_check`. Finalise: `PATCH /api/quick-report/reports/{id}/finalise`. | `POST /api/templates/{id}/generate` (main.py ~1707). **Check** whether it streams and what it stores in `candidate_reports`. | Store the same fields in the same places, so the viewer and the rail read both sides identically. |
| **Audit and enhance** | Shared | Shared | Nothing. It already runs on both sides. |

## The contract this branch must produce

The Review rail reads only this and never checks which pathway produced it. Names can be refined
in the rail spec, but the **shape is agreed**:

```
GenerationArtifacts {
  report              final report text
  dictated_findings   source of truth for checks (templated: input_data.variables.FINDINGS today)
  sections[]          ORDERED heading names as they appear in the report (not just FINDINGS/IMPRESSION)
  options[]           {id, kind, section, sentence, reason, source, finding?}, where section ∈ sections
  brief.decisions     routing rows (why each negative was stated, offered or dropped)
  quality_check       post-generation telemetry
}
```

Sections are generic. Templates have TECHNIQUE, COMPARISON, per-organ subheadings and so on. Anything
keyed by a section (options, anchors, probes) must use the template's real headings.

## Decisions already made (don't reopen without cause)

- **Same flow, separate code.** Each side keeps its own generator and prompts. Neither side imports
  the other's prompts or generator (`tests/test_report_path_split.py`).
- **No stopgap** on the current template generator. Templated reports get options and finding
  negatives when this branch lands. Until then the rail shows audit fixes, contradictions,
  classifications and chat for them.
- **Safety rules carry over unchanged:**
  - repairs never turn a negative into a finding (L-47);
  - negatives are removed only in code;
  - impression negatives are never trimmed (memory `feedback_impression_negatives`);
  - policy-1 silence rules apply (memory `project_silence_policy_1`);
  - clinical history is never emitted in the report (L-36).
- **Analyser prompts stay case-agnostic**, using structural or multi-domain examples (memory
  `feedback_case_agnostic_prompts`).
- **Model routing:** Qwen writes, Jev/gpt-oss checks (memory `project_model_routing`). Settings go
  through `normalise_model_settings` (memory `reference_pydantic_ai_settings_shape`).

## Open questions for the brainstorm

1. **Shared or copied?** The brief machinery and the quality check are pathway-neutral logic, while
   the prompts are not. The options are: move the neutral parts (sheet parsing, routing, Jev
   questions, repair) into shared modules that both sides import, or copy them per side. The split
   test forbids cross-imports between the *pathway* modules, not shared modules.
   *Leaning:* share the logic and keep the prompts separate. This needs Hassan's decision.
2. **Template sheet format against `parse_sheet`.** Can the brief read fixed blocks, `{{parameters}}`
   and IF-THEN clauses, or does it need an adapter? Test it on the 26 stored sheets before designing.
3. **Legacy templates (31, no sheet).** Choices:
   - generate a sheet from their examples (`analyze_examples_to_skill_sheet`) and migrate them to
     `skill_sheet_guided`;
   - give them audit, rail and chat only;
   - retire them.
4. **Refreshing the 26 stored sheets** with the L-45 directive. Are they rewritten in place, or
   versioned? Users may have edited them (`refine_skill_sheet`).
5. **Streaming parity.** Does the template generate endpoint need SSE `candidate` events like quick,
   or is one response enough?
6. **The `global_style_guide.py` sign-off package.** Bundle the impression guard (L-48), the L-36
   history decision and brief-awareness into one reviewed change.

## Coordination with the Review rail branch (`feat/review-rail`, spec pending)

- The rail branch creates `report_review.py` and moves `repair_report`, `insert_findings`,
  `remove_negative_clause` and `edit_allowed` into it. Build on that, or agree the module name
  before either branch moves the code.
- The rail consumes `GenerationArtifacts` and generic `sections[]`, so don't build any rail UI here.
- Whichever branch merges second rebases onto the first. The contract above is the interface
  between them.

## Suggested process

1. `superpowers:brainstorming` on the open questions. Settle Q1 (shared or copied) and Q2
   (sheet format) first; they decide how big the work is.
2. Spec: `docs/superpowers/specs/<date>-template-pipeline-mirror-design.md`, then
   `superpowers:writing-plans`.
3. Build test-first. Put the new template flow behind a flag with a Railway kill switch, following
   the pattern of `RR_QUALITY_CHECK` / `rr_dictation_v2`.
4. **Evaluate** on real templated reports: reuse existing outputs, at most 2 runs, and read them by
   hand (memory `feedback_eval_economy`). Compare old and new template output for the same
   dictations. The ledger conventions apply: log it as a new L-entry in
   `docs/model-migration/parameter-ledger.md`.
5. Check in the live app through a Chrome session (memory `reference_prod_smoke_testing`), on at
   least one `skill_sheet_guided` template.

## Context worth reading first

- Ledger `docs/model-migration/parameter-ledger.md`:
  - L-35 `prune_v1` (line ~875)
  - L-36 history out (~932)
  - L-40 production swap (~1124)
  - L-45 finding negatives (~1341)
  - L-46 to L-48: post-generation check, repair safety, impression guard
- Specs in `docs/superpowers/specs/`:
  - `2026-09-24-v1-subtraction-design.md`
  - `2026-09-29-policy1-confirmed-branch-negatives-design.md`
  - `2026-09-30-post-generation-check-design.md` (its "Hand-off to the UI spec" lists the payload
    fields)
- Memory:
  - `project_report_path_split`
  - `project_compiled_brief`
  - `project_finding_negatives`
  - `project_post_generation_check`
  - `project_silence_policy_1`
  - `reference_jev_capability_profile`
- Code:
  - quick: `quick_report_generator.py` (198 lines, orchestration at 136–198), `quick_report_brief.py`
    (658), `quick_report_quality.py` (373), `quick_report_analyser.py` (1085);
  - templated: `template_manager.py` (3836), `global_style_guide.py` (291).
