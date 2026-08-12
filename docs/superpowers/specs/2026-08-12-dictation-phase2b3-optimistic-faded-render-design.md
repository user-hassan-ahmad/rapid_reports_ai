# Dictation Phase 2b.3 — Optimistic faded-render for incremental dictation

**Date:** 2026-08-12
**Status:** Design — approved, pending spec review
**Depends on:** Phase 2b.2 (incremental processing, `rr_incremental` flag) — `b800517`
**Component:** `frontend/src/lib/components/DictationScratchpad.svelte` (+ `frontend/src/lib/utils/`)

## 1. Problem

There is a perceived ~1.8 s gap between finishing an utterance and seeing polished text land in the scratchpad. Measured from a real session log:

| Stage | Time | Source |
|---|---|---|
| Silence → `speech_final` | ~300 ms | Deepgram `endpointing=300` (`main.py:4968`) |
| Frontend → backend hop + queue | ~360 ms | network + `processTranscriptQueue` |
| Gemma-4 polish (Cerebras) | ~1150 ms | `[canvas.process] 1.15s` |

The raw words are *already* visible immediately in a live caption strip, but the **scratchpad editor is only ever written by the polish** (`processTranscript`), so it sits empty during the whole pause+model cycle. The model latency itself (~0.5–1.1 s) is largely irreducible; the fix is to remove the *perceived* void.

## 2. Goal / non-goals

**Goal:** Raw `is_final` word-groups appear in the scratchpad **immediately, rendered faded**, then are replaced **in place with solid** polished text when the polish returns — so the radiologist sees their words land instantly and understands the faded text is not yet final.

**Non-goals:**
- Reducing actual model latency (no streaming of the polish response — deferred).
- Changing flag-off behavior. Everything here lives behind `rr_incremental`; flag-off is byte-for-byte today.
- Streaming interim (pre-final) words into the editor — interim stays in the caption (see §4.1).

## 3. Key decisions (from brainstorming)

- **Granularity:** only stable `is_final` groups land in the editor faded; volatile interim words stay in the caption.
- **Failure handling:** model error → backend already returns active unchanged → resolves to solid automatically. Network failure / non-superseded abort → **promote faded → solid** (never leave text dimmed). Superseded → stays faded, the re-run resolves it.
- **One growing pending region**, not per-utterance sealed regions — the abort/re-run machinery makes this correct.
- **Faded style:** 45% opacity (muted); optional subtle fade-in on the solid swap.

## 4. Design

### 4.1 Rendering — the pending decoration
Add a third CodeMirror `StateField` alongside the existing `highlightField` / `integrityField`, driven by effects `addPendingMark({from,to})` and `clearPendingMarks` (or `clearPendingBefore(pos)`), applying `Decoration.mark({ class: 'cm-dictation-pending' })`. CSS: `.cm-dictation-pending { opacity: 0.45 }`. Like the sibling fields, it does `deco = deco.map(tr.changes)` so marks track document edits; when a change replaces a faded span, those marks are dropped and the text renders solid.

The caption strip loses the `rawFeed` block (`DictationScratchpad.svelte:825–832`) — it would otherwise show the same is_final text twice (once in the strip, once faded in the editor). Caption keeps only `currentInterim` (in-progress words). `rawFeed` state is removed if it has no other consumer. Flow: **interim in caption → settles into editor faded → polish makes it solid.**

### 4.2 Insert (on `is_final`)
In the websocket `onmessage` `is_final` branch (`DictationScratchpad.svelte:519`), in addition to today's `sessionTranscript` accumulation, append `data.transcript` to the end of the editor doc as a faded pending region:
- **Separator:** reuse `mergeIncremental`'s boundary rule — newline when starting a fresh statement (active tail empty and committed non-empty), space when continuing within the active tail. One source of truth for the separator across insert and resolve.
- The insert dispatches an editor change plus `addPendingMark` over the inserted range.
- No `committedBoundary` change (raw goes into the active tail, beyond the boundary).
- Guarding: raw inserts occur while `isRecording === true`, so the manual-edit branch (gated `!isRecording`, line 618) never fires on them; no boundary corruption.

