# Decision-First Dictation — Architecture Design (rev 2)

**Date:** 2026-09-24
**Status:** Rev 2. Supersedes rev 1 (same path, see git history). Direction approved in conversation; each component ships under its own spec.
**Evidence base:** triage shadow spec §12; bake-offs `docs/model-migration/{triage,coverage,boundary}-bakeoff-2026-09-24.json`; five lab mic sessions; handover `docs/superpowers/handover/2026-09-24-jev-dictation-lab-handover.md`
**What changed from rev 1:** the utterance front door's complete/continues choice is retired in favour of a cheap default operation; routing now uses confidence bands instead of floors; placement merges into per-utterance section coverage; a new §6 defines when Jev calls are chained rather than run in parallel; build order re-ranked against measured latency.

## 1. The principle

Most pipeline steps are decisions wearing a generation costume. A decision is typed, calibrated, parallelisable and about 300 ms; generation is 0.5–9 s and can hallucinate. Ask of every step: **is this a choice, or is this prose?** Only prose gets a language model.

Rev 2 adds a corollary learned in the lab: **make the default operation cheap and reversible, and most decisions stop being urgent.** The boundary work spent five mic sessions tuning timers because the operation behind the decision (full-scratchpad polish) was expensive and destructive on fragments. Fix the operation, not the timer.

## 2. What Jev is good at (evidence), and the rule that follows

| Strong | Weak |
|---|---|
| Choice among semantically distinct options with clear definitions — action triage 0.979 (47/48), commands 1.00 | Time and the future — "continues" at 0.97 after 5 s silence; `silence_s` in state had no effect |
| Nouls about text on the page — coverage P 1.0 / R 0.955, scores bimodal (19 % in 0.2–0.8) | Taste — placement raw 0.69 at low confidence |
| Latency 233–389 ms (p10–p90 triage), parallel questions nearly free | Absolute detection — `asr_risk` ranks the true error first but its clean baseline spans 0.25–0.68 |
| Calibrated probabilities | Unstated domain knowledge — collectives ("thoracic structures") under-credited |

**Rule:** ask Jev only about properties of the words already present. Time, punctuation, ASR confidence and domain maps live in code and enter Jev either as a gate or as a runtime-built option set.

**Jev's distinct value is calibration, not accuracy.** Qwen reasoning-off tied at 0.979 on triage. If a component does not use the probabilities (bands, escalation, margins), the vendor dependency is not earned and the Qwen-off implementation is preferred.

**Honest error bars.** 47/48 has a 95 % Wilson lower bound of ~0.89. The only triage miss (append-06, temporal comparison read as correction) came at **0.93** confidence — the expensive confusion, just under the 0.95 cut. A five-minute regex (command lexicon + trailing function word/number) scored 0.816 vs Jev 0.868 on the 38 boundary cases, the misses concentrating on the disputed labels (written after seeing the fixtures; directional only). Every bake-off from now on reports a plain-code baseline and an interval.

## 3. Target architecture

```
Deepgram final chunk (+ per-word confidence, terminal punctuation)
   │
   ├──► optimistic faded render (immediate, as today with rr_incremental)
   │
   └──► [Jev bundle — one call, parallel questions, ~300 ms, off the visual critical path]
          action            choice  append | correct | restate | delete | format | noise
          command           choice  none | generate | switch_mode | jump_to_section | undo
          section.*         noul    one per checklist section, asked of THIS utterance
          standalone        noul    the open line could stand as a complete statement
          asr_sense.<w>     noul    per Deepgram-flagged word: makes clinical sense here
          tiebreak.*        noul    fixed known confusion pairs (e.g. comparison vs correction)
          needs_committed   noul    edit touches the frozen zone
   │
   ▼
[band router — code]
   confident + cheap op   → deterministic handler
   confident + needs args → chained Jev step (§6)
   uncertain band         → Qwen, scoped to one line / one utterance
   Jev failure            → today's polish path (fail open)
   │
   ▼
[scratchpad op log] (utterance hash, decisions, op, model used) → provenance, replay, fixtures
```

### 3.1 Verbatim fast-append is the default operation

- An append writes the chunk verbatim into an **open line**: Deepgram punctuation, our command lexicon (`process_dictation_transcript`), deterministic filler removal.
- The line **closes** on terminal punctuation (code) or `standalone ≥ τ` at a silence milestone; on close it may receive a single-line polish if (and only if) a decision asks for one.
- A premature close costs one extra line join, not a scratchpad rewrite. The complete/continues choice and most of the silence schedule are retired; `standalone` + punctuation + a hard limit remain.

