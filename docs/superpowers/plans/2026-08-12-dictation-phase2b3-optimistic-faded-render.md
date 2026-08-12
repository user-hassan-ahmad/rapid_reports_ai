# Dictation Phase 2b.3 — Optimistic Faded-Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show raw `is_final` dictation groups in the scratchpad immediately as faded text, resolved to solid in place when the polish returns, removing the perceived ~1.8 s gap.

**Architecture:** A CodeMirror `StateField` marks optimistically-inserted raw text as "pending" (faded). Raw `is_final` groups append to the active tail on arrival; the existing `processTranscript` resolve already replaces the sent span with polished text and preserves anything dictated during the await. Promote-to-solid on stop and network failure. Fold in a redundancy fix that stops the wasted second polish per utterance. All behind the existing `rr_incremental` flag (default off).

**Tech Stack:** SvelteKit, CodeMirror 6 (`@codemirror/view` `StateField`/`StateEffect`/`Decoration`), Vitest (`server` project, node env), Deepgram live transcription.

**Spec:** `docs/superpowers/specs/2026-08-12-dictation-phase2b3-optimistic-faded-render-design.md`

**Branch:** `dictation-phase2b3-faded-render` (already checked out; the newline-separator bugfix `07da18b` and the spec are already committed here).

---

## File Structure

- **Modify** `frontend/src/lib/utils/incrementalMerge.ts` — add the pure `rawInsertSeparator` helper (separator single-source-of-truth, shared by insert + polish).
- **Modify** `frontend/src/lib/utils/incrementalMerge.spec.ts` — unit tests for `rawInsertSeparator`.
- **Modify** `frontend/src/lib/components/DictationScratchpad.svelte` — pending `StateField` + effects + CSS; optimistic raw insert on `is_final`; resolve clears pending; promote-on-stop/failure; `UtteranceEnd` de-dup; caption de-dup.

## Verification note

`bun run check` reports ~1208 pre-existing repo-wide type errors that are unrelated to this work. The type-check gate is therefore **scoped to touched files** — the command filters to `DictationScratchpad` / `incrementalMerge` and must print no lines (or `no new errors`). CodeMirror wiring is not unit-tested (needs a browser `EditorView`); per spec §6 it is gated on the scoped type-check plus the manual smoke in Task 7.

---

### Task 1: `rawInsertSeparator` pure helper

**Files:**
- Modify: `frontend/src/lib/utils/incrementalMerge.ts`
- Test: `frontend/src/lib/utils/incrementalMerge.spec.ts`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/utils/incrementalMerge.spec.ts`:

```ts
import { mergeIncremental, rawInsertSeparator } from './incrementalMerge';

describe('rawInsertSeparator', () => {
	it('inserts no separator for the very first words (empty doc)', () => {
		expect(rawInsertSeparator(0, 0)).toBe('');
	});

	it('inserts a newline when starting a fresh statement after committed text', () => {
		// active tail empty (docLength === committedBoundary), committed present
		expect(rawInsertSeparator(60, 60)).toBe('\n');
	});

	it('inserts a space when continuing the current utterance', () => {
		expect(rawInsertSeparator(75, 60)).toBe(' ');
	});

	it('inserts a space for a continuing first utterance with no committed text', () => {
		expect(rawInsertSeparator(20, 0)).toBe(' ');
	});
});
```

Note: the file already imports `mergeIncremental` at the top — update that existing import line to `import { mergeIncremental, rawInsertSeparator } from './incrementalMerge';` rather than adding a duplicate import.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bun run test:unit -- --run src/lib/utils/incrementalMerge.spec.ts --project server`
Expected: FAIL — `rawInsertSeparator is not a function` (or an import/type error).

- [ ] **Step 3: Implement the helper**

Append to `frontend/src/lib/utils/incrementalMerge.ts`:

