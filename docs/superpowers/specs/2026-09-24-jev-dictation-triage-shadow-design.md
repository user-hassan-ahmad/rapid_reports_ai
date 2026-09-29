# Dictation Utterance Triage — System 1 Pilot with a Local Dictation Lab (Jev vs Qwen reasoning-off)

> **Retired 2026-09-29.** The shadow, debug and route modes, the Qwen candidate, the labels module and the fixture endpoint were removed after the decision-first package shipped (`rr_dictation_v2`). `JevTriager`, the formatting lexicon and the triage fixtures (routing eval set) remain. Kept as a historical record.

**Date:** 2026-09-24
**Status:** Implemented on branch `dictation-triage-lab`; bake-off run 1 and run 2 recorded in §12; in-browser lab smoke pending sign-in
**Branch:** skill-sheet-v3 (spec only; implementation on its own branch)
**Fills:** Dictation program Phase 3 slots §7.5 "Triage front-door" and §7.6 "Model router" (see `2026-08-09-dictation-fidelity-and-orchestration-design.md`)

## 1. Problem

Every dictation utterance goes through the same full-cost canvas process call: the whole session transcript plus scratchpad is sent to Qwen 27B (Cerebras, `reasoning_effort: low`) and the active zone is regenerated. A formatting command ("new paragraph"), a delete ("scratch that"), filler ("um so er"), and a substantive correction all pay the same latency. The August spec reserved a Phase 3 triage front-door to classify each utterance before deciding how much model to spend on it, but never specified what would do the classifying.

Two candidates now exist for a "System 1" classifier — one that returns a typed decision, not prose:

- **Jev 1.13** (TypeSafe, via OpenRouter's System One endpoint): a purpose-built decision model. Typed `Choice` / `Score` / `Noul` questions over a JSON state; returns probabilities and a calibrated confidence. $0.042 per 1M input tokens, output free, 32K context, ~0.3 s round trip measured from this machine.
- **Qwen 27B with reasoning off** (already in production on Cerebras): the same model as the live path, asked a structured question with a tiny output schema and `reasoning_effort: none`.

We do not know which is accurate enough on radiology dictation, how well Jev's confidence is calibrated on our data, or whether Qwen-off is fast enough to make a new vendor unnecessary. We also have no fast local loop for iterating on the dictation flow: the only way to exercise the production dictation UI is the home page against a running backend, with a microphone, one utterance at a time.

This pilot delivers three things: the two triage candidates behind one interface; a **Dictation Lab** — a gated dev route that mounts the real production dictation UI beside an instrumentation panel with a scripted utterance feeder and per-utterance triage traces; and a **gated routing experiment mode** so the fast path can be felt in the browser before any production routing is specified. Production traffic sees at most a log-only shadow.

## 2. Evidence so far (2026-09-24 probes, synthetic text, OpenRouter key)

Jev, one Choice + two Nouls per call, state = `{committed, active, latest_utterance}`:

| Utterance | Jev action | Confidence | Latency |
|---|---|---|---|
| actually make that the left upper lobe | correct_previous_finding | 1.00 | 0.24 s |
| scratch that | delete_previous_utterance | 0.97 | 0.36 s |
| new paragraph | formatting_command | 1.00 | 0.30 s |
| no pleural effusion no pneumothorax | append_new_finding | 0.99 | 0.27 s |
| um so er let me see | ignore_noise | 1.00 | 0.32 s |
| change the liver lesion to say hepatic haemangioma | correct_previous_finding; needs_committed_edit 0.89 | 1.00 | 0.28 s |
| it was five millimetres on the prior now ten millimetres | correct_previous_finding | **0.72** | 0.28 s |
| there is a six millimetre nodule in the right upper lobe (already in active) | append 0.37 / correct 0.34 / noise 0.27 | **0.21** | 0.27 s |

The two low-confidence rows are the design signal: a temporal comparison (our canvas prompt says "keep both") and a restatement of a finding already captured. Both are cases a threshold should hand to System 2. The restatement case motivates a dedicated `restate_existing_finding` option.

Request shape notes (learned the hard way): endpoint is `POST https://openrouter.ai/api/v1/systemone`, bearer = `OPENROUTER_API_KEY`, body `{model, state, questions}`. A `choice` question takes `criteria` as a map `{option: description}`, not an `options` list. `noul` takes `instructions` and optional `criteria: {true, false}`. Response `answers[id]` carries `type`, and per type `choice`/`confidence`/`probabilities`, `score`/`confidence`/`probabilities`/`legend`, or `noul` (a 0–1 float, no confidence).

## 3. Goals / Non-goals

### Goals
- Classify each utterance into a fixed action set with two auxiliary yes/no signals, using two interchangeable System 1 candidates behind one interface.
- A **Dictation Lab** dev route that reuses the production dictation components unchanged (no fork), adds a scripted utterance feeder, and shows a per-utterance trace of live-path latency, derived label, and both candidates' decisions.
- A **routing experiment mode**, honoured only when a backend env flag is set, in which the selected candidate's decision above a chosen confidence threshold short-circuits the live model for the deterministic classes.
- A production **shadow** mode (separate env flag): zero added latency, zero behaviour change, one structured log line per call.
- A hand-labelled fixture set (grown from lab sessions with one click) and a bake-off script that reports accuracy, confusion, latency, cost, and Jev confidence calibration per candidate.
- Exit criteria that would justify a production routing spec.

### Non-goals
- Production routing. Routing is lab-only in this pilot; `RR_TRIAGE_DEBUG` is never set in production.
- Verbatim fast-append (skipping the model for `append_new_finding`). It forfeits homophone correction and consolidation; it is a later strategy once the classifier is trusted.
- The audit pre-screen and the coverage-checklist swap. Each gets its own spec if this pilot passes.
- Fixing the dead tier-2 semantic check (`dictation_semantic`). Separate defect, already tracked.
- Mounting the copilot sidebar (`ReportEnhancementSidebar`) in the lab. The lab targets the dictation loop; the sidebar is post-generation editing and can be added to the lab page later without touching this design.
- A persisted shadow table / Metabase card. Logs first; a table is a follow-up if the data proves useful (migrations are gated in this repo).
- Adopting the TypeSafe SDK. A ~30-line client is enough and avoids a dependency on an alpha SDK.

## 4. Architecture

```
/dictation-lab (+page.ts: requireDevRoute)            production home page (unchanged)
  ├─ <IntelliDictateTab>  ── real component ──┐          └─ <IntelliDictateTab> (no lab props)
  │     └─ <DictationScratchpad>              │
  │           mic → ws /api/transcribe ─┐     │
  │           injectTranscript(text) ───┴─ handleFinalTranscript() ─ processTranscriptQueue()
  │                                              │
  │                          POST /api/canvas/process { ..., last_utterance, triage_debug, triage_route }
  └─ <DictationLabPanel>  ◄── onProcessTrace ────┘
        feeder · strategy · threshold · timeline · export-as-fixture

backend process_transcript
  ├─ lab routing  (RR_TRIAGE_DEBUG=1 and triage_route):  triage(selected) → deterministic handler | live model
  ├─ lab debug    (RR_TRIAGE_DEBUG=1 and triage_debug):  gather(live, jev, qwen) → response.triage
  ├─ shadow       (RR_TRIAGE_SHADOW=1 and last_utterance): live → BackgroundTasks(jev, qwen, derive, log)
  └─ default:     live model only (identical to today)
```

The three backend modes are independent flags. Production sets neither debug flag; shadow is the only mode that can run there.

## 5. Components

### 5.1 `src/rapid_reports_ai/dictation_triage.py` (new)

```python
TriageAction = Literal[
    "append_new_finding",        # new observation or normality claim not yet captured
    "correct_previous_finding",  # revises / replaces / retracts a value already captured
    "restate_existing_finding",  # repeats something already captured; no change needed
    "delete_previous_utterance", # "scratch that", "delete that" — remove the preceding statement
    "formatting_command",        # new line, new paragraph, full stop, etc.
    "ignore_noise",              # filler, hesitation, thinking aloud
]

@dataclass(frozen=True)
class TriageState:
    committed: str          # frozen zone (may be "")
    active: str             # active zone before this utterance
    latest_utterance: str
    scan_type: str = ""

@dataclass(frozen=True)
class TriageDecision:
    candidate: Literal["jev", "qwen"]
    action: TriageAction
    confidence: float | None          # Jev: calibrated confidence; Qwen: None
    probabilities: dict[str, float] | None
    is_correction: float | None       # 0–1; Qwen reports 0.0/1.0
    needs_committed_edit: float | None
    latency_ms: int
    input_tokens: int | None
    cost_usd: float | None

class Triager(Protocol):
    name: str
    async def classify(self, state: TriageState) -> TriageDecision: ...
```

**`JevTriager`**
- `httpx.AsyncClient`, `POST https://openrouter.ai/api/v1/systemone`, `Authorization: Bearer $OPENROUTER_API_KEY`, timeout 3.0 s total.
- Model id constant `JEV_MODEL = "typesafe/jev-1.13"` (pinned; `jev-latest` is a redirect and would silently change behaviour mid-pilot).
- State sent as a JSON object with keys `committed`, `active`, `latest_utterance`, `scan_type`.
- `TRIAGE_QUESTIONS` is a module constant: one `choice` question `action` whose `criteria` map is the six actions with one-sentence descriptions (as in the probe), plus two `noul` questions `is_correction` and `needs_committed_edit`.
- Validation: non-2xx → raise; missing answer id → raise; `choice` not in the action set → raise; any probability or noul outside [0, 1] → raise. A broken decision must never look like a valid one.
- Reads `usage.input_tokens` and `usage.cost` when present.

**`QwenTriager`**
- Calls `enhancement_utils._run_agent_with_model` with `model_name=MODEL_CONFIG["CANVAS_PROCESS"]`, `output_type=QwenTriageOutput`, `use_thinking=False`.
- `QwenTriageOutput(BaseModel)`: `action: TriageAction`, `is_correction: bool`, `needs_committed_edit: bool`. Nothing else, so the schema cannot invite prose.
- Settings: temperature 0.0, `max_completion_tokens` 120, reasoning **off** via `extra_body: {"reasoning_effort": "none"}` in the Cerebras form. Settings are passed through `canvas_routes._adapt_canvas_settings` so the Groq fallback shape stays correct if the config entry moves provider (ledger L-34 / provider-map comment at `enhancement_utils.py:251`).
- System prompt: the same six action definitions, verbatim from `TRIAGE_QUESTIONS`, so both candidates answer an identical question. User prompt: the four state fields, labelled.
- `confidence`, `probabilities`, `cost_usd` are `None`; `is_correction` / `needs_committed_edit` are 0.0 or 1.0.
- Timeout 8.0 s.

`get_triager(name)` returns the singleton for `"jev"` or `"qwen"`; `run_both(state)` runs them with `asyncio.gather(return_exceptions=True)` and returns `dict[name, TriageDecision | Exception]`.

### 5.2 `src/rapid_reports_ai/dictation_triage_labels.py` (new)

```python
DerivedAction = Literal["append", "correct", "delete", "noop", "committed_edit"]

def derive_action(before_active: str, after_active: str, committed_edits: list[tuple[str, str]]) -> DerivedAction
```

Pure, deterministic, line-based (the scratchpad is one finding per line):
1. `committed_edits` non-empty → `committed_edit`.
2. Normalised `before == after` → `noop`.
3. `after` lines ⊇ `before` lines and `len(after) > len(before)` → `append`.
4. `len(after) < len(before)` → `delete`.
5. Otherwise → `correct`.

Normalisation: strip, collapse internal whitespace, drop blank lines, case-fold.

`AGREEMENT_MAP` from `TriageAction` to the `DerivedAction`s it agrees with:

| TriageAction | agrees with |
|---|---|
| append_new_finding | append |
| correct_previous_finding | correct, committed_edit |
| restate_existing_finding | noop, correct |
| delete_previous_utterance | delete |
| formatting_command | noop, append |
| ignore_noise | noop |

`needs_committed_edit` agrees when `(value >= 0.5) == (derived == "committed_edit")`. The map is lenient by design; the fixture set carries precise labels.

### 5.3 `src/rapid_reports_ai/dictation_triage_router.py` (new) — lab routing

```python
DETERMINISTIC_ACTIONS = {"formatting_command", "delete_previous_utterance", "ignore_noise", "restate_existing_finding"}

def apply_deterministic(action: TriageAction, state: TriageState) -> str | None:
    """New active text, or None to fall through to the live model."""
```

- `formatting_command`: map the utterance through the same command lexicon as `main.process_dictation_transcript` (new line → `\n`, new paragraph → `\n\n`, full stop → `.`); if the mapped text is non-empty, append it to `active`; otherwise return `active` unchanged. Never calls the model.
- `ignore_noise`, `restate_existing_finding`: return `active` unchanged.
- `delete_previous_utterance`: remove the last non-blank line of `active`; if `active` has no non-blank line, return `None` (the target may be in the committed zone, which only the live model may edit).
- `append_new_finding`, `correct_previous_finding`: return `None`.

```python
def route(decision: TriageDecision, threshold: float, state: TriageState) -> tuple[Literal["deterministic", "model"], str | None]
```
Deterministic only when `decision.action in DETERMINISTIC_ACTIONS` and `(decision.confidence if decision.confidence is not None else 1.0) >= threshold` and `apply_deterministic(...)` is not `None`. Qwen carries no confidence, so its deterministic decisions always route when selected — measuring the consequence of that is part of the experiment.

### 5.4 Request, response and route changes (`canvas_routes.py`)

```python
class TriageRouteConfig(BaseModel):
    candidate: Literal["jev", "qwen"]
    threshold: float = Field(0.9, ge=0.0, le=1.0)

class CanvasProcessRequest(BaseModel):
    ...
    last_utterance: str | None = None     # trimmed transcript delta since the previous call
    triage_debug: bool = False            # lab: attach both candidates' decisions (RR_TRIAGE_DEBUG=1 only)
    triage_route: TriageRouteConfig | None = None   # lab: act on triage (RR_TRIAGE_DEBUG=1 only)
```

Both response models gain `triage: TriageTrace | None = None`:

```python
class TriageCandidateTrace(BaseModel):
    action: TriageAction | None; confidence: float | None; probabilities: dict[str, float] | None
    is_correction: float | None; needs_committed_edit: float | None
    latency_ms: int | None; input_tokens: int | None; cost_usd: float | None; error: str | None

class TriageTrace(BaseModel):
    mode: Literal["debug", "route"]
    derived: DerivedAction | None            # debug: label from live before/after; route: None when deterministic
    routed: Literal["deterministic", "model"] | None
    routed_by: Literal["jev", "qwen"] | None
    live_latency_ms: int | None
    jev: TriageCandidateTrace | None
    qwen: TriageCandidateTrace | None
```

`process_transcript` flow, in order:

1. `lab = _triage_debug_enabled() and request.last_utterance` (env `RR_TRIAGE_DEBUG == "1"` read once at import, plus key presence).
2. **Route mode** (`lab and request.triage_route`): await the selected triager; on success call `route(...)`. If deterministic, build the response with the new active text (incremental: `active_scratchpad`, `committed_edits=[]`; full: `scratchpad`), `triage.mode="route"`, `routed="deterministic"`, and return without calling the live model. Otherwise fall through to step 3 with the decision kept for the trace. A triager exception falls through to the live model and is recorded in the trace.
3. **Live call** exactly as today. In **debug mode** (`lab and request.triage_debug`, and not already routed deterministically) both triagers run under the same `asyncio.gather` as the live call, so the response waits for `max(live, jev, qwen)`; Jev's 0.3 s hides inside the live call. The trace then carries both candidates, `derived` from before/after, and `live_latency_ms`.
4. **Shadow** (`_triage_shadow_enabled() and request.last_utterance`, env `RR_TRIAGE_SHADOW == "1"`): after the live result exists (including the fallback-return path), `_shadow_triage(...)` is scheduled with FastAPI `BackgroundTasks` (runs after the response is sent; a bare `asyncio.create_task` would be unreferenced and could be garbage-collected), and it runs both candidates, derives the label, and logs one JSON line:

```json
{"event": "canvas.triage.shadow", "mode": "clean", "incremental": true,
 "utterance_len": 41, "utterance_sha8": "3f9a1c2b", "derived": "correct",
 "jev": {"action": "correct_previous_finding", "confidence": 0.97, "is_correction": 0.94,
         "needs_committed_edit": 0.03, "latency_ms": 262, "input_tokens": 578, "cost_usd": 2.4e-05,
         "agrees": true, "error": null},
 "qwen": {"action": "correct_previous_finding", "confidence": null, "is_correction": 1.0,
          "needs_committed_edit": 0.0, "latency_ms": 640, "input_tokens": null, "cost_usd": null,
          "agrees": true, "error": null}}
```

The utterance text is **not** logged (length + 8-char SHA-256 prefix only); the scratchpad is not logged. Shadow and debug are not run together for one request (debug already produced the decisions; the lab panel is the sink). Without `RR_TRIAGE_DEBUG`, `triage_debug` and `triage_route` are ignored and `triage` is `None` — the response is byte-identical to today.

### 5.5 Frontend: production components (small, backward-compatible edits)

**`DictationScratchpad.svelte`**
- Extract the `is_final` branch of the websocket handler into `handleFinalTranscript(transcript: string, speechFinal: boolean)`; the websocket handler calls it; behaviour unchanged.
- `export function injectTranscript(text: string, speechFinal = true): void` → `handleFinalTranscript(text, speechFinal)`. Works whether or not the mic is running.
- Keep `let lastSentTranscript = ''`. In `processTranscript`, compute `last_utterance = sessionTranscript.slice(lastSentTranscript.length).trim()` when `sessionTranscript.startsWith(lastSentTranscript)`, include it in the body when non-empty; after the response, `lastSentTranscript = sessionTranscript`. (The transcript window `SESSION_TRANSCRIPT_WINDOW` can drop the prefix; the `startsWith` check handles that by sending no delta that call.)
- New optional props: `labConfig: { triage_debug: boolean; triage_route: { candidate: 'jev'|'qwen'; threshold: number } | null } | null = null` — when non-null its fields are spread into the request body; and `onProcessTrace: (t: ProcessTrace) => void = () => {}` called once per completed `/process` call with `{ utterance, requestBody (minus transcript text), response, latency_ms, triage }`.
- Home page passes neither prop; nothing changes there.

**`IntelliDictateTab.svelte`**
- Pass-through props `labConfig` and `onProcessTrace` to the scratchpad; `export function injectTranscript(text, speechFinal)` forwarding to the scratchpad ref. Nothing else.

**Type file** `src/lib/types/dictationLab.ts`: `ProcessTrace`, `TriageTrace`, `LabConfig`, and `FixtureCase` (mirrors the backend fixture line).

### 5.6 Frontend: the Dictation Lab (`src/routes/dictation-lab/`)

- `+page.ts`: `export const load = () => requireDevRoute();` — first commit, per the dev-route rule.
- `+page.svelte`: fetches API key status the same way the home page does, mounts `<IntelliDictateTab bind:this={tabRef} {apiKeyStatus} labConfig={$labConfig} onProcessTrace={pushTrace} ...>` with the same bindings as the home page for response, model, loading, error and reportId, no-op handlers for sidebar and hover-popup events, and a two-column layout: production tab left, `DictationLabPanel` right (stacked below at narrow widths).
- `src/lib/components/DictationLabPanel.svelte`:
  - **Feeder**: textarea, one utterance per line; buttons *Step* (inject next line, `speechFinal=true`), *Play* with a delay input (default 1500 ms), *Stop*, *Reset feeder*; *Load fixtures* pulls `GET /api/canvas/triage/fixtures` (dev-gated, returns the fixture file) and fills the textarea with its utterances grouped by case.
  - **Strategy**: radio `shadow (observe)` / `route on Jev` / `route on Qwen`; threshold slider 0.5–1.0 step 0.05 (disabled for Qwen with a note that it has no confidence); toggle *show both candidates* (sets `triage_debug`). Persisted in `localStorage` under `rr_lab_config`, wrapped in try/catch.
  - **Timeline**: one row per trace, newest last, auto-scroll: utterance, `derived`, live latency, routed-by/handler, Jev action + confidence + latency, Qwen action + latency; agreement colouring (both agree with derived: green; one: amber; neither: red; deterministic route: blue). Click a row to expand the full request/response JSON.
  - **Export**: per-row *Add to fixtures* opens a small form pre-filled with committed/active/utterance and the candidates' action, lets you set `expected_*`, `hard`, `note`, and appends a JSON line to a textarea buffer; *Copy fixtures* copies the buffer for pasting into `tests/fixtures/triage_utterances.jsonl`. No write endpoint — the file stays under git review.
  - **Session summary**: counts per routed handler, mean live latency for model vs deterministic rows, agreement rate per candidate. Resets with *Clear timeline*.
- `GET /api/canvas/triage/fixtures` (backend, `canvas_routes.py`): returns the fixture file as JSON; 404 unless `RR_TRIAGE_DEBUG=1`. Read-only.

### 5.7 Fixtures: `backend/tests/fixtures/triage_utterances.jsonl` (new)

```json
{"id": "corr-laterality-01", "committed": "", "active": "- 6 mm nodule right upper lobe",
 "utterance": "actually make that the left upper lobe", "scan_type": "CT chest",
 "expected_action": "correct_previous_finding", "expected_is_correction": true,
 "expected_needs_committed_edit": false, "hard": false, "note": "explicit 'actually' correction"}
```

Target 60–100 cases across all six actions, at least eight per action, and a `hard: true` subset (temporal comparisons, restatements with slight rewording, corrections addressed to the committed zone, negatives dictated as a run-on, homophone-heavy phrasing). Synthetic text, British spelling, radiology register, Deepgram-like surface form. Initial seed of ~40 written by hand; the rest grown from lab sessions via the export buffer.

### 5.8 Bake-off script: `backend/src/rapid_reports_ai/scripts/triage_bakeoff.py` (new)

- Loads the fixture file, runs every case through both triagers (concurrency 4; Jev and Qwen sequential per case so latencies are not contended), writes `docs/model-migration/triage-bakeoff-<date>.json` and prints:
  - per candidate: overall accuracy, per-action precision/recall, confusion matrix, `is_correction` and `needs_committed_edit` accuracy at 0.5, p50/p95 latency, total cost, error count;
  - Jev only: accuracy bucketed by confidence (`<0.5`, `0.5–0.8`, `0.8–0.95`, `≥0.95`) and coverage at each threshold;
  - `hard` subset separately.
- Shares `summarise(decisions)` with the shadow-log analysis (`scripts/triage_shadow_report.py`, which reads a log dump and prints the same summary against derived labels).
- Requires `OPENROUTER_API_KEY` and `CEREBRAS_API_KEY`; never run by pytest.

## 6. Data flow

**Lab, debug strategy:** feeder or mic → `handleFinalTranscript` → `/process` with `last_utterance` and `triage_debug` → backend gathers live + Jev + Qwen → response with `triage` → `onProcessTrace` → timeline row.

**Lab, route strategy:** same until the backend; the selected triager runs first (~0.3 s Jev); deterministic classes above threshold return immediately with the edited active text and `routed="deterministic"`; everything else falls through to the live model with the decision in the trace.

**Production shadow:** `/process` with `last_utterance` only → live path unchanged → background task → one log line. Railway logs are the data store; `triage_shadow_report.py` summarises a log dump in the bake-off format.

## 7. Error handling

| Failure | Behaviour |
|---|---|
| No flags set, or `last_utterance` absent/empty | No triage. Identical to today. |
| A debug/shadow flag on, key missing | One warning at import; that mode disabled. |
| Jev HTTP error, timeout, bad shape, out-of-range value | `JevTriager` raises. Debug: recorded as `error` in its trace slot. Route: fall through to the live model, `routed="model"`, error in trace. Shadow: logged as `error`. |
| Qwen error / timeout | Symmetric. |
| Deterministic delete on empty active | `apply_deterministic` returns `None`; live model runs. |
| Derived label raises (should not; pure) | Debug: `derived=None`. Shadow: caught at task top level, whole line logged as error. |
| Live path fails and returns the fallback response | Shadow still runs (derived = `noop`). Debug: trace still attached. |
| Lab page without `PUBLIC_ENABLE_DEV_ROUTES=true` | SvelteKit 404 from the load function. |
| Backend without `RR_TRIAGE_DEBUG=1` receiving lab fields | Fields ignored; `triage=None`; fixtures endpoint 404. |

No path exists by which triage changes a production response or adds latency beyond scheduling a background task.

## 8. Testing

All pytest and frontend tests are offline; no network, no keys.

**Backend**
- `tests/test_dictation_triage.py`: Jev request body exactness (`httpx.MockTransport`), response parsing, raises on non-2xx / missing id / unknown choice / out-of-range / timeout; Qwen passes `use_thinking=False`, `reasoning_effort: none`, temperature 0.0, `QwenTriageOutput` to a monkeypatched runner and maps booleans to 0.0/1.0 with `confidence None`; both candidates' prompts contain each action description verbatim.
- `tests/test_dictation_triage_labels.py`: table-driven `derive_action` cases incl. whitespace/case noise, reordering (not a change), blank-line insertion (`noop`), in-place replacement (`correct`), committed edit precedence; `AGREEMENT_MAP` exhaustive over `TriageAction`.
- `tests/test_dictation_triage_router.py`: `apply_deterministic` per action incl. formatting lexicon mapping, delete of last non-blank line, delete on empty → `None`; `route` threshold logic with and without confidence.
- `tests/test_canvas_triage_modes.py` (route level, `client` fixture + auth override pattern from `test_dictation_check_route.py`, triagers monkeypatched with sentinels):
  - no flags: `last_utterance`/`triage_debug`/`triage_route` present → response identical to a request without them; no triager called; `triage` absent.
  - shadow flag: response byte-identical; both triagers called once with the expected `TriageState`; one `canvas.triage.shadow` log record; utterance text absent from the log; Jev raising → `jev.error` set, `qwen.action` present.
  - debug flag + `triage_debug`: response carries `triage.mode == "debug"` with both slots, `derived`, `live_latency_ms`; live output unchanged.
  - debug flag + `triage_route`: deterministic decision above threshold → live model **not** called, active text edited as specified, `routed == "deterministic"`; below threshold or non-deterministic action → live model called, `routed == "model"`; triager exception → live model called, error in trace.
  - fixtures endpoint: 404 without the flag, JSON list with it.
- Fixture-file validation test: parses, ids unique, actions valid, ≥ 8 per action.
- `tests/test_dictation_triage_live.py`, `@pytest.mark.live`, skipped unless `RR_LIVE_TESTS=1` and keys exist; five fixtures through `JevTriager`; asserts shape only.

**Frontend** (vitest, matching the repo's existing test setup)
- `DictationScratchpad`: `injectTranscript` appends to the session transcript and triggers one `/process` call with `last_utterance` equal to the injected text; a second inject sends only the new delta; `labConfig` fields appear in the body when set and are absent when `null`; `onProcessTrace` fires once with the response's `triage`.
- `DictationLabPanel`: Step injects the next line; Play respects the delay and Stop halts it; strategy changes update `labConfig`; timeline row colouring per agreement class; export form produces a valid fixture line.
- `dictation-lab/+page.ts`: 404 when `PUBLIC_ENABLE_DEV_ROUTES` is unset (existing dev-route test pattern).

## 9. Bake-off exit criteria (proposal; decided before any production routing spec)

A candidate is eligible to route real traffic only if, on the fixture set:

- ≥ 0.95 accuracy on `formatting_command`, `delete_previous_utterance`, `ignore_noise`, `restate_existing_finding`;
- ≥ 0.90 accuracy separating `correct_previous_finding` from `append_new_finding`, and ≥ 0.90 on `needs_committed_edit`;
- for Jev: accuracy in the `≥ 0.95` confidence bucket ≥ 0.98 with that bucket covering ≥ 70 % of non-hard cases, and accuracy monotone across buckets;
- p95 latency ≤ 800 ms;
- from at least one week of shadow logs, agreement with the derived label ≥ 0.85 on non-`noop` classes (a floor, since the derived label is lenient);
- and, from lab sessions in route mode, no deterministic route that a reviewer would have reversed (tracked via the export buffer's `note` field).

If Qwen-off meets the accuracy bars, vendor count wins and Jev is dropped unless its calibration is decisive for confidence-gated routing. If neither meets them, the fixture set and question wording are revisited before any model change.

## 10. Risks and mitigations

- **Jev's calibration is group-level and trained elsewhere.** The confidence buckets in the bake-off are the calibration test; no threshold is chosen from the docs.
- **New sub-processor for dictation text (TypeSafe via OpenRouter).** Same category as existing Cerebras / Groq / OpenRouter traffic; fixtures are synthetic; shadow logs carry no text. Add to the vendor list when shadow goes live.
- **Lab flags leaking to production.** Two independent gates: the SvelteKit route 404s without the build-time flag, and the backend ignores lab fields without `RR_TRIAGE_DEBUG`. Route-level tests assert byte-identical responses without the flag.
- **Refactoring the transcript branch could change live behaviour.** The extraction is a pure move; the websocket path is covered by the `injectTranscript` tests exercising the same function.
- **Derived label is a heuristic.** Tested, lenient, used only as the shadow floor.
- **`jev-latest` drift.** Pinned to `typesafe/jev-1.13`.
- **Prompt-injection surface.** Dictation text goes into `state`, not `instructions`; Jev returns typed values; Qwen has a 120-token typed schema.
- **Cost.** Jev ≈ $0.00002 per call; Qwen-off is a short call on an already-provisioned provider; both bounded by flags.

## 11. Follow-ups this pilot unlocks (each its own spec)

1. Production routing on triage (the lab's route mode, promoted, plus verbatim fast-append if the classifier earns it).
2. Audit pre-screen: nine Nouls in one Jev call over dictation + report; System 2 only for flagged or uncertain criteria.
3. Coverage checklist as Nouls, replacing the Qwen coverage call and its output normaliser.
4. Copilot sidebar in the lab; persisted shadow table + Metabase card.

## 12. Bake-off runs (2026-09-24, 48 fixtures, 8 per action, 17 hard)

Data: `docs/model-migration/triage-bakeoff-2026-09-24.json` (run 2). Run 1 differed only in Qwen erroring on 11 cases (see below).

| | Jev 1.13 | Qwen 27B reasoning-off (Groq) |
|---|---|---|
| accuracy (all / hard) | 0.979 / 0.941 | 0.979 / 0.941 |
| errors | 0 | 0 (run 1: 11) |
| p50 / p95 latency | 292 ms / 864 ms | 239 ms / 1285 ms |
| is_correction @0.5 | 0.979 | 0.813 |
| needs_committed_edit @0.5 | 1.0 | 1.0 |
| cost, 48 calls | $0.0012 | $0 (already-provisioned provider) |
| confidence ≥0.95 bucket | accuracy 1.0, coverage 0.83 | n/a (no confidence) |
| confidence 0.8–0.95 bucket | accuracy 0.833, n=6 | n/a |

**What it says against §9.** Both candidates clear the accuracy bars on every deterministic class (formatting, delete, noise, restate all at recall 1.0 and precision 1.0) and on correct-vs-append (only one miss each). Jev's calibration is usable: everything at or above 0.95 was right, that bucket covers 83 % of cases, and accuracy is monotone across buckets, so a 0.95 routing threshold is defensible from this set. Neither candidate meets the p95 ≤ 800 ms bar on this run (Jev 864 ms, Qwen 1285 ms); p50 is well under for both. Qwen's `is_correction` signal is noticeably weaker (0.81 vs 0.98).

**The one shared miss** is `append-06`, the temporal comparison ("it was five millimetres on the prior now ten millimetres"): both candidates call it a correction; Jev at 0.93, i.e. below the 0.95 threshold, which is exactly the fall-through-to-System-2 behaviour the design wants.

**Run 1 defect, fixed.** Qwen erred on 11/48 because Groq's tool-call validator rejects the model's `True`/`False` strings for JSON boolean fields; the two aux signals are now yes/no string literals (`dictation_triage.QwenTriageOutput`).

**Live route smoke (real models, TestClient with auth override).** Debug mode attaches both decisions with no added latency over the live call; route mode on Jev at 0.9 answered `um so er`, `new paragraph` and `scratch that` deterministically in 260–290 ms versus 470 ms–8.8 s for model calls. One observation for the routing spec: "scratch that" immediately after "new paragraph" deletes the last finding line (the deterministic delete removes the last non-blank line), not just the paragraph break.

**Next:** grow the fixture set from lab sessions (especially restatements and temporal comparisons), decide the latency bar against real p95 over more runs, and start production shadow (`RR_TRIAGE_SHADOW=1`) to get the derived-label agreement floor.
