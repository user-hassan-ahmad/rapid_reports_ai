# Plan — two-pass ASR in the live lab path (2026-09-29, draft for review)

**Why.** Captured sessions: the live stream dropped a phrase at a forced final ("Actually, make that 54 millimetres", said, lost, repeated) and a word ("The"). Deepgram batch on the audio *since the previous final* recovered both, with 0 errors on two sessions at ~300 ms p50 (`scripts/two_pass_experiment.py`, `scripts/asr_bakeoff.py`). Independent engines (Whisper, gpt-4o-transcribe) added clinical-term errors, short-clip hallucinations and prompt leakage, so they are not second voters yet (bake-off `dc6c3ff`). Harder captured sessions (CTPA, MRI spine) will decide whether an independent engine joins later.

## Design (option b: decide on live text, swap in the batch text when it differs)

1. **Backend, on each live final (lab flag `RR_TWO_PASS=1`, capture's audio buffer):** cut the audio from the previous final's end to this final's end + 0.3 s and send it to Deepgram batch (same model, keyterms, UK spelling). Forward the live final at once, as now. When the batch text returns, send a `revision` message `{final_id, text, words, differs}` (it is never delayed behind the live final).
2. **Differs** means a normalised word diff beyond punctuation or case (units normalised). Most finals will not differ (2 of 18 in the captured session), so nothing else happens.
3. **Frontend, when a revision differs:**
   - If the final's decision has not been applied yet (a queued or held final), replace its text before deciding.
   - If it was applied as fast-append and the range is intact, replace the written words with the revision (code, no model), mark it with the auto-mark, and log `revised: words` in the decision record.
   - If it went to polish, re-run the lean polish on the revised words when the range is intact; otherwise leave it and underline the words that differ.
   - **Speech the stream dropped** (the revision has words before the live final's first word): insert them as their own utterance through the normal decision path (Jev bundle, route), faded then solid.
4. **Guards:** the fidelity check applies to any rewrite; a revision never removes a number, side or negation the live final had without the batch having an alternative in the same place (else underline, not replace). A revision older than the next user edit on that range is dropped.
5. **Logging (data only):** per final `two_pass_ms`, `differs`, `recovered_words` (count), `applied` (replaced / re-polished / underlined / dropped).

## Tasks (TDD, commit each)

1. Backend clip + batch call + `revision` message (flag), with a fake Deepgram in tests; latency logged.
2. `revisionDiff` (frontend pure): differs?, dropped-speech prefix, per-word differences.
3. Scratchpad: apply revision by state (pending / fast-append intact / polished intact / touched).
4. Export and `lab_session_summary`: two-pass counts and latency.
5. Live check with synthetic speech (a dropped phrase forced by a mid-word Finalize), then a mic session.

**Open question for the user:** in 3, should a revision that changes a fast-appended sentence be replaced silently (with the auto-mark and one-step undo), or underlined for you to accept?
