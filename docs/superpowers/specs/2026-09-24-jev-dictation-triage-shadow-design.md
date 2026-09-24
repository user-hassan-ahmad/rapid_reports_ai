# Dictation Utterance Triage — System 1 Shadow Pilot (Jev vs Qwen reasoning-off)

**Date:** 2026-09-24
**Status:** Design approved in conversation; awaiting spec review
**Branch:** skill-sheet-v3 (spec only; implementation on its own branch)
**Fills:** Dictation program Phase 3 slots §7.5 "Triage front-door" and §7.6 "Model router" (see `2026-08-09-dictation-fidelity-and-orchestration-design.md`)

## 1. Problem

Every dictation utterance goes through the same full-cost canvas process call: the whole session transcript plus scratchpad is sent to Qwen 27B (Cerebras, `reasoning_effort: low`) and the active zone is regenerated. A formatting command ("new paragraph"), a delete ("scratch that"), filler ("um so er"), and a substantive correction all pay the same latency. The August spec reserved a Phase 3 triage front-door to classify each utterance before deciding how much model to spend on it, but never specified what would do the classifying.

Two candidates now exist for a "System 1" classifier — one that returns a typed decision, not prose:

- **Jev 1.13** (TypeSafe, via OpenRouter's System One endpoint): a purpose-built decision model. Typed `Choice` / `Score` / `Noul` questions over a JSON state; returns probabilities and a calibrated confidence. $0.042 per 1M input tokens, output free, 32K context, ~0.3 s round trip measured from this machine.
- **Qwen 27B with reasoning off** (already in production on Cerebras): the same model as the live path, asked a structured question with a tiny output schema and `reasoning_effort: none`.

We do not know which is accurate enough on radiology dictation, how well Jev's confidence is calibrated on our data, or whether Qwen-off is fast enough to make a new vendor unnecessary. This pilot produces that evidence without changing anything the radiologist sees.

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
- Run both candidates in **shadow** on live traffic: zero added latency on the live path, zero behaviour change, one structured log line per call.
- Derive a ground-truth label from what the live path actually did, deterministically, and record agreement.
- Ship a hand-labelled fixture set and a bake-off script that reports accuracy, confusion, latency, cost, and Jev confidence calibration per candidate.
- Define the exit criteria that would justify letting triage route real traffic (a separate spec).

### Non-goals
- Acting on triage decisions. No routing changes, no deterministic command handling, no skipping the live model.
- The audit pre-screen and the coverage-checklist swap. Each gets its own spec if this pilot passes.
- Fixing the dead tier-2 semantic check (`dictation_semantic`). Separate defect, already tracked.
- A persisted shadow table / Metabase card. Logs first; a table is a follow-up if the data proves useful (migrations are gated in this repo).
- Adopting the TypeSafe SDK. A ~30-line client is enough and avoids a dependency on an alpha SDK.

## 4. Architecture

```
DictationScratchpad.svelte
  └─ POST /api/canvas/process  { ..., last_utterance }       (new optional field)
        │
        ├─ live path (unchanged): Qwen 27B → CanvasIncrementalResponse / CanvasProcessResponse
        │
        └─ if RR_TRIAGE_SHADOW=1 and last_utterance:  asyncio.create_task(_shadow_triage(...))
                 ├─ JevTriager.classify(state)      ──┐  asyncio.gather(return_exceptions=True)
                 ├─ QwenTriager.classify(state)     ──┘
                 ├─ derive_action(before_active, after_active, committed_edits)
                 └─ logger.info("[canvas.triage.shadow] {json}")
```

The shadow task is scheduled **after** the live response object exists and is returned; it never blocks or mutates the response.

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

Timeout for Qwen: 8.0 s (it is the same model as the live path; if it is slower than that the bake-off will say so).

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
5. Otherwise (same count, ≥1 line differs, or a line replaced) → `correct`.

Normalisation: strip, collapse internal whitespace, drop blank lines, case-fold. Lines are compared as sets for containment and as ordered lists for counts.

Mapping from `TriageAction` to `DerivedAction` for agreement, `AGREEMENT_MAP`:

| TriageAction | agrees with DerivedAction |
|---|---|
| append_new_finding | append |
| correct_previous_finding | correct, committed_edit |
| restate_existing_finding | noop, correct (absorbed into an existing line) |
| delete_previous_utterance | delete |
| formatting_command | noop, append (a line break can add a line) |
| ignore_noise | noop |

`needs_committed_edit` agrees when `(value >= 0.5) == (derived == "committed_edit")`.

The map is deliberately lenient where the live model's rewrite is not a clean signal; the fixture set is where precise labels live.

### 5.3 Request and route changes (`canvas_routes.py`)

- `CanvasProcessRequest.last_utterance: str | None = None` with a comment: "Trimmed transcript delta since the previous process call. Shadow triage only; never affects the response."
- In `process_transcript`, after the live `output` is obtained (inside the `try`, before `return output`) and also on the fallback-return path:

```python
if _triage_shadow_enabled() and request.last_utterance:
    asyncio.create_task(_shadow_triage(request, output, incremental))
```

- `_triage_shadow_enabled()` reads `RR_TRIAGE_SHADOW == "1"` once at import and additionally requires `OPENROUTER_API_KEY` to be set; if the flag is on but the key is missing it logs one warning at import and stays off.
- `_shadow_triage` builds `TriageState(committed=request.committed_context or "", active=request.scratchpad_content, latest_utterance=request.last_utterance, scan_type=request.scan_type)`, runs both triagers with `asyncio.gather(..., return_exceptions=True)`, derives the label from `request.scratchpad_content` → `output.active_scratchpad` (or `output.scratchpad` in full mode) and `output.committed_edits` (or `[]`), and logs:

```json
{"event": "canvas.triage.shadow", "mode": "clean", "incremental": true,
 "utterance_len": 41, "utterance_sha8": "3f9a1c2b",
 "derived": "correct",
 "jev": {"action": "correct_previous_finding", "confidence": 0.97, "is_correction": 0.94,
         "needs_committed_edit": 0.03, "latency_ms": 262, "input_tokens": 578, "cost_usd": 2.4e-05,
         "agrees": true, "error": null},
 "qwen": {"action": "correct_previous_finding", "confidence": null, "is_correction": 1.0,
          "needs_committed_edit": 0.0, "latency_ms": 640, "input_tokens": null, "cost_usd": null,
          "agrees": true, "error": null}}
```

The utterance text is **not** logged (length + 8-char SHA-256 prefix only); the scratchpad is not logged. A candidate's exception is captured as `error: "<ExceptionType>"` with `action: null`, never re-raised. The task's own top level catches everything and logs `[canvas.triage.shadow] ❌`.

### 5.4 Frontend (`DictationScratchpad.svelte`)

- Keep `let lastSentTranscript = ''`.
- At the process call: `const last_utterance = sessionTranscript.slice(lastSentTranscript.length).trim();` include it in the body when non-empty; on a successful response set `lastSentTranscript = sessionTranscript`.
- If `sessionTranscript` no longer starts with `lastSentTranscript` (transcript reset), send no `last_utterance` and reset `lastSentTranscript = sessionTranscript` after the call. No other change. Nothing is gated in the frontend; the backend flag decides.

### 5.5 Fixtures: `backend/tests/fixtures/triage_utterances.jsonl` (new)

One JSON object per line:

```json
{"id": "corr-laterality-01", "committed": "", "active": "- 6 mm nodule right upper lobe",
 "utterance": "actually make that the left upper lobe", "scan_type": "CT chest",
 "expected_action": "correct_previous_finding", "expected_is_correction": true,
 "expected_needs_committed_edit": false, "hard": false, "note": "explicit 'actually' correction"}
```

Target 60–100 cases across all six actions, with at least eight per action, and a `hard: true` subset (temporal comparisons, restatements with slight rewording, corrections addressed to the committed zone, negatives dictated as a run-on, homophone-heavy phrasing). Text is synthetic. British spelling, radiology register. Utterances mirror Deepgram output: lower-case, no punctuation unless dictated.

### 5.6 Bake-off script: `backend/src/rapid_reports_ai/scripts/triage_bakeoff.py` (new)

- Loads the fixture file, runs every case through both triagers (concurrency 4, Jev and Qwen sequentially per case so latencies are not contended), and writes `docs/model-migration/triage-bakeoff-<date>.json` plus a printed summary:
  - per candidate: overall accuracy, per-action precision/recall, confusion matrix, `is_correction` and `needs_committed_edit` accuracy at the 0.5 threshold, p50/p95 latency, total cost, error count;
  - Jev only: accuracy bucketed by confidence (`<0.5`, `0.5–0.8`, `0.8–0.95`, `≥0.95`) and coverage at each threshold (fraction of cases at or above it), so a routing threshold can be read off;
  - `hard` subset reported separately.
- Requires `OPENROUTER_API_KEY` and `CEREBRAS_API_KEY`; exits with a clear message otherwise. Never run by pytest.

## 6. Data flow (shadow, per utterance)

1. Frontend computes the delta and posts the existing body plus `last_utterance`.
2. Route runs the live path exactly as today and obtains `output`.
3. Route schedules the shadow task and returns `output`. Response latency is unaffected.
4. Shadow task runs Jev and Qwen concurrently, derives the label, logs one JSON line.
5. Railway logs are the data store for the pilot. A `grep '"event": "canvas.triage.shadow"'` over a day of logs feeds the same summary code the bake-off script uses (shared `summarise(decisions)` helper), so live agreement and fixture accuracy are reported in one format.

## 7. Error handling

| Failure | Behaviour |
|---|---|
| Flag off, or `last_utterance` absent/empty | No triage. Identical to today. |
| Flag on, key missing | One warning at import; shadow disabled. |
| Jev HTTP error, timeout, bad shape, out-of-range value | `JevTriager` raises; captured by `gather`; logged as `error`. Qwen result still logged. |
| Qwen error / timeout | Symmetric. |
| Derived label raises (should not; pure function) | Caught at task top level; whole line logged as error. |
| Live path itself fails and returns the fallback response | Shadow still runs (the fallback returns the input unchanged, so `derived` is `noop`; that is real data about what the user saw). |
| Event loop shutdown with tasks pending | `create_task` results are fire-and-forget; a lost line at shutdown is acceptable for a shadow pilot. |

No path exists by which triage changes the response, raises into the request, or adds latency beyond scheduling a task.

## 8. Testing

All pytest tests are offline; no network, no keys.

**`tests/test_dictation_triage.py`**
- `JevTriager` builds the exact request body (model id, state keys, six criteria, two nouls) — asserted against a captured transport (`httpx.MockTransport`).
- Parses a canned success response into `TriageDecision` with the right fields and types.
- Raises on: non-2xx, missing answer id, unknown choice, probability > 1, noul < 0, timeout.
- `QwenTriager` passes `use_thinking=False`, `reasoning_effort: none` in `extra_body`, temperature 0.0, and the `QwenTriageOutput` type to a monkeypatched `_run_agent_with_model`; maps booleans to 0.0/1.0; `confidence is None`.
- Both triagers share the same six action definitions (assert the Qwen system prompt contains each Jev criteria description verbatim).

**`tests/test_dictation_triage_labels.py`**
- Table-driven cases for each `DerivedAction`, including whitespace/case noise, reordering that must not count as a change, blank-line insertion (`noop`), a line replaced in place (`correct`), and a committed edit taking precedence.
- `AGREEMENT_MAP` covers every `TriageAction` (exhaustiveness test).

**`tests/test_canvas_triage_shadow.py`** (route level, using the existing `client` fixture and auth override pattern from `test_dictation_check_route.py`)
- Flag off: request with `last_utterance` returns the same response as without; no triager called (monkeypatched sentinels).
- Flag on: response is byte-identical to flag off; both triagers are called once with the expected `TriageState`; one log record with `event == canvas.triage.shadow` is emitted (caplog); the utterance text does not appear in the log.
- Flag on, Jev raises: response unaffected; log has `jev.error` set and `qwen.action` present.
- Flag on, `last_utterance` missing: no triager called.

**Fixture-file validation test**: every line parses, ids unique, every `expected_action` in the set, at least eight cases per action.

**Live test**: `tests/test_dictation_triage_live.py` marked `@pytest.mark.live`, skipped unless `RR_LIVE_TESTS=1` and the keys exist; runs the first five fixtures through `JevTriager` only and asserts shape, not answers. Documents the wire contract against the real endpoint.

## 9. Bake-off exit criteria (proposal; decided before any routing spec)

A candidate is eligible to route real traffic only if, on the fixture set:

- ≥ 0.95 accuracy on `formatting_command`, `delete_previous_utterance`, `ignore_noise` (the classes deterministic handlers would act on);
- ≥ 0.90 accuracy separating `correct_previous_finding` from `append_new_finding`, and ≥ 0.90 on `needs_committed_edit`;
- for Jev: accuracy in the `≥ 0.95` confidence bucket ≥ 0.98 with that bucket covering ≥ 70 % of non-hard cases (i.e. a usable threshold exists), and accuracy monotone across buckets;
- p95 latency ≤ 800 ms;
- and, from at least one week of shadow logs, agreement with the derived label ≥ 0.85 on the non-`noop` classes (the derived label is lenient by construction, so this is a floor, not the target).

If Qwen-off meets the accuracy bars, vendor count wins and Jev is dropped unless its calibration is decisive for the confidence-gated routing design. If neither meets them, the fixture set and the question wording are the first things to revisit, before any model change.

## 10. Risks and mitigations

- **Jev's calibration is group-level and trained on other domains.** Mitigation: the confidence buckets in the bake-off are the calibration test; no threshold is chosen from the docs.
- **New sub-processor for dictation text (TypeSafe via OpenRouter).** Same category as the existing Cerebras / Groq / OpenRouter traffic; synthetic fixtures in the repo; shadow logs carry no text. Flag it in the vendor list when the pilot goes live.
- **Derived label is a heuristic.** It is tested, lenient, and used only for the shadow agreement floor; the fixture set carries the precise labels.
- **`jev-latest` drift.** Pinned to `typesafe/jev-1.13`.
- **Prompt-injection surface.** Dictation text is user-controlled and goes into `state`, not `instructions`; Jev returns typed values only, so there is nothing to inject into. The Qwen candidate has a fixed 120-token typed schema.
- **Shadow doubles model calls per utterance during the pilot.** Costs: Jev ≈ $0.00002 per call; Qwen-off is a short call on an already-provisioned provider. Bounded by the flag.

## 11. Follow-ups this pilot unlocks (each its own spec)

1. Routing on triage: deterministic handlers for `formatting_command` / `delete_previous_utterance`, skip-model for `ignore_noise` / `restate_existing_finding`, confidence-gated fallthrough to the live model.
2. Audit pre-screen: nine Nouls in one Jev call over dictation + report; System 2 only for flagged or uncertain criteria.
3. Coverage checklist as Nouls, replacing the Qwen coverage call and its output normaliser.
4. Persisted shadow table + Metabase card if log analysis proves too coarse.
