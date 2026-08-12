<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { EditorView, keymap, Decoration, type DecorationSet } from '@codemirror/view';
	import { EditorState, Compartment, StateEffect, StateField } from '@codemirror/state';
	import IntelliPromptsMargin from './IntelliPromptsMargin.svelte';
	import { markdown } from '@codemirror/lang-markdown';
	import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
	import { syntaxHighlighting, HighlightStyle } from '@codemirror/language';
	import { tags } from '@lezer/highlight';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';
	import { mergeIncremental } from '$lib/utils/incrementalMerge';

	interface IntelliPrompt { question: string; source_text: string; rationale?: string; }

	export let checklistSections: string[] = [];
	export let activePrompts: IntelliPrompt[] = [];
	export let scanType: string = '';
	export let clinicalHistory: string = '';
	export let polishMode: 'clean' | 'structured' = 'clean';
	export let onModeChange: (mode: 'clean' | 'structured') => void = () => {};
	export let apiKeyStatus = { deepgram_configured: false, groq_configured: false };
	export let onContentChange: (content: string) => void = () => {};
	export let onRecordingChange: (isRecording: boolean) => void = () => {};
	export let onCoveredSectionsChange: (covered: string[]) => void = () => {};
	export let onPromptsChange: (prompts: IntelliPrompt[]) => void = () => {};
	export let onScratchpadClear: () => void = () => {};
	export let onReviewingChange: (reviewing: boolean) => void = () => {};

	// CM6 highlight decoration for IntelliPrompt source linking
	const setHighlight = StateEffect.define<{ from: number; to: number } | null>();
	const highlightField = StateField.define<DecorationSet>({
		create: () => Decoration.none,
		update(deco, tr) {
			deco = deco.map(tr.changes);
			for (const e of tr.effects) {
				if (e.is(setHighlight)) {
					deco = e.value
						? Decoration.set([Decoration.mark({ class: 'cm-intelliprompt-hl' }).range(e.value.from, e.value.to)])
						: Decoration.none;
				}
			}
			return deco;
		},
		provide: (f) => EditorView.decorations.from(f)
	});

	// Dictation-integrity marks. A separate field from the IntelliPrompt
	// highlight above, not a reuse of it: the two have different lifetimes
	// (integrity persists while the dictation is flagged; the prompt highlight
	// is transient on click) and must be able to coexist without one clearing
	// the other. Ranges are mapped through document changes so the mark tracks
	// the token as the radiologist keeps typing.
	const setIntegrityMarks = StateEffect.define<{ from: number; to: number }[]>();
	const integrityField = StateField.define<DecorationSet>({
		create: () => Decoration.none,
		update(deco, tr) {
			deco = deco.map(tr.changes);
			for (const e of tr.effects) {
				if (e.is(setIntegrityMarks)) {
					deco = Decoration.set(
						e.value.map((r) =>
							Decoration.mark({ class: 'cm-integrity-flag' }).range(r.from, r.to)
						)
					);
				}
			}
			return deco;
		},
		provide: (f) => EditorView.decorations.from(f)
	});

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

	let editorContainer: HTMLDivElement;
	let editor: EditorView | null = null;
	const editableCompartment = new Compartment();

	// Audio pipeline state
	let isRecording = false;
	let isConnecting = false;
	let isProcessing = false;
	let websocket: WebSocket | null = null;
	let audioContext: AudioContext | null = null;
	let workletNode: AudioWorkletNode | null = null;
	let stream: MediaStream | null = null;
	let dummyAudioEl: HTMLAudioElement | null = null;
	let rawFeed: string[] = [];
	let currentInterim = '';
	let recordingError = '';

	// Microphone device selection
	// Chrome on macOS cannot use Bluetooth headset mics (A2DP/HFP profile conflict).
	// Exposing a device picker lets users choose the built-in mic while keeping headset audio.
	interface AudioDevice { deviceId: string; label: string; }
	let audioDevices: AudioDevice[] = [];
	let selectedDeviceId = 'default';
	let showDevicePicker = false;

	async function loadAudioDevices(): Promise<void> {
		try {
			// Permissions must be granted before labels are populated
			const devices = await navigator.mediaDevices.enumerateDevices();
			audioDevices = devices
				.filter((d) => d.kind === 'audioinput')
				.map((d) => ({
					deviceId: d.deviceId,
					label: d.label || `Microphone (${d.deviceId.slice(0, 8)}…)`
				}));
		} catch {
			// ignore — device list just won't populate
		}
	}

	// Sliding window of recent dictation — last SESSION_TRANSCRIPT_WINDOW chars. The
	// scratchpad is the persistent memory; the model only needs recent context to
	// resolve the current utterance.
	let sessionTranscript = '';
	const SESSION_TRANSCRIPT_WINDOW = 2500;

	// Latest-wins processing: only one Qwen call runs at a time.
	// If new speech arrives while a call is in flight, we record it as pending
	// and make exactly one more call after the current one finishes.
	let isProcessingQueue = false;
	let pendingProcess = false;
	let isQwenWriting = false; // suppresses debounce when Qwen itself updates the editor

	// Same latest-wins pattern for review calls — prevents concurrent Groq requests
	// that return [] and destabilise the side panel.
	let isReviewing = false;
	let pendingReview = false;

	// Debounce timer for typed (non-dictation) edits
	let typingDebounceTimer: ReturnType<typeof setTimeout> | null = null;
	const TYPING_DEBOUNCE_MS = 1000;

	// Content hash to skip redundant /review calls (dictation + typing debounce overlap)
	let lastReviewedHash = '';
	function simpleHash(s: string): string {
		let h = 0;
		for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
		return String(h);
	}

	// Markdown highlight style (from ReportEditor)
	const markdownHighlightStyle = HighlightStyle.define([
		{ tag: tags.heading1, fontSize: '1.15em', fontWeight: '700', color: '#f9fafb' },
		{ tag: tags.heading2, fontSize: '1.05em', fontWeight: '700', color: '#f3f4f6' },
		{ tag: tags.heading3, fontWeight: '700', color: '#e5e7eb' },
		{ tag: tags.heading4, fontWeight: '600', color: '#d1d5db' },
		{ tag: tags.strong, fontWeight: '700', color: '#f3f4f6' },
		{ tag: tags.emphasis, fontStyle: 'italic', color: '#d1d5db' },
		{ tag: tags.strikethrough, textDecoration: 'line-through', color: '#6b7280' },
		{ tag: tags.link, color: '#a78bfa', textDecoration: 'underline' },
		{ tag: tags.url, color: '#818cf8' },
		{
			tag: tags.monospace,
			fontFamily: '"IBM Plex Mono", "Fira Code", ui-monospace, monospace',
			color: '#34d399',
			background: 'rgba(52,211,153,0.08)'
		},
		{ tag: tags.quote, color: '#9ca3af', fontStyle: 'italic' }
	]);

	const darkTheme = EditorView.theme({
		'&': {
			background: 'transparent',
			color: '#e5e7eb',
			fontSize: '0.9rem',
			fontFamily: '"IBM Plex Sans", "Source Sans Pro", system-ui, -apple-system, sans-serif'
		},
		'.cm-content': {
			padding: '0',
			lineHeight: '1.75',
			caretColor: '#a855f7',
			letterSpacing: '0.01em',
			fontFamily: '"IBM Plex Sans", "Source Sans Pro", system-ui, -apple-system, sans-serif',
			fontSize: '0.9rem'
		},
		'.cm-cursor, .cm-dropCursor': {
			borderLeftColor: '#a855f7',
			borderLeftWidth: '2px'
		},
		'&.cm-focused': {
			outline: 'none'
		},
		'.cm-scroller': {
			overflow: 'visible'
		},
		'.cm-line': {
			padding: '0 2px'
		},
		'.cm-selectionBackground': {
			background: 'rgba(168, 85, 247, 0.25) !important'
		},
		'&.cm-focused .cm-selectionBackground': {
			background: 'rgba(168, 85, 247, 0.3) !important'
		},
		'.cm-activeLine': {
			background: 'rgba(255, 255, 255, 0.03)'
		},
		'.cm-gutters': {
			display: 'none'
		},
		'.cm-tooltip': {
			display: 'none'
		}
	});

	export function getContent(): string {
		return editor ? editor.state.doc.toString() : '';
	}

	export function reset(newDoc: string): void {
		if (!editor) return;
		editor.dispatch({
			changes: { from: 0, to: editor.state.doc.length, insert: newDoc }
		});
		// Restored/settled content is frozen; new dictation starts a fresh active tail.
		committedBoundary = newDoc.length;
		// Bypass the typing debounce for restored/reset content — kick off the review immediately
		// so cards appear as soon as the scratchpad is populated rather than waiting 1s + API time.
		if (newDoc.trim().length > 0) {
			if (typingDebounceTimer) { clearTimeout(typingDebounceTimer); typingDebounceTimer = null; }
			processReview();
		}
	}

	export function highlightSource(text: string): void {
		if (!editor || !text) return;
		const doc = editor.state.doc.toString();
		const idx = doc.toLowerCase().indexOf(text.toLowerCase());
		if (idx === -1) return;
		editor.dispatch({
			effects: setHighlight.of({ from: idx, to: idx + text.length }),
			scrollIntoView: true
		});
	}

	export function clearHighlight(): void {
		if (!editor) return;
		editor.dispatch({ effects: setHighlight.of(null) });
	}

	/**
	 * Decorate the spans a dictation-integrity check flagged.
	 *
	 * Ranges are character offsets into the editor document — the check is sent
	 * the raw document text precisely so these map 1:1 and need no re-derivation
	 * here. Out-of-range values are dropped rather than throwing: a response can
	 * land after the radiologist has already deleted the text it describes.
	 */
	export function setIntegrityRanges(ranges: { from: number; to: number }[]): void {
		if (!editor) return;
		const len = editor.state.doc.length;
		const safe = ranges
			.filter((r) => r.from >= 0 && r.to <= len && r.from < r.to)
			.map((r) => ({ from: r.from, to: r.to }));
		editor.dispatch({ effects: setIntegrityMarks.of(safe) });
	}

	export function revealIntegrityRange(range: { from: number; to: number }): void {
		if (!editor) return;
		const len = editor.state.doc.length;
		if (range.from < 0 || range.to > len) return;
		editor.dispatch({ selection: { anchor: range.from, head: range.to }, scrollIntoView: true });
		editor.focus();
	}

	let processAbort: AbortController | null = null;

	// Phase 2b.2 incremental: [0, committedBoundary) is FROZEN; the rest is the mutable ACTIVE tail.
	let committedBoundary = 0;
	// Set on UtteranceEnd (a real pause): freeze the whole active burst after the next polish.
	let freezeAfterNextProcess = false;

	function incrementalEnabled(): boolean {
		return typeof localStorage !== 'undefined' && localStorage.getItem('rr_incremental') === '1';
	}

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
				// Committed text is already clean from prior passes — only the active tail is sanitized.
				// mergeIncremental applies committed_edits verbatim (drop-if-not-found) and rejoins the
				// zones with the one-statement-per-line separator the model no longer emits (was: the
				// zones were concatenated raw, producing "lobe.The spleen").
				const merged = mergeIncremental(committed, sanitize(data.active_scratchpad), data.committed_edits);
				content = merged.content;
				newBoundary = merged.boundary;
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
				// Scratchpad is updated — now fire IntelliPrompts analysis in background.
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

	async function processTranscriptQueue(): Promise<void> {
		if (isProcessingQueue) {
			pendingProcess = true;
			processAbort?.abort();  // cancel the now-stale in-flight polish; the loop re-runs fresh
			return;
		}
		isProcessingQueue = true;
		pendingProcess = false;
		await processTranscript();
		// If new speech landed while we were processing, make one more call with latest context
		while (pendingProcess) {
			pendingProcess = false;
			await processTranscript();
		}
		isProcessingQueue = false;
	}

	// Lightweight pass for manual typing: updates review guide + consider panel only,
	// never rewrites the scratchpad, so the user types uninterrupted.
	async function processReview(): Promise<void> {
		if (isReviewing) {
			pendingReview = true;
			return;
		}
		isReviewing = true;
		pendingReview = false;
		await _runReview();
		while (pendingReview) {
			pendingReview = false;
			await _runReview();
		}
		isReviewing = false;
	}

	async function _runReview(): Promise<void> {
		if (!editor) return;
		const scratchpad_content = editor.state.doc.toString();
		const hashInput = scratchpad_content + checklistSections.join();
		const currentHash = simpleHash(hashInput);
		if (currentHash === lastReviewedHash) return;

		onReviewingChange(true);
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/review`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					scratchpad_content,
					checklist_sections: checklistSections,
					scan_type: scanType,
					clinical_history: clinicalHistory,
					mode: polishMode
				})
			});
			const data = await res.json();
			if (data.covered_sections && Array.isArray(data.covered_sections)) {
				onCoveredSectionsChange(data.covered_sections);
			}
			// Backend now owns the full merge — replace activePrompts with the final merged list
			if (data.prompts && Array.isArray(data.prompts)) {
				onPromptsChange(data.prompts);
			}
			lastReviewedHash = currentHash;
		} catch {
			// silently ignore review errors
		} finally {
			onReviewingChange(false);
		}
	}

	async function startRecording(): Promise<void> {
		// Anything already in the scratchpad is settled — freeze it so dictation never re-authors it.
		committedBoundary = editor ? editor.state.doc.length : 0;
		if (!apiKeyStatus?.deepgram_configured) {
			recordingError = 'Dictation is not available. Contact your administrator.';
			return;
		}
		try {
			recordingError = '';
			isConnecting = true;

			stream = await navigator.mediaDevices.getUserMedia({
				audio: {
					deviceId: selectedDeviceId !== 'default' ? { exact: selectedDeviceId } : undefined,
					echoCancellation: false,
					noiseSuppression: false,
					autoGainControl: false,
					channelCount: 1
				}
			});
			// Populate device list now that permission is granted (labels only appear post-permission)
			await loadAudioDevices();

			// Chrome bug: createMediaStreamSource() produces silence unless the stream is
			// also attached to a playing (muted) audio element first. This forces Chrome's
			// audio pipeline to actually render the MediaStreamTrack before Web Audio taps it.
			// See: https://issues.chromium.org/issues/40799779
			dummyAudioEl = new Audio();
			dummyAudioEl.srcObject = stream;
			dummyAudioEl.muted = true;
			await dummyAudioEl.play().catch(() => {});

			// Use AudioContext + AudioWorkletNode for raw PCM capture.
			// Do NOT force sampleRate: 16000 — external devices (headsets, USB mics) operate
			// at 44100 or 48000 Hz and Chrome goes silent when the context rate doesn't match
			// the device's native rate. Safari resamples transparently; Chrome does not.
			// We read back audioContext.sampleRate and pass it to the backend so Deepgram
			// knows the exact format it's receiving.
			audioContext = new AudioContext();
			await audioContext.audioWorklet.addModule('/pcm-processor.js');
			const source = audioContext.createMediaStreamSource(stream);
			workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');
			source.connect(workletNode);
			workletNode.connect(audioContext.destination);

			const wsUrlBase = API_URL.replace(/^http/, 'ws');
			const sr = audioContext.sampleRate;
			const tokenPart = $token
				? `?token=${encodeURIComponent($token)}&pcm=1&sr=${sr}`
				: `?pcm=1&sr=${sr}`;
			const wsUrl = `${wsUrlBase}/api/transcribe${tokenPart}`;
			websocket = new WebSocket(wsUrl);

			workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
				if (websocket?.readyState === WebSocket.OPEN) {
					websocket.send(event.data);
				}
			};

			websocket.onopen = () => {
				sessionTranscript = '';
				isRecording = true;
				onRecordingChange(true);
				isConnecting = false;
				if (editor) {
					editor.dispatch({
						effects: editableCompartment.reconfigure(EditorView.editable.of(false))
					});
				}
			};

			websocket.onmessage = async (event) => {
				try {
					const data = JSON.parse(event.data);
					if (data.error) {
						recordingError = 'Dictation failed. Please try again.';
						stopRecording();
						return;
					}
					if (data.utterance_end) {
						// Deepgram UtteranceEnd: a real pause — freeze the active burst after the
						// next polish (commit rule A), and fire the backup polish.
						freezeAfterNextProcess = true;
						processTranscriptQueue();
					} else if (data.transcript) {
						if (!data.is_final) {
							// Interim: live preview while speaking
							currentInterim = data.transcript;
						} else {
							// is_final: word-group committed — update display and trigger Qwen immediately
							currentInterim = '';
							rawFeed = [...rawFeed.slice(-1), data.transcript];

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
						}
					}
				} catch {
					// ignore parse errors
				}
			};

			websocket.onerror = () => {
				recordingError = 'Connection error';
				stopRecording();
			};

			websocket.onclose = () => {};
		} catch (err) {
			recordingError = err instanceof Error ? err.message : 'Failed to start recording';
			isConnecting = false;
			onRecordingChange(false);
		}
	}

	function stopRecording(): void {
		isRecording = false;
		onRecordingChange(false);
		isConnecting = false;
		if (workletNode) {
			workletNode.disconnect();
			workletNode = null;
		}
		if (audioContext) {
			audioContext.close();
			audioContext = null;
		}
		if (dummyAudioEl) {
			dummyAudioEl.pause();
			dummyAudioEl.srcObject = null;
			dummyAudioEl = null;
		}
		if (stream) {
			stream.getTracks().forEach((t) => t.stop());
		}
		if (websocket) {
			websocket.close();
			websocket = null;
		}
		stream = null;
		// Flush: the polish trigger is gated on speech_final, so a quick stop mid-utterance
		// could otherwise drop the last words. Process the final accumulated transcript once.
		if (sessionTranscript.trim()) processTranscriptQueue();
		if (editor) {
			editor.dispatch({
				effects: editableCompartment.reconfigure(EditorView.editable.of(true))
			});
		}
	}

	function toggleRecording(): void {
		if (isRecording) {
			stopRecording();
		} else {
			startRecording();
		}
	}

	onMount(() => {
		editor = new EditorView({
			state: EditorState.create({
				doc: '',
				extensions: [
					history(),
					keymap.of([...defaultKeymap, ...historyKeymap]),
					markdown(),
					syntaxHighlighting(markdownHighlightStyle),
					EditorView.lineWrapping,
					editableCompartment.of(EditorView.editable.of(true)),
					darkTheme,
					highlightField,
					integrityField,
					pendingField,
					EditorView.updateListener.of((update) => {
				if (update.docChanged) {
					const content = update.state.doc.toString();
					onContentChange(content);
					if (!isRecording && !isQwenWriting) {
					let hasWordChange = false;
					let charsDeleted = 0;
					const docNowEmpty = update.state.doc.length === 0;
					update.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
						const insertedText = inserted.toString();
						const isListContinuation = /^\n[\t ]*[-*+][\t ]*$/.test(insertedText);
						if (!isListContinuation && /\w/.test(insertedText)) {
							hasWordChange = true;
						}
						if (fromA !== toA) {
							hasWordChange = true;
							charsDeleted += toA - fromA;
						}
					});
					if (docNowEmpty) {
						committedBoundary = 0;
						if (typingDebounceTimer) { clearTimeout(typingDebounceTimer); typingDebounceTimer = null; }
						onScratchpadClear();
					} else if (hasWordChange) {
						// Cards whose source_text is deleted fade out automatically via the anchor filter
						// in IntelliPromptsMargin — no need to clear the prompt list eagerly here.
						// Manual edit: freeze the current doc so dictation never re-authors what was typed.
						committedBoundary = update.state.doc.length;
						if (typingDebounceTimer) clearTimeout(typingDebounceTimer);
						typingDebounceTimer = setTimeout(() => {
							typingDebounceTimer = null;
							processReview();
						}, TYPING_DEBOUNCE_MS);
					}
					}
					}
				})
				]
			}),
			parent: editorContainer
		});
		editor.focus();
	});

	onDestroy(() => {
		if (typingDebounceTimer) clearTimeout(typingDebounceTimer);
		if (editor) {
			editor.destroy();
			editor = null;
		}
		stopRecording();
	});

	function setMode(mode: 'clean' | 'structured') {
		if (mode === polishMode) return;
		polishMode = mode;
		onModeChange(mode);
		// Re-run the polish so the visible scratchpad starts converting to the new mode.
		// (Full re-derivation of long scratchpads waits on Phase 2b's incremental rework.)
		if (editor && editor.state.doc.length > 0) processTranscriptQueue();
	}
</script>

<div class="flex flex-col flex-1 min-h-0">

	<!-- Floating dictate button — centered, overlaps the top edge of the editor+margin row -->
	<div class="flex flex-col items-center gap-1.5 relative z-10">
		<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5" role="group" aria-label="Polish mode">
			<button type="button" onclick={() => setMode('clean')}
				class={polishMode === 'clean'
					? 'px-2.5 py-1 text-xs rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
					: 'px-2.5 py-1 text-xs rounded-md text-gray-400 hover:text-gray-300'}>
				Verbatim
			</button>
			<button type="button" onclick={() => setMode('structured')}
				class={polishMode === 'structured'
					? 'px-2.5 py-1 text-xs rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
					: 'px-2.5 py-1 text-xs rounded-md text-gray-400 hover:text-gray-300'}>
				Structured
			</button>
		</div>
		<button
			type="button"
			onclick={toggleRecording}
			disabled={isConnecting || !apiKeyStatus?.deepgram_configured}
			class="dictate-btn flex items-center gap-2.5 px-6 py-2.5 rounded-full text-white text-sm font-semibold
				transition-all duration-300 select-none
				disabled:opacity-40 disabled:cursor-not-allowed disabled:scale-100
				{isRecording
					? 'bg-gradient-to-r from-red-600 to-rose-600 shadow-lg shadow-red-500/40 hover:shadow-red-500/60 recording-btn'
					: isConnecting
					? 'bg-gradient-to-r from-purple-700 to-blue-700 shadow-md shadow-purple-500/20'
					: 'bg-gradient-to-r from-purple-600 to-blue-600 shadow-lg shadow-purple-500/30 hover:shadow-purple-500/50 hover:scale-[1.04] hover:from-purple-500 hover:to-blue-500'}"
			title={isRecording ? 'Stop Dictation' : 'Start Dictation'}
		>
			{#if isConnecting}
				<!-- Connecting spinner -->
				<svg class="w-4 h-4 animate-spin shrink-0" fill="none" viewBox="0 0 24 24">
					<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
					<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
				</svg>
				<span>Connecting</span>
			{:else if isRecording}
				<!-- Animated sound bars -->
				<span class="flex items-end gap-[3px] h-4 shrink-0">
					<span class="sound-bar w-[3px] rounded-full bg-white/90" style="animation-delay: 0ms"></span>
					<span class="sound-bar w-[3px] rounded-full bg-white/90" style="animation-delay: 150ms"></span>
					<span class="sound-bar w-[3px] rounded-full bg-white/90" style="animation-delay: 300ms"></span>
					<span class="sound-bar w-[3px] rounded-full bg-white/90" style="animation-delay: 150ms"></span>
					<span class="sound-bar w-[3px] rounded-full bg-white/90" style="animation-delay: 0ms"></span>
				</span>
				<span>Recording — tap to stop</span>
			{:else}
				<!-- Mic icon -->
				<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
						d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
				</svg>
			{/if}
		</button>
		{#if recordingError}
			<p class="text-xs text-red-400">{recordingError}</p>
		{/if}

		<!-- Mic device picker — shown below the button when not recording -->
		{#if !isRecording && !isConnecting && audioDevices.length > 1}
			<div class="flex items-center gap-1.5 mt-0.5">
				{#if showDevicePicker}
					<select
						bind:value={selectedDeviceId}
						class="text-xs bg-black/40 border border-white/10 text-gray-300 rounded-lg px-2 py-1 max-w-[220px] truncate focus:outline-none focus:border-purple-500/50"
					>
						{#each audioDevices as d}
							<option value={d.deviceId}>{d.label}</option>
						{/each}
					</select>
					<button
						type="button"
						onclick={() => (showDevicePicker = false)}
						class="text-gray-500 hover:text-gray-300 transition-colors"
						title="Close"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				{:else}
					<button
						type="button"
						onclick={() => (showDevicePicker = true)}
						class="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
						title="Change microphone"
					>
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
								d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
						</svg>
						<span class="truncate max-w-[160px]">
							{audioDevices.find((d) => d.deviceId === selectedDeviceId)?.label ?? 'Default mic'}
						</span>
						<svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</button>
				{/if}
			</div>
		{/if}
	</div>

	<!-- CM6 scratchpad wrapper — overlapped from above by the button -->
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div
		class="scratchpad-wrapper -mt-[22px] flex-1 rounded-xl border overflow-hidden transition-all duration-300 min-h-[360px] flex flex-col cursor-text {isRecording
			? 'border-purple-500/50 dictation-glow'
			: 'border-white/10 bg-black/40'}"
		onclick={(e) => { if (e.target === e.currentTarget || !(e.target as Element).closest('.cm-editor')) editor?.focus(); }}
	>
		<!-- Scroll container — holds both the editor and the margin so they scroll together.
		     This means card overflow is never clipped: the area simply becomes scrollable. -->
		<div class="flex-1 min-h-0 overflow-auto pb-4 pt-8">
			<div class="flex flex-row items-start min-h-full">

				<!-- Editor column -->
				<div class="flex-1 min-h-full pl-4 pr-4">
					<div bind:this={editorContainer} class="min-h-full"></div>
				</div>

				<!-- Margin column — width animates open/closed; stops click bubbling to editor focus handler -->
				<div
					class="shrink-0 overflow-hidden"
					style="width: {activePrompts.length > 0 ? '240px' : '0px'}; transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1)"
					onclick={(e) => e.stopPropagation()}
				>
					<IntelliPromptsMargin
						{activePrompts}
						{editor}
						{isReviewing}
						onHighlight={highlightSource}
						onClearHighlight={clearHighlight}
					/>
				</div>

			</div>
		</div>

		<!-- Inline transcript feed at the bottom of the box — only when dictation is on -->
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
	</div>

</div>

<style>
	@keyframes dictationGlow {
		0%, 100% { box-shadow: 0 0 20px rgba(139, 92, 246, 0.3), 0 0 40px rgba(139, 92, 246, 0.2); }
		50%       { box-shadow: 0 0 30px rgba(139, 92, 246, 0.5), 0 0 60px rgba(139, 92, 246, 0.3); }
	}
	.dictation-glow { animation: dictationGlow 2s ease-in-out infinite; }

	/* Sound wave bars */
	@keyframes soundBar {
		0%, 100% { height: 4px; }
		50%       { height: 14px; }
	}
	.sound-bar { animation: soundBar 0.7s ease-in-out infinite; height: 4px; }

	/* Subtle recording pulse on the button itself */
	@keyframes recordingPulse {
		0%, 100% { box-shadow: 0 0 12px rgba(239, 68, 68, 0.5), 0 4px 20px rgba(239, 68, 68, 0.3); }
		50%       { box-shadow: 0 0 24px rgba(239, 68, 68, 0.7), 0 4px 28px rgba(239, 68, 68, 0.4); }
	}
	.recording-btn { animation: recordingPulse 1.6s ease-in-out infinite; }

	:global(.cm-intelliprompt-hl) {
		background: rgba(251, 191, 36, 0.22);
		border-radius: 2px;
		outline: 1px solid rgba(251, 191, 36, 0.4);
	}

	/* Dictation-integrity mark. Deliberately a squiggle rather than the block
	   fill used above: the two can appear at once, and the proofreading idiom
	   reads as "look here" without claiming the text is wrong. */
	:global(.cm-integrity-flag) {
		text-decoration: underline wavy rgba(251, 146, 60, 0.85);
		text-decoration-skip-ink: none;
		text-underline-offset: 3px;
		background: rgba(251, 146, 60, 0.1);
		border-radius: 2px;
	}

	/* Optimistic-render pending mark: raw dictation shown faded until the polish
	   swaps it for solid text, so it never reads as final. */
	:global(.cm-dictation-pending) {
		opacity: 0.45;
	}

</style>