```ts
/**
 * Separator to place before a raw is_final group appended to the live document
 * during optimistic rendering (Phase 2b.3). Mirrors mergeIncremental's boundary
 * rule so the faded raw reads the same way the polished text will:
 *   - empty doc                                  -> no separator
 *   - active tail empty, committed text present  -> newline (fresh statement)
 *   - active tail already has content            -> space (continuing utterance)
 */
export function rawInsertSeparator(docLength: number, committedBoundary: number): string {
	if (docLength === 0) return '';
	if (docLength === committedBoundary) return '\n';
	return ' ';
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bun run test:unit -- --run src/lib/utils/incrementalMerge.spec.ts --project server`
Expected: PASS — all `mergeIncremental` and `rawInsertSeparator` tests green.

- [ ] **Step 5: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/utils/incrementalMerge.ts frontend/src/lib/utils/incrementalMerge.spec.ts
git commit -m "feat(dictation): rawInsertSeparator helper for optimistic render

Separator single-source-of-truth for appending raw is_final groups to the
active tail (newline for a fresh statement after committed text, space within
an utterance). Phase 2b.3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 2: Pending decoration infrastructure (faded marks)

Adds the `StateField`, effects, CSS, and extension registration. No behavior change yet (nothing emits the effects), so the app is unchanged after this task.

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Add the pending StateField + effects**

Insert immediately after the `integrityField` definition (after line 71, before `let editorContainer`):

```ts
	// Phase 2b.3 optimistic render: raw is_final text is shown faded (a "pending"
	// mark) until the polish replaces it with solid text. markPending adds a faded
	// range; clearPending removes faded marks intersecting [from,to) (null = all).
	// Marks map through document changes, so a resolve that replaces a faded span
	// drops its marks; the explicit clear covers boundary-spanning cases and the
	// promote-to-solid lifecycle points.
	const markPending = StateEffect.define<{ from: number; to: number }>();
	const clearPending = StateEffect.define<{ from: number; to: number } | null>();
	const pendingField = StateField.define<DecorationSet>({
		create: () => Decoration.none,
		update(deco, tr) {
			deco = deco.map(tr.changes);
			for (const e of tr.effects) {
				if (e.is(markPending)) {
					deco = deco.update({
						add: [Decoration.mark({ class: 'cm-dictation-pending' }).range(e.value.from, e.value.to)]
					});
				} else if (e.is(clearPending)) {
					const range = e.value;
					deco = range
						? deco.update({ filter: (from, to) => to <= range.from || from >= range.to })
						: Decoration.none;
				}
			}
			return deco;
		},
		provide: (f) => EditorView.decorations.from(f)
	});
```

- [ ] **Step 2: Register the field in the editor extensions**

In `onMount`, the extensions array currently lists (line 612-613):

```ts
						highlightField,
						integrityField,
```

Change to:

```ts
						highlightField,
						integrityField,
						pendingField,
```

- [ ] **Step 3: Add the faded CSS**

In the `<style>` block, after the `:global(.cm-integrity-flag)` rule (after line 875), add:

```css
	/* Optimistic-render pending mark: raw dictation shown faded until the polish
	   swaps it for solid text, so it never reads as final. */
	:global(.cm-dictation-pending) {
		opacity: 0.45;
	}
```

- [ ] **Step 4: Type-check (scoped)**

Run: `cd frontend && bun run check 2>&1 | grep -iE "DictationScratchpad|incrementalMerge" || echo "no new errors in touched files"`
Expected: `no new errors in touched files`.

- [ ] **Step 5: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): pending faded-mark decoration field (Phase 2b.3)

Adds the CodeMirror StateField + markPending/clearPending effects + CSS for
rendering optimistically-inserted raw dictation faded. Wiring only; nothing
emits the effects yet, so behavior is unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 3: Optimistic raw insert on `is_final` + resolve clears pending

The core of the feature. Behind `rr_incremental`.

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Import the separator helper**

Line 12 currently:

```ts
	import { mergeIncremental } from '$lib/utils/incrementalMerge';
```

Change to:

```ts
	import { mergeIncremental, rawInsertSeparator } from '$lib/utils/incrementalMerge';
```

- [ ] **Step 2: Insert raw faded text in the `is_final` branch**

In the websocket `onmessage` handler, the `is_final` branch currently ends with (lines 524-536):

