# Jev Phase A (work order steps 1–3) Implementation Plan

> **For agentic workers:** executed inline with superpowers:executing-plans; TDD per task; commit after each task.

**Goal:** Make the Jev numbers true: one keep-alive client (D-01), calibration metrics with a Qwen-off contrast (D-03), one versioned question registry logged with every decision (D-10).

**Architecture:** A small `jev_client.py` owns the one shared `httpx.AsyncClient` (per event loop), the warm-up call and the close hook; the four Jev callers post through it and keep their injectable transport for tests. Calibration is pure functions in `scripts/bakeoff_stats.py`; Qwen-off gets a probability via Cerebras first-token logprobs in an eval-only `scripts/qwen_logprob.py`. `jev_questions.py` holds every question, criteria map and threshold plus `QSET_VERSION`; the old modules re-export, and a digest test proves the move changed no byte of wording.

**Tech stack:** Python 3, httpx 0.28 (no h2 installed → HTTP/1.1 keep-alive), FastAPI lifespan, pytest. Run with `PYTHONPATH=src <main>/backend/.venv/bin/python` from `worktree/backend`.

**Standing rules (work order):** wording and lexicon frozen; production unchanged (all new behaviour env-gated, off by default); every number with a plain-code baseline where one applies and a 95 % interval; failures reported plainly.

**Found while reading:** there are *four* per-request clients, not three: `utterance_boundary.py:149` too. All four move. Groq `qwen/qwen3.6-27b` (the shipped Qwen-off) rejects `logprobs`; Cerebras `qwen-3.8-27b` with `reasoning_effort: none` returns top-logprobs (probed 2026-09-26).

---

## Step 1 — D-01 shared client

### Task 1: `jev_client.py`

**Files:** create `backend/src/rapid_reports_ai/jev_client.py`, test `backend/tests/test_jev_client.py`.

API:
- `async def jev_post(body, api_key, timeout_s, transport=None) -> httpx.Response`. With `transport`: a per-call client on that transport (tests, unchanged behaviour). Without: the shared client, `timeout=timeout_s` per request. With `RR_JEV_FRESH_CLIENT=1` (measurement only): a new client per call, the pre-D-01 behaviour.
- `def shared_client() -> httpx.AsyncClient`: one per running event loop (rebuilt if the loop changed, so scripts and pytest loops never share a dead client). Limits: keep-alive 20 connections, keep-alive expiry 60 s.
- `async def warm_up(api_key=None) -> int | None`: one minimal Jev call (one noul on a one-word state); returns ms, `None` on any failure; never raises.
- `def warmup_wanted() -> bool`: True only when a Jev path is on (`RR_TRIAGE_DEBUG=1`, `RR_TRIAGE_SHADOW=1` or `RR_COVERAGE_CANDIDATE=jev`) and `OPENROUTER_API_KEY` is set.
- `def schedule_warm_up() -> asyncio.Task | None`: fire-and-forget if wanted, holds a reference to the task.
- `async def aclose() -> None`: closes the shared client.

Tests (MockTransport patched into the shared builder): the same client is returned twice in one loop; a new loop gets a new client; `jev_post` without transport reuses it (one construction for two posts); with transport uses that transport; fresh flag constructs per call; `warm_up` returns None on HTTP 500 and on a transport error; `warmup_wanted` false with no flags / with flag but no key, true for each flag; `schedule_warm_up` returns None when not wanted.

### Task 2: route the four callers through `jev_post`

**Files:** modify `dictation_triage.py`, `utterance_bundle.py`, `section_coverage.py`, `utterance_boundary.py`. Replace each `async with httpx.AsyncClient(...)` block with `resp = await jev_post(body, self._api_key, self._timeout_s, self._transport)`; error strings unchanged. Test: a new test per module is unnecessary; add one test in `test_jev_client.py` that constructs each of the four classes without transport, patches the shared builder with a MockTransport returning a valid answer for that class, calls classify twice, and asserts one client construction. Existing 391 tests stay green.

### Task 3: lifecycle

**Files:** modify `main.py` lifespan (after `yield`: `await jev_client.aclose()`), `/api/transcribe` websocket right after `accept()`: `jev_client.schedule_warm_up()`. No behaviour when flags are off (covered by Task 1 tests).

### Task 4: measure

**Files:** create `backend/src/rapid_reports_ai/scripts/jev_latency_ab.py` (pure `summarise_arms(arms) -> dict` tested in `tests/test_jev_latency_ab.py`: p50, p95, bootstrap 95 % CI for both, n per arm).
- Arms interleaved per iteration with alternating order, same real bundle bodies (from the parity fixtures): `fresh` (new client per call, pre-D-01) vs `shared` (warm pool). `cold`: new client + first call, spaced 3 s apart, n=20.
- Bundle parity twice, back to back: `RR_JEV_FRESH_CLIENT=1` (before) then default (after). Report bundle and separate p50/p95 with bootstrap intervals; verdict unchanged.
- Results: `docs/model-migration/jev-client-latency-2026-09-26.json`.

## Step 2 — D-03 calibration

### Task 5: pure calibration functions in `bakeoff_stats.py`

