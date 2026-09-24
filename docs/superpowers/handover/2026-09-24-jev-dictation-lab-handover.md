# Handover — Jev (System 1) dictation work, 2026-09-24

**Branch:** `dictation-triage-lab`, worktree `.claude/worktrees/dictation-triage-lab` (from `skill-sheet-v3` head; ~55 commits; tree clean). Not merged. Production unchanged: every new path is env-gated and off by default.

## 1. Intent

Replace generation with typed decisions wherever a pipeline step is really a *choice*. Jev 1.13 (TypeSafe, via OpenRouter `POST /api/v1/systemone`, ~300 ms, $0.04/M in) returns calibrated probabilities for Choice / Score / Noul questions over a JSON state; no prose. The language model (Qwen 27B on Cerebras/Groq) runs only when prose is needed. The scratchpad is **capture**, not the report: snappy, fidelity-preserving, fillers cut; heavy formatting belongs to report generation.

Architecture spec (the map for everything below): `docs/superpowers/specs/2026-09-24-decision-first-dictation-design.md` — one decision bundle per utterance, nine components in build order, invariants (thresholds in code; shadow → lab routing → prod behind env; log data never text; fixtures grow from the lab).

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

## 6. Outstanding / next steps (in the order I'd take them)

1. **Read the next mic run** with the punctuation + standalone rules: expect "(punct.)" completes, "silence 2s → complete" rows, few/no hard limits. If sentences still split, the remaining lever is Deepgram `endpointing` (200 ms) now that the faded render hides waits.
2. **Placement:** give the question the checklist pills as its region vocabulary (new_paragraph = different section from the last line); skip it when action triage says correction; derive at sentence level. Then decide whether to *act* on it (verbatim append to the chosen place = component #2 "fast-append").
3. **ASR-risk:** try the relative rule on the four sessions' data; tighten the criteria (phonetic-neighbour requirement); then the fast-append spec can gate on it.
4. **Coverage recall on collectives** (sharpen the group-membership sentence; more collective fixtures from lab exports) → flip `RR_COVERAGE_CANDIDATE=jev` in prod when recall ≥ Qwen's.
5. **Relabel** disputed boundary fixtures (`cnt-01/02/11`: grammatically complete clauses → complete); keep growing all three fixture sets via the lab export buttons.
6. **Stop-flush waste:** in front-door mode, the stop-recording flush should only polish when something is buffered or the transcript changed.
7. **Production shadow** for action triage: set `RR_TRIAGE_SHADOW=1` on Railway; summarise with `scripts/triage_shadow_report.py` (log-only, no text).
8. Later components per the architecture spec: correction kind/target, app commands, integrity Nouls, IntelliPrompts as retrieval, audit pre-screen, generation plan as decisions.

## 7. Jev wire contract (so nobody rediscovers it)

Body `{model:"typesafe/jev-1.13", state:<json>, questions:{id:q}}`. `choice` takes `criteria` as a **map** option→description (not an `options` list); `noul` takes `instructions` (+ optional `criteria:{true,false}`); `score` takes `criteria:[levels]`. Answers: `choice/confidence/probabilities`, `noul` 0–1, `score/confidence/probabilities/legend`. Many questions per call, evaluated in parallel. Pin `jev-1.13`. Memory note: `~/.claude/projects/-Users-hassan-Code-rapid-reports-ai/memory/reference_jev_system_one_api.md`, `project_dictation_triage_lab.md`.
