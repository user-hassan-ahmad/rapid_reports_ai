# Plan — work-order step 5: decision-first dictation live in the lab (2026-09-26)

**Scope:** rev 2 component 2 as a *lab strategy*. Production unchanged: the new endpoint is 404 unless `RR_TRIAGE_DEBUG=1`, and the frontend path runs only when the lab's front door is set to `decision`. Wording frozen; only new thresholds are added (QSET_VERSION bump). No calibration work.

## Flow per Deepgram final (front door = `decision`)

```
final → faded render (always, this strategy) → POST /api/canvas/bundle (one Jev bundle, shared client)
      ← {decision_id, route, reason, text, insert, closes_line, close_on_silence, probabilities, …}
route fast_append → pending span replaced by cleaned verbatim text on the OPEN line (auto mark, undoable)
route command     → pending span replaced by the lexicon's characters (auto mark, undoable)
route skip        → filler only after cleaning: pending span removed
route polish      → today's /api/canvas/process with this utterance (fail open); open line closes
```

- **Cleaning (code):** our command lexicon (`new paragraph`, `new line`, `full stop`, Deepgram's literal forms) + hesitation-token removal (`um`, `uh`, `erm`, lowercase `er`, `ah`, `hmm`; never `mm`, never `ER`). Deepgram punctuation kept.
- **Line close (code):** terminal punctuation or newline in the cleaned text; else at the silence milestone if the bundle's `standalone ≥ τ`; else at the hard limit. All three numbers live in `jev_questions.py` and travel in the response.
- **Band router (code, `fast_append.route_bundle`):** confident append (action = append ≥ act, `is_correction` < ceiling) → fast_append; formatting_command ≥ command band *and* a lexicon mapping → command; everything else (correct / restate / delete / noise, low confidence, Jev error, empty mapping) → polish. While a polish is queued or in flight, later utterances also go to polish (the full-regeneration polish rewrites a range fixed at request time).
- **Outcomes (frontend):** every decision has an id (from the backend; `local-n` if the request failed). Logged against it: `undo` (one-step, Mod-Z or button, for every route incl. polish), `edit` (user change touching the affected line within 10 s; the editor stays editable while recording in this strategy), `redictate` (a later utterance within 15 s whose tokens overlap the affected utterance's ≥ 0.6). Records carry lengths, 8-hex hashes, probabilities, qset, route, reason, latency, `polish_called`; never text.

## Tasks (TDD, one commit each)

1. **Registry:** provisional bands + line-close constants in `jev_questions.py`, `QSET_VERSION = 2026-09-26.2`; test pins the values to the version.
2. **`fast_append.py`:** `clean_verbatim`, `closes_line`, `route_bundle` (pure) + tests.
3. **`POST /api/canvas/bundle`** (lab only): cleaning, bundle call through the shared client, router, one `canvas.bundle.decision` log line (data only) + tests.
4. **Frontend pure helpers** `dictation-lab/decisionFirst.ts`: separator, changed range, re-dictation match, counters, session export + vitest.
5. **Scratchpad wiring** (`DictationScratchpad.svelte`, `IntelliDictateTab.svelte`, `labConfig`): strategy `decision`, route application, auto mark, one-step undo, line-close timers, outcome tracking.
6. **Lab panel:** per-utterance route rows, running counters (polish calls avoided, undo/edit/re-dictation rate by route), session export (JSON, data only).
7. **`scripts/lab_session_summary.py`:** per session + overall: polish calls/utterance vs polish-everything baseline (Wilson), undo/edit rate per route (Wilson), bundle p50/p95 (bootstrap) + tests.
8. **Docs:** work order step 5 → built, not yet exercised; handover §5 how to run.

## Known limits (accepted for the lab)

- Manual edits during a polish in flight are overwritten by the polish (same as today's path).
- One-step undo covers the most recent action only, and only while its range is intact.
- `ignore_noise` routes to polish (not in the user's fast list); filler-only utterances are skipped by code before Jev.
