# Utterance Front Door — Boundary Classification with Jev (Design)

**Date:** 2026-09-24
**Status:** Design approved in conversation; awaiting spec review
**Branch:** dictation-triage-lab
**Parent:** `2026-09-24-decision-first-dictation-design.md` (this is the per-chunk decision bundle, v1)
**Evidence:** lab session 2026-09-24 (26 calls; 12 with no new text; sentence fragments triaged with 0.58–0.68 confidence; two ASR errors)

## 1. Problem

The scratchpad decides *when* to send words for polish with two timers: Deepgram's `speech_final` after 200 ms of silence, and `utterance_end` after 1 s as a backup. Silence is not a sentence boundary. In the recorded session "There is a 10 millimeter nodule / in the right upper lobe / which is speculated in nature" arrived as three chunks, each sent for a full polish, each triaged as a half-thought. The backup timer then re-sent an unchanged transcript twelve times. Half the model traffic was waste and the triage question was asked about fragments.

Whether a chunk completes a clinical statement is a reading judgement, which is a System 1 decision. This spec replaces the timers with one Jev call per finalised chunk that answers **boundary** (complete / continues / command), carries the existing **action** triage for the merged statement, and records an **ASR-risk** signal for the next component.

## 2. Goals / Non-goals

### Goals
- One `/api/canvas/utterance` call per finalised Deepgram chunk, returning a boundary decision with confidence in ~300 ms.
- The frontend buffers chunks on `continues`, sends the merged statement for polish on `complete`, and hands `command` chunks to triage immediately.
- Polish and review run once per completed statement, not once per fragment or per silence.
- The merged statement becomes `last_utterance` for the existing `/process` triage, so action triage sees whole clauses.
- Lab visibility: chunk rows in the timeline with boundary decisions, a strategy toggle (`timer` / `jev`), and counters for polish calls saved.
- Backstop: a chunk marked `continues` that is not followed by another chunk within 1.5 s is sent anyway.

### Non-goals
- Acting on ASR risk (verbatim fast-append). The Noul is asked and shown; routing on it is the next spec.
- Changing production. The endpoint and the frontend path are honoured only under `RR_TRIAGE_DEBUG=1` and a lab strategy; the home page keeps the timers.
- Moving action triage off `/process`. It stays where it is and simply receives better input.
- Replacing Deepgram endpointing values. They stay at 200 ms / 1000 ms; the classifier decides what to do with the chunks they produce.

## 3. The decision

State sent to Jev per chunk:

```json
{"scan_type": "CT chest",
 "buffered": "further satellite lesions noted in the",      // chunks held since the last send, "" if none
 "chunk": "left lower lobe the largest measuring",           // the chunk just finalised
 "scratchpad_tail": "There is a 10 mm nodule in the right upper lobe which is spiculated in nature."}
```

Questions, one call:

```
boundary  choice
  complete:  "buffered + chunk together form a finished clinical statement a radiologist would end here:
              a finding, a measurement, a normality claim, or a correction that is fully specified"
  continues: "the statement is still in progress: it ends on a preposition, article, conjunction, verb without
              its object, an unfinished measurement, or otherwise needs more words to be a claim"
  command:   "the chunk is an instruction to the application or a dictation command rather than report content:
              scratch that, delete that, new paragraph, new line, generate report, switch mode, and similar"

asr_risk  noul
  "buffered + chunk contain a likely speech-to-text error: a word that is phonetically close to a
   radiological term the scan type or scratchpad makes expected, and that makes no clinical sense as heard"
```

Thresholds in code: act on `complete` at confidence ≥ 0.6, on `command` at ≥ 0.8; anything below is treated as `continues` (waiting is the cheap error; the backstop bounds it). `asr_risk` is recorded only.

## 4. Components

### 4.1 `backend/src/rapid_reports_ai/utterance_boundary.py` (new)
- `BOUNDARY_QUESTIONS` constant with the criteria above; `BoundaryDecision(boundary, confidence, probabilities, asr_risk, latency_ms, input_tokens, cost_usd)`.
- `JevBoundary.classify(scan_type, buffered, chunk, scratchpad_tail)`; same HTTP discipline as `JevTriager` (3 s timeout, raise on any invalid answer).
- `resolve(decision) -> Literal["complete","continues","command"]` applying the thresholds; a `TriageError` resolves to `complete` (fail open to the current behaviour).

