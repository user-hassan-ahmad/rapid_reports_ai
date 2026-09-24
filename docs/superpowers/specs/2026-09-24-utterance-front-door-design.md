# Utterance Front Door — Boundary Classification with Jev (Design)

**Date:** 2026-09-24
**Status:** Implemented on branch `dictation-triage-lab` (lab only); bake-off run 1 and lab run in §7
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

Thresholds in code (revised after run 1, see §7): act on `complete` at confidence ≥ 0.4, on `command` at ≥ 0.3; anything below is treated as `continues` (waiting is the cheap error; the backstop bounds it). `asr_risk` is recorded only; `ASR_RISK_THRESHOLD = 0.7` is the recorded cut for the next spec.

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
  4. on `complete`: queue `chunkBuffer + chunk` as one statement; on `command`: queue the buffered words as their own statement (if any) and then the command as a second utterance, so a formatting or delete command is never glued onto a finding; each process call takes exactly one queued utterance as `last_utterance`, and a queued utterance never aborts an in-flight polish;
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

## 7. Run 1 (2026-09-24)

### Bake-off, 38 fixtures (16 complete, 12 continues, 10 command; 3 ASR-error cases)

Data: `docs/model-migration/boundary-bakeoff-2026-09-24.json`.

| | raw choice | resolved (0.6 / 0.8, as first specified) | resolved (0.4 / 0.3, shipped) |
|---|---|---|---|
| accuracy | 0.868 | 0.711 | 0.868 |
| complete | 0.88 | 0.62 | 0.88 |
| continues | 0.75 | 0.75 | 0.75 |
| command | 1.00 | 0.80 | 1.00 |
| wrong sends (extra polish) | 3 | 3 | 3 |
| wrong waits (stall ≤ 1.5 s) | 2 | 8 | 2 |
| p50 / p95 latency | 311 ms / 451 ms | | |

**Thresholds are a floor, not a lever.** A sweep over the saved results showed the three wrong sends are the same three at every threshold (they come from the raw choice), while every threshold above 0.4 only converted correct answers into stalls. So the shipped thresholds act on the raw choice and guard only against near-uniform distributions. Confidence buckets: ≥ 0.95 → 1.00 (n=15), 0.8–0.95 → 0.90 (n=10), 0.5–0.8 → 0.64 (n=11).

**The three wrong sends are label disputes, not errors.** `cnt-01/02/11` label grammatically complete clauses as `continues` because the recorded session showed a continuation followed ("there is a 10 millimetre nodule" → "in the right upper lobe"). Jev calls them complete at 0.72–0.84. Sending a complete clause early costs one extra polish and the continuation is then merged by action triage, so the classifier's reading is the safer one; those labels should move to `complete` and the fixture note kept.

**ASR risk.** The Noul separates the three true cases (0.72, 0.77, 0.80) from every clean case at a 0.7 cut (0 false positives, 0 misses), but its baseline on clean text sits at 0.50–0.67, so 0.5 is useless (24 false positives). In the live lab run the clean baseline was higher still (0.54–0.76, including 0.75 on a correctly spelt "spiculated"), so 0.7 is not yet trustworthy on live text. Not acted on; the fast-append spec must tighten the criteria (name the phonetic-neighbour requirement more strictly) and re-measure.

### Lab run, front door = jev, feeder at 1.5 s, 9 fragments

| chunk | resolved | conf | ms |
|---|---|---|---|
| there is a 10 millimeter nodule | complete | 0.71 | 397 |
| in the right upper lobe | continues | 0.91 | 363 |
| which is spiculated in nature | continues (raw complete below floor) | 0.28 | 340 |
| new paragraph | command | 0.79 | 296 |
| further satellite lesions noted in the | continues | 1.00 | 264 |
| left lower lobe the largest measuring | continues | 1.00 | 302 |
| 8 mm in size | complete | 0.76 | 1056 |
| the mediastinum is unremarkable | complete | 0.95 | 263 |
| scratch that | command | 0.94 | 295 |

9 chunks → 5 sends → 4 polish calls saved, 0 backstops, mean boundary latency 397 ms. The three-fragment satellite-lesion sentence reached the polish as one statement and action triage scored it append at 1.00. Polish per statement: 5 calls for 4 statements + 1 command, against 9 with the timers (and 26 in the recorded mic session, 12 of them empty).

**Defect found and fixed in this run.** "new paragraph" was glued onto the buffered "in the right upper lobe which is spiculated in nature" and sent as one utterance. Commands now flush the buffer as its own statement first and go out separately (`applyBoundary` returns a list of sends; the utterance queue takes one per polish and never aborts an in-flight call).

**Against §5.** Command accuracy 1.00 and complete 0.88 meet or approach the bars; continues at 0.75 does not, and most of that gap is the label dispute above. Polish per statement in the lab was 1.25 against the 1.2 target. ASR risk needs criteria work before it can gate anything. Next: relabel the disputed fixtures, grow the set from mic sessions via the chunk export, and re-run.
