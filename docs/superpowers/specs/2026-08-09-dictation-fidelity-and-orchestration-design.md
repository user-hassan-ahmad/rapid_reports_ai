# Dictation Scratchpad — Fidelity Modes & Speech-Engine Orchestration

- **Date:** 2026-08-09
- **Status:** Draft for review
- **Scope:** Backend (`backend/src/rapid_reports_ai/canvas_routes.py`, `enhancement_utils.py`, `dictation_semantic.py`, `main.py`) + Frontend (`frontend/src/lib/components/DictationScratchpad.svelte`, `frontend/src/routes/components/IntelliDictateTab.svelte`)
- **Related memory:** `project_report_integrity_hardening`, `project_quality_rubric_v21`, `reference_railway_deploy_architecture`, `project_analyser_dual_variant`

---

## 1. Problem

Radiologists report that the scratchpad dictation "polishes" their speech so heavily they no longer recognise it as their own words. We want to keep the useful scrubbing (fillers, false starts, dictation debris) while preserving high fidelity to what the radiologist actually said — including their own formatting.

Two intertwined problems, established during design:

1. **Fidelity (behaviour).** The polish is designed as a *transformation* — it re-authors dictation into terse anatomical bullets, at high temperature — so "sounds like me" is lost by design, not by accident.
2. **Orchestration.** The live speech engine regenerates the *entire* scratchpad on *every* utterance, has no per-stage telemetry, ships a semantic safety-check that is dead in production, and routes every utterance (trivial or complex) through the same full-cost path. The full-regeneration behaviour is itself a *fidelity* liability — it re-authors already-settled findings continuously.

This spec covers both, delivered in three phases.

---

## 2. Goals / Non-goals

### Goals
- A **Verbatim Clean** mode that preserves the radiologist's words, order, and dictated formatting, removing only speech debris — shipped as the **default**.
- Retain today's **Structured** (anatomical-bullet) behaviour as a per-report toggle.
- Preserve the radiologist's **dictated formatting commands** (new line / new paragraph) as authoritative; auto-format for clarity only where no command was given.
- Apply **spoken corrections surgically** (change the corrected span, leave everything else verbatim) rather than by full rewrite.
- **Stop re-authoring settled text** — process incrementally so committed findings are frozen.
- **Instrument** the live path (per-stage latency + a zero-edit/manual-correction metric).
- **Fix** the dead tier-2 semantic check.
- Make the model choice a **config change** (router) so the Gemma-4 evaluation and GLM migration are low-friction.

### Non-goals
- Replacing Deepgram or the ASR layer.
- Building a fine-tuned/compiled cleanup model (noted as a future option; not in scope).
- Full structured-reporting/template-field NLP mapping (separate initiative).
- Swapping the production model in this spec — Gemma-4 is an *evaluated* Phase 3 spike behind a fallback, not a committed swap.

---

## 3. Current architecture (verified against working tree)

Live path per settled utterance:

1. **Capture** — `DictationScratchpad.svelte` streams raw PCM over WebSocket to `/api/transcribe`. Transcript accumulated in `sessionTranscript`, sliding window `SESSION_TRANSCRIPT_WINDOW = 2500` chars (`DictationScratchpad.svelte:113`; note stale "600 chars" comment at `:110`).
2. **ASR** — `/api/transcribe` proxies to **Deepgram Nova-3-medical** (`en-GB`, `smart_format`, `punctuate`, `dictation`, `measurements`) (`main.py:4955`). `process_dictation_transcript()` converts `<\n>`→`\n`, `<\n\n>`→`\n\n`, "full stop"→"." (`main.py:4850`). **Dictated line/paragraph breaks and punctuation therefore already exist in the transcript** that reaches `/process`.
3. **Polish** — `/api/canvas/process` runs a **single** Groq **Qwen3-32B** pass, non-thinking, `temperature 0.7`, `top_p 0.8`, `max_tokens 8000` (`canvas_routes.py:501`, `:531`). Structured output `CanvasProcessResponse{scratchpad, covered_sections}`. **Full prior scratchpad + transcript in, complete replacement scratchpad out** (`DictationScratchpad.svelte:275`, `:295`). Error guard returns the unchanged scratchpad (`canvas_routes.py:538`).
4. **Review** — `/api/canvas/review` fires *after* `/process` resolves (`DictationScratchpad.svelte:299`); runs coverage + IntelliPrompts in parallel via `asyncio.gather` (`canvas_routes.py:710`), each re-reading the full scratchpad.

