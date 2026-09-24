# Decision-First Dictation — Architecture Design

**Date:** 2026-09-24
**Status:** Vision + architecture, approved in conversation as direction; each component ships under its own spec
**Evidence base:** `2026-09-24-jev-dictation-triage-shadow-design.md` §12 (bake-off runs 1–2, live smoke, lab session)
**First component:** `2026-09-24-section-coverage-jev-design.md`

## 1. The principle

Every step in the dictation pipeline today is generation. The polish model rewrites the whole scratchpad on each utterance. Coverage is a generation call with a normaliser. IntelliPrompts are generated. The audit reasons in prose over nine criteria. Report generation reasons its way to a plan and then writes.

Most of those steps are decisions wearing a generation costume. A decision is typed, calibrated, parallelisable, and about 300 ms. Generation is 500 ms to 9 s, and it can hallucinate. The lean architecture asks one question of every step: **is this a choice, or is this prose?** Only prose gets a language model. Everything else gets a System 1 model and deterministic code.

What the pilot established (spec §12): on 48 fixtures both Jev and Qwen-reasoning-off classify utterances at 0.979 with zero errors; Jev's confidence is calibrated enough that a 0.95 threshold covers 83 % of cases with no errors; deterministic routes answer in 260–300 ms versus 470 ms–8.8 s for the live model; and the lab surfaced a real semantic disagreement (delete after a paragraph break) that fixtures alone would not have.

## 2. Target architecture: one decision bundle per utterance

```
final transcript chunk
   │
   ▼
[Jev: decision bundle — one call, all questions evaluated in parallel, ~300 ms]
   action            choice   append | correct | restate | delete | format | noise      (shipped)
   is_command        noul     the utterance addresses the app, not the report            (new)
   command           choice   generate | switch_mode | jump_to_section | undo | none     (new)
   section           choice   which checklist section this utterance belongs to          (new)
   asr_risk          noul     likely speech-to-text error given scan type + established terms (new)
   correction_kind   choice   laterality | measurement | descriptor | other               (new)
   correction_target choice   which existing line the correction applies to               (new)
   needs_committed   noul     the edit touches the frozen zone                             (shipped)
   integrity.*       noul×3   laterality contradiction | measurement/descriptor mismatch | self-contradiction (new)
   │
   ▼
[deterministic handlers]                        [language model, only when needed]
   format → insert break/punctuation             correction_kind = descriptor/other → targeted rewrite of one line
   delete → remove target line                    asr_risk high → polish this utterance only
   noise / restate → no-op                        structured placement needing consolidation
   command → app action                           committed-zone edit
   append + asr_risk low → verbatim line under `section`
   correction laterality/measurement → string edit on `correction_target`
   │
   ▼
[scratchpad op log]  ← every utterance: (utterance, decisions, op applied, model used)
   → provenance per line (dictated vs system-added vs corrected)
   → replay for tests; fixture growth via the lab export
   → coverage nouls (separate call on /review today; can ride the bundle for deterministic routes)
```

Two consequences follow:

- **The live model becomes a tool the router calls, not the loop.** It rewrites one line, or polishes one utterance, never the whole scratchpad. "Stop re-authoring settled text" (Phase 2 goal of the August spec) stops being a prompt instruction and becomes structural.
- **The op log is the provenance mechanism** the August spec parked as a sibling workstream. Because every line's origin is a decision record, dictated-vs-added rendering and evidence linking need no extra machinery.

## 3. Components, in build order

Each is its own spec and lab experiment, gated the same way as the triage pilot: shadow → lab routing → production switch behind an env setting → exit criteria met.

| # | Component | Question type | Replaces | Why this order |
|---|---|---|---|---|
| 1 | **Section coverage** (spec written) | Noul per section | Qwen coverage call + normaliser | Cleanest fit; already a checklist; validates Nouls on scratchpad-scale state |
| 2 | **Verbatim fast-append** | Noul `asr_risk` + shipped `action` | Polish call for clean appends | Appends are the majority of utterances; largest remaining latency win |
| 3 | **Section placement** | Choice over checklist | Structured-mode rewrite | Turns structured mode into deterministic placement; pairs with 1 |
| 4 | **Correction kind + target** | Choice ×2 | Full-scratchpad rewrite on corrections | Laterality/measurement swaps become string edits; descriptor edits become one-line rewrites |
| 5 | **App commands** | Noul + Choice | Nothing (new capability) | Voice control with no model in the loop; small, high delight |
| 6 | **Integrity signals** | Noul ×3 | Dead tier-2 semantic check | Resurrects a feature that has never worked in production, at zero marginal latency |
| 7 | **IntelliPrompts as retrieval** | Score per prompt template | Generated prompts | Pick from a curated prompt library by relevance score; generation only for the long tail |
| 8 | **Audit pre-screen** | Noul ×9 | Nine-criteria prose audit for clean reports | System 2 only on flagged or uncertain criteria |
| 9 | **Generation plan as decisions** | Choice/Score/Noul | Planner reasoning | Which sections apply, impression-worthy findings, management-altering negatives, tiers; prose model writes only prose |

Components 2–6 all live in the same per-utterance call, so their marginal latency is zero once the bundle exists; the cost is fixture writing and a deterministic handler each.

## 4. Invariants that every component inherits

- **Typed decisions, thresholds in code.** The model never decides a threshold. Calibration is measured on our fixtures per component before any threshold is chosen.
- **Prose only when a decision says so.** A component may not add a language-model call except behind a decision that says it is needed.
- **Shadow before route, route in the lab before production, production behind an env setting.** Same three gates as the triage pilot.
- **Every decision is logged as data, never text.** Utterance length and hash, not content, in production logs.
- **Fixtures grow from the lab.** Each component adds an export button; each export line is a test case.
- **Vendor-neutral interface.** Every component is written against a `classify(state) -> decision` protocol with Jev and a Qwen-off implementation. If Qwen-off keeps matching Jev's accuracy without calibration being decisive, vendor count wins.

## 5. What "revolutionary" would look like, concretely

- A radiologist dictates a normal chest CT in twelve utterances. Ten are appends with low ASR risk, one is "new paragraph", one is "no wait, left". Today: twelve full-scratchpad regenerations, roughly ten seconds of model time. Target: twelve 300 ms decision calls, eleven deterministic ops, one single-line rewrite. The scratchpad is never re-authored; every line shows where it came from.
- Pills light up as sections are addressed, with partial states for hedged claims, updated within a third of a second of the utterance.
- "Generate report" spoken mid-flow is a command, not a finding, and fires without a round trip through the polish model.
- The audit on a clean report returns in one Jev call; the nine-criteria reasoning runs only where a Noul says something is off.

## 6. Open questions to settle per component, not here

- Threshold per component (from its own bake-off).
- Whether coverage rides the bundle or stays on `/review` (component 1 keeps it on `/review`; revisit when 3 lands).
- The delete semantics after a formatting command (lab observation from the pilot).
- Whether restatements should be silently dropped or shown faded (UX decision, not a model one).
