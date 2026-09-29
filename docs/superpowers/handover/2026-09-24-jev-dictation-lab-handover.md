# Handover — Jev (System 1) dictation work, 2026-09-24

**Branch:** `dictation-triage-lab`, worktree `.claude/worktrees/dictation-triage-lab` (from `skill-sheet-v3` head; ~55 commits; tree clean). Not merged. Production unchanged: every new path is env-gated and off by default.

## 1. Intent

Replace generation with typed decisions wherever a pipeline step is really a *choice*. Jev 1.13 (TypeSafe, via OpenRouter `POST /api/v1/systemone`, ~300 ms, $0.04/M in) returns calibrated probabilities for Choice / Score / Noul questions over a JSON state; no prose. The language model (Qwen 27B on Cerebras/Groq) runs only when prose is needed. The scratchpad is **capture**, not the report: snappy, fidelity-preserving, fillers cut; heavy formatting belongs to report generation.

Architecture spec (the map for everything below): `docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md`, **rev 2** — one decision bundle per utterance, verbatim fast-append as the default step, confidence bands instead of floors, parallel-vs-chained Jev patterns, re-ranked build order, invariants (thresholds in code; ask about the page, not the clock; shadow → lab routing → prod behind env; log data never text; baseline + interval in every bake-off).

## 2. What exists (all specs in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`, same date prefix)

| Component | State | Key files |
|---|---|---|
| **Dictation Lab** `/dictation-lab` (dev route, gated) | working; mounts the production `IntelliDictateTab` unchanged + instrumentation panel (feeder, strategy, timeline, chunk rows, coverage table, fixture export) | `frontend/src/routes/dictation-lab/`, `frontend/src/lib/components/DictationLabPanel.svelte`, `frontend/src/lib/dictation-lab/*.ts` (pure helpers, vitest "server" project) |
| **Utterance action triage** (append/correct/restate/delete/format/noise + 2 nouls) | shipped; Jev + Qwen-reasoning-off candidates; shadow/debug/route modes on `/api/canvas/process` | `backend/src/rapid_reports_ai/dictation_triage*.py`, `canvas_routes.py` |
| **Section pill coverage** (one Noul per checklist section) | shipped; `RR_COVERAGE_CANDIDATE=jev\|qwen` (default qwen) on `/api/canvas/review`; three-state pills in lab | `section_coverage.py` |
| **Utterance front door** (boundary complete/continues/command + placement + standalone + asr_risk, one Jev call per Deepgram chunk) | shipped, lab only, iterated over 5 mic sessions | `utterance_boundary.py`, `POST /api/canvas/utterance`, `DictationScratchpad.svelte` (buffer, silence schedule, utterance queue), `frontDoor.ts` |
| Fixtures + bake-offs | `tests/fixtures/{triage_utterances,coverage_cases,boundary_cases}.jsonl`; `scripts/{triage,coverage,boundary}_bakeoff.py`; results in `docs/model-migration/*-bakeoff-2026-09-24.json` | |

Tests: backend 344 passed (1 live test skipped unless `RR_LIVE_TESTS=1`); frontend 32 in `src/lib/dictation-lab`.

## 3. Results that matter

- **Action triage bake-off (48 cases):** Jev 0.979, Qwen-off 0.979, both 0 errors; Jev ≥0.95-confidence bucket 100 % right at 83 % coverage; p50 ~290 ms. Only shared miss: temporal comparison. Deterministic route rows 260–290 ms vs 470 ms–8.8 s live model.
- **Coverage bake-off (26 cases):** Jev P 1.0 / R 0.955 / exact 0.92, p50 303 ms; Qwen exact 1.0, p50 860 ms, p95 1.7 s. Jev under-credits some collectives ("thoracic structures"); on live text *both* missed a solid-organ collective. Recall gap must close before flipping prod.
- **Boundary bake-off (38 cases):** raw 0.868, command 1.00; thresholds only add stalls → floors are 0.2 (near-uniform guard). Placement raw 0.69 with low confidence (taste-heavy; new_line default).
- **Lab mic sessions:** classifier was right on almost every chunk; every failure mode was a *timer or upstream* problem (see §4).

**Baselines + 95 % intervals (rerun 2026-09-24, `scripts/bakeoff_baselines.py`; lexicon drafted after the fixtures, so the code column is an optimistic ceiling):**

