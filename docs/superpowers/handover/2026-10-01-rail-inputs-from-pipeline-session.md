# Review rail: inputs from the pipeline session (2026-10-01)

These decisions and facts come from the template-mirror and quick-hardening session. They feed the rail spec; see also the addenda at the end of `2026-09-30-suggestions-panel-handover.md`.

## What the backend already produces for the rail

**Quick (live on main):** the post-generation check writes `quality_check.review[]` into the saved candidate. Kinds:
- `partial`: a dictated detail is missing, with `missing_detail`.
- `differs`: the report says something different from the dictation.
- `contradiction`: a report statement the dictation contradicts. These are review-only since PR #7 and are never auto-rewritten.

Automatic edits are limited to two cases:
- code removal of a contradicted negative, never one the dictation itself states (PR #6);
- insertion of a dictated finding classed `absent`.

Ledger entry: L-49.

**Options:** quick produces options as today. The lean template path (`feat/template-lean`, unmerged and dormant) adds Phase 1 options. Those are computed in the background after generate and served by `GET /api/reports/{id}/options` with fields `status`, `options`, `review`, `phase1_source` and `artifacts`.

## Decisions Hassan made today that the rail must honour

1. **Editor overlays and rail, both views, in sync.** Every item anchored to text gets:
   - a CM6 underline coloured by type, plus a gutter marker;
   - a popover showing a diff, with Apply / Edit / Dismiss.

   The rail lists everything, options and unanchored items included. Reuse the existing CM6 decoration code: `lib/dictation-lab/pendingMarks.ts`, `ghostText.ts`, `IntelliPromptsMargin.svelte`.
2. **Fixes are proposed, never auto-applied.** Qwen adjudicates and proposes, Jev verifies, and the radiologist clicks. The flag-only check output becomes one-click fixes this way.
3. **Review-item policy:** memory file `feedback_review_item_policy.md`.
   - Missing detail is flagged unless it is absorbed by rewording; a lost normal-variant descriptor is flagged too.
   - Report differs: the dictation is the truth, and "out of scope" is never a valid drop.
   - Laterality is flagged only when no study title or subheading bounds it.
   - A dictation slip the report fixed becomes an **info tag** (audit trail, no action). It may be removed later if the overlays get busy.
   - Only genuine contradictions are flagged; "remaining X unremarkable" is fine.
   - A sensible undictated recommendation is a feature and never flagged.
4. **Item classes for the UI:** `action` (card or overlay with a fix), `info` (a subtle tag), `suppress` (not shown). Round 2 of the adjudication lab, which validates the classifier against Hassan's calls, is running in the pipeline session.
5. **The impression core stays tight:** short, synthesised, one recommendation line. Everything extra goes to options, so options are where a radiologist adds more (memory `feedback_impression_core_tight.md`).
6. **An "upgrade" apply mode,** from the earlier addendum. A specific negative beside a general normal should rewrite the normal sentence rather than add a sentence next to it.

## Dependency

The lean template path only delivers visible value once the rail renders options and review items. Ship order: rail first (or together), then the template path is switched on.

## Addendum (2026-10-02): one review engine, with the audit folded in

Hassan's realisation: the post-generation check was meant to auto-fix the report. Its corrections proved unreliable (duplicates, incoherent lines, invented findings), so it is now mostly flag-only. That makes it a second fidelity audit running beside the existing parallel audit. Fold both into one review engine feeding the rail.

Existing audit (`enhancement_utils.run_audit_phase1` / `run_audit_phase2`; endpoints `/api/audit` and `/api/audit/phase2`):
- **Phase 1a `input_fidelity`:** the same job as the fidelity check.
- **Phase 1b:** anatomical_accuracy, clinical_relevance, recommendations, clinical_flagging, report_completeness, diagnostic_fidelity.
- **Phase 2:** guideline compliance, run after S4 synthesis in /enhance.
- **How it runs:** LLM judges with reasoning on, temperature 0.8, giving pass/warning/flag criteria.

Proposed shape:
- **The report returns immediately.** The review lane runs in the background and streams items into the rail.
- **Detectors:**
  - fidelity: the Jev selector, classify-first and contradiction checks, replacing Phase 1a;
  - audit Phase 1b;
  - audit Phase 2;
  - options from the brief and Phase 1.
- **One adjudicator** (Qwen with reasoning on, a short principle-based prompt, uncertain → suppress; lab "round 3": 7 actions / 3 info / 40 suppress on 50 real items, the known misreads fixed, 9 of 50 unstable across two runs). It:
  - de-duplicates across detectors;
  - classifies items as action, info or suppress;
  - proposes the fix, which Jev verifies.
- **Output:** review items into the rail and CM6 overlays, each with Apply / Edit / Dismiss.
- **Open decision:** keep the two remaining automatic edits (code removal of a contradicted negative; insertion of an absent finding, which was 11/148 correct in the production re-score) as pre-render fixes, or move them to one-click rail items. The pipeline session leans towards moving them, for consistency: the radiologist confirms every change.
- **Lab artefacts** (adjudicator prompt v3, harness, cards) are in the pipeline session's scratchpad: `cards50/prompt_v3.txt`, `run_v3.py`, `review_cards50_v3.json`.