Trigger cadence: `/process` fires on **every Deepgram `is_final`** plus `UtteranceEnd` (`DictationScratchpad.svelte:461`), no debounce; a "latest-wins" single-flight queue coalesces but **does not cancel** in-flight calls (`:314`).

Integrity gates: `/api/dictation/check` (`main.py:2579`) — tier-1 regex (`dictation_integrity.py`, 600 ms debounce, no LLM) + tier-2 semantic (`dictation_semantic.py`, 2500 ms debounce, Cerebras `STRUCTURE_VALIDATOR`).

Concurrency: a single global `asyncio.Semaphore(4)` guards **Cerebras only** (`enhancement_utils.py:29`); the Groq `/process`+`/review` hot path is uncapped server-side.

Telemetry: **none** on `/process` or `/transcribe`; `print()` stopwatches on coverage/IntelliPrompts only (`canvas_routes.py:580`, `:670`); frontend fully untimed.

### Confirmed defect (independent of this feature)
`dictation_check_endpoint` is `async`, and calls the synchronous `check_semantic()` (`main.py:2600`), which calls `_default_analyse()`, which runs `asyncio.run(_run())` (`dictation_semantic.py:134`). `asyncio.run()` inside a running event loop raises `RuntimeError`, swallowed by the bare `except Exception: return []` (`dictation_semantic.py:157`). **The tier-2 semantic check therefore always returns zero flags in production**; only the test-injected `analyse=` path works.

---

## 4. Root cause of over-refinement

Three compounding causes, in priority order:

1. **The prompt is engineered to re-author.** `CANVAS_PROCESS_SYSTEM_PROMPT`'s `# Consolidation` and `# Response shape` sections order the model to compose utterances into terse anatomical bullets and drop the radiologist's connectives/phrasing. The `# Hard fidelity rule` constrains *substance* (no invented findings) but explicitly not *form* — and "sounds like me" is a form property.
2. **Temperature 0.7** injects lexical paraphrase on every pass.
3. **Full-document regeneration every utterance** gives the model repeated opportunities to re-author previously-settled findings. This is an *orchestration* cause of a *fidelity* symptom.

Fixing (1) and (2) is necessary but not sufficient; (3) must be addressed for a cleaned finding to *stay* clean.

---

## 5. Design decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Two modes**: Verbatim Clean (new) + Structured (current) | Radiologists want to choose per case |
| D2 | **Verbatim Clean is the default**; per-report toggle to Structured; remember last choice | Directly answers the complaint |
| D3 | **Dictated `\n`/`\n\n` are authoritative**; auto-format for clarity only in gaps; **voice is the formatting control surface** (no primary UI layout selector) | The formatting intent already exists in the transcript; radiologists already control layout by voice (Dragon/PowerScribe convention) |
| D4 | Robustness = **instruction + validation** (verify dictated-break structure survived; repair/re-run on violation) | Guarantees commands land without freezing text (needed for corrections) |
| D5 | **Corrections are surgical** — minimal in-place edit, everything else verbatim; `scratch that` folded in | Keeps the smart context-finding, drops the rewrite |
| D6 | **Model plan**: fix fidelity on current Groq Qwen3-32B; evaluate Gemma-4 31B (Cerebras) as a separate benchmarked spike behind a fallback | Over-refinement is prompt+temp+orchestration, orthogonal to the model; Gemma-4 is public-preview ("evaluation only") and `zai-glm-4.7` deprecates 2026-08-17 |
| D7 | **Freeze settled text / incremental processing** | Biggest single fidelity + efficiency win; industry-standard (see §9) |

---

## 6. Behaviour design

### 6.1 Modes and routing
`/api/canvas/process` and `/api/canvas/review` gain `mode: "clean" | "structured"` (default `"clean"`). One handler, per-mode system prompt + decoding params; shared model, `CanvasProcessResponse` schema, retries, and error guard. IntelliPrompts branches its one "bulleted list" framing sentence on `mode` (`canvas_routes.py:302`). Rejected alternatives: two endpoints (duplicates plumbing); one blended prompt (behaviour leakage).