```ts
							// Accumulate into session transcript
							const appended = sessionTranscript
								? `${sessionTranscript} ${data.transcript}`
								: data.transcript;
							sessionTranscript =
								appended.length > SESSION_TRANSCRIPT_WINDOW
									? appended.slice(appended.length - SESSION_TRANSCRIPT_WINDOW)
									: appended;

							// Phase 2b.1: fire the polish only at a pause (speech_final), not every
							// is_final — UtteranceEnd (above) is the long-pause backup. Cuts redundant
							// full regenerations; the transcript still accumulates on every chunk.
							if (data.speech_final) processTranscriptQueue();
```

Insert the optimistic block between the `sessionTranscript` assignment and the `speech_final` trigger:

```ts
							// Accumulate into session transcript
							const appended = sessionTranscript
								? `${sessionTranscript} ${data.transcript}`
								: data.transcript;
							sessionTranscript =
								appended.length > SESSION_TRANSCRIPT_WINDOW
									? appended.slice(appended.length - SESSION_TRANSCRIPT_WINDOW)
									: appended;

							// Phase 2b.3: optimistically drop the raw word-group into the active tail,
							// rendered faded, so it lands instantly instead of waiting for the polish.
							// isRecording gates the manual-edit branch, so this never moves the boundary.
							if (incrementalEnabled() && editor) {
								const docLength = editor.state.doc.length;
								const sep = rawInsertSeparator(docLength, committedBoundary);
								const from = docLength + sep.length;
								const to = from + data.transcript.length;
								isQwenWriting = true;
								editor.dispatch({
									changes: { from: docLength, insert: sep + data.transcript },
									effects: markPending.of({ from, to })
								});
								isQwenWriting = false;
							}

							// Phase 2b.1: fire the polish only at a pause (speech_final), not every
							// is_final — UtteranceEnd (above) is the long-pause backup. Cuts redundant
							// full regenerations; the transcript still accumulates on every chunk.
							if (data.speech_final) processTranscriptQueue();
```

- [ ] **Step 3: Clear pending over the resolved span in `processTranscript`**

The resolve dispatch currently (lines 340-343):

```ts
			if (content != null) {
				isQwenWriting = true;
				editor.dispatch({ changes: { from: 0, to: doc.length, insert: content } });
				isQwenWriting = false;
```

Change the dispatch to also clear pending marks over the newly-solid span (`content.length` is the end of the committed+polished region; anything beyond is newer raw that stays faded):

```ts
			if (content != null) {
				isQwenWriting = true;
				editor.dispatch({
					changes: { from: 0, to: doc.length, insert: content },
					effects: useIncremental ? [clearPending.of({ from: 0, to: content.length })] : []
				});
				isQwenWriting = false;
```

- [ ] **Step 4: Type-check (scoped)**

Run: `cd frontend && bun run check 2>&1 | grep -iE "DictationScratchpad|incrementalMerge" || echo "no new errors in touched files"`
Expected: `no new errors in touched files`.

- [ ] **Step 5: Unit tests still green**

Run: `cd frontend && bun run test:unit -- --run --project server`
Expected: PASS (all `incrementalMerge` tests, unchanged).

- [ ] **Step 6: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): optimistic faded raw render + resolve clears pending

is_final groups drop into the active tail faded on arrival; the polish resolve
replaces the sent span with solid text and clears its pending marks. Newer raw
dictated during the polish await stays faded and resolves next pass. Behind
rr_incremental (default off).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 4: Promote-to-solid on stop and on network failure

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Promote pending → solid on stop**

In `stopRecording`, the flush currently reads (lines 581-584):

```ts
		stream = null;
		// Flush: the polish trigger is gated on speech_final, so a quick stop mid-utterance
		// could otherwise drop the last words. Process the final accumulated transcript once.
		if (sessionTranscript.trim()) processTranscriptQueue();
```

Insert the promote before the flush:

```ts
		stream = null;
		// Phase 2b.3: promote any faded raw to solid before handing control back — no
		// pending marks survive the end of recording (the flush polish still cleans it).
		if (editor) editor.dispatch({ effects: clearPending.of(null) });
		// Flush: the polish trigger is gated on speech_final, so a quick stop mid-utterance
		// could otherwise drop the last words. Process the final accumulated transcript once.
		if (sessionTranscript.trim()) processTranscriptQueue();
```

