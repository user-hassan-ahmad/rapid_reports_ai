# Dictation Phase 2b.2 (frontend) — Activate incremental processing behind a client flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan. Steps use checkbox (`- [ ]`) syntax. No unit-test framework on the frontend — each task verifies with `svelte-check` on the touched file plus a manual-smoke protocol at the end.

**Goal:** Turn on the incremental `/process` path (backend already merged, dormant): split the scratchpad into a frozen **committed** prefix and a mutable **active** tail, send both, apply the model's `committed_edits` + `active_scratchpad`, and **freeze the active burst on `UtteranceEnd`** (commit rule A) — all behind a **localStorage client flag** (`rr_incremental=1`), default OFF, so full regeneration stays the default until we've A/B'd it.

**Architecture:** All changes are in `frontend/src/lib/components/DictationScratchpad.svelte`. A `committedBoundary` char offset marks where frozen ends / active begins. When the flag is off, behaviour is byte-for-byte today's (no `committed_context` sent → backend full path). The freeze guarantee is preserved because committed text is only ever changed by applying a verbatim `committed_edit` (locate-and-replace, drop-if-not-found).

**Tech Stack:** SvelteKit, CodeMirror, localStorage. Backend contract (already on main): request `committed_context`; response `CanvasIncrementalResponse { active_scratchpad, committed_edits: [{original, corrected}] }`.

**Spec/design:** `docs/superpowers/specs/2026-08-09-...` §7.3; backend plan `docs/superpowers/plans/2026-08-10-dictation-phase2b2-incremental-backend.md`. In-session decision: commit rule **A (freeze-on-`UtteranceEnd`)**, no regex (model patches committed).

**Frontend check:** `npm run check` from `frontend/` (~1200 pre-existing errors unrelated to this — judge only `DictationScratchpad`).

---

## File Structure
Modify only `frontend/src/lib/components/DictationScratchpad.svelte`:
- State: `committedBoundary`, `freezeAfterNextProcess`, `incrementalEnabled()` helper (near `processAbort`, line 265).
- `processTranscript` (267-318): branch on the flag — build incremental body, apply the incremental response, update the boundary.
- `websocket.onmessage` `utterance_end` branch (469): set `freezeAfterNextProcess`.
- Boundary resets: `reset()` (211), `startRecording()` (392), the manual-edit + clear branches of the `updateListener` (571-599).

---

## Task 1: State + flag helper

**Files:** Modify `DictationScratchpad.svelte:265`.

- [ ] **Step 1: Add state + helper** — replace line 265 (`let processAbort...`) with:

```javascript
	let processAbort: AbortController | null = null;

	// Phase 2b.2 incremental: [0, committedBoundary) is FROZEN; the rest is the mutable ACTIVE tail.
	let committedBoundary = 0;
	// Set on UtteranceEnd (a real pause): freeze the whole active burst after the next polish.
	let freezeAfterNextProcess = false;

	function incrementalEnabled(): boolean {
		return typeof localStorage !== 'undefined' && localStorage.getItem('rr_incremental') === '1';
	}
```