| Set | Plain code | Jev | Qwen-off |
|---|---|---|---|
| Triage action (n=49) | 0.918 [0.81, 0.97] (45/49) | 0.980 [0.89, 1.00] (48/49) | 0.980 [0.89, 1.00] (48/49) |
| Coverage exact set (n=26) | 0.538 [0.35, 0.71] (14/26) | 0.923 [0.76, 0.98] (24/26) | 0.962 [0.81, 0.99] (25/26) |
| Coverage recall (sections) | 0.532 [0.39, 0.67] (25/47) | 0.979 [0.89, 1.00] (46/47) | 1.000 [0.92, 1.00] (47/47) |
| Boundary 3-way (n=39) | 0.897 [0.76, 0.96] (35/39) | raw 0.846 [0.70, 0.93] (33/39) | — |
| Standalone@0.5 (n=29, complete/continues) | 0.862 [0.69, 0.94] (25/29) | 0.724 [0.54, 0.85] (21/29) | — |

Jev's interval clears the lexicon only on coverage; on triage the intervals overlap, and on boundary and `standalone` the lexicon is ahead. `standalone` under-fires on finished statements split across buffer + chunk or carrying ASR errors (cmp-02/04/10/12/13, asr-01/02 at 0.23–0.48); rev 2 leans on it for line close, so this needs a fix or a code-first rule before component 2. Qwen coverage had one 93.8 s call (lab-cov-01, 14 sections), hence its p95 interval [1191, 93778] ms.

