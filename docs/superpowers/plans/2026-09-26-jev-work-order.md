# Jev work order — dictation first, then the wider product (2026-09-26)

**Source of the IDs:** `../research/2026-09-26-jev-field-research.md` (D-/X- ideas) and decision-first rev 2 `../specs/2026-09-24-decision-first-dictation-design.md` (component numbers). This file is the sequence; each step still gets its own plan before execution.

## Ordering rules

1. **Truthful measurement before tuning.** Latency and calibration numbers feed every later decision.
2. **Learn from consequences, not just predictions.** *(Revised 2026-09-26.)* Decisions run live in the Dictation Lab, so every undo, manual fix or re-dictation labels the decision that caused it. A production shadow only sees what Jev *would* have done; it moves to the pre-launch gate.
3. **Backbone before features.** Fast-append is where appends, corrections and ASR fixes all land.
4. **De-risk in parallel.** Uncertain ideas get an offline measurement on a side track so the main track never waits on an unknown.
5. **Don't over-calibrate early.** Provisional thresholds live in the registry with a version; real sessions set the final bands.

Standing rules for every step: question wording and lexicon frozen unless the step is explicitly about wording (2026-09-26, deliberate: spoken punctuation, disc levels, colon rule and headings added from lab sessions; `spoken_format.py`); production behaviour env-gated and off by default; every number with a plain-code baseline and a 95 % interval; fixtures grow from lab exports; tuning is scored only on sessions it has not seen; every automatic action fails open to today's polish path and is visible and undoable.

## Phase A — Make the numbers true

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 1 | **D-01** One shared keep-alive Jev client + warm-up on dictation socket open | Every latency figure afterwards depends on it; hours of work | Bundle parity p50/p95 with intervals, before vs after; cold first call measured separately | **done 2026-09-26**: bundle p50 288 [285, 292] → 247 [243, 250] ms, p95 378 [356, 399] → 331 [304, 349] ms; parity fresh FAIL (1 ReadTimeout) → shared PASS; cold first call p50 328 [283, 351] ms; ~40–50 ms, not 400 |
| 2 | **D-03** Brier, ECE (10 bins + counts) and reliability table in `bakeoff_stats`, printed per question for Jev and Qwen-off | Rev 2 §2 rests on calibration. If Jev is not better calibrated than Qwen-off, the plan changes here | Calibration table for all three sets, with a plain verdict | **done 2026-09-26**: **not shown**. vs qwen-lp (logprobs): Jev better 1 (coverage), qwen-lp better 2 (needs_committed_edit, asr_risk; offset, AUC 1.0), 4 not shown. Rev 2 §2: vendor not earned on calibration → **your decision before step 5** |
| 3 | **D-10** Question registry with `QSET_VERSION`, logged per decision; also log full `probabilities` (enables D-07 later) | The shadow must be attributable to a wording, and its week of data must carry distributions | Parity still PASS with unchanged wording; logs carry version + probabilities | **done 2026-09-26**: `jev_questions.py`, `QSET_VERSION 2026-09-26.1`; wording digest unchanged across the move; parity PASS, 0 errors, bundle p95 338 [306, 359] ms; qset + full probabilities on shadow, triage, coverage and utterance decision lines |

**Phase A outcome (2026-09-26):** numbers now true. Calibration did *not* come out in Jev's favour (handover §3), decided in step 4: keep Jev for the bundle on one-call-many-questions and ranking, with Qwen-off kept as the contrast. Next: step 5, live in the lab.