- [ ] **Step 2: svelte-check** — `cd frontend && npm run check 2>&1 | grep -i DictationScratchpad | grep -i error || echo clean`. Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): incremental client flag + committed-boundary state (default off)"
```

---

## Task 2: Incremental `processTranscript`

**Files:** Modify `DictationScratchpad.svelte:267-318` (the whole `processTranscript`).

- [ ] **Step 1: Replace `processTranscript`** (lines 267-318) with:

```javascript
	async function processTranscript(): Promise<void> {
		if (!editor) return;
		isProcessing = true;
		recordingError = '';
		const controller = new AbortController();
		processAbort = controller;
		const useIncremental = incrementalEnabled();
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const doc = editor.state.doc.toString();
			const boundary = useIncremental ? Math.min(committedBoundary, doc.length) : 0;
			const committed = doc.slice(0, boundary);
			const active = doc.slice(boundary);

			const body: Record<string, unknown> = {
				session_transcript: sessionTranscript,
				scratchpad_content: useIncremental ? active : doc,
				scan_type: scanType,
				clinical_history: clinicalHistory,
				preferred_section_names: checklistSections,
				mode: polishMode
			};
			if (useIncremental) body.committed_context = committed;

			const res = await fetch(`${API_URL}/api/canvas/process`, {
				method: 'POST',
				headers,
				signal: controller.signal,
				body: JSON.stringify(body)
			});
			const data = await res.json();

			const sanitize = (s: string): string =>
				s
					.split('\n')
					.filter((line: string) => !/^[-*_]{3,}\s*$/.test(line.trim()))
					.map((line: string) => line.replace(/\*\*/g, '').replace(/^_{1,2}|_{1,2}$/g, ''))
					.join('\n');

			let content: string | null = null;
			let newBoundary = 0;
			if (useIncremental && data.active_scratchpad != null) {
				// Apply committed_edits verbatim (drop-if-not-found), then splice the active tail back.
				// Committed text is already clean from prior passes — only the active tail is sanitized.
				let editedCommitted = committed;
				for (const e of (data.committed_edits ?? [])) {
					if (!e || !e.original) continue;
					const idx = editedCommitted.lastIndexOf(e.original);
					if (idx !== -1) {
						editedCommitted =
							editedCommitted.slice(0, idx) + (e.corrected ?? '') + editedCommitted.slice(idx + e.original.length);
					}
				}
				content = editedCommitted + sanitize(data.active_scratchpad);
				newBoundary = editedCommitted.length;
			} else if (data.scratchpad != null) {
				content = sanitize(data.scratchpad);
			}

			if (content != null) {
				isQwenWriting = true;
				editor.dispatch({ changes: { from: 0, to: doc.length, insert: content } });
				isQwenWriting = false;
				if (useIncremental) {
					// Freeze-on-pause (rule A): an UtteranceEnd-triggered polish freezes the whole
					// burst; otherwise keep the boundary at the (possibly edit-shifted) committed end.
					committedBoundary = freezeAfterNextProcess ? content.length : Math.min(newBoundary, content.length);
					freezeAfterNextProcess = false;
				}
				processReview();
			}
			if (data.covered_sections && Array.isArray(data.covered_sections)) {
				onCoveredSectionsChange(data.covered_sections);
			}
		} catch {
			// Superseded (AbortError) or network error — keep raw transcript, surface nothing.
		} finally {
			if (processAbort === controller) processAbort = null;
			isProcessing = false;
		}
	}
```

- [ ] **Step 2: svelte-check** — `npm run check 2>&1 | grep -i DictationScratchpad | grep -i error || echo clean`. Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): incremental processTranscript (committed/active split + patch apply)"
```

---

## Task 3: Freeze on `UtteranceEnd` + boundary resets

**Files:** Modify `DictationScratchpad.svelte` — `utterance_end` branch (469), `reset()` (211), `startRecording()` (392), the `updateListener` clear + manual-edit branches (590-593).

- [ ] **Step 1: Freeze on UtteranceEnd** — replace the `utterance_end` branch (line 469-471):

```javascript
					if (data.utterance_end) {
						// Deepgram UtteranceEnd: a real pause — freeze the active burst after the
						// next polish (commit rule A), and fire the backup polish.
						freezeAfterNextProcess = true;
						processTranscriptQueue();
```

(keep the existing `} else if (data.transcript) {` that follows.)

- [ ] **Step 2: Freeze existing content on `reset()`** — in `reset(newDoc)` (line 211), after the `editor.dispatch(...)` that inserts `newDoc`, add:

```javascript
		// Restored/settled content is frozen; new dictation starts a fresh active tail.
		committedBoundary = newDoc.length;
```

- [ ] **Step 3: Freeze existing content on `startRecording()`** — at the top of `startRecording()` (line 392, after the opening brace), add:

```javascript
		// Anything already in the scratchpad is settled — freeze it so dictation never re-authors it.
		committedBoundary = editor ? editor.state.doc.length : 0;
```

- [ ] **Step 4: Boundary on manual edits + clear** — in the `updateListener` (571-599): in the `docNowEmpty` branch (line 590) add `committedBoundary = 0;`, and in the `else if (hasWordChange)` branch (line 593) add `committedBoundary = update.state.doc.length;` (a manual edit re-freezes the whole doc — safe: nothing already typed gets re-authored; new dictation continues as active). Result:

```javascript
						if (docNowEmpty) {
							committedBoundary = 0;
							if (typingDebounceTimer) { clearTimeout(typingDebounceTimer); typingDebounceTimer = null; }
							onScratchpadClear();
						} else if (hasWordChange) {
							// Manual edit: freeze the current doc so the model never re-authors what the
							// radiologist typed; new dictation appends a fresh active tail.
							committedBoundary = update.state.doc.length;
							if (typingDebounceTimer) clearTimeout(typingDebounceTimer);
							typingDebounceTimer = setTimeout(() => {
								typingDebounceTimer = null;
								processReview();
```

(Only the two `committedBoundary` lines are added; the rest is context.)

- [ ] **Step 5: svelte-check** — `npm run check 2>&1 | grep -i DictationScratchpad | grep -i error || echo clean`. Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/DictationScratchpad.svelte
git commit -m "feat(dictation): freeze-on-UtteranceEnd + boundary resets (reset/start/manual-edit)"
```

---

## Task 4: Manual-smoke protocol (flag ON)

No automated frontend tests — validate on the deployed build. Enable the flag in the browser console: `localStorage.setItem('rr_incremental','1')`, reload.

- [ ] **Freeze holds:** dictate 3–4 findings with pauses between them. Watch the logs — after the first finding + pause you should see `[canvas.process] … incremental=true active_chars=<small> committed_chars=<growing>`. Confirm earlier findings' text does **not** change as you dictate later ones.
- [ ] **Correction reaches back:** after several findings, dictate a correction to an *early* (frozen) one ("actually, the pancreatic mass was 6 cm"). Confirm the frozen line updates (a `committed_edit` applied) and nothing else moves.
- [ ] **Comparison stays:** dictate "it was 5 mm on the prior, now 10 mm" → both values remain (not treated as a correction).
- [ ] **Manual edit safe:** hand-edit an earlier line, then dictate more → your edit persists (frozen), new dictation appends.
- [ ] **Flag OFF = today:** `localStorage.removeItem('rr_incremental')`, reload → logs show `incremental=false`, behaviour identical to current full regeneration.

If freeze/patch behaves, we flip the flag default to on in a follow-up. If a boundary edge case misbehaves (e.g. mid-finding pause fragments a finding, or sanitize shifts the boundary), note it — those are the known rough edges to refine before defaulting on.

---

## Self-Review
- **Spec §7.3 (frontend half):** committed/active split + send ✅ (Task 2); apply patch-edits verbatim ✅ (Task 2); freeze-on-pause ✅ (Task 3); flag-gated, full path unchanged when off ✅ (Task 2 `useIncremental` branches).
- **Placeholder scan:** none — full target code given. The manual-smoke "flip default later" is a deliberate rollout gate, not a placeholder.
- **Consistency:** `committedBoundary` is a char offset everywhere; set to `doc.length`/`newDoc.length` (freeze) or `editedCommitted.length` (post-patch) or `0` (clear/full); read only under `useIncremental`. `incrementalEnabled()` is the single flag source.
- **Known rough edges (documented, behind flag):** mid-finding pause can freeze early; a committed line that is not verbatim-locatable drops its edit (safe); manual edit freezes the whole doc (conservative). All acceptable for a flag-gated A/B; refine before defaulting on.

---

## Execution Handoff
Inline (with checkpoints) — same as the backend. After the manual-smoke holds and we've watched real sessions, a one-line follow-up flips the flag default to on.