- **Bundle parity (2026-09-24, 114 fixtures, ref→bundle→ref, `utterance_bundle.py` + `scripts/bundle_parity.py`):** **PASS**. Per question (ref vs bundle, bundle-only/ref-only/noise): action 48/49 vs 47/49 (1/0/0, at the allowance of 1; format-07 "comma" at 0.47); is_correction 48/49 vs 48/49 (0/0/0); needs_committed_edit 49/49 vs 49/49; standalone 21/29 vs 24/29 (0/3/2: bundle *better* with the open-line + latest-utterance wording, still under the lexicon's 25/29); coverage sections 96/98 vs 96/98 (1/1/1). Bundle p50/p95 284/361 ms [337, 424] over 228 calls (≤8 q: p95 442; >8 q: p95 337, so checklist length is not the latency lever) vs separate p95 triage 360 / boundary 397 / coverage 352. Commands caught by action: 10/10. Cost $0.0097 for 228 bundle calls. `docs/model-migration/bundle-parity-2026-09-24.json`.

### Phase A (work order steps 1–3), 2026-09-26 — plan `plans/2026-09-26-jev-phase-a-client-calibration-registry.md`

**D-01 shared client** (`jev_client.py`; four callers, not three: boundary had one too). Interleaved A/B, same bundle bodies, 60 rounds (`scripts/jev_latency_ab.py`, `jev-client-latency-2026-09-26.json`):

| Arm | p50 [95 % CI] | p95 [95 % CI] |
|---|---|---|
| fresh client per call (before) | 303 ms [293, 320] | 377 ms [342, 411] |
| shared keep-alive (after) | 268 ms [260, 274] | 328 ms [303, 349] |
| cold: first call on a new client (n=20) | 328 ms [283, 351] | 390 ms [351, 595] |

Process-first call (DNS included) 430 ms; live warm-up 522 → 250 → 227 ms. Bundle parity back to back: **fresh FAIL** (every question PASS, but one 3 s ReadTimeout on lab-cov-01), bundle p50/p95 288 [285, 292] / 378 [356, 399] ms; **shared PASS**, 0 errors, 247 [243, 250] / 331 [304, 349] ms; separate calls p95 363 → 297 ms. Gain is ~40 ms at p50 and ~50 ms at p95 with non-overlapping p50 intervals: real, but far smaller than the voice browser's 700 → 300 ms. Our handshake was never the big cost. Warm-up fires on `/api/transcribe` open only when a Jev flag is on.

**D-03 calibration** (`bakeoff_stats`: Brier, ECE 10 bins, reliability table, case-level bootstrap; `calibration-2026-09-26.json`). Qwen-off has no probabilities as shipped (Groq qwen3.6 rejects `logprobs`), so two contrasts: **qwen** = shipped, hard labels scored as certainty; **qwen-lp** = Cerebras qwen-3.8-27b reasoning off, one call per question, first-token logprobs (different model version and prompt form; eval only). Differences are other − Jev with paired 95 % intervals; positive = Jev better.

| Set / question | Accuracy jev · qwen · qwen-lp | Brier jev | qwen − jev | qwen-lp − jev | Verdict vs qwen-lp |
|---|---|---|---|---|---|
| triage action (n=49) | 48 · 48 · 48 /49 | 0.050 | −0.009 [−0.035, +0.010] | +0.008 [−0.022, +0.036] | not shown |
| triage is_correction | 48 · 39 · 47 /49 | 0.038 | **+0.166 [+0.063, +0.270]** | −0.013 [−0.034, +0.006] | not shown |
| triage needs_committed_edit | 49 · 49 · 49 /49 | 0.061 | **−0.061** [−0.071, −0.052] | **−0.027** [−0.039, −0.014] | **qwen-lp better** |
| coverage section (98 units, 26 cases) | 95 · 97 · 84 /98 | 0.033 | **−0.023** [−0.047, −0.007] | **+0.058 [+0.018, +0.110]** | **Jev better** |
| boundary 3-way (n=39) | 33 · — · 29 /39 | 0.215 | — | +0.171 [−0.025, +0.366] | not shown |
| standalone (n=29) | 21 · — · 23 /29 | 0.186 | — | −0.026 [−0.124, +0.083] | not shown |
| asr_risk (n=39) | 24 · — · 36 /39 | 0.234 | — | **−0.174** [−0.230, −0.110] | **qwen-lp better** |

**Verdict: no. On our data Jev is not shown to be better calibrated than Qwen-off.** Against the logprob contrast: Jev better on 1 question (coverage), qwen-lp better on 2, 4 not shown. Against shipped hard-label Qwen: Jev better only on is_correction, and that is an accuracy gap (0.98 vs 0.80), not calibration; hard Qwen scores better on needs_committed_edit and coverage because it is right and certain there. Where Jev loses on nouls the loss is an **offset, not ranking**: clean negatives sit at a median 0.25 (needs_committed_edit) and asr_risk's baseline is ~0.5, yet AUC is 1.0 on both (only 2 and 4 positives, so weak evidence). A threshold set in code absorbs an offset; ECE and Brier punish it. Triage action has 1 miss in 49 for every candidate, so calibration there is untestable at this n. Rev 2 §2's rule therefore says the vendor is **not earned on calibration**; what remains to earn it is one call for every question (qwen-lp needs one call per question: triage p95 1243 ms [615, 1279] for three parallel calls vs Jev bundle p95 331 ms) and ranking quality. **The keep-or-drop call is yours, before step 5.** Jev triage p95 in this run was 882 ms [297, 904]: one tail, not repeated in parity.

**D-10 registry** (`jev_questions.py`, `QSET_VERSION = "2026-09-26.1"`): every question, criteria map and threshold (triage, boundary, coverage, bundle, route default 0.9), moved verbatim; the old modules re-export. `tests/test_jev_questions.py` pins the wording by a digest computed *before* the move, unchanged after. Every decision log line carries `qset` and full probabilities, never text: `canvas.triage.shadow` (+qset), new `canvas.triage.decision` (debug/route), `canvas.coverage.decision` (only when Jev ran), `canvas.utterance.decision`; `TriageTrace`, `CoverageTrace`, `UtteranceResponse` and `BundleDecision` carry `qset`. Parity after the move: **PASS**, 0 errors, bundle p50/p95 243 / 338 [306, 359] ms (`bundle-parity-2026-09-26-registry.json`); one new bundle-only miss (needs_committed_edit format-05 at 0.51) within the allowance of 1, which is noise on unchanged wording.

## 4. What worked / what failed (the insights)

1. **Jev is calibrated and fast; the surrounding rules were the problem every time.** A 0.4 floor demoted correct completes; a 1.5 s backstop cut sentences a radiologist pauses mid-way while reading images; a 9 s backstop then over-waited. Lesson: act on the raw choice; put *time* and *punctuation* in code, not in the model.
2. **Jev does not weigh non-linguistic state.** Adding `silence_s` to the state + an instruction did nothing (raw "continues" 0.88 after 5 s). What works: ask a sharper linguistic question at the milestone (`standalone`: "could these words stand alone as a statement") and apply the time rule in code. Current schedule: chunk ends with `.?!` → complete (code); 2 s silence → send if standalone ≥ 0.5; 5 s → send regardless.
3. **Deepgram `dictation=true` turns the organ "colon" into ":".** Lab runs with `DEEPGRAM_DICTATION=0` (env gate in `main.py` websocket URL); polish punctuates anyway; new line/paragraph/full stop handled by our lexicon. With dictation off, Deepgram's `punctuate` closes sentences it is sure of — a free, high-precision boundary signal, now used.
4. **Pydantic output schemas leak into the model's tool schema.** Adding `triage` to `CanvasProcessResponse` made the live model try to fill it. Route return types are subclasses (`CanvasProcessResult`) that the model never sees.
5. **Groq's tool validator rejects `True`/`False` strings for JSON booleans** → Qwen aux fields are `yes`/`no` literals.
6. **A command must flush buffered words as their own statement**, never be glued onto a finding; and a queued utterance must never abort an in-flight polish (would drop its triage). Both fixed.
7. **ASR-risk Noul ranks the true error first in every session** ("inoculins", "white base", "speculated", "upstream…tery") but its clean baseline drifts 0.5–0.8, so no absolute cut works; a relative rule (session-high or ≥0.85) is the likely shape. Not acted on.
8. **Derived labels are lenient heuristics.** Line-based `derive_action`/`derivePlacement` mismatch Verbatim mode where the polish writes multi-sentence lines; judge placement in Structured mode or derive at sentence level.
9. **Repo quirks:** dev-route guard read `import.meta.env.PUBLIC_*`, which Vite never exposes — fixed to `$env/dynamic/public` (all dev routes had 404'd locally). `bun run build` fails locally in adapter-vercel on Node 26 on every branch (Vite build succeeds; `preview` still works). Run backend from the worktree with `PYTHONPATH=src` + main venv (editable install points at main tree). Symlink/copy `.env` into the worktree; frontend needs a real `.env` copy for Vite.

## 5. How to run the lab

```
# backend (worktree/backend)
RR_TRIAGE_DEBUG=1 DEEPGRAM_DICTATION=0 DEEPGRAM_UK_SPELLING=1 DEEPGRAM_SPOKEN_FORMAT=1 PYTHONPATH=src <main>/backend/.venv/bin/uvicorn rapid_reports_ai.main:app --port 8000
# frontend (worktree/frontend)   bun run dev      → sign in, open /dictation-lab
# in the tab: localStorage rr_incremental=1 (faded optimistic render), Strategy → front door = Jev boundary
# bake-offs: PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.boundary_bakeoff', run_name='__main__')"
#   same form for triage_bakeoff, coverage_bakeoff (print calibration; need OPENROUTER, GROQ and CEREBRAS keys),
#   bundle_parity, jev_latency_ab (fresh vs shared client). RR_JEV_FRESH_CLIENT=1 restores per-request clients.
```

Tests (2026-09-26, after Phase A): backend 439 passed, 1 skipped. After step 5: backend 490 passed, 1 skipped; frontend `src/lib/dictation-lab` 48.

### Decision-first live (work-order step 5, built 2026-09-26, not yet exercised)

Plan: `plans/2026-09-26-live-lab-fast-append.md`. Production unchanged: `/api/canvas/bundle` returns 404 unless `RR_TRIAGE_DEBUG=1`, and the scratchpad path runs only with the lab's front door set to `decision`.

```
# backend: same command as above (RR_TRIAGE_DEBUG=1 DEEPGRAM_DICTATION=0 …); needs OPENROUTER_API_KEY
# frontend: bun run dev → sign in → /dictation-lab
# panel → Strategy → front door → "decision-first (live)"   (faded render is automatic in this mode)
# dictate. Each Deepgram final: faded → one Jev bundle → route:
#   fast-append (green dotted mark, 10 s)  |  command (\n, \n\n, .)  |  polish (today's /process)  |  skip (filler only)
# undo the latest action (any route, incl. polish): ⌘Z in the scratchpad or "Undo last" under the mic button
# the editor stays editable while recording: fix a line by hand within 10 s and it counts as an edit
# say a line again within 15 s (≥ 0.7 token overlap) and it counts as a re-dictation
# panel → Decision-first → "Export session" writes lab-session-<start>.json (data only, no text)
# after a batch of sessions:
PYTHONPATH=src <main>/backend/.venv/bin/python -m rapid_reports_ai.scripts.lab_session_summary ~/Downloads/lab-session-*.json [--json out.json]
```

Routing (provisional, `jev_questions.FAST_APPEND_BANDS`, QSET `2026-09-26.3`): append ≥ 0.90 with `is_correction` < 0.50 and Deepgram's lowest word confidence ≥ 0.70 (when present) → fast-append; formatting_command ≥ 0.80 with a lexicon mapping → command; everything else, any Jev or network error, a pending-text mismatch, or a polish already queued or running → polish. The line closes on terminal punctuation or newline, at 2 s silence if `standalone` ≥ 0.50, and at 5 s regardless. **Line close is a statement boundary, not layout** (first mic session, 2026-09-26): Deepgram ends nearly every final with a full stop, so starting a new line on close put each fragment on its own line until a polish reflowed it. Fast-append now always continues the text with a space; new lines come only from commands. Close still sets Jev's `open_line` and the logged `line_closed_by`. Backend log: one `canvas.bundle.decision` line per decision (id, qset, route, reason, probabilities, lengths, hash). "Clear" in the panel starts a new session (new start time, counters reset).

British spelling: Deepgram returns US spelling even with `language=en-GB` (its docs); `DEEPGRAM_UK_SPELLING=1` adds its `replace` find-and-replace with a radiology US→UK list (`deepgram_spelling.py`, checked live on the streaming websocket) and restores sentence-initial capitals. Off by default; production unchanged.

Spoken formatting (`spoken_format.py`, 2026-09-26, deliberate lexicon change): slash, comma, semicolon, hyphen, brackets and question mark always convert; disc levels normalise to L3/4, L5/S1 (adjacent levels and the C7/T1, T12/L1, L5/S1 junctions; Deepgram's formatter glues "L3 slash 4" into "L3four"). `colon` is ':' after a heading or disc level (read across finals against the scratchpad), the organ after a modifier or before a verb, otherwise ambiguous → polish. A heading said alone is written by code ("Conclusion:"); a disc level or heading opens its own paragraph. `DEEPGRAM_SPOKEN_FORMAT=1` applies the unambiguous part at the websocket for every path; the colon rule runs in the bundle route only.

`open_line` (2026-09-27): read from the text — the statement after the last . ? ! (not a decimal point), colon or line break — instead of the line-open flag. The flag was reset by Deepgram's full stops and by every polish, so in the fragment-heavy spine session Jev got no open line on 32/32 decisions; replayed with the new rule, 22/32 carry their unfinished sentence.

**Jev sees faded finals too (2026-09-27).** Each final's faded range is tracked through later edits; its decision shows Jev everything on screen before it, including earlier finals still waiting for a polish. Before this, a polish queue (full polishes run one at a time, ~600 ms) left Jev deciding on a stale scratchpad: in the CTPA session `open_line` was set on 3/34 decisions and fragments like "Measuring" and "of the thyroid." were called noise; replayed with the new context, 20/34 carry their unfinished sentence. Racing span and fast-append placement still use the solid text.

**Word-sense spotter + fixer (2026-09-27, plan `plans/2026-09-27-jev-word-sense-spotter-fixer.md`).** Real-word mishearings ("renal glands", "supplemental emboli", "nipple effusion") passed every polish prompt tried (≤ 23/33 fixed, never those). The bundle now asks one noul per content word ("makes clinical sense as heard", commands and discourse words excluded); below 0.6 `asr_repair` proposes sound-alikes from the case lexicon (checklist sections + a broad radiology list; windows of 1–3 words, a negated form for n-sounds, never deleting words) and one chained Jev Choice picks between whole sentences with "as heard" always offered; a pick at ≥ 0.8 is applied as a plain substitution, an unfixed word below 0.35 is underlined. Offline eval, 260 finals from 12 scripted sessions: misheard 22/30 caught, 11/30 fixed to the script's word, 0 wrong fixes, 0/230 clean lines changed, 8/230 clean lines underlined; chained call on ~20 % of finals, p50 ~250 ms. Misses: real words that fit ("enhancement", "continues", "a bright", "has thickened"). Thresholds read off those sessions (QSET `2026-09-27.3`): judge on fresh ones.

**Racing with the lean scoped polish (2026-09-27, plan `plans/2026-09-27-lean-race-and-small-fixes.md`).** Lab panel → Strategy → *polish: lean span, raced with Jev* (decision-first front door, Verbatim mode). Each final fires `/bundle` and `POST /api/canvas/polish-span` together; code picks the span (last two sentences of the current line, ≤600 chars of context). Jev's route decides: fast-append / command / skip ignore the lean result; a polish route applies it to the span (+ committed edits found exactly once); otherwise the full polish runs as before (reason `…; full:<why>` in the row). Rows show `lean|full <ms> · in+out tok`; the summary reports polish time and tokens per kind. Replays: lean p50 268 ms alone, polish-routed lines ~272 ms raced vs ~650 ms (Jev then full), total prompt volume ~half of today's; the lean prompt was written on those sessions, so judge it on fresh ones (watch every correction; known misses: "Sorry that's the right kidney" not applied; a misheard correction rewriting a finding).

Same day: word-confidence gate 0.80 (QSET `2026-09-27.1`); polish tokens logged (`canvas.process … in_tokens= out_tokens=`, lab responses carry `polish_usage`); `RR_JEV_ROUTE=direct` + `JEV_API_KEY` sends Jev to TypeSafe directly (`jev-1.13.0`, ~25 ms faster p50, default stays OpenRouter pending governance); a disc level or heading that opens a paragraph gets a capital after it.

**Deepgram audit, per-case keyterms, "scratch that" (2026-09-27, plan `plans/2026-09-27-deepgram-params-keyterms-scratch.md`).** Docs audit: `nova-3-medical` + `en-GB` are current. The URL is now built in `deepgram_config.py` (tested) and gains `numerals=true` ("segment seven" → 7) and `mip_opt_out=true`; `punctuate` is dropped (`smart_format` covers it; spoken commands checked live). These three reach **production** on deploy (approved). Per-case keyterms (lab, `DEEPGRAM_CASE_KEYTERMS=1` on the backend): `POST /api/canvas/keyterms` asks the model once per case for ≤ 40 finding and descriptor terms (~1 s, cached; the schema has no `maxItems` because the model overshoots it and the provider then rejects the call → a 25 s fallback). Code filters them and merges the core list up to 50 terms and 450 tokens (Deepgram advises 20–50). The scratchpad prefetches when the scan type is set, and recording waits ≤ 1.5 s, then uses the core list. A bare "scratch that / delete that / strike that" is now route `delete` (code, no Jev): it restores what the previous utterance replaced, if untouched and not a command, with no polish pending; otherwise polish, as before. It is not logged as an `undo` outcome. "Scratch that, <content>" still goes to polish.

**Lean polish on Cerebras, pills, IntelliPrompts, Verbatim/Structured (2026-09-27).** The lab lean polish runs on Cerebras `qwen-3.8-27b` with reasoning off (Groq qwen fallback; bake-off on 167 finals, p50 311 ms). Pydantic-ai drops a top-level `reasoning_effort` and `max_completion_tokens`: pass `max_tokens` and `extra_body={"reasoning_effort": ...}`, or Cerebras runs at its default. **Production Cerebras gpt-oss roles still pass the dropped form: unchecked.** IntelliPrompts (production, approved) moved to Cerebras qwen-3.8 with reasoning off: with reasoning on, every structured answer failed and the fallback took 35–137 s. `/review` takes `parts=coverage|prompts`, so the section pills no longer wait for IntelliPrompts. The lab backend now starts with `RR_COVERAGE_CANDIDATE=jev` (pills 265 ms p50 vs Qwen 1.4 s). Verbatim and Structured are two stored views (plan `plans/2026-09-27-verbatim-structured-views.md`): verbatim is the source and structured is derived by `/process`; switching never re-polishes.

Lab backend command now: `RR_TRIAGE_DEBUG=1 RR_COVERAGE_CANDIDATE=jev DEEPGRAM_DICTATION=0 DEEPGRAM_UK_SPELLING=1 DEEPGRAM_SPOKEN_FORMAT=1 DEEPGRAM_CASE_KEYTERMS=1 …uvicorn rapid_reports_ai.main:app --port 8000`.

**Audio capture and review (2026-09-29).** With `RR_LAB_AUDIO_CAPTURE=1` (and `RR_TRIAGE_DEBUG=1`, PCM), each dictation session saves the audio sent to Deepgram and every Deepgram message (interim and final, with word timings) to `backend/.lab_audio/session-<utc>/` (git-ignored, local only; `lab_audio.py`). `python -m rapid_reports_ai.scripts.lab_audio_review [dir] [--export lab-session.json]` re-transcribes the WAV with Deepgram batch (same model, keyterms and UK spelling) and prints, per final: the stream's text, where it differed from the batch pass, how long after speech ended it arrived, and the decision it got, plus the pauses and where the stream cut its finals. When batch and stream agree on a wrong word, the audio or pronunciation is at fault, not streaming. The export also records `wait_ms` and `final_to_solid_ms` per decision.

Known limits: manual edits made while a polish is running are overwritten by it (same as today's path); undo is one step, and only while the range is untouched; `ignore_noise` goes to polish; `standalone` sits just under 0.5 on complete statements (live smoke 0.47–0.48), so expect `⏎ hard_limit` more than `⏎ standalone` on unpunctuated lines.

## 6. Outstanding / next steps — follow decision-first **rev 2**

> **2026-09-26: the working sequence is now `docs/superpowers/plans/2026-09-26-jev-work-order.md`** (15 steps from the Jev field research, `docs/superpowers/research/2026-09-26-jev-field-research.md`). It folds in the items below and adds shared client, calibration metrics, question registry, governance before shadow, and interim-transcript commands. Update its status column as steps land.

The architecture spec was rewritten as rev 2 after this handover (`c12f801`). It retires the front door's complete/continues trigger, the backstop timers and the `placement` question; the front-door spec carries a superseded note. **Do not resume timer or placement tuning.** Build order and exit criteria: rev 2 §4; first experiments: rev 2 §7; when to chain Jev calls: rev 2 §6.

1. **Production shadow** (component 0): set `RR_TRIAGE_SHADOW=1` on Railway; summarise with `scripts/triage_shadow_report.py` after a week. The action mix and confidence distribution set the bands.
2. **Done 2026-09-24** (§3 table). **Baselines in every bake-off:** add a plain-code (regex/lexicon) column and 95 % intervals to the triage, coverage and boundary scripts. A quick regex scored 0.816 vs Jev 0.868 on boundary.
3. **Done 2026-09-24 — PASS** (§3; not wired into routes, first consumer is component 2). **One bundle per utterance** (component 1): merge the triage, boundary (`standalone` only) and coverage question sets into one call; confirm per-question parity and p95 < 500 ms.
4. **Fast-append + band router** (component 2): offline replay of lab-exported sessions first — polish calls saved, and every correction/ASR case that would have passed verbatim.
5. **Coverage on Jev per utterance** (component 3): section nouls on the utterance, static collective → section map in code; flip `RR_COVERAGE_CANDIDATE=jev` when recall ≥ Qwen's.
6. **ASR-repair chain** (rev 2 §6.2 A): gate on Deepgram per-word confidence (currently unused), `asr_sense` noul, phonetic candidates from the scan-type keyterms, Jev choice with an "as heard" option. Test set: the four sessions' known errors plus clean controls.
7. **Correction chain** (rev 2 §6.2 C): add target-line and kind labels to `triage_utterances.jsonl`.
8. **Relabel fixtures by what the system should do**, not grammar; keep growing all sets via the lab export buttons.
9. Later: IntelliPrompts as retrieval (largest measured dictation latency, 2.8–6 s), app commands, audit screen → locate, generation plan as decisions.

## 7. Jev wire contract (so nobody rediscovers it)

Body `{model:"typesafe/jev-1.13", state:<json>, questions:{id:q}}`. `choice` takes `criteria` as a **map** option→description (not an `options` list); `noul` takes `instructions` (+ optional `criteria:{true,false}`); `score` takes `criteria:[levels]`. Answers: `choice/confidence/probabilities`, `noul` 0–1, `score/confidence/probabilities/legend`. Many questions per call, evaluated in parallel. Pin `jev-1.13`. Memory note: `~/.claude/projects/-Users-hassan-Code-rapid-reports-ai/memory/reference_jev_system_one_api.md`, `project_dictation_triage_lab.md`.