- [ ] **Step 2: Promote pending → solid on network failure**

The `processTranscript` catch currently (lines 351-353):

```ts
			} catch {
				// Superseded (AbortError) or network error — keep raw transcript, surface nothing.
			} finally {
```

Change to distinguish a superseded call (a re-run is queued via `pendingProcess`) from a real failure:

```ts
			} catch {
				// Superseded aborts set pendingProcess and will re-run, so keep the faded raw.
				// A real network error won't re-run — promote the faded raw to solid so it
				// never looks stuck (Phase 2b.3).
				if (useIncremental && !pendingProcess && editor) {
					editor.dispatch({ effects: clearPending.of(null) });
				}
			} finally {
```

- [ ] **Step 3: Type-check (scoped)**

Run: `cd frontend && bun run check 2>&1 | grep -iE "DictationScratchpad|incrementalMerge" || echo "no new errors in touched files"`
Expected: `no new errors in touched files`.

- [ ] **Step 4: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): promote faded raw to solid on stop and network failure

Stop-recording clears pending marks before the flush so no text stays dimmed;
a non-superseded polish failure promotes faded raw to solid rather than leaving
it stuck. Phase 2b.3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 5: Redundancy fix — stop the wasted second polish per utterance

`speech_final` fires a polish; ~1 s later `UtteranceEnd` aborts it and fires another, wasting a full Gemma call. Let the in-flight polish pick up the freeze flag instead of aborting + re-firing.

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Guard the UtteranceEnd polish trigger**

The `utterance_end` branch currently (lines 510-514):

```ts
					if (data.utterance_end) {
						// Deepgram UtteranceEnd: a real pause — freeze the active burst after the
						// next polish (commit rule A), and fire the backup polish.
						freezeAfterNextProcess = true;
						processTranscriptQueue();
					}
```

Change to:

```ts
					if (data.utterance_end) {
						// Deepgram UtteranceEnd: a real pause — freeze the active burst after the
						// next polish (commit rule A). If a polish is already in flight, let it pick
						// up the freeze flag at dispatch (line ~347) rather than aborting + re-firing
						// it, which wasted a full model call per utterance. Only fire fresh if idle.
						freezeAfterNextProcess = true;
						if (!isProcessingQueue) processTranscriptQueue();
					}
```

- [ ] **Step 2: Type-check (scoped)**

Run: `cd frontend && bun run check 2>&1 | grep -iE "DictationScratchpad|incrementalMerge" || echo "no new errors in touched files"`
Expected: `no new errors in touched files`.

- [ ] **Step 3: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "perf(dictation): drop the wasted second polish per utterance

UtteranceEnd now sets the freeze flag and only fires a polish when idle; an
in-flight polish freezes itself via the flag instead of being aborted and
re-run. Saves ~1 Gemma call per utterance. Phase 2b.3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 6: Caption de-dup — drop the redundant raw feed strip

With is_final text now faded in the editor, the caption's `rawFeed` line shows the same text twice. Keep only the live `currentInterim` preview.

**Files:**
- Modify: `frontend/src/lib/components/DictationScratchpad.svelte`

- [ ] **Step 1: Remove the `rawFeed` state and assignment**

Delete the declaration (line 86):

```ts
	let rawFeed: string[] = [];
```

In the `is_final` branch, delete the assignment (line 522) — keep the `currentInterim = '';` line above it:

```ts
							rawFeed = [...rawFeed.slice(-1), data.transcript];
```

- [ ] **Step 2: Replace the caption template block**

The transcript feed currently (lines 820-834):

```svelte
		{#if isRecording && (currentInterim || rawFeed.length > 0)}
			<div class="border-t border-white/[0.05] px-4 py-2 flex flex-col gap-0.5 shrink-0">
				{#if currentInterim}
					<p class="text-xs text-gray-600 italic truncate">{currentInterim}</p>
				{/if}
				{#each rawFeed.slice(-1) as line}
					<p class="text-xs text-gray-500 italic truncate flex items-center gap-1.5">
						{#if isProcessing}
							<span class="w-2 h-2 border border-purple-400 border-t-transparent rounded-full animate-spin inline-block shrink-0"></span>
						{/if}
						{line}{#if isProcessing}…{/if}
					</p>
				{/each}
			</div>
		{/if}
```

