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

## Addendum (2026-10-02): production audit vs the new fidelity lane, same reports

The comparison covered 41 production quick reports, 37 of them with a stored audit, and 81 non-pass audit criteria hand-read against Hassan's rules. Data: `scratchpad/audit_compare/compare.json` in the pipeline session.

**Audit usefulness by criterion:**

| Criterion | Useful |
|---|---|
| input_fidelity | 11/13 |
| clinical_flagging banners | 16/22 |
| anatomical_accuracy | 4/7 |
| characterisation_gap | 3/7 |
| recommendations | 4/20 (mostly noise) |
| report_completeness | 1/7 |

**What the audit uniquely catches:**
- report-only errors with no dictation anchor: wrong modality terms ("signal" on CT), impossible anatomy, a size word that contradicts the measurement;
- banners;
- a few safety-critical missing steps (anticoagulant reversal, MSCC MRI within 24 h).

**What the fidelity lane uniquely catches:**
- fine descriptor losses;
- correct slip handling (info tags);
- Jev-verified find/replace fixes;
- stable results. The audit runs once at temperature 0.8 and flips between runs.

**Neither catches FABRICATION** (an invented hiatus hernia, an invented prior study, an invented "CBD 6 mm"), certainty upgrades ("may represent" → "in keeping with"), or re-attributed measurements. A unified engine needs a **report-to-source grounding lane**: every positive finding, measurement and prior-study reference in the report must trace back to the dictation or history.

**Recommended composition:**
1. **The fidelity lane** as the backbone, adjudicating EVERY Jev flag (the lab sampled 50 of about 72), with the suppress bias softened. 4 audit-flagged real losses were detected but suppressed.
2. **The new grounding/fabrication lane.**
3. **An internal-consistency check,** from anatomical_accuracy.
4. **Banners as a separate feature,** with tightened tiers.
5. **Low-salience extras:** characterisation_gap, and safety-critical recommendations only.
6. **Drop** report_completeness, scan_coverage and diagnostic_fidelity as currently prompted.

Phase 1a becomes redundant only after the fidelity lane's recall is fixed.

Cost: comparable to the audit with two adjudication runs, about half with one; latency about the same as Phase 1.

## Addendum (2026-10-02): guideline lane, turning Phase 2 research into applicable review items

**Today:** the prefetch (S1–S3, run from the findings alongside generation) feeds the S4 synthesis cards (`enhancement_models.py`):
- PathwaySynthesis: urgency, authority, refs, follow_up_actions[] (modality, timing, indication, urgency, guideline_source);
- ClassificationSynthesis: classifications[] (system, grade, criteria, management) and thresholds[];
- DifferentialSynthesis;
- the `tnm_staging` table: UICC 9th edition, with search.

These land as Guidelines-tab cards to read. Phase 2 audit turns them into 3 prose criteria (4/20 useful). Nothing produces applicable edits. The synthesis is stored per report in `enhancement_json`.

**Proposed: a guideline lane in the same review engine.**
- Synthesis outputs become candidate items, then go through the same adjudicate → propose fix → Jev verify path as fidelity items.
- Candidate mappings:
  - **A classification gradable from dictated features** → action: add the grade to the finding or impression line (e.g. "…complex cyst, Bosniak IIF").
  - **Not gradable from the dictation** → info (or not shown), stating what is missing.
  - **A threshold crossed** (AAA ≥ 5.5 cm, nodule size…) → action: name it in the impression where it changes management.
  - **A sourced follow-up action** → an UPGRADE of the existing recommendation line, made specific: "follow-up CT" → "CT chest at 3 months (Fleischner 2017)".
  - **Further actions** → options only.
  - **Differentials and imaging flags** → low-salience options.
- Every item carries a citation chip linking to its Guidelines-tab card.
- Safety rules:
  - (1) **grounding:** never infer a grade or threshold from undictated features; every input must be dictated;
  - (2) **radiology remit only:** no management;
  - (3) **one recommendation line in the core;** extras are options (Hassan's rule);
  - (4) **the same reasoning adjudicator** (uncertain → no card), plus the Jev already-in-report gate.
- **Timing:** non-blocking. Items stream into the rail when S4 lands, tagged "Guideline", and are re-verified against the current text by the live loop.
- **This replaces Phase 2's audit criteria.**
- **Suggested first step:** a lab prototype on the 41 production reports already compared (stored synthesis in `enhancement_json`), producing guideline cards for Hassan to eyeball.
