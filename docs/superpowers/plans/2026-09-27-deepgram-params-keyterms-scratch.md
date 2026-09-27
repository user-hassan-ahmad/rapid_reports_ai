# Plan — Deepgram parameters, per-case keyterms, deterministic "scratch that" (2026-09-27)

**Why:** Deepgram docs audit + live tests (2026-09-27): model `nova-3-medical` and `en-GB` are current and correct; `numerals` was missing ("segment seven" → "7" with it); `punctuate` is redundant with `smart_format`; without `mip_opt_out=true` requests may join Deepgram's Model Improvement Program (the user approved opting out); keyterms are a fixed generic list of 52 that missed every word misheard in the lab (Deepgram advises 20–50 focused terms, 500-token cap). A lab session lost a finding when the lean polish over-deleted on "Scratch that".

## Tasks (TDD, one commit each)

1. **Deepgram URL builder** (`deepgram_listen_url`, tested): adds `numerals=true`, `mip_opt_out=true`; drops `punctuate` once a live check confirms commands still arrive with `smart_format` alone. Shared websocket: production gets these on deploy (approved).
2. **Per-case keyterms:** `POST /api/canvas/keyterms` {scan_type, clinical_history, sections} → one model call (reasoning off) proposing up to 50 terms; code filters (lowercase, de-duplicated, ≤ 3 words, no common words, token budget) and merges a trimmed core list; cached per case; falls back to the core list. The scratchpad fetches them when the workspace is set up and passes them on the websocket URL; the backend uses them only with `DEEPGRAM_CASE_KEYTERMS=1`.
3. **"Scratch that" / "delete that" by code:** a bare delete command is decided by code (route `delete`); the scratchpad removes what the previous utterance wrote (its tracked range, restored to what was there before), and the command's own faded text. No model.
4. Docs.