### 6.2 Verbatim Clean system prompt (draft)
Replaces the structured prompt's `# Consolidation` / `# Response shape` with:

```
# Role
You clean up a radiologist's live dictation so it reads as their own words, tidied.
Your single source of truth is the transcript. You preserve what they said and how
they said it; you remove only the debris of speaking aloud.

# Hard fidelity rule
You do not complete, restructure, or summarise. Do not add findings, descriptors, or
qualifiers they did not dictate. Do not reorganise, regroup, or reorder their findings.
Do not compress sentences into notes. The radiologist must recognise the result as their
own speech with the ums removed — not a rewritten summary.

# Remove (and nothing else)
- Filler / disfluency: "um", "uh", "you know", "sort of", stutters, repeated words
- Dictation control debris left in the text: stray "okay", "let's start", "next"
- Thinking-aloud with no clinical content: "right so", "let me see", "as I was saying"
- False starts / self-corrections: keep the corrected intent, drop the abandoned attempt

# Preserve exactly
- Their sentence structure, phrasing, word choice, and the order they said things in
- All clinical substance: measurements+units, laterality, location, confidence qualifiers,
  temporal comparators, staging, specific pathology terms
- Natural connecting prose — keep whole sentences; do NOT reduce to bullet fragments

# Speech-to-text correction (surface form only)
Fix clear homophones / phonetic ASR errors using radiology knowledge, the scan type +
clinical history, and terms already established this session. Phonetic proximity + context
consistency is the test. Changes spelling, never substance or phrasing. When unsure, keep
the transcript verbatim.

# Dates: British DD/MM/YYYY — surface form only.

# Revisions (explicit changes to prior content)
When a later utterance explicitly corrects, replaces, or retracts something said earlier —
signalled by "actually", "no", "sorry", "I mean", "scratch that", "correction", or by
directly contradicting a prior value — apply the change to the earlier text and remove the
correction utterance itself, so the scratchpad reads as if the final version was said first.
Make the MINIMAL edit: change only what the correction changes; leave the rest of that
finding, every other finding, and all dictated line/paragraph breaks exactly as dictated.
This is a licence to apply directed corrections only — never to rephrase or reorganise
anything the radiologist did not ask you to change.
Correction vs comparison: "it's NOT 5 mm, it's 10 mm" is a correction (5 mm is gone);
"it was 5 mm on the prior, now 10 mm" is a temporal comparison (both stay). When genuinely
ambiguous, KEEP BOTH and let the radiologist resolve it — never silently erase a measurement.

# Output
Preserve the radiologist's own structure. Treat existing line and paragraph breaks in the
transcript as authoritative — never merge across them or reorder across them. One distinct
statement per line, in the order dictated. Where the radiologist ran several findings
together without a break, you MAY add a line break for readability, but explicit breaks
always win. Apply sensible punctuation and capitalisation (surface tidying, never new words).
Do NOT regroup by anatomy or add bullet symbols. Plain text, update in place. Empty → empty.
```

Response schema unchanged (`covered_sections: []`).

### 6.3 Structured mode
Retained as-is behaviourally, with one tuning change: `temperature 0.7 → 0.3` (needless lexical drift even for users who want the organised view). Prompt otherwise unchanged.

### 6.4 Formatting model
- Dictated `\n`/`\n\n` (already in the transcript, §3) are **authoritative anchors**. Clean mode preserves every one.
- **Auto-clarity only in gaps**: within a radiologist-run-together segment, the model may add line breaks; explicit breaks win.
- **Validation (D4)**: after the model returns, a deterministic check confirms the count/position of dictated breaks survived; on violation, repair or re-run. Layout control is therefore *voice-driven*; a manual bullet toggle may exist as an optional convenience but is not load-bearing.
- Adopt Deepgram's **finalization-timing** rule for partial measurements ("10… mm"): wait for non-entity continuation or ~3 s silence, forceable via `Finalize`, so measurements are not formatted prematurely.

### 6.5 Corrections
- Surgical Revisions section (§6.2). The incremental "update in place" architecture already supplies the prior scratchpad, so **deferred** corrections work even if the original utterance has left the 2,500-char transcript window (the value lives in the scratchpad).
- **Deterministic erase/select lexicon** added alongside the LLM behaviour: `scratch that` / `delete that` handled in the command layer (extend `process_dictation_transcript` or a dedicated command pass) so they never survive as literal words. (Radiology-incumbent pattern; see §9.)

