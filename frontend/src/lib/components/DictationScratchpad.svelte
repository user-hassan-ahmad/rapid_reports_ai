<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { computeDelta } from '$lib/dictation-lab/delta';
	import { toRequestFields } from '$lib/dictation-lab/labConfig';
	import type { ChunkTrace, CoverageTrace, LabConfig, ProcessTrace, TriageTrace, UtteranceResponse } from '$lib/dictation-lab/types';
	import {
		applyBoundary,
		endsWithTerminalPunctuation,
		flushBuffer,
		lastNonEmptyLine,
		nextSilenceStep,
		silenceVerdict
	} from '$lib/dictation-lab/frontDoor';
	import {
		EDIT_WINDOW_MS,
		REDICTATE_WINDOW_MS,
		asrFields,
		changedRange,
		applyAsrFixes,
		commandInsert,
		flagRanges,
		committedEditChanges,
		isUnfinishedCorrection,
		jevContext,
		openStatement,
		splitSpan,
		hash8,
		isRedictation,
		keytermQuery,
		deletePrevious,
		keytermCaseKey,
		separatorFor,
		substituteLast,
		tokenSet,
		type AsrFields,
		type BundleRouteResponse,
		type DecisionRecord,
		type FastRoute,
		type LineClosedBy,
		type OutcomeEvent
	} from '$lib/dictation-lab/decisionFirst';
	import { EditorView, keymap, Decoration, type DecorationSet, type ViewUpdate } from '@codemirror/view';
	import { clearPending, markPending, pendingField, replaceAndClear } from '$lib/dictation-lab/pendingMarks';
	import { EditorState, Compartment, Prec, StateEffect, StateField } from '@codemirror/state';
	import IntelliPromptsMargin from './IntelliPromptsMargin.svelte';
	import { markdown } from '@codemirror/lang-markdown';
	import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
	import { syntaxHighlighting, HighlightStyle } from '@codemirror/language';
	import { tags } from '@lezer/highlight';
	import { token } from '$lib/stores/auth';
	import { acceptBuild, emptyStructured, isCurrent, noteEdit, shouldBuild, startBuild, type StructuredState } from '$lib/utils/structuredView';
	import { API_URL } from '$lib/config';

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
	/** Dictation Lab only. null in production: nothing is added to the request. */
	export let labConfig: LabConfig | null = null;
	/** Dictation Lab only. Called once per completed /process call. */
	export let onProcessTrace: (trace: ProcessTrace) => void = () => {};
	/** Dictation Lab only. Per-section scores from the selected coverage candidate. */
	export let onCoverageScoresChange: (scores: Record<string, number> | null) => void = () => {};
	/** Dictation Lab only. Both candidates' coverage results when coverage_debug is on. */
	export let onCoverageTrace: (trace: CoverageTrace) => void = () => {};
	/** Dictation Lab only. One record per finalised chunk when the front door is 'jev'. */
	export let onChunkTrace: (trace: ChunkTrace) => void = () => {};
	/** Dictation Lab only, front door 'decision': one record per routed utterance, re-sent
	 *  (same id) when it changes. `display` is the utterance for the panel; never exported. */
	export let onDecision: (record: DecisionRecord, display: string) => void = () => {};
	/** Dictation Lab only, front door 'decision': undo / edit / re-dictation against a decision id. */
	export let onOutcome: (event: OutcomeEvent) => void = () => {};

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
	// markPending / clearPending / pendingField live in $lib/dictation-lab/pendingMarks.

	// Decision-first (lab): text written by an automatic action (fast-append, command) is
	// marked for the edit window, so what the machine did is visible while it can still be
	// undone. Same map-through-changes lifecycle as the pending mark.
	const markAuto = StateEffect.define<{ from: number; to: number }>();
	const clearAuto = StateEffect.define<{ from: number; to: number }>();
	const autoField = StateField.define<DecorationSet>({
		create: () => Decoration.none,
		update(deco, tr) {
			deco = deco.map(tr.changes);
			for (const e of tr.effects) {
				if (e.is(markAuto)) {
					deco = deco.update({ add: [Decoration.mark({ class: 'cm-dictation-auto' }).range(e.value.from, e.value.to)] });
				} else if (e.is(clearAuto)) {
					const r = e.value;
					deco = deco.update({ filter: (from, to) => to <= r.from || from >= r.to });
				}
			}
			return deco;
		},
		provide: (f) => EditorView.decorations.from(f)
	});

	// Word-sense spotter (lab): words Jev says make no clinical sense as heard and that no
	// fix was found for, underlined so the radiologist checks them. Mapped through edits.
	const markAsrFlag = StateEffect.define<{ from: number; to: number }>();
	const asrFlagField = StateField.define<DecorationSet>({
		create: () => Decoration.none,
		update(deco, tr) {
			deco = deco.map(tr.changes);
			for (const e of tr.effects) {
				if (e.is(markAsrFlag)) {
					deco = deco.update({ add: [Decoration.mark({ class: 'cm-asr-flag' }).range(e.value.from, e.value.to)] });
				}
			}
			return deco;
		},
		provide: (f) => EditorView.decorations.from(f)
	});
	function underlineFlags(at: number, text: string, flags: { word: string }[] | undefined): number {
		if (!editor || !flags?.length) return 0;
		const ranges = flagRanges(text, flags).map((r) => markAsrFlag.of({ from: at + r.from, to: at + r.to }));
		if (ranges.length) editor.dispatch({ effects: ranges });
		return ranges.length;
	}

	let editorContainer: HTMLDivElement;
	let editor: EditorView | null = null; // always the verbatim text: dictation, polish and undo work here

	// Structured view: a second editor holding text derived from the verbatim text, so the
	// toggle never re-polishes (or loses) either one. Plan: 2026-09-27-verbatim-structured-views.md
	let structuredContainer: HTMLDivElement;
	let structuredEditor: EditorView | null = null;
	let structured: StructuredState = emptyStructured();
	let structuredWanted = polishMode === 'structured'; // no background rebuilds until Structured is used
	let structuredTimer: ReturnType<typeof setTimeout> | null = null;
	let writingStructured = false;
	let structuredNotice = '';
	let verbatimNow = '';
	const STRUCTURE_DEBOUNCE_MS = 1500;
	$: structuredStale = polishMode === 'structured' && !!verbatimNow.trim() && !isCurrent(structured, verbatimNow);
	// The parent can set the mode too (a draft restored in Structured view): build for it.
	$: if (polishMode === 'structured' && editor) {
		structuredWanted = true;
		scheduleStructure(0);
	}
	function visibleEditor(): EditorView | null {
		return polishMode === 'structured' ? structuredEditor : editor;
	}
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
	// Transcript as of the last /process call that completed, so the next call can
	// send the delta as `last_utterance` (triage only; never affects the live response).
	let lastSentTranscript = '';
	let traceSeq = 0;
	// Front door (lab): chunks held until Jev says the statement is complete.
	let chunkBuffer: string[] = [];
	let pendingUtterance: string | null = null;
	let chunkSeq = 0;
	let backstopTimer: ReturnType<typeof setTimeout> | null = null;
	let silenceStep = 0;
	let classifyChain: Promise<void> = Promise.resolve();
	function frontDoorIsJev(): boolean {
		return labConfig?.frontDoor === 'jev';
	}

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

	/** The view on screen (Generate Report uses what the user is looking at). */
	export function getContent(): string {
		if (polishMode === 'structured' && structuredEditor && structured.text !== null) {
			return structuredEditor.state.doc.toString();
		}
		return editor ? editor.state.doc.toString() : '';
	}

	export function reset(newDoc: string): void {
		if (!editor) return;
		structured = emptyStructured();
		showStructured('');
		editor.dispatch({
			changes: { from: 0, to: editor.state.doc.length, insert: newDoc }
		});
		// Bypass the typing debounce for restored/reset content — kick off the review immediately
		// so cards appear as soon as the scratchpad is populated rather than waiting 1s + API time.
		if (newDoc.trim().length > 0) {
			if (typingDebounceTimer) { clearTimeout(typingDebounceTimer); typingDebounceTimer = null; }
			processReview();
		}
	}

	export function highlightSource(text: string): void {
		const view = visibleEditor();
		if (!view || !text) return;
		const doc = view.state.doc.toString();
		const idx = doc.toLowerCase().indexOf(text.toLowerCase());
		if (idx === -1) return;
		view.dispatch({
			effects: setHighlight.of({ from: idx, to: idx + text.length }),
			scrollIntoView: true
		});
	}

	export function clearHighlight(): void {
		const view = visibleEditor();
		if (!view) return;
		view.dispatch({ effects: setHighlight.of(null) });
	}

	/**
	 * Decorate the spans a dictation-integrity check flagged.
	 *
	 * Ranges are character offsets into the editor document — the check is sent
	 * the raw document text precisely so these map 1:1 and need no re-derivation
	 * here. Out-of-range values are dropped rather than throwing: a response can
	 * land after the radiologist has already deleted the text it describes.
	 */
	// The check runs on the text on screen (onContentChange follows the view), so its offsets
	// index the visible editor; the hidden one is cleared.
	export function setIntegrityRanges(ranges: { from: number; to: number }[]): void {
		const view = visibleEditor();
		if (!view) return;
		const len = view.state.doc.length;
		const safe = ranges
			.filter((r) => r.from >= 0 && r.to <= len && r.from < r.to)
			.map((r) => ({ from: r.from, to: r.to }));
		view.dispatch({ effects: setIntegrityMarks.of(safe) });
		const hidden = view === editor ? structuredEditor : editor;
		hidden?.dispatch({ effects: setIntegrityMarks.of([]) });
	}

	export function revealIntegrityRange(range: { from: number; to: number }): void {
		const view = visibleEditor();
		if (!view) return;
		const len = view.state.doc.length;
		if (range.from < 0 || range.to > len) return;
		view.dispatch({ selection: { anchor: range.from, head: range.to }, scrollIntoView: true });
		view.focus();
	}

	let processAbort: AbortController | null = null;

	// Phase 2b.3: faded optimistic render on the full-regeneration path. When enabled,
	// raw is_final groups are shown faded immediately and the polish rewrites the whole
	// scratchpad, replacing them with coherent solid text. No freezing.
	function fadedEnabled(): boolean {
		// Decision-first always renders faded: every final shows before its route is known.
		if (decisionFirst()) return true;
		return typeof localStorage !== 'undefined' && localStorage.getItem('rr_incremental') === '1';
	}

	/**
	 * One committed word-group from the speech engine (or from the lab feeder).
	 * Accumulates into the session transcript, renders it faded when Phase 2b.3 is
	 * on, and fires the polish at a pause. This is the body the websocket handler
	 * used to hold inline; it moved so the lab can drive it without a microphone.
	 */
	function handleFinalTranscript(transcript: string, speechFinal: boolean, asr: AsrFields | null = null): void {
		currentInterim = '';

		// Accumulate into session transcript
		const appended = sessionTranscript ? `${sessionTranscript} ${transcript}` : transcript;
		sessionTranscript =
			appended.length > SESSION_TRANSCRIPT_WINDOW
				? appended.slice(appended.length - SESSION_TRANSCRIPT_WINDOW)
				: appended;

		// Phase 2b.3: optimistically drop the raw word-group into the doc, rendered
		// faded, so it lands instantly instead of waiting for the polish. The whole
		// raw region is display-only — excluded from the model input and replaced by
		// the polish (see processTranscript). isRecording gates the manual-edit branch.
		if (fadedEnabled() && editor) {
			const docLength = editor.state.doc.length;
			const pend = editor.state.field(pendingField, false);
			const hasPending = !!pend && pend.size > 0;
			// New utterance starts on its own faded line; groups within one are space-joined.
			// Decision-first continues the text instead, so a fast-append lands where it showed.
			const sep =
				docLength === 0
					? ''
					: decisionFirst()
						? /\s$/.test(editor.state.doc.toString()) ? '' : ' '
						: hasPending
							? ' '
							: '\n';
			const to = docLength + sep.length + transcript.length;
			isQwenWriting = true;
			editor.dispatch({
				changes: { from: docLength, insert: sep + transcript },
				effects: markPending.of({ from: docLength, to })
			});
			isQwenWriting = false;
			// Decision-first: remember where this final sits (mapped through later changes),
			// so its decision can show Jev everything before it, faded words included.
			if (decisionFirst()) chunkRanges.set(++chunkRangeSeq, { from: docLength + sep.length, to });
		}

		// Phase 2b.1: fire the polish only at a pause (speech_final), not every
		// is_final — UtteranceEnd is the long-pause backup. Cuts redundant
		// full regenerations; the transcript still accumulates on every chunk.
		if (decisionFirst()) {
			// New speech: the silence the line-close timers were counting has ended.
			clearLineTimers();
			const arrivedAt = Date.now();
			const rangeId = chunkRangeSeq;
			if (heldCorrection) clearTimeout(heldCorrection.timer); // speech resumed: the next decision joins it
			decisionChain = decisionChain
				.then(() => decideUtterance(transcript, arrivedAt, asr, rangeId))
				.catch(() => {})
				.finally(() => {
					for (const k of [...chunkRanges.keys()]) {
						if (k <= rangeId && k !== heldCorrection?.rangeId) chunkRanges.delete(k);
					}
				});
			return;
		}
		if (frontDoorIsJev()) {
			// Serialise so decisions see the buffer in arrival order.
			classifyChain = classifyChain.then(() => classifyChunk(transcript)).catch(() => {});
			return;
		}
		if (speechFinal) processTranscriptQueue();
	}

	/** Dictation Lab: feed text exactly as a Deepgram final word-group would arrive. */
	export function injectTranscript(text: string, speechFinal = true): void {
		const t = text.trim();
		if (!t) return;
		handleFinalTranscript(t, speechFinal);
	}

	function clearSilence(): void {
		if (backstopTimer) {
			clearTimeout(backstopTimer);
			backstopTimer = null;
		}
		silenceStep = 0;
	}

	/** After a `continues`: re-ask at each silence milestone; send without asking at the hard limit. */
	function armSilence(): void {
		if (backstopTimer) clearTimeout(backstopTimer);
		const { delayMs, silenceS } = nextSilenceStep(silenceStep);
		backstopTimer = setTimeout(() => {
			backstopTimer = null;
			if (silenceS === null) {
				forceFlush();
				return;
			}
			silenceStep += 1;
			classifyChain = classifyChain.then(() => classifyBuffered(silenceS)).catch(() => {});
		}, delayMs);
	}

	function forceFlush(): void {
		const { sends, buffer } = flushBuffer(chunkBuffer);
		chunkBuffer = buffer;
		silenceStep = 0;
		for (const send of sends) {
			onChunkTrace({
				seq: ++chunkSeq, at: Date.now(), chunk: '', buffered: send, resolved: 'complete', boundary: null,
				confidence: null, asr_risk: null, latency_ms: 0, error: null, sent: send, viaBackstop: true,
				placement: null, placement_confidence: null, silence_s: SILENCE_HARD_LIMIT, standalone: null, via: 'hard_limit'
			});
			enqueueUtterance(send);
		}
	}
	const SILENCE_HARD_LIMIT = 5;

	function scratchpadTail(): string {
		const doc = editor ? editor.state.doc.toString() : '';
		let pendingStart = doc.length;
		editor?.state.field(pendingField, false)?.between(0, doc.length, (from) => {
			pendingStart = from;
			return false;
		});
		return lastNonEmptyLine(doc.slice(0, pendingStart));
	}

	async function askBoundary(buffered: string, chunk: string, silenceS: number): Promise<UtteranceResponse> {
		let data: UtteranceResponse = {
			resolved: 'complete', boundary: null, confidence: null, probabilities: null, asr_risk: null, latency_ms: null, error: null
		};
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/utterance`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ scan_type: scanType, buffered, chunk, scratchpad_tail: scratchpadTail(), silence_s: silenceS })
			});
			if (res.ok) data = (await res.json()) as UtteranceResponse;
			else data.error = `http ${res.status}`;
		} catch (e) {
			data.error = (e as Error).name;
		}
		return data;
	}

	function applyDecision(buffer: string[], chunk: string, data: UtteranceResponse, silenceS: number, buffered: string, t0: number): void {
		// Time and punctuation are decided here, not by the model.
		let resolved = data.resolved;
		let via: 'jev' | 'punctuation' | 'silence' = 'jev';
		if (silenceS > 0) {
			if (resolved === 'continues' && silenceVerdict(data.standalone, silenceS) === 'send') resolved = 'complete';
			via = 'silence';
		} else if (resolved === 'continues' && endsWithTerminalPunctuation(chunk)) {
			resolved = 'complete';
			via = 'punctuation';
		}
		const { sends, buffer: next } = applyBoundary(buffer, chunk, resolved);
		chunkBuffer = next;
		const send = sends.length ? sends.join(' ‖ ') : null;
		onChunkTrace({
			seq: ++chunkSeq, at: Date.now(), chunk: silenceS > 0 ? '' : chunk, buffered: silenceS > 0 ? [...buffer, chunk].join(' ') : buffered,
			resolved, boundary: data.boundary, confidence: data.confidence, asr_risk: data.asr_risk,
			latency_ms: Math.round(performance.now() - t0), error: data.error, sent: send, viaBackstop: false,
			placement: send !== null ? (data.placement ?? 'new_line') : null,
			placement_confidence: send !== null ? (data.placement_confidence ?? null) : null,
			silence_s: silenceS > 0 ? silenceS : null,
			standalone: data.standalone ?? null,
			via
		});
		if (sends.length) {
			silenceStep = 0;
			for (const s of sends) enqueueUtterance(s);
		} else {
			armSilence();
		}
	}

	/** A new chunk arrived: classify it against the buffer with no silence evidence. */
	async function classifyChunk(chunk: string): Promise<void> {
		clearSilence();
		const buffered = chunkBuffer.join(' ');
		const t0 = performance.now();
		const data = await askBoundary(buffered, chunk, 0);
		applyDecision(chunkBuffer, chunk, data, 0, buffered, t0);
	}

	/** Silence milestone: re-ask about the same buffer, now with silence as evidence. */
	async function classifyBuffered(silenceS: number): Promise<void> {
		if (!chunkBuffer.length) return;
		const buffer = chunkBuffer.slice(0, -1);
		const chunk = chunkBuffer[chunkBuffer.length - 1];
		const t0 = performance.now();
		const data = await askBoundary(buffer.join(' '), chunk, silenceS);
		applyDecision(buffer, chunk, data, silenceS, buffer.join(' '), t0);
	}

	// ── Decision-first (lab, front door 'decision'; work-order step 5) ────────────────
	// Every Deepgram final → one Jev bundle → band router (backend). fast_append and
	// command are applied here verbatim; polish goes to today's /process path (fail open).
	// Each applied action keeps its affected range so undo, edits and re-dictation can be
	// logged against the decision id. Text never leaves this component in a record.
	function decisionFirst(): boolean {
		return labConfig?.frontDoor === 'decision';
	}
	let decisionChain: Promise<void> = Promise.resolve();
	// A correction whose corrected statement was unfinished, waiting for the next final.
	const HOLD_CORRECTION_MS = 4000;
	let heldCorrection: { text: string; rangeId: number; recId: string; timer: ReturnType<typeof setTimeout> } | null =
		null;
	/** Nothing followed in time (or recording stopped): polish the held correction alone. */
	function flushHeld(): void {
		const h = heldCorrection;
		if (!h) return;
		heldCorrection = null;
		clearTimeout(h.timer);
		const prev = decisionRecords.get(h.recId)?.rec.reason ?? '';
		patchDecision(h.recId, { polish_called: true, reason: `${prev}; flushed alone` });
		enqueueUtterance(h.text, h.recId);
	}
	// Where each undecided final sits in the document (faded), keyed by arrival.
	const chunkRanges = new Map<number, { from: number; to: number }>();
	let chunkRangeSeq = 0;
	let decisionSeq = 0;
	let localDecisionSeq = 0;
	let lineOpen = false;
	let openLineDecisionId: string | null = null;
	let lineTimers: ReturnType<typeof setTimeout>[] = [];
	const decisionRecords = new Map<string, { rec: DecisionRecord; display: string }>();
	interface Affected {
		id: string;
		route: FastRoute;
		at: number;
		from: number;
		to: number;
		before: string; // text the action replaced; restored by undo
		lineOpenBefore: boolean;
		tokens: Set<string>; // in memory only, for re-dictation matching
		intact: boolean; // nothing but the user has touched the range since
		edited: boolean;
		redictated: boolean;
	}
	let affected: Affected[] = [];
	let lastAction: Affected | null = null;

	function emitDecision(rec: DecisionRecord, display: string): void {
		decisionRecords.set(rec.id, { rec, display });
		onDecision({ ...rec }, display);
	}
	function patchDecision(id: string, patch: Partial<DecisionRecord>): void {
		const d = decisionRecords.get(id);
		if (!d) return;
		d.rec = { ...d.rec, ...patch };
		onDecision({ ...d.rec }, d.display);
	}
	function outcome(a: Affected, kind: OutcomeEvent['kind']): void {
		const now = Date.now();
		onOutcome({ decision_id: a.id, kind, route: a.route, ms_since: now - a.at, at: now });
	}

	function clearLineTimers(): void {
		for (const t of lineTimers) clearTimeout(t);
		lineTimers = [];
	}
	function closeLine(by: LineClosedBy): void {
		clearLineTimers();
		if (!lineOpen) return;
		lineOpen = false;
		if (openLineDecisionId) patchDecision(openLineDecisionId, { line_closed_by: by });
		openLineDecisionId = null;
	}
	/** Time is code: close at the silence milestone if standalone ≥ τ (decided by the
	 *  backend), and at the hard limit regardless. Silence counts from the final's arrival. */
	function armLineTimers(closeOnSilence: boolean, lc: BundleRouteResponse['line_close'], arrivedAt: number): void {
		clearLineTimers();
		const since = Date.now() - arrivedAt;
		if (closeOnSilence) lineTimers.push(setTimeout(() => closeLine('standalone'), Math.max(0, lc.silence_s * 1000 - since)));
		lineTimers.push(setTimeout(() => closeLine('hard_limit'), Math.max(0, lc.hard_limit_s * 1000 - since)));
	}

	function firstPendingRange(): { from: number; to: number } | null {
		if (!editor) return null;
		let found: { from: number; to: number } | null = null;
		editor.state.field(pendingField, false)?.between(0, editor.state.doc.length, (from, to) => {
			found = { from, to };
			return false;
		});
		return found;
	}

	function track(a: Affected): void {
		affected = [...affected, a];
		lastAction = a;
	}

	/** Map every affected range through a document change; attribute user edits. */
	function trackChanges(update: ViewUpdate, byUser: boolean): void {
		const now = Date.now();
		const doc0 = update.startState.doc;
		if (byUser) lastAction = null; // Mod-Z now belongs to the user's own typing
		for (const a of affected) {
			let hit = false;
			let lineHit = false;
			const ls = doc0.lineAt(Math.min(a.from, doc0.length)).from;
			const le = doc0.lineAt(Math.min(a.to, doc0.length)).to;
			update.changes.iterChangedRanges((fromA, toA) => {
				if (fromA < a.to && toA > a.from) hit = true;
				if (fromA <= le && toA >= ls) lineHit = true;
			});
			if (byUser && lineHit && a.intact && !a.edited && now - a.at <= EDIT_WINDOW_MS) {
				a.edited = true;
				outcome(a, 'edit');
			}
			if (hit || (byUser && lineHit)) a.intact = false;
			a.from = update.changes.mapPos(a.from, 1);
			a.to = Math.max(a.from, update.changes.mapPos(a.to, -1));
		}
		const keep = Math.max(EDIT_WINDOW_MS, REDICTATE_WINDOW_MS);
		affected = affected.filter((a) => a === lastAction || now - a.at <= keep);
	}

	function noteRedictation(chunk: string, now: number): void {
		const toks = tokenSet(chunk);
		for (const a of affected) {
			if (a.redictated || now - a.at > REDICTATE_WINDOW_MS) continue;
			if (isRedictation(a.tokens, toks)) {
				a.redictated = true;
				outcome(a, 'redictate');
			}
		}
	}

	/** One-step undo of the latest action (any route), while its range is intact. */
	export function undoLast(): boolean {
		const a = lastAction;
		if (!editor || !a || !a.intact) return false;
		isQwenWriting = true;
		editor.dispatch({
			changes: { from: a.from, to: a.to, insert: a.before },
			effects: clearAuto.of({ from: a.from, to: a.to })
		});
		isQwenWriting = false;
		a.intact = false;
		lastAction = null;
		clearLineTimers();
		lineOpen = a.lineOpenBefore;
		outcome(a, 'undo');
		return true;
	}

	async function askBundle(chunk: string, solid: string, asr: AsrFields | null): Promise<{ data: BundleRouteResponse | null; error: string | null }> {
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/bundle`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					scan_type: scanType,
					committed: '',
					active: solid,
					// The unfinished statement, read from the text (not the line-open flag, which
					// Deepgram's full stops and every polish reset, leaving it empty in practice).
					open_line: openStatement(solid),
					latest_utterance: chunk,
					checklist: checklistSections,
					...(asr ?? {})
				})
			});
			if (!res.ok) return { data: null, error: `http ${res.status}` };
			return { data: (await res.json()) as BundleRouteResponse, error: null };
		} catch (e) {
			return { data: null, error: (e as Error).name };
		}
	}

	/** Racing (lab switch): the lean scoped polish, fired together with the bundle. */
	interface LeanResult {
		data: {
			active_scratchpad: string;
			committed_edits: { original: string; corrected: string }[];
			skipped: boolean;
			usage: { input_tokens?: number; output_tokens?: number } | null;
			error: string | null;
		} | null;
		error: string | null;
		ms: number;
	}
	// Per-case Deepgram keyterms (lab): fetched once per case when the workspace is set up,
	// never on the dictation path. Recording waits at most KEYTERM_WAIT_MS for them, then
	// starts with the core list (fail open).
	const KEYTERM_WAIT_MS = 1500;
	let keytermKey = '';
	let keytermFetch: Promise<string[]> | null = null;
	function prefetchKeyterms(): Promise<string[]> | null {
		if (!labConfig || !scanType.trim()) return null;
		const key = keytermCaseKey(scanType, clinicalHistory, checklistSections);
		if (key !== keytermKey || !keytermFetch) {
			keytermKey = key;
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			keytermFetch = fetch(`${API_URL}/api/canvas/keyterms`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ scan_type: scanType, clinical_history: clinicalHistory, sections: checklistSections })
			})
				.then((r) => (r.ok ? r.json() : { terms: [] }))
				.then((d) => (Array.isArray(d?.terms) ? d.terms : []))
				.catch(() => []);
		}
		return keytermFetch;
	}
	// Prefetch when the scan type is set; a history or checklist edit after that is picked up
	// at record start (the case key differs, so it refetches) rather than on every keystroke.
	$: if (labConfig && scanType) prefetchKeyterms();
	async function caseKeyterms(): Promise<string[]> {
		const f = prefetchKeyterms();
		if (!f) return [];
		const timeout = new Promise<string[]>((r) => setTimeout(() => r([]), KEYTERM_WAIT_MS));
		return Promise.race([f, timeout]);
	}

	async function askLean(split: { context: string; span: string }, chunk: string): Promise<LeanResult> {
		const t0 = performance.now();
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/polish-span`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ scan_type: scanType, context: split.context, span: split.span, new: chunk })
			});
			const ms = Math.round(performance.now() - t0);
			if (!res.ok) return { data: null, error: `http ${res.status}`, ms };
			return { data: await res.json(), error: null, ms };
		} catch (e) {
			return { data: null, error: (e as Error).name, ms: Math.round(performance.now() - t0) };
		}
	}
	function racing(): boolean {
		return labConfig?.polish === 'race';
	}

	/** Apply a raced lean polish to its span: [span start, end of this final's faded text].
	 *  Returns why it could not, so the caller falls back to the full polish. */
	function applyLean(
		lean: LeanResult,
		split: { span: string; spanFrom: number },
		solid0: string,
		utterance: string,
		to: number,
		rec: DecisionRecord,
		asr: { fixes?: { heard: string; replacement: string }[]; flags?: { word: string }[] } = {}
	): string | null {
		if (!editor) return 'no_editor';
		if (!lean.data) return `lean_${lean.error ?? 'error'}`;
		if (lean.data.skipped) return 'lean_skipped';
		if (lean.data.error) return `lean_${lean.data.error}`;
		if (isProcessingQueue || utteranceQueue.length > 0) return 'full_polish_in_flight';
		const doc = editor.state.doc.toString();
		const norm = (x: string) => x.replace(/\s+/g, ' ').trim();
		if (doc.slice(0, solid0.length) !== solid0) return 'span_changed';
		if (to <= solid0.length || norm(doc.slice(solid0.length, to)) !== norm(utterance)) return 'pending_moved';
		const pend = { to };
		// Word-sense fixes apply to the polish's output too, where the heard words survived it.
		const out = applyAsrFixes(lean.data.active_scratchpad, asr.fixes ?? []);
		const insert = (split.span ? '' : separatorFor(solid0, out, false)) + out;
		const edits = committedEditChanges(doc, split.spanFrom, lean.data.committed_edits ?? []);
		isQwenWriting = true;
		editor.dispatch(replaceAndClear({ from: split.spanFrom, to: pend.to, insert }, edits));
		isQwenWriting = false;
		// Undo restores the span as it was (committed edits, if any, stay: they were asked for).
		const shift = edits.reduce((n, e) => n + e.insert.length - (e.to - e.from), 0);
		const from = split.spanFrom + shift;
		const r = changedRange(split.span, insert);
		track({
			id: rec.id, route: 'polish', at: Date.now(), from: from + r.from, to: from + r.to, before: r.before,
			lineOpenBefore: false, tokens: tokenSet(utterance), intact: true, edited: false, redictated: false
		});
		rec.asr_flag_count = underlineFlags(from, insert, asr.flags);
		rec.polish_kind = 'lean';
		rec.polish_ms = lean.ms;
		rec.polish_tokens_in = lean.data.usage?.input_tokens ?? null;
		rec.polish_tokens_out = lean.data.usage?.output_tokens ?? null;
		return null;
	}

	async function decideUtterance(
		chunk: string,
		arrivedAt: number,
		asr: AsrFields | null,
		rangeId: number | null = null
	): Promise<void> {
		if (!editor) return;
		// A correction held back from the previous final is decided together with this one.
		const heldNow = heldCorrection;
		if (heldNow) {
			clearTimeout(heldNow.timer);
			heldCorrection = null;
		}
		const utterance = heldNow ? `${heldNow.text} ${chunk}` : chunk;
		const firstRangeId = heldNow ? heldNow.rangeId : rangeId;
		noteRedictation(chunk, Date.now());
		const pend0 = firstPendingRange();
		const doc0 = editor.state.doc.toString();
		const solid0 = doc0.slice(0, pend0 ? pend0.from : doc0.length);
		const t0 = performance.now();
		// Racing: the lean polish starts now, alongside the bundle; Jev's route decides whether it is used.
		const split = racing() ? splitSpan(solid0) : null;
		const leanP = split ? askLean(split, utterance) : null;
		// Jev sees everything before this final, including earlier faded finals still waiting
		// for a polish; the racing span and fast-append placement keep using the solid text.
		const firstRange = firstRangeId !== null ? (chunkRanges.get(firstRangeId) ?? null) : null;
		const context = jevContext(doc0, firstRange, heldNow ? heldNow.text : chunk, solid0.length);
		const { data, error } = await askBundle(utterance, context, asr);
		const roundtrip = Math.round(performance.now() - t0);
		if (!editor) return;

		let route: FastRoute = data?.route ?? 'polish';
		let reason = data?.reason ?? `request_error:${error}`;
		if (heldNow) {
			route = 'polish'; // the joined correction is always polished, whatever the fragment looked like
			reason = `held_correction_joined (${reason})`;
		}
		// The document as it is now, not as it was when the bundle was asked.
		const pend = firstPendingRange();
		const doc = editor.state.doc.toString();
		const pendingText = pend ? doc.slice(pend.from, pend.to).trim() : null;
		if (
			(route === 'fast_append' || route === 'command' || route === 'skip' || route === 'delete') &&
			pendingText !== chunk.trim()
		) {
			route = 'polish';
			reason = pend ? 'pending_mismatch' : 'pending_lost';
		} else if ((route === 'fast_append' || route === 'command') && (isProcessingQueue || utteranceQueue.length > 0)) {
			// A full-regeneration polish rewrites a range fixed at request time; writing
			// under it would be overwritten or duplicated. Join the polish instead.
			route = 'polish';
			reason = 'polish_in_flight';
		}

		// Polish (now or later) is given the cleaned text, not the raw final: the code-side
		// fixes (levels, spoken punctuation, colon, headings) must survive a polish.
		if (!heldNow && data?.clean_text && (route === 'fast_append' || route === 'polish')) {
			sessionTranscript = substituteLast(sessionTranscript, chunk, data.clean_text);
		}

		const rec: DecisionRecord = {
			id: data?.decision_id ?? `local-${++localDecisionSeq}`,
			seq: ++decisionSeq,
			at: Date.now(),
			route,
			reason,
			qset: data?.qset ?? null,
			action: data?.action ?? null,
			confidence: data?.confidence ?? null,
			probabilities: data?.probabilities ?? null,
			is_correction: data?.is_correction ?? null,
			standalone: data?.standalone ?? null,
			latency_ms: data?.latency_ms ?? null,
			roundtrip_ms: roundtrip,
			polish_called: route === 'polish',
			polish_ms: null,
			utterance_len: chunk.length,
			utterance_hash: hash8(chunk),
			applied_len: 0,
			closes_line: false,
			line_closed_by: null,
			error: data?.error ?? error,
			asr_fix_count: data?.asr_fixes?.length ?? 0,
			asr_flag_count: 0,
			repair_ms: data?.repair_ms ?? null,
			asr_conf: asr?.asr_conf ?? null,
			asr_min_conf: asr?.asr_min_conf ?? null,
			asr_word_confs: asr?.asr_word_confs ?? null
		};

		if ((route === 'fast_append' || route === 'command') && data && pend) {
			const solid = doc.slice(0, pend.from);
			let insert: string;
			let closedBy: LineClosedBy | null = null;
			if (route === 'fast_append') {
				insert = separatorFor(solid, data.text, !!data.starts_paragraph) + data.text;
				if (data.closes_line) closedBy = data.text.endsWith('\n') ? 'newline' : 'punctuation';
			} else {
				insert = commandInsert(solid, data.insert);
				// a spoken colon (L5/S1:) leaves the line open; newlines and stops close it
				closedBy = !data.closes_line ? null : data.insert.includes('\n') ? 'newline' : 'punctuation';
			}
			isQwenWriting = true;
			const spec = replaceAndClear({ from: pend.from, to: pend.to, insert });
			editor.dispatch({
				...spec,
				effects: [
					...[spec.effects ?? []].flat(),
					...(insert ? [markAuto.of({ from: pend.from, to: pend.from + insert.length })] : [])
				]
			});
			isQwenWriting = false;
			const a: Affected = {
				id: rec.id, route, at: rec.at, from: pend.from, to: pend.from + insert.length, before: '',
				lineOpenBefore: lineOpen, tokens: tokenSet(route === 'fast_append' ? data.text : ''),
				intact: true, edited: false, redictated: false
			};
			track(a);
			setTimeout(() => editor?.dispatch({ effects: clearAuto.of({ from: a.from, to: a.to }) }), EDIT_WINDOW_MS);
			rec.applied_len = insert.length;
			rec.closes_line = closedBy !== null;
			if (closedBy) {
				closeLine(closedBy); // closes the previous open line, if any, as part of this one
				rec.line_closed_by = closedBy;
				lineOpen = false;
			} else {
				lineOpen = true;
				openLineDecisionId = rec.id;
				armLineTimers(data.close_on_silence, data.line_close, arrivedAt);
			}
			if (route === 'fast_append') rec.asr_flag_count = underlineFlags(pend.from, insert, data.asr_flags);
			emitDecision(rec, chunk);
			processReview();
			return;
		}
		if (route === 'delete' && pend) {
			// "Scratch that": undo the previous utterance's text by code, and drop the command's
			// own faded words. Anything else (touched, a command, a polish pending) → polish.
			const del = deletePrevious(lastAction, pend, isProcessingQueue || utteranceQueue.length > 0);
			if (del.edits) {
				const prev = lastAction as Affected;
				isQwenWriting = true;
				const spec = replaceAndClear({ from: pend.from, to: pend.to, insert: '' }, del.edits);
				editor.dispatch({ ...spec, effects: [...[spec.effects ?? []].flat(), clearAuto.of({ from: prev.from, to: prev.to })] });
				isQwenWriting = false;
				prev.intact = false;
				lastAction = null;
				clearLineTimers();
				lineOpen = prev.lineOpenBefore;
				// Not logged as an 'undo' outcome: the speaker retracted their own words, which says
				// nothing about whether the previous automatic action was right.
				emitDecision(rec, chunk);
				return;
			}
			route = 'polish';
			rec.route = 'polish';
			rec.reason = `${reason}; ${del.reason}`;
		}
		if (route === 'skip' && pend) {
			isQwenWriting = true;
			editor.dispatch(replaceAndClear({ from: pend.from, to: pend.to, insert: '' }));
			isQwenWriting = false;
			emitDecision(rec, chunk);
			return;
		}
		// polish. Racing: use the lean result already in flight; otherwise (or if it cannot be
		// applied) today's full polish. The open line closes either way.
		rec.route = 'polish';
		// An unfinished correction ("Correction. The nodule is in the") waits for the next
		// final, so the polish sees the whole corrected statement once.
		if (!heldNow && rangeId !== null && isUnfinishedCorrection(data?.clean_text || chunk)) {
			rec.reason = `${rec.reason}; held for next final`;
			rec.polish_called = false;
			heldCorrection = { text: chunk, rangeId, recId: rec.id, timer: setTimeout(flushHeld, HOLD_CORRECTION_MS) };
			emitDecision(rec, chunk);
			return;
		}
		rec.polish_called = true;
		closeLine('polish');
		if (split && leanP) {
			const own = rangeId !== null ? (chunkRanges.get(rangeId) ?? null) : null;
			const to = own && own.to > own.from ? own.to : (firstPendingRange()?.to ?? -1);
			const why = applyLean(await leanP, split, solid0, utterance, to, rec, {
				fixes: data?.asr_fixes,
				flags: data?.asr_flags
			});
			if (why === null) {
				emitDecision(rec, chunk);
				processReview();
				return;
			}
			rec.reason = `${rec.reason}; full:${why}`;
		}
		emitDecision(rec, heldNow ? utterance : chunk);
		enqueueUtterance(data?.clean_text || utterance, rec.id);
	}

	// One polish per statement: utterances queue up and each process call takes exactly one.
	let utteranceQueue: string[] = [];
	// Decision-first: the decision id behind each queued utterance (null on other front doors).
	let utteranceDecisionIds: (string | null)[] = [];
	function enqueueUtterance(s: string, decisionId: string | null = null): void {
		utteranceQueue.push(s);
		utteranceDecisionIds.push(decisionId);
		// Never abort an in-flight polish for a queued statement (that would drop its triage);
		// the queue loop picks the next one up when the current call completes.
		if (isProcessingQueue) pendingProcess = true;
		else processTranscriptQueue();
	}

	/** Queue without starting a call (the stop-time flush starts one itself). */
	function enqueueLater(s: string): void {
		utteranceQueue.push(s);
		utteranceDecisionIds.push(null);
	}

	async function processTranscript(): Promise<void> {
		if (!editor) return;
		isProcessing = true;
		recordingError = '';
		const controller = new AbortController();
		processAbort = controller;
		const faded = fadedEnabled();
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const doc = editor.state.doc.toString();
			// Full regeneration: the model rewrites the whole scratchpad from the transcript
			// plus the prior polished text. When faded render is on, exclude the pending
			// (faded raw) region — it's a display-only placeholder the polish output replaces,
			// never sent to the model and never frozen.
			let pendingStart = doc.length;
			if (faded) {
				editor.state.field(pendingField, false)?.between(0, doc.length, (markFrom) => {
					pendingStart = markFrom;
					return false;
				});
			}

			const sentTranscript = sessionTranscript;
			const { delta } = computeDelta(sentTranscript, lastSentTranscript);
			const activeBefore = faded ? doc.slice(0, pendingStart) : doc;
			const body: Record<string, unknown> = {
				session_transcript: sentTranscript,
				scratchpad_content: activeBefore,
				scan_type: scanType,
				clinical_history: clinicalHistory,
				preferred_section_names: checklistSections,
				mode: 'clean' // the live polish always writes the verbatim text; Structured is derived from it
			};
			const queuedDecisionId = utteranceQueue.length ? (utteranceDecisionIds.shift() ?? null) : null;
			const queued = utteranceQueue.length ? utteranceQueue.shift()! : null;
			if (utteranceQueue.length) pendingProcess = true;
			const utterance = queued ?? pendingUtterance ?? delta;
			pendingUtterance = null;
			if (utterance) body.last_utterance = utterance;
			if (labConfig) Object.assign(body, toRequestFields(labConfig));
			const t0 = performance.now();

			const res = await fetch(`${API_URL}/api/canvas/process`, {
				method: 'POST',
				headers,
				signal: controller.signal,
				body: JSON.stringify(body)
			});
			const data = await res.json();
			// The call completed: everything up to sentTranscript has been seen by the model.
			// (An aborted/superseded call never reaches here, so its words stay in the next delta.)
			lastSentTranscript = sentTranscript;

			const content = data.scratchpad != null ? sanitizeScratchpad(data.scratchpad) : null;

			if (content != null) {
				isQwenWriting = true;
				editor.dispatch({
					changes: { from: 0, to: doc.length, insert: content },
					effects: faded ? [clearPending.of({ from: 0, to: content.length })] : []
				});
				isQwenWriting = false;
				if (queuedDecisionId) {
					// Decision-first: the polish is undoable and edit-tracked like any route,
					// so its undo/edit rate is the baseline the automatic routes are held to.
					const r = changedRange(activeBefore, content);
					track({
						id: queuedDecisionId, route: 'polish', at: Date.now(), from: r.from, to: r.to, before: r.before,
						lineOpenBefore: false, tokens: tokenSet(utterance ?? ''), intact: true, edited: false, redictated: false
					});
					lineOpen = false;
					patchDecision(queuedDecisionId, {
						polish_ms: Math.round(performance.now() - t0),
						polish_kind: 'full',
						polish_tokens_in: data.polish_usage?.input_tokens ?? null,
						polish_tokens_out: data.polish_usage?.output_tokens ?? null
					});
				}
				// Scratchpad is updated — now fire IntelliPrompts analysis in background.
				processReview();
			}
			if (data.covered_sections && Array.isArray(data.covered_sections)) {
				onCoveredSectionsChange(data.covered_sections);
			}
			onProcessTrace({
				seq: ++traceSeq,
				at: Date.now(),
				utterance: utterance ?? '',
				committed: '',
				activeBefore,
				activeAfter: content ?? activeBefore,
				scanType,
				latency_ms: Math.round(performance.now() - t0),
				triage: (data.triage as TriageTrace | null | undefined) ?? null
			});
		} catch {
			// Superseded aborts set pendingProcess and will re-run, so keep the faded raw.
			// A real network error won't re-run — promote the faded raw to solid so it
			// never looks stuck (Phase 2b.3).
			if (faded && !pendingProcess && editor) {
				editor.dispatch({ effects: clearPending.of(null) });
			}
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

	function sanitizeScratchpad(s: string): string {
		return s
			.split('\n')
			.filter((line: string) => !/^[-*_]{3,}\s*$/.test(line.trim()))
			.map((line: string) => line.replace(/\*\*/g, '').replace(/^_{1,2}|_{1,2}$/g, ''))
			.join('\n');
	}

	// --- Structured view -------------------------------------------------------------
	function showStructured(text: string): void {
		if (!structuredEditor || structuredEditor.state.doc.toString() === text) return;
		writingStructured = true;
		structuredEditor.dispatch({ changes: { from: 0, to: structuredEditor.state.doc.length, insert: text } });
		writingStructured = false;
	}
	function structureBusy(): boolean {
		return !!firstPendingRange() || isProcessingQueue || utteranceQueue.length > 0 || !!heldCorrection;
	}
	function scheduleStructure(delay = STRUCTURE_DEBOUNCE_MS): void {
		if (!structuredWanted) return;
		if (structuredTimer) clearTimeout(structuredTimer);
		structuredTimer = setTimeout(() => {
			structuredTimer = null;
			void buildStructured();
		}, delay);
	}
	/** Derive the structured text from the verbatim text: /process in structured mode, the
	 *  verbatim text as the transcript, an empty scratchpad. Never while a final is faded or a
	 *  polish is pending (it would structure half a statement); the next settle retries. */
	async function buildStructured(): Promise<void> {
		if (!editor) return;
		const verbatim = editor.state.doc.toString();
		const busy = structureBusy();
		if (!shouldBuild(structured, verbatim, { wanted: structuredWanted, busy })) {
			if (busy && structuredWanted && verbatim.trim() && !isCurrent(structured, verbatim)) scheduleStructure();
			return;
		}
		structured = startBuild(structured, verbatim);
		let text: string | null = null;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/process`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					session_transcript: verbatim,
					scratchpad_content: '',
					scan_type: scanType,
					clinical_history: clinicalHistory,
					preferred_section_names: checklistSections,
					mode: 'structured'
				})
			});
			if (res.ok) {
				const data = await res.json();
				if (typeof data.scratchpad === 'string') text = sanitizeScratchpad(data.scratchpad);
			}
		} catch {
			// fail open: the previous structured text stays; the next settle retries
		}
		const r = acceptBuild(structured, verbatim, text);
		if (!r) {
			structured = { ...structured, building: null };
			return;
		}
		structured = r.state;
		if (r.replacedEdits) structuredNotice = 'Structured view refreshed from new dictation: your edits there were replaced.';
		showStructured(r.state.text ?? '');
		if (polishMode === 'structured') onContentChange(r.state.text ?? '');
		if (editor && !isCurrent(structured, editor.state.doc.toString())) scheduleStructure();
	}

	async function _runReview(): Promise<void> {
		if (!editor) return;
		const scratchpad_content = editor.state.doc.toString();
		const hashInput = scratchpad_content + checklistSections.join();
		const currentHash = simpleHash(hashInput);
		if (currentHash === lastReviewedHash) return;

		onReviewingChange(true);
		const headers: Record<string, string> = { 'Content-Type': 'application/json' };
		if ($token) headers['Authorization'] = `Bearer ${$token}`;
		const review = (parts: 'coverage' | 'prompts') =>
			fetch(`${API_URL}/api/canvas/review`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					scratchpad_content,
					checklist_sections: checklistSections,
					scan_type: scanType,
					clinical_history: clinicalHistory,
					mode: 'clean', // review reads the verbatim text
					parts,
					...(labConfig && parts === 'coverage' ? { coverage_debug: labConfig.coverageDebug } : {})
				})
			}).then((r) => r.json());
		// Two halves in parallel, each applied as it lands: the section pills (coverage,
		// sub-second) never wait for the IntelliPrompts call.
		const coverage = review('coverage').then((data) => {
			if (data.covered_sections && Array.isArray(data.covered_sections)) {
				onCoveredSectionsChange(data.covered_sections);
			}
			onCoverageScoresChange(data.coverage_scores ?? null);
			if (data.coverage) onCoverageTrace(data.coverage as CoverageTrace);
		});
		const prompts = review('prompts').then((data) => {
			// Backend now owns the full merge — replace activePrompts with the final merged list
			if (data.prompts && Array.isArray(data.prompts)) {
				onPromptsChange(data.prompts);
			}
		});
		try {
			const [c, p] = await Promise.allSettled([coverage, prompts]);
			if (c.status === 'fulfilled' && p.status === 'fulfilled') lastReviewedHash = currentHash;
		} catch {
			// silently ignore review errors
		} finally {
			onReviewingChange(false);
		}
	}

	async function startRecording(): Promise<void> {
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
			const kt = labConfig ? keytermQuery(await caseKeyterms()) : '';
			const wsUrl = `${wsUrlBase}/api/transcribe${tokenPart}${kt}`;
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
				// Decision-first keeps the editor editable: a manual fix of an automatic
				// action is one of the outcomes it measures.
				if (editor && !decisionFirst()) {
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
						// Deepgram UtteranceEnd (~1s pause) is a backup polish trigger; the primary is
						// speech_final (~endpointing). Only fire if idle, so we never abort + re-run an
						// in-flight polish (which wasted a full model call per utterance).
						if (!frontDoorIsJev() && !decisionFirst() && !isProcessingQueue) processTranscriptQueue();
					} else if (data.transcript) {
						if (!data.is_final) {
							// Interim: live preview while speaking
							currentInterim = data.transcript;
						} else {
							handleFinalTranscript(data.transcript, !!data.speech_final, asrFields(data));
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
		// Decision-first: undecided finals keep their faded raw until their route lands;
		// the decision chain, not a flush polish, finishes them.
		if (decisionFirst()) {
			closeLine('stop');
			decisionChain = decisionChain.then(flushHeld);
			if (editor) {
				editor.dispatch({ effects: editableCompartment.reconfigure(EditorView.editable.of(true)) });
			}
			return;
		}
		// Phase 2b.3: promote any faded raw to solid before handing control back — no
		// pending marks survive the end of recording (the flush polish still cleans it).
		if (editor) editor.dispatch({ effects: clearPending.of(null) });
		// Flush: the polish trigger is gated on speech_final, so a quick stop mid-utterance
		// could otherwise drop the last words. Process the final accumulated transcript once.
		clearSilence();
		const flushed = flushBuffer(chunkBuffer);
		chunkBuffer = flushed.buffer;
		for (const s of flushed.sends) enqueueLater(s);
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
					// Decision-first: Mod-Z undoes the latest routed action first; with none
					// (or after the user typed) it falls through to ordinary history undo.
					Prec.highest(keymap.of([{ key: 'Mod-z', run: () => decisionFirst() && undoLast() }])),
					keymap.of([...defaultKeymap, ...historyKeymap]),
					markdown(),
					syntaxHighlighting(markdownHighlightStyle),
					EditorView.lineWrapping,
					editableCompartment.of(EditorView.editable.of(true)),
					darkTheme,
					highlightField,
					integrityField,
					pendingField,
					autoField,
					asrFlagField,
					EditorView.updateListener.of((update) => {
				if (update.docChanged && decisionFirst() && affected.length) trackChanges(update, !isQwenWriting);
				if (update.docChanged && chunkRanges.size) {
					for (const r of chunkRanges.values()) {
						r.from = update.changes.mapPos(r.from, 1);
						r.to = Math.max(r.from, update.changes.mapPos(r.to, -1));
					}
				}
				if (update.docChanged) {
					const content = update.state.doc.toString();
					verbatimNow = content;
					if (polishMode === 'clean') onContentChange(content);
					if (!content.trim()) {
						structured = emptyStructured();
						showStructured('');
					} else scheduleStructure();
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
						if (typingDebounceTimer) { clearTimeout(typingDebounceTimer); typingDebounceTimer = null; }
						onScratchpadClear();
					} else if (hasWordChange) {
						// Cards whose source_text is deleted fade out automatically via the anchor filter
						// in IntelliPromptsMargin — no need to clear the prompt list eagerly here.
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
		structuredEditor = new EditorView({
			state: EditorState.create({
				doc: '',
				extensions: [
					history(),
					keymap.of([...defaultKeymap, ...historyKeymap]),
					markdown(),
					syntaxHighlighting(markdownHighlightStyle),
					EditorView.lineWrapping,
					darkTheme,
					highlightField,
					integrityField,
					EditorView.updateListener.of((update) => {
						if (!update.docChanged || writingStructured) return;
						const text = update.state.doc.toString();
						structured = noteEdit(structured, text); // kept until the verbatim text changes
						if (polishMode === 'structured') onContentChange(text);
					})
				]
			}),
			parent: structuredContainer
		});
		if (polishMode === 'structured') structuredEditor.focus();
		else editor.focus();
	});

	onDestroy(() => {
		if (typingDebounceTimer) clearTimeout(typingDebounceTimer);
		if (editor) {
			editor.destroy();
			editor = null;
		}
		if (structuredTimer) clearTimeout(structuredTimer);
		structuredEditor?.destroy();
		structuredEditor = null;
		stopRecording();
	});

	function setMode(mode: 'clean' | 'structured') {
		if (mode === polishMode) return;
		polishMode = mode;
		onModeChange(mode);
		structuredNotice = '';
		// Switching shows the other stored view; nothing is re-polished or overwritten.
		if (mode === 'structured') {
			structuredWanted = true;
			onContentChange(structured.text ?? editor?.state.doc.toString() ?? '');
			void buildStructured(); // no-op when already current
		} else {
			onContentChange(editor?.state.doc.toString() ?? '');
		}
		requestAnimationFrame(() => {
			const view = visibleEditor();
			view?.requestMeasure();
			view?.focus();
		});
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
		{#if labConfig?.frontDoor === 'decision'}
			<button
				type="button"
				onclick={() => undoLast()}
				disabled={!lastAction?.intact || polishMode === 'structured'}
				class="text-xs px-2 py-0.5 rounded border border-white/10 text-gray-300 disabled:opacity-30"
				title="Undo the latest routed action (⌘Z)"
			>
				Undo last{lastAction ? ` (${lastAction.route.replace('_', '-')})` : ''}
			</button>
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
		onclick={(e) => { if (e.target === e.currentTarget || !(e.target as Element).closest('.cm-editor')) visibleEditor()?.focus(); }}
	>
		<!-- Scroll container — holds both the editor and the margin so they scroll together.
		     This means card overflow is never clipped: the area simply becomes scrollable. -->
		<div class="flex-1 min-h-0 overflow-auto pb-4 pt-8">
			<div class="flex flex-row items-start min-h-full">

				<!-- Editor column -->
				<div class="flex-1 min-h-full pl-4 pr-4">
					{#if polishMode === 'structured' && (structuredStale || structuredNotice)}
						<div class="mb-2 text-xs {structuredNotice ? 'text-amber-300/80' : 'text-gray-400'}" aria-live="polite">
							{structuredNotice || (structured.text === null ? 'Structuring…' : 'Updating structured view…')}
						</div>
					{/if}
					<div bind:this={editorContainer} class="min-h-full" class:hidden={polishMode === 'structured'}></div>
					<div bind:this={structuredContainer} class="min-h-full" class:hidden={polishMode !== 'structured'}></div>
				</div>

				<!-- Margin column — width animates open/closed; stops click bubbling to editor focus handler -->
				<div
					class="shrink-0 overflow-hidden"
					style="width: {activePrompts.length > 0 ? '240px' : '0px'}; transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1)"
					onclick={(e) => e.stopPropagation()}
				>
					<IntelliPromptsMargin
						{activePrompts}
						editor={polishMode === 'structured' ? structuredEditor : editor}
						{isReviewing}
						onHighlight={highlightSource}
						onClearHighlight={clearHighlight}
					/>
				</div>

			</div>
		</div>

		<!-- Inline transcript feed at the bottom of the box — only when dictation is on -->
		{#if isRecording && currentInterim}
			<div class="border-t border-white/[0.05] px-4 py-2 flex flex-col gap-0.5 shrink-0">
				<p class="text-xs text-gray-600 italic truncate">{currentInterim}</p>
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

	/* Word-sense spotter: a word that makes no clinical sense as heard, left for the radiologist. */
	:global(.cm-asr-flag) {
		text-decoration: underline wavy rgba(250, 204, 21, 0.9);
		text-decoration-skip-ink: none;
		text-underline-offset: 3px;
	}

	/* Decision-first: text an automatic action wrote, marked while it can be undone. */
	:global(.cm-dictation-auto) {
		background: rgba(16, 185, 129, 0.1);
		border-bottom: 1px dotted rgba(16, 185, 129, 0.6);
	}

</style>