### 3.2 Bands, not floors

Each decision gets two thresholds from its own cost matrix: **act** (deterministic) above the upper, **escalate** (Qwen, scoped) in the band, **default cheap op** below where the default is safe. Thresholds are set from production shadow distributions plus fixture calibration, never by the model.

Cost asymmetries that set the bands:

| Confusion | Cost | Consequence |
|---|---|---|
| correction ↔ append | High: silent duplication or loss of a finding | Wide escalate band; tie-break question in bundle |
| ASR error passed verbatim | Medium–high when it changes meaning (laterality, negation) | Gate on Deepgram word confidence + `asr_sense` |
| Early line close | Low: visible, joinable | Act on `standalone` at 0.5 |
| Wrong section/paragraph | Low in capture mode | Act on argmax |

### 3.3 Placement merges into section coverage

Section nouls asked of each utterance give three things at once: which section it belongs to (Structured mode placement), paragraph breaks (section changed), and pill coverage accumulated monotonically. The standalone `placement` question is dropped. A full-scratchpad coverage recompute runs only after a correction or delete. Collective phrases resolve through a **static group-membership map in code** (e.g. which sections a thoracic collective covers); Jev judges only whether a definitive claim is made.

## 4. Components, in build order

Order is set by measured latency (lab, Qwen path: IntelliPrompts 2.8–6 s/utterance, coverage 0.8–2.3 s, `/process` 0.3–1.35 s) and by dependency.

| # | Component | Shape | Replaces | Exit criterion |
|---|---|---|---|---|
| 0 | **Production triage shadow** | log-only | nothing | 1 week of real action mix + confidence distribution |
| 1 | **Per-utterance bundle** | parallel | three separate calls (`/process` triage, `/utterance` boundary, `/review` coverage) | one call, p95 < 500 ms, parity with each component's bake-off |
| 2 | **Verbatim fast-append + band router** | bundle + code | polish on clean appends; complete/continues timers | zero-edit rate ≥ today's; polish calls/utterance ↓ ≥ 60 % |
| 3 | **Section coverage on Jev, per utterance** | bundle + code map | Qwen coverage + normaliser; placement | recall ≥ Qwen's on fixtures incl. lab-exported collectives |
| 4 | **ASR repair** | chain (§6.2 A) | polish as ASR fixer | ≥ polish's fix rate on lab ASR cases, zero introduced errors |
| 5 | **Correction target + kind** | chain (§6.2 C) | full rewrite on corrections | laterality/measurement corrections applied with no model call |
| 6 | **IntelliPrompts as retrieval** | Score per template | generated prompts | top-3 relevance ≥ generated on judged sample; latency < 400 ms |
| 7 | **App commands** | bundle | nothing (new) | command precision 1.0 on fixtures + lab |
| 8 | **Audit screen → locate** | chain (§6.2 B) | nine-criteria prose audit on clean reports | spans agree with current audit on flagged set |
| 9 | **Generation plan as decisions** | chain (§6.2 D) | planner reasoning (93–95 % of generation) | quality rubric v2.1 parity with reasoning off |

## 5. Invariants every component inherits

- **Typed decisions, thresholds in code**, set per component from its cost matrix; bands, not floors.
- **Ask about the page, not the clock.** Time, punctuation, ASR confidence and domain maps are code.
- **Prose only when a decision says so**, scoped to one line or one utterance.
- **Default operation cheap and reversible.** A wrong decision must be visible and undoable.
- **Shadow → lab routing → prod behind an env setting.**
- **Log data, never text** (length + hash in prod).
- **Fixtures grow from the lab**, labelled by *what the system should do*, not by grammar; distribution-weighted reporting alongside balanced sets.
- **Every bake-off reports a plain-code baseline and a 95 % interval.**
- **Vendor-neutral `classify(state) -> decision` protocol** with Jev and Qwen-off implementations; Jev must win on calibration use, tail latency or cost to stay.

## 6. Pipeline patterns: parallel vs chained

### 6.1 The rule

Extra questions in one call are nearly free; each chained call adds ~300 ms. So:

- **A gate alone does not justify a chain.** Ask the gate and the gated question in the same call; code ignores the gated answer when the gate is closed.
- **Known confusion pairs go in the bundle** as tie-break nouls (e.g. "describes change relative to a prior study" vs "replaces something said in this dictation").

**Chain only when step 2 needs something step 1 produced:**

