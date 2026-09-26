# Jev work order — dictation first, then the wider product (2026-09-26)

**Source of the IDs:** `../research/2026-09-26-jev-field-research.md` (D-/X- ideas) and decision-first rev 2 `../specs/2026-09-24-decision-first-dictation-design.md` (component numbers). This file is the sequence; each step still gets its own plan before execution.

## Ordering rules

1. **Truthful measurement before tuning.** Latency and calibration numbers feed every later decision.
2. **Start slow clocks early.** The production shadow needs a week of real data, so it starts while other work runs.
3. **Backbone before features.** Fast-append is where appends, corrections and ASR fixes all land.
4. **De-risk in parallel.** Uncertain ideas get an offline measurement on a side track so the main track never waits on an unknown.

Standing rules for every step: question wording and lexicon frozen unless the step is explicitly about wording; production behaviour env-gated and off by default; every number with a plain-code baseline and a 95 % interval; fixtures grow from lab exports; tuning is scored only on sessions it has not seen.

## Phase A — Make the numbers true

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 1 | **D-01** One shared keep-alive Jev client + warm-up on dictation socket open | Every latency figure afterwards depends on it; hours of work | Bundle parity p50/p95 with intervals, before vs after; cold first call measured separately | **done 2026-09-26**: bundle p50 288 [285, 292] → 247 [243, 250] ms, p95 378 [356, 399] → 331 [304, 349] ms; parity fresh FAIL (1 ReadTimeout) → shared PASS; cold first call p50 328 [283, 351] ms; ~40–50 ms, not 400 |
| 2 | **D-03** Brier, ECE (10 bins + counts) and reliability table in `bakeoff_stats`, printed per question for Jev and Qwen-off | Rev 2 §2 rests on calibration. If Jev is not better calibrated than Qwen-off, the plan changes here | Calibration table for all three sets, with a plain verdict | **done 2026-09-26**: **not shown**. vs qwen-lp (logprobs): Jev better 1 (coverage), qwen-lp better 2 (needs_committed_edit, asr_risk; offset, AUC 1.0), 4 not shown. Rev 2 §2: vendor not earned on calibration → **your decision before step 5** |
| 3 | **D-10** Question registry with `QSET_VERSION`, logged per decision; also log full `probabilities` (enables D-07 later) | The shadow must be attributable to a wording, and its week of data must carry distributions | Parity still PASS with unchanged wording; logs carry version + probabilities | **done 2026-09-26**: `jev_questions.py`, `QSET_VERSION 2026-09-26.1`; wording digest unchanged across the move; parity PASS, 0 errors, bundle p95 338 [306, 359] ms; qset + full probabilities on shadow, triage, coverage and utterance decision lines |

**Phase A outcome (2026-09-26):** numbers now true. Calibration did *not* come out in Jev's favour (handover §3), so before step 5 decide: keep Jev (earned on one call for all questions and on ranking, not on calibration), or shadow Qwen-off as well. Unblocked now: step 4 (needs you), S1 (after 3), S2 (after 2).

## Phase B — Start the real-world clock

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 4 | **X-09** Governance decision on sending dictation text to TypeSafe via OpenRouter | The shadow sends real text, so this is needed *before* step 5, not before default-on | Written decision: what may be sent, in what form (text, redacted, hashed) | todo |
| 5 | **Component 0** Production shadow (`RR_TRIAGE_SHADOW=1`), summarised with `scripts/triage_shadow_report.py` | Takes a week; the action mix and confidence distributions set the bands in step 7 | One week of data + summary | todo |

## Phase C — Fix known weak spots while the shadow runs

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 6 | **D-05 + D-08** (arms: criteria examples, statement-form nouls; D-09 double-ask and D-11 `addressed_to_system` as extra arms) | Fast-append closes lines on `standalone`, which under-fires today. Needs **new lab mic sessions** as the test set | Beats the frozen lexicon on unseen sessions | todo |

**Side track S1 (any time after 3):** **D-02 offline.** Label correction fixtures with target line + kind (handover item 7), write the candidate-span extractor (laterality, measurements, negations per section), measure Jev's target pick against a code-only baseline with intervals. Decides whether component 5 is viable. No production wiring.

**Side track S2 (any time after 2):** **OpenJev bake-off column.** Governance fallback and a third calibration reference.

## Phase D — The backbone

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 7 | **Component 2** Verbatim fast-append + band router, offline replay of lab sessions first | Bands come from shadow (5) + calibration (2); every later operation plugs in here | Polish calls/utterance ↓ ≥ 60 %; zero-edit rate ≥ today | todo |
| 8 | **Component 3** Section coverage per utterance on Jev + static collective→section map in code | Corrections need section selection to narrow candidates; replaces the Qwen coverage call | Recall ≥ Qwen's incl. lab-exported collectives | todo |

## Phase E — Latency off the path, and corrections

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 9 | **D-04 + component 7** Bundle on Deepgram interim results; closed-set commands may act early, free text waits for the final | Needs the registry's command question and the router | Command precision 1.0 on fixtures + lab; perceived command latency ≈ 0 | todo |
| 10 | **D-02 + D-06 / component 5** Span-copy corrections with numbered-badge fallback | Needs fast-append (7), section selection (8) and the S1 result | Laterality / measurement / negation fixed with no model call | todo |
| 11 | **Component 4** ASR repair chain (code proposes candidates, Jev picks, "as heard" mandatory) | Same mechanism as step 10 | ≥ polish's fix rate on lab ASR cases, zero introduced errors | todo |

## Phase F — Beyond dictation

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 12 | **X-04 / component 6** IntelliPrompts as retrieval | Largest measured dictation latency (2.8–6 s). Independent: move earlier if latency is the priority | Top-3 relevance ≥ generated on judged sample; < 400 ms | todo |
| 13 | **X-01** Per-sentence report integrity nouls, shadow | Highest value outside dictation; reuses client, registry and calibration work | Agreement with current audit on flagged set | todo |
| 14 | **X-06** Normal-fill as selection (with component 9) | Changes generation, so it follows the integrity check that would catch regressions | Quality rubric v2.1 parity | todo |
| 15 | Backlog: **X-05** corpus analytics, **X-07** critical tier, **X-08** prior comparison, **X-02 / X-03** routing and agent guards | Each needs its own labelled set | Per item | backlog |

## Gate before any production default-on

All four: X-09 decision written; shadow week reviewed; calibration measured (step 2); a blind radiologist-labelled sample scored (not fixtures we wrote).

## Minimum path

Steps 1–3 and 5 give truthful data; step 7 delivers the user-visible win. Everything else refines or extends those two.