Tests first in `tests/test_bakeoff_stats.py`, hand-computed values:
- `brier(p, y) -> float` — binary, mean (p − y)².
- `brier_multiclass(probs: list[dict], labels: list[str]) -> float` — mean Σₖ(pₖ − 1[k=label])², range 0–2; missing classes count as 0.
- `reliability_table(p, y, n_bins=10) -> list[dict]` — equal-width bins, last bin closed at 1.0; each `{lo, hi, n, mean_p, freq}` (`mean_p`/`freq` None when n=0).
- `ece(p, y, n_bins=10) -> float` — Σ nᵦ/N · |mean_pᵦ − freqᵦ|.
- `bootstrap_stat_ci(items, stat, groups=None, n_boot=2000, seed=0) -> (lo, hi)` — percentile; resamples groups (cases) when given.
- `paired_bootstrap_diff_ci(a, b, stat, groups=None, ...) -> (diff, lo, hi)` — same resampled indices for both.
- `fmt_reliability(table) -> str`.

Convention: a choice question enters as top-label pairs (p = confidence of the chosen option, y = chosen is right) for ECE/reliability and as full distributions for multiclass Brier; a noul enters as (p(true), label).

### Task 6: Qwen-off with probabilities, eval only

**Files:** create `scripts/qwen_logprob.py`, test `tests/test_qwen_logprob.py`.
- Same inputs as Jev: the state JSON Jev receives is the user message; the question's own `instructions` and `criteria` texts are imported from where they live (no copy, no rewording).
- Choice: options numbered `1..k` (`N. name: description`), "Reply with the option number only." Noul: the statement plus its criteria when present, "Reply yes if the statement is true of the state, no otherwise. One word."
- Call Cerebras `qwen-3.8-27b`, `reasoning_effort: none`, `temperature 0`, `max_completion_tokens 3`, `logprobs true`, `top_logprobs 10`.
- Pure `choice_probs(top_logprobs, options) -> dict` and `noul_prob(top_logprobs) -> float`: sum exp over tokens that match after strip/lowercase, renormalise over valid answers; raise on zero valid mass.
- Reported as **qwen-lp**, next to the shipped **qwen** (Groq qwen3.6, hard labels, entered as p ∈ {0, 1}). Different model version and provider from the shipped candidate; stated in every output.

### Task 7: print calibration in the three bake-offs

**Files:** create pure `scripts/calibration_report.py` (`calibration_block(question, by_candidate) -> (dict, str)` with n, accuracy, Brier (+CI), ECE (+CI), reliability table, and the paired Jev − other difference with CI), test `tests/test_calibration_report.py`. Wire into `triage_bakeoff.py` (action, is_correction, needs_committed_edit), `coverage_bakeoff.py` (section noul, groups = case), `boundary_bakeoff.py` (boundary, standalone, asr_risk; Jev + qwen-lp; no shipped Qwen boundary candidate exists).

### Task 8: run all three live, write the verdict

Verdict rule, fixed before the run: per question, "Jev better calibrated" only if the paired 95 % interval of Jev − qwen-lp excludes 0 in Jev's favour on Brier **and** ECE does not favour qwen-lp with an interval excluding 0. Anything else: "not shown on this data", said plainly. Results in `docs/model-migration/calibration-2026-09-26.json` and handover §3.

## Step 3 — D-10 question registry

### Task 9: registry by move

1. **First** add `tests/test_jev_questions.py::test_qset_digest_pins_wording` computing a sha256 over canonical JSON of: `TRIAGE_QUESTIONS`, `BOUNDARY_QUESTIONS`, `STANDALONE_QUESTION`, `COVERAGE_CRITERIA`, `coverage_questions(["X"])`, `bundle_questions(["X","Y"])` and the thresholds, imported from the *current* modules, and record the digest. Green at HEAD.
2. Create `jev_questions.py` holding `QSET_VERSION = "2026-09-26.1"`, `JEV_MODEL`, all of the above, `BINARY_THRESHOLD`, `COMPLETE_THRESHOLD`, `COMMAND_THRESHOLD`, `ASR_RISK_THRESHOLD`, `PLACEMENT_THRESHOLD`, `ROUTE_THRESHOLD_DEFAULT = 0.9`. Old modules import and re-export; `TriageRouteConfig.threshold` defaults to `ROUTE_THRESHOLD_DEFAULT`. Switch the digest test to import from the registry: same digest = pure move. A second test asserts the old names are the same objects as the registry's.

### Task 10: log version + probabilities with every decision

- Shadow line (`canvas.triage.shadow`): add `"qset"`; Jev slot already carries `probabilities`, nouls are single floats.
- Route mode: a JSON `canvas.triage.route` line with qset, action, confidence, probabilities, nouls (no text).
- Coverage (`/review`, Jev selected or debug): JSON `canvas.coverage.decision` with qset, candidate, scores.
- Utterance (`/utterance`): JSON `canvas.utterance.decision` with qset, boundary probabilities, standalone, asr_risk, placement probabilities.
- Traces (`TriageTrace`, `CoverageTrace`, `UtteranceResponse`) and `BundleDecision` gain `qset`.
Tests: the shadow test asserts `qset` and `probabilities` in the logged JSON; route/coverage/utterance tests assert the qset line.

### Task 11: parity must still PASS

Rerun bundle parity after the move. Wording digest unchanged is the proof; parity is the live check.

### Task 12: docs

Work order status → done with numbers (steps 1–3); handover §3; state which of step 4 and S1/S2 are unblocked; memory note.