### 6.6 Decoding params
| Mode | temperature | top_p | notes |
|------|-------------|-------|-------|
| Clean | 0.15 | 0.8 | minimal paraphrase, max fidelity |
| Structured | 0.3 | 0.8 | down from 0.7 |

---

## 7. Orchestration design

### 7.1 Fix tier-2 semantic (Phase 1)
Make the analyser awaitable rather than calling `asyncio.run()` inside the loop. Minimal fix: `flags += await asyncio.to_thread(check_semantic, ...)` (runs the sync function, with its own `asyncio.run`, in a worker thread where no loop is running). Preferred long-term: make `_default_analyse`/`check_semantic` natively `async` and `await` them; keep test injection working. Verify against a real (non-injected) laterality/contradiction case.

### 7.2 Telemetry + zero-edit metric (Phase 1)
- Structured per-stage timing on **`/process`** and **`/transcribe`** (currently untimed), plus frontend **end-to-end** timing (capture → render). Replace `print()` stopwatches with structured logs/metrics.
- Capture a **zero-edit / manual-correction rate** per session (fraction of dictations the radiologist did not hand-edit) — the north-star product metric (see §9).
- Surface per-stage p50/p95 for the live path. This is a prerequisite for the Phase 3 model decision.

### 7.3 Freeze settled text / incremental processing (Phase 2)
Process only the **new tail** against the committed scratchpad, passing prior committed text as **read-only carried context** (AssemblyAI "Context Carryover" pattern). Settled findings are not re-emitted or re-authored. Corrections remain able to reach back and edit a prior span (a *directed* edit, not a regeneration). This turns per-utterance work from O(scratchpad) to O(tail) and removes the continuous re-drift of settled text.

### 7.4 Cadence + cancellation (Phase 2)
Trigger `/process` on **pause** (`speech_final` / `UtteranceEnd`) rather than every `is_final`; add `AbortController` cancellation of superseded in-flight calls.

### 7.5 Triage front-door (Phase 3)
A cheap classifier routes each new utterance: **plain append** (fast path — clean the new segment, append) vs **revision** (full-context edit path) vs **formatting-only** (deterministic). Reserves the expensive path for the minority of utterances that need it.

### 7.6 Model router (Phase 3)
A small routing layer: `task-class → {primary, fallback, params}` with health-aware failover, replacing scattered `MODEL_CONFIG` constants + inline 503 fallbacks. Consistent backpressure across providers (extend the concurrency guard beyond Cerebras-only). Makes the Gemma-4 swap and GLM migration config changes.

### 7.7 Other
- **Merge coverage + IntelliPrompts** into one `/review` call with a combined structured output (both re-read the same scratchpad).
- **Grounding verifier (atomic-fact critic pass)**: after cleaning, decompose the output into atomic claims and check each for entailment against the raw transcript (+ prior scratchpad); keep only supported claims, flag/withhold the rest — the strongest evidenced clinical-scribe guardrail (Nabla atomic-fact verification; Abridge detector+corrector). Cheaper first cut: diff/span-align the cleaned output against the raw transcript and flag introduced clinical entities. Companion to the existing truncation detector + defeasible normal-fill.
- **Evidence-linking (future UX):** attach each scratchpad/report line to its transcript span — a trust surface for the radiologist and the best correction-capture signal (Abridge "Linked Evidence"; Suki grounding). Not in the phased scope; noted as the natural review-UX evolution.
- **Case key-terms**: inject `scan_type`/`clinical_history`-derived vocabulary as **Deepgram key-terms** (not only LLM context) to move WER on the terms that matter.

---

## 8. Phased delivery

### Phase 1 — Stabilise & instrument (low risk, ships first)
**Scope:** §7.1 tier-2 fix; §7.2 telemetry + zero-edit metric; hygiene (stale window comment, dead `getFindingCount`).
**Acceptance:**
- A real (non-injected) semantic check returns flags on a known laterality/contradiction case; tier-2 eval basket passes against the live async path.
- Per-stage p50/p95 latency for `/transcribe`, `/process`, `/review` and frontend end-to-end are recorded.
- Zero-edit / manual-correction rate is emitted per session (establishes the pre-change baseline).

