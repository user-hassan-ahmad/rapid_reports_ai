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
RR_TRIAGE_DEBUG=1 DEEPGRAM_DICTATION=0 PYTHONPATH=src <main>/backend/.venv/bin/uvicorn rapid_reports_ai.main:app --port 8000
# frontend (worktree/frontend)   bun run dev      → sign in, open /dictation-lab
# in the tab: localStorage rr_incremental=1 (faded optimistic render), Strategy → front door = Jev boundary
# bake-offs: PYTHONPATH=src python -c "from dotenv import load_dotenv; load_dotenv('.env'); import runpy; runpy.run_module('rapid_reports_ai.scripts.boundary_bakeoff', run_name='__main__')"
```

## 6. Outstanding / next steps — follow decision-first **rev 2**

The architecture spec was rewritten as rev 2 after this handover (`c12f801`). It retires the front door's complete/continues trigger, the backstop timers and the `placement` question; the front-door spec carries a superseded note. **Do not resume timer or placement tuning.** Build order and exit criteria: rev 2 §4; first experiments: rev 2 §7; when to chain Jev calls: rev 2 §6.

1. **Production shadow** (component 0): set `RR_TRIAGE_SHADOW=1` on Railway; summarise with `scripts/triage_shadow_report.py` after a week. The action mix and confidence distribution set the bands.
2. **Baselines in every bake-off:** add a plain-code (regex/lexicon) column and 95 % intervals to the triage, coverage and boundary scripts. A quick regex scored 0.816 vs Jev 0.868 on boundary.
3. **One bundle per utterance** (component 1): merge the triage, boundary (`standalone` only) and coverage question sets into one call; confirm per-question parity and p95 < 500 ms.
4. **Fast-append + band router** (component 2): offline replay of lab-exported sessions first — polish calls saved, and every correction/ASR case that would have passed verbatim.
5. **Coverage on Jev per utterance** (component 3): section nouls on the utterance, static collective → section map in code; flip `RR_COVERAGE_CANDIDATE=jev` when recall ≥ Qwen's.
6. **ASR-repair chain** (rev 2 §6.2 A): gate on Deepgram per-word confidence (currently unused), `asr_sense` noul, phonetic candidates from the scan-type keyterms, Jev choice with an "as heard" option. Test set: the four sessions' known errors plus clean controls.
7. **Correction chain** (rev 2 §6.2 C): add target-line and kind labels to `triage_utterances.jsonl`.
8. **Relabel fixtures by what the system should do**, not grammar; keep growing all sets via the lab export buttons.
9. Later: IntelliPrompts as retrieval (largest measured dictation latency, 2.8–6 s), app commands, audit screen → locate, generation plan as decisions.

## 7. Jev wire contract (so nobody rediscovers it)

Body `{model:"typesafe/jev-1.13", state:<json>, questions:{id:q}}`. `choice` takes `criteria` as a **map** option→description (not an `options` list); `noul` takes `instructions` (+ optional `criteria:{true,false}`); `score` takes `criteria:[levels]`. Answers: `choice/confidence/probabilities`, `noul` 0–1, `score/confidence/probabilities/legend`. Many questions per call, evaluated in parallel. Pin `jev-1.13`. Memory note: `~/.claude/projects/-Users-hassan-Code-rapid-reports-ai/memory/reference_jev_system_one_api.md`, `project_dictation_triage_lab.md`.