1. **Runtime options.** Step 2's `criteria` map is built from step 1's answer — actual scratchpad lines, phonetic candidates, one guideline's categories.
2. **Narrowed state or fan-out.** Per-sentence or per-finding questions too costly to ask unconditionally.
3. **Rare or hidden.** Step 1 filters most traffic away, or the step runs behind the faded render / in the background.

### 6.2 Patterns

**A. Code proposes, Jev chooses — ASR repair**
```
Deepgram word confidence < c (code) → flagged words
  → bundle: asr_sense.<w> noul "makes clinical sense here for {scan_type}"
  → if not: code builds phonetic neighbours from the scan-type radiology lexicon / keyterms
  → Jev choice over {candidates…, "<word> (as heard)"}
  → confident → string substitution; else → Qwen on that line
```
Jev cannot generate a correction, but it can pick one. The "as heard" option is mandatory.

**B. Screen, then locate — audit spans**
```
audit bundle: 9 criteria as nouls over the report
  → flagged criteria only: code splits sentences
  → noul per sentence "this sentence violates <criterion>"
  → high-scoring sentences = highlighted spans; Qwen writes rationale only for those, if needed
```
Gives Jev the spans it cannot produce natively; the fan-out runs only on flagged reports.

**C. Target, then kind — corrections**
```
bundle: action = correct (act band)
  → code: candidate lines = lines in the section(s) the bundle's section nouls selected
  → Jev: correction_target (choice over those lines + "none of these")
         correction_kind (laterality | measurement | negation | descriptor)
  → laterality / measurement / negation → string edit (code)
  → descriptor → Qwen rewrites that one line
  → "none of these" or low confidence → today's scoped polish
```

**D. Classify, then specialise — generation plan**
```
code: split scratchpad into findings
  → stage 1: per finding abnormal / incidental nouls; which report sections apply
  → code: candidate guidelines per abnormal finding's organ (guideline_prefetch registry)
  → stage 2: per finding guideline choice (candidates + "none"); significance score
            (incidental | relevant | actionable | critical)
  → code: fetch that guideline's category definitions
  → stage 3: category choice (e.g. nodule / cyst classification)
  → Qwen, reasoning off: writes prose from the fixed plan
```
Three chained calls (~1 s) against reasoning that is 93–95 % of generation time.

**E. Escalate state on uncertainty**
Ask first with a small state (utterance + recent lines). If the margin between the top two options is below the band, re-ask with the full scratchpad or prior report. Most calls stay small; hard cases get context.

### 6.3 Chain hazards and the rules that contain them

- **Compounding recall loss.** Gates are set for recall (low threshold); precision is the later step's job. Shadow logs every gated-out case.
- **Forced choice.** Every chained choice carries an escape option ("none of these", "as heard").
- **Compounding confidence.** Chain confidence is the product of step confidences; the escalate band applies to the product.
- **Parallel first.** Before building a chain, test the conditional phrasing inside the bundle ("If this is a correction, which line…"). Chain only where the lab shows runtime options or narrowed state beat it.

## 7. First experiments

1. **Bundle parity (component 1).** Merge the three current question sets into one call on the existing fixtures; confirm per-question accuracy and p95 unchanged. Add a regex baseline column to all three bake-off scripts.
2. **Fast-append replay (component 2).** Replay lab-exported sessions through fast-append + bands offline; measure polish calls saved, zero-edit rate proxy, and every correction/ASR case that would have passed verbatim.
3. **ASR repair chain (pattern A).** Build the phonetic-candidate generator from the scan-type keyterm list; test on the four sessions' known errors ("inoculins", "white base", "speculated", "upstream…tery") plus clean controls. Compare against a conditional-phrasing bundle version.
4. **Correction chain (pattern C).** Extend `triage_utterances.jsonl` with target-line and kind labels; measure target accuracy and the share of corrections resolvable without a model.

## 8. Retired from rev 1 / the front-door spec

- The complete/continues boundary choice as the send trigger, confidence-scaled backstops and the 9 s wait. `standalone`, terminal punctuation and a hard limit remain as line-close signals.
- The `placement` question (absorbed by per-utterance section nouls).
- A fixed `asr_risk` threshold (replaced by Deepgram confidence gate + `asr_sense` + pattern A).

## 9. Open questions

- Delete semantics after a formatting command (pilot observation).
- Whether restatements are dropped or shown faded (UX).
- Deepgram `endpointing` value once fast-append makes early sends cheap.
- Whether the bundle's section nouls stay accurate on long multi-region checklists (REGIONS protocols), or need a region-first chain.