## Phase B — Live in the lab *(revised 2026-09-26; replaces "start the production shadow")*

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 4 | **Decision record:** keep Jev for the per-utterance bundle; keep Qwen-off as the contrast candidate. Lab sessions (own, practice or de-identified dictation) run without the X-09 decision; X-09 moves to the gate | Phase A showed Jev's case is many typed probabilities in one ~250–330 ms call with good ranking, not calibration. Qwen-off matched it on triage alone (p50 214 vs 255 ms) but returns hard labels and needs one call per question for probabilities | Written here | **done 2026-09-26** |
| 5 | **Component 2 live in the lab:** bundle on every Deepgram final, verbatim fast-append as the default op, band router with **provisional** thresholds (confident append → fast-append; command → deterministic; correct / restate / delete, low confidence or any Jev error → today's polish), **outcome logging** (decision id; undo, manual edit of the line within 10 s, re-dictation logged against it; data only, never text), lab panel counters, session summary script | Real dictation produces consequence labels the shadow cannot; moves the user-visible win (fewer polish calls) forward four steps | Lab strategy behind a lab-only flag; a week of mic sessions summarised: polish calls per utterance vs polish-everything baseline, undo/edit rate per route, bundle p50/p95, all with intervals | **built 2026-09-26, not yet exercised** (plan `2026-09-26-live-lab-fast-append.md`): front door `decision`, `POST /api/canvas/bundle`, `fast_append.py`, bands in `jev_questions.FAST_APPEND_BANDS` (QSET `2026-09-26.2`), outcome log + session export, `scripts/lab_session_summary.py`. Live smoke: 6 utterances routed as intended, bundle 264–448 ms; `standalone` 0.47–0.48 on complete statements, so unpunctuated lines will mostly close at the hard limit. No mic session yet |

## Phase C — Tune from live data

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 6 | **D-05 + D-08** (arms: criteria examples, statement-form nouls; D-09 double-ask and D-11 `addressed_to_system` as extra arms) | Fast-append closes lines on `standalone`, which under-fires today. Test set: **live-lab sessions** not used for tuning | Beats the frozen lexicon on unseen sessions | todo |
| 7 | **Set the bands from outcomes:** per decision type, thresholds from undo/edit rate at each confidence level (risk–coverage), not from ECE; thresholds versioned in the registry | Replaces "bands from shadow + calibration" | Polish calls/utterance ↓ ≥ 60 % vs baseline; undo/edit rate on automatic actions no worse than polish's | todo |

**Side track S1 (any time):** **D-02 offline.** Label correction fixtures with target line + kind (handover item 7), write the candidate-span extractor (laterality, measurements, negations per section), measure Jev's target pick against a code-only baseline with intervals. Decides whether component 5 is viable. No production wiring.

**Side track S2 (any time):** **OpenJev bake-off column.** Governance fallback and a third reference.

**Side track S3 (small, before step 7):** **risk–coverage** (accuracy when acting on the top X % most confident) in `bakeoff_stats`, and **per-session offset drift** per noul in the session summary. These are the metrics the bands actually consume; asr_risk's baseline drifted 0.5–0.8 across sessions.

## Phase D — The backbone, completed

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 8 | **Component 3** Section coverage per utterance on Jev + static collective→section map in code | Corrections need section selection to narrow candidates; replaces the Qwen coverage call | Recall ≥ Qwen's incl. lab-exported collectives | todo |

## Phase E — Latency off the path, and corrections

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 9 | **D-04 + component 7** Bundle on Deepgram interim results; closed-set commands may act early, free text waits for the final | Needs the registry's command question and the router | Command precision 1.0 on fixtures + lab; perceived command latency ≈ 0 | todo |
| 10 | **D-02 + D-06 / component 5** Span-copy corrections with numbered-badge fallback | Needs fast-append (5), section selection (8) and the S1 result | Laterality / measurement / negation fixed with no model call | todo |
| 11 | **Component 4** ASR repair chain (code proposes candidates, Jev picks, "as heard" mandatory) | Same mechanism as step 10 | ≥ polish's fix rate on lab ASR cases, zero introduced errors | todo |

## Phase F — Beyond dictation

| # | Item | Why here | Exit | Status |
|---|---|---|---|---|
| 12 | **X-04 / component 6** IntelliPrompts as retrieval | Largest measured dictation latency (2.8–6 s). Independent: move earlier if latency is the priority | Top-3 relevance ≥ generated on judged sample; < 400 ms | todo |
| 13 | **X-01** Per-sentence report integrity nouls, shadow | Highest value outside dictation; reuses client, registry and calibration work | Agreement with current audit on flagged set | todo |
| 14 | **X-06** Normal-fill as selection (with component 9) | Changes generation, so it follows the integrity check that would catch regressions | Quality rubric v2.1 parity | todo |
| 15 | Backlog: **X-05** corpus analytics, **X-07** critical tier, **X-08** prior comparison, **X-02 / X-03** routing and agent guards | Each needs its own labelled set | Per item | backlog |

## Gate before any production default-on *(revised 2026-09-26)*

All five:
1. **X-09** governance decision written (framed as adding one sub-processor, TypeSafe via OpenRouter; the same dictation text already goes to US language-model providers for polish and generation).
2. **Production shadow week** (`RR_TRIAGE_SHADOW=1`, Jev and Qwen-off side by side, `scripts/triage_shadow_report.py`) reviewed: action mix, per-question offset drift, latency.
3. **Live-lab outcome targets** met (step 7 exit).
4. A **blind radiologist-labelled sample** scored (not fixtures we wrote).
5. Calibration and risk–coverage reported for the shipped thresholds (Phase A tooling + S3).

## Minimum path

Steps 1–3 made the numbers true. **Step 5 (live lab) is now the shortest route to a user-visible win**; step 7 turns its data into bands. Everything else refines or extends those two.