### Phase 2 — Fidelity core (the main change)
**Scope:** §6.1 mode routing; §6.2 Verbatim Clean prompt (default); §6.3 structured retune; §6.4 formatting model + validation; §6.5 surgical corrections + `scratch that` lexicon; §6.6 params; §7.3 freeze/incremental; §7.4 cadence + cancellation; §7.7 grounding verifier; frontend mode toggle (default Clean, persisted, re-runs `/process` on flip).
**Acceptance:**
- Verbatim Clean default; toggle persists and re-processes on flip.
- Fidelity metric (transcript n-gram/token overlap) above threshold **except at correction sites**; scrub check confirms fillers/nav removed.
- Dictated breaks preserved in 100% of validation cases.
- **Regression test:** a previously-settled finding is byte-identical after N subsequent unrelated utterances (proves freeze).
- Correction/comparison eval basket passes (corrections applied surgically; comparisons keep both).
- Zero-edit rate improves vs the Phase 1 baseline.

### Phase 3 — Orchestration sophistication & model evaluation
**Scope:** §7.5 triage; §7.6 router + backpressure; §7.7 merged review + key-terms; §6.4 finalization timing; Gemma-4 evaluation (§10).
**Acceptance:**
- Simple appends take the cheap path (measured latency/cost reduction vs Phase 2).
- Model choice is a single config change; failover exercised.
- Gemma-4-vs-Qwen decision backed by A/B telemetry (latency + fidelity + structured-output reliability), with a committed fallback.

---

## 9. Competitor best-practice alignment