### 4.2 `POST /api/canvas/utterance` (canvas_routes.py)
- Request: `scan_type, buffered, chunk, scratchpad_tail`. Response: `resolved`, plus the decision fields and `error` when the call failed.
- 404 unless `RR_TRIAGE_DEBUG=1` (lab only in this spec).

### 4.3 Frontend, `DictationScratchpad.svelte`
- New prop `frontDoor: 'timer' | 'jev'` via `labConfig.frontDoor`; default `'timer'`, which is today's behaviour untouched.
- In `handleFinalTranscript`, when `frontDoor === 'jev'`:
  1. append the chunk to `sessionTranscript` and render it faded exactly as now;
  2. push the chunk onto `chunkBuffer`;
  3. call `/api/canvas/utterance` with the buffer (minus the chunk), the chunk, the last non-empty scratchpad line;
  4. on `complete` or `command`: set `pendingUtterance = chunkBuffer.join(' ')`, clear the buffer, call `processTranscriptQueue()`;
  5. on `continues`: arm the 1.5 s backstop timer (reset on each chunk); when it fires, do step 4.
- `processTranscript` sends `last_utterance = pendingUtterance ?? delta` so action triage receives the merged statement.
- Deepgram's `speech_final` and `utterance_end` no longer trigger the polish while `frontDoor === 'jev'`; stop-recording still flushes.
- `onProcessTrace` gains a chunk-level sibling `onChunkTrace({chunk, buffered, resolved, boundary, confidence, asr_risk, latency_ms})`.

### 4.4 Lab panel
- Strategy section gets a **Front door** radio: `timer` / `jev`.
- Timeline shows chunk rows (thin, grey) between process rows: the chunk text, resolved boundary, confidence, asr risk.
- Session summary adds: chunks, statements sent, polish calls saved (= chunks − sends), mean boundary latency.
- Export: a chunk row can be added to `boundary_cases.jsonl` with the expected boundary.

### 4.5 Fixtures and bake-off
- `backend/tests/fixtures/boundary_cases.jsonl`: `{id, scan_type, buffered, chunk, scratchpad_tail, expected_boundary, expected_asr_risk, hard, note}`; seed 36 cases (12 per boundary class) built from the recorded session and the triage fixtures; ASR cases include "white base", "speculated", "hepatic haemangioma" said correctly.
- `scripts/boundary_bakeoff.py`: accuracy per class, confidence buckets, p50/p95, ASR-risk accuracy at 0.5; same summary style as the others.

### 4.6 Tests
- Unit: question shape, parsing, thresholds in `resolve`, fail-open on error.
- Route: 404 without the flag; resolved fields with a fake classifier; error → `resolved == "complete"` with `error` set.
- Frontend pure helper `frontDoor.ts`: `nextState(buffer, chunk, resolved)` returns `{send: string | null, buffer}`; backstop arming logic; tested in vitest.

## 5. Exit criteria before this can leave the lab
- Boundary accuracy ≥ 0.95 on `complete` and `command`, ≥ 0.90 on `continues`, with the ≥ 0.6 bucket for `complete` at ≥ 0.98.
- In lab sessions: polish calls per statement ≤ 1.2 (today ≈ 2.3 in the recorded session), no visible stall beyond the backstop.
- ASR-risk Noul ≥ 0.9 accuracy on the seeded cases, which decides whether the fast-append spec can start.

## 6. Risks
- **Over-waiting.** A wrongly confident `continues` delays the polish by up to 1.5 s. Mitigated by the backstop and by the low `complete` threshold.
- **Corrections split across chunks.** "actually" … "make that the left upper lobe" must merge before triage; the `continues` criteria name unfinished corrections explicitly, and fixtures cover it.
- **Serial dependency.** The boundary call precedes the polish; 300 ms is hidden by the faded render, but it is on the path. If the ≥ 0.6 bucket proves clean, the polish could be started speculatively in parallel and discarded on `continues`.