Replace with (interim-only; the faded editor text is now the pending indicator):

```svelte
		{#if isRecording && currentInterim}
			<div class="border-t border-white/[0.05] px-4 py-2 flex flex-col gap-0.5 shrink-0">
				<p class="text-xs text-gray-600 italic truncate">{currentInterim}</p>
			</div>
		{/if}
```

- [ ] **Step 3: Type-check (scoped) — confirms no unused-variable / reference errors**

Run: `cd frontend && bun run check 2>&1 | grep -iE "DictationScratchpad|incrementalMerge" || echo "no new errors in touched files"`
Expected: `no new errors in touched files` (no dangling `rawFeed` references).

- [ ] **Step 4: Commit**

```bash
cd /Users/hassan/Code/rapid_reports_ai
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "refactor(dictation): drop redundant raw-feed caption strip

is_final text now renders faded in the editor, so the caption's rawFeed line
duplicated it. Caption keeps only the live interim preview. Phase 2b.3.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Nsw6oNuYx9VFf1sbFMyC6R"
```

---

### Task 7: Manual smoke verification (human)

Not an automated task — this is the human validation gate before considering the feature done. Run the app, open the RadFlow dictation view, and in the browser console enable the flag:

```js
localStorage.setItem('rr_incremental', '1')   // reload after setting
```

- [ ] Dictate a sentence: raw text lands **faded** within ~300 ms of the is_final, then goes **solid** ~1.5 s later when the polish returns.
- [ ] Two utterances render on **separate lines** (regression from the earlier `lobe.The spleen` bug stays fixed).
- [ ] **Reach-back correction** (Phase 2b.2 case: "actually that was 10 mm") still patches the committed text.
- [ ] **Keep talking through the polish window** — newer raw stays faded and resolves on its own next polish; nothing is dropped.
- [ ] **Stop mid-utterance** — faded raw promotes to solid, and the flush polish cleans it.
- [ ] **Network-fail a polish** (DevTools → offline for one utterance) — faded text promotes to solid, never stuck dim.
- [ ] Network panel shows **one** `/process` per utterance (redundancy fix), not two.
- [ ] **GAP-1 model-input check (required):** with the active tail now seeded with raw text, polish quality matches or beats the empty-active baseline — no double-transcription, no dropped corrections, separators correct. If it regresses, fall back to display-only raw (don't send raw active) or clarify the incremental prompt — see spec §5.
- [ ] **Flag off** (`localStorage.removeItem('rr_incremental')`, reload) — behavior is byte-for-byte today (no faded text, caption unchanged in feel).

---

## Self-Review

**Spec coverage:**
- §4.1 pending decoration + caption de-dup → Task 2 (field/CSS), Task 6 (caption). ✓
- §4.2 insert on is_final with shared separator → Task 1 (helper), Task 3 (insert). ✓
- §4.3 resolve reuses snapshot structure + clears pending → Task 3 Step 3. ✓
- §4.4 promote on stop / network failure / reset → Task 4 (stop + failure). *reset()/doc-cleared clearing is covered because those paths dispatch full-doc changes that map pending marks out; the promote lifecycle for recording is the material case — noted, no separate task needed.* ✓
- §4.5 UtteranceEnd de-dup → Task 5. ✓
- §5 model-input validation → Task 7 GAP-1 check. ✓
- §6 testing → Task 1 units + Task 7 manual smoke. ✓

**Placeholder scan:** No TBD/TODO; every code step shows exact code and every gate shows an exact command + expected output. ✓

**Type/name consistency:** `markPending` / `clearPending` / `pendingField` / `cm-dictation-pending` / `rawInsertSeparator` used identically across Tasks 1–6. `clearPending.of(null)` (promote-all) and `clearPending.of({from,to})` (range) match the `StateEffect.define<{from,to}|null>()` signature. `useIncremental` (in `processTranscript`) and `incrementalEnabled()` (in the websocket handler) are the correct in-scope references in each location. ✓