From the competitor scan (consumer AI dictation + radiology incumbents + ambient clinical scribes):
- **Incremental + carried context** (AssemblyAI Context Carryover, verified) — validates §7.3; we are the outlier in doing full-document regeneration.
- **Model-tier the cleanup layer** (Wispr: small fine-tuned Llama on TensorRT-LLM, verified) — informs §7.5/§7.6 and reframes Gemma-4 (a *smaller* model may be the better cleanup engine).
- **Selection-scoped surgical corrections** (Aqua Edit Mode, verified; incumbents' `select <phrase>` → overwrite) — validates §6.5; we can exceed incumbents with semantic "change 5 mm → 10 mm".
- **Deterministic command grammar** (all three radiology incumbents, verified) — we are already correct on new line/paragraph; §6.5 adds the correction lexicon.
- **Deterministic entity formatting + finalization timing** (Deepgram, verified) — §6.4.
- **Anti-hallucination = contract + verifier** (superwhisper prompt contract; Aqua Strict Mode, verified/claimed) — §7.7.
- **Real-time consistency nudges before sign** (Fluency CAPD, PS1 Ambient, claimed) — validates the tier-1/tier-2 concept; reinforces the §7.1 fix.
- **Zero-edit rate + latency modes** (Wispr, AssemblyAI, verified/claimed); **QA-feedback loop measurably lowers error rate over time** (213,977-report study, verified) — motivates §7.2.
- **Atomic-fact verification critic pass** (Nabla: decompose→entail-check→keep-only-proven, verified) + **detector+corrector** (Abridge, verified) — upgraded §7.7 grounding verifier.
- **Route by sub-task** (Suki "LLM Manager", claimed; Nabla multi-query; Abridge multi-model, verified) — §7.5/§7.6.
- **⚠️ Lossy-intermediate caution** (npj Digital Medicine 2025, verified): a naive "break transcript into facts, then generate" intermediate step *increased* hallucinations and omissions dramatically vs structured direct generation. Our scratchpad **is** an extract-to-intermediate — so it must stay lossless/grounded. This *favours* high-fidelity Clean mode and the grounding verifier, and becomes a first-class risk (§12).
- **Eval rubrics** — modified PDQI-9 + binary hallucination flag (PMC, verified), fabrication/negation/causality/contextual × major/minor taxonomy (npj, verified), Nabla three-axis judge (Recall/Style/Veracity), amendment-rate KPI (Suki 48%, claimed) — adopted in §11.

Load-bearing recommendations are anchored to *verified* engineering, not vendor latency/accuracy claims (Wispr <700 ms p99, Willow "200 ms", "beats everyone", Abridge "6x", any "hallucination-free" number are unbenchmarked/self-published). Note also: across all ambient scribes, **note generation is batch-at-end, not live per-utterance** — RadFlow's live-updating scratchpad is a deliberate product divergence, which makes freeze-settled-text (§7.3) more important, not less.

---

## 10. Gemma-4 evaluation plan (Phase 3 spike)

Benchmark **Gemma-4 31B on Cerebras** (`gemma-4-31b`; multimodal, 131K ctx, function-calling + JSON structured output) against Groq Qwen3-32B on the **finalised** Clean + Structured prompts:
- **Metrics:** per-stage latency (vs sub-6 s clinical budget), fidelity metric, structured-output reliability, correction/comparison basket pass-rate.
- **Guardrails:** keep Qwen (or `gpt-oss-120b`) as fallback; Gemma-4 is **public-preview** ("evaluation only, may be discontinued on short notice") — not on the clinical critical path without a fallback; `zai-glm-4.7` deprecates 2026-08-17 (independent migration reason).
- **Decision:** production model chosen from A/B telemetry via the §7.6 router.

---

## 11. Evaluation methodology

Adopted from clinical-scribe best practice (Nabla, Abridge, and two independent papers):

- **Fidelity metric (Clean mode):** n-gram/token overlap between cleaned output and the raw transcript — high overlap = faithful — measured *except at correction sites*. Automated tripwire against regression toward re-authoring.
- **Scrub check:** assert fillers / nav / false-starts removed.
- **Break-preservation check:** dictated `\n`/`\n\n` count and position preserved (deterministic).
- **Grounding / veracity:** decompose output into atomic facts, verify each is entailed by the transcript; report % proven (Nabla three-axis: Recall / Style / Veracity).
- **Correction/comparison basket:** curated raw→expected pairs locking surgical-correction and keep-both-on-comparison behaviour.
- **Error taxonomy for human review:** fabrication / negation / causality / contextual, each major vs minor (npj); plus a modified PDQI-9 + binary hallucination flag rubric (PMC) for periodic blind scoring — reuse the Sonnet quality harness (`quality_scoring.py`, rubric v2.1).
- **Top-line production KPI:** zero-edit / manual-correction (amendment) rate per session — captured in Phase 1, tracked across phases.
- **Change gating:** gate prompt/model changes behind blind head-to-head on a fixed benchmark before rollout (Abridge staged-release pattern).

---

## 12. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Clean-mode "Revisions" licence reopens over-refinement | Narrow, explicit prompt licence + fidelity metric guardrail + freeze-settled-text so drift can't accumulate |
| Scratchpad-as-intermediate drops/alters content that propagates to the report (npj Exp-5: naive extract-to-facts step *increased* errors) | Favour high-fidelity Clean mode; grounding verifier (§7.7); verify defeasible normal-fill never overrides a dictated abnormal that survived into the scratchpad |
| Correction misread as comparison erases a measurement | Conservative "keep both when ambiguous" rule; correction/comparison eval basket; it remains a visible, editable scratchpad |
| Incremental processing loses cross-segment homophone context | Carried read-only context (not full isolation); validation pass |
| Gemma-4 preview discontinued mid-eval | Fallback wired via router; no production commitment in this spec |
| Freeze-settled-text interacts badly with the 2,500-char transcript window | Corrections target the persisted scratchpad, not the transcript window; verify in Phase 2 regression tests |

---

## 13. Open questions
- Manual bullet toggle in Clean mode — ship in Phase 2 or defer? (Voice is the primary control; toggle is convenience-only.)
- Does Structured mode also honour dictated breaks, or only Clean? (Current lean: Clean only; Structured keeps its anatomical layout.)
- Zero-edit metric definition — any keystroke, or clinically-meaningful edits only?

---

## Appendix — verified references
`DictationScratchpad.svelte`: capture `:275/:295`, window `:113`, cadence `:461`, queue `:314`, review coupling `:299`. `canvas_routes.py`: `/process` `:501/:531`, prompts `:162/:214/:302`, review `:560/:710`, timing `:580/:670`. `main.py`: Deepgram `:4955`, `process_dictation_transcript` `:4850`, `/dictation/check` `:2579/:2600`. `dictation_semantic.py`: `asyncio.run` `:134`, swallow `:157`. `enhancement_utils.py`: model config `:146`, Cerebras semaphore `:29`, agent runner `:3766`.