### 4.3 Resolve (in `processTranscript`) — mostly already correct
The existing resolve structure already handles the hard parts and needs only small additions:
- `const doc` is snapshotted at request start (line 290); `active = doc.slice(boundary)` is now the **raw faded text** (previously empty).
- On success, dispatch replaces `[0, doc.length@requestStart)` with `mergeIncremental(committed, sanitize(active_scratchpad), committed_edits).content` (line 342). Text dictated *during* the await lands at positions `≥ doc.length@requestStart` and is **preserved** (stays faded, resolves on its own next polish).
- Freeze boundary uses `content.length` (line 347) = committed + polished-active, which **excludes** any newer raw — so newer raw is never frozen. Correct as-is.
- **Addition:** on the resolve dispatch, clear pending marks intersecting the replaced span `[0, doc.length@requestStart)` (the sent raw becomes solid); pending marks beyond it map forward and stay faded.

### 4.4 Lifecycle & failure
- **Stop recording** (`stopRecording`, line 557): **promote all pending → solid** (clear pending marks) *before* re-enabling edit (line 587) and firing the flush polish (line 584). No pending marks survive the end of recording. The flush polish then reconciles solid → polished; if the user edits first, the manual-edit freeze + abort handles it.
- **Network failure / non-superseded abort:** promote all pending → solid (same rule as stop; simple and unambiguous).
- **`reset(newDoc)` (line 211) and doc-cleared (line 634):** clear pending marks.
- **`onContentChange`** continues to fire on every doc change, now including raw inserts during recording (already fires on polish dispatches today). Draft content during recording is transient; final content on stop is solid. No change required.

### 4.5 Redundancy fix — eliminate the wasted aborted polish
Currently `speech_final` fires a polish, then `UtteranceEnd` (~1 s later) **aborts it and fires another** — but the aborted call still completes server-side (~1 wasted Gemma call per utterance; log line 168 = 1.15 s discarded).

Fix: on `UtteranceEnd` (`DictationScratchpad.svelte:510`), set `freezeAfterNextProcess = true` and **only fire a new polish if none is in-flight**. An in-flight polish reads `freezeAfterNextProcess` at dispatch time (line 347), so it will freeze correctly without being aborted and re-run. If no polish is in-flight (the `speech_final` one already resolved), fire one as today. Net: one polish per utterance instead of two.

## 5. Required validation (model-input change)

This is **not** a pure UI change. Today `active` is always empty at `/process` (logs show `active_chars=0` on every call — freeze-per-utterance keeps the tail empty). Optimistic insert makes `active` = the raw current utterance, so the model receives raw active *plus* the overlapping `session_transcript`. The Clean/Incremental prompts were only ever exercised with empty active.

**Validation requirement:** smoke-test that polish quality with a raw-seeded active matches or beats the empty-active baseline — no double-transcription, no dropped corrections, separators correct. If quality regresses, options are (a) clarify the incremental prompt that ACTIVE may contain the raw transcript to be cleaned, or (b) stop sending the raw active and keep it display-only (the model rebuilds from `session_transcript` as today). Decide based on smoke results.

## 6. Testing

**Pure units (vitest, `server` project):**
- Extend `incrementalMerge.spec.ts` / add coverage for the separator rule shared by insert and resolve.
- Any extracted pending-region helper (e.g. `pendingRegion.ts`): "raw beyond the sent span is preserved", "sent span resolves to solid", separator selection.

**CodeMirror wiring** (`StateField`, dispatch, decoration mapping) stays thin in the component — covered by manual smoke rather than unit tests.

**Manual smoke (flag on, `localStorage.rr_incremental='1'`):**
1. Raw `is_final` lands faded instantly; goes solid ~1.5 s later.
2. Reach-back correction still patches committed text (Phase 2b.2 case).
3. Keep talking through the polish window — newer raw stays faded, resolves next polish; nothing dropped.
4. Stop mid-utterance — pending promotes to solid, flush polishes.
5. Network-fail a polish (devtools offline) — faded promotes to solid, not stuck.
6. Only **one** `/process` per utterance in the network panel (redundancy fix).
7. Flag off — unchanged from today.

## 7. Rollout
Behind the existing `rr_incremental` flag (default off). No new flag. Ships dormant; validated via manual smoke before the eventual default-on flip (tracked separately in the dictation program).

## 8. Out of scope
- Streaming the polish response token-by-token (`option B`).
- Tightening `endpointing` (`option C` timing part).
- Mode-toggle full re-derivation of committed text (pre-existing limitation, `setMode` line 671).
