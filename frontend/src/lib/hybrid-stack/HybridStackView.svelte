<script lang="ts">
	// Scratchpad checklist (spec 2026-10-11-scratchpad-checklist §3): live strip, the referral row, abnormal
	// regions with their amber rows and the normals that will be reported, the tray, the conclusion and the gate
	// bar. Every line is the radiologist's own sentence from the verbatim text; a click opens it for editing.
	// Rows are asked, never assumed: a tap adds only the sentences listed above its button.
	import { tick } from 'svelte';
	import { fade } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { buildView } from './stackState';
	import { CONCLUSION, GENERAL, OTHER, TECHNIQUE, regionStates, showsGroup } from './regionState';
	import { coveredStructures, regionChips } from './subPills';
	import { checkLabel, replaced, segments, withoutQuote, type CheckAnswer, type CheckFlag } from './checks';
	import { QUIET_MAX, anchorRegion, answerLabel, isFlagged as flaggedIn, openCount, quietLine, rowSentences, unansweredChecks, waiting } from './items';
	import type { StackItem, StackUnit, ValueChip, ViewRow } from './types';
	import ValueChips from './ValueChips.svelte';
	import { openCount as openValueChips } from './values';

	export type ConclusionState =
		| { kind: 'waiting' }
		| { kind: 'dictated' }
		| { kind: 'none'; failed?: boolean }
		| { kind: 'loading' }
		| { kind: 'draft'; text: string; edited: boolean; typed?: boolean };
	/** Findings changed under a conclusion the radiologist owns, and Jev says it no longer reflects them. */
	export type ConclusionNote = { added: string[]; suggestion: string | null; loading: boolean };

	let {
		units,
		groups,
		pillRegions,
		pending = [],
		ghost = '',
		editGhost = '',
		items = [],
		more = [],
		moreWaiting = 0,
		moreOpen = false,
		onToggleMore = () => {},
		tapped = [],
		removed = [],
		assumed = {},
		structures = {},
		flagged = {},
		confirmNote = null,
		namedNormals = false,
		skipped = [],
		values = [],
		onEnterValue = () => {},
		onValueNa = () => {},
		onValuesRestNa = () => {},
		onKeepValue = () => {},
		onPickValue = () => {},
		reviewing = false,
		reviewWaiting = false,
		reviewFailed = false,
		assumedReady = false,
		assumedFailed = false,
		actionsReady = true,
		recording = false,
		onToggleMic = () => {},
		conclusion = { kind: 'none' },
		conclusionNote = null,
		checks = [],
		checkAnswers = {},
		onCheckAnswer = () => {},
		onConfirmGenerate = null,
		gateConfirmed = false,
		guidelinesUnresolved = [],
		onOpenGuideline = () => {},
		deleteRegion = null,
		incoming = null,
		onMove,
		onEditLine,
		onEditing = () => {},
		onAnswer = () => {},
		onAnswerTemplate = () => {},
		onRemoveSentence = () => {},
		onDictateInto = () => {},
		onSkip = () => {},
		onAbnormal = () => {},
		onEditAssumed = () => {},
		onDraftEdit = () => {},
		onDraftRefresh = () => {},
		onNoteSuggest = () => {},
		onNoteAccept = () => {},
		onNoteDismiss = () => {},
		onConfirm,
		onDeleteRegion = () => {},
		onAppend = () => {},
		syncing = false,
		checking = false
	}: {
		units: StackUnit[];
		groups: string[];
		/** The schema's regions except the catch-all: the tray. */
		pillRegions: string[];
		pending?: string[];
		ghost?: string;
		/** Words being spoken into an open inline edit: shown faded at that edit, never in the scratchpad box. */
		editGhost?: string;
		/** Checklist rows: referral and finding (answered ones fold away; the parent drops them). */
		items?: StackItem[];
		/** Rows over the writer's caps (E1b): behind one quiet "N more checks" line at the end of the checklist; opened,
		 *  they are ordinary rows. Never needed for Confirm. */
		more?: StackItem[];
		/** N: the rows behind the line still asked (not tapped, skipped or answered). */
		moreWaiting?: number;
		moreOpen?: boolean;
		onToggleMore?: () => void;
		/** Rows the radiologist answered with a tap: their listed sentences are stated. */
		tapped?: string[];
		/** Sentences the radiologist removed (×): never stated. */
		removed?: string[];
		/** Region normals that will be reported unless removed (the slim sheet, checked against the dictation). */
		assumed?: Record<string, string[]>;
		/** Template sessions: region -> {structure -> its sentences} for a paragraph covering several structures; its
		 *  assumed chip splits into one per structure (sub-pills). Absent: one chip per region, as before. */
		structures?: Record<string, Record<string, string[]>>;
		/** Assumed normals the dictation may conflict with (review R1): kept, shown with an amber "check" marker. */
		flagged?: Record<string, string[]>;
		/** Why the last Confirm press did not gate (a re-checked rule added a normal; the dictation moved on). */
		confirmNote?: string | null;
		/** No sheet this session: untouched regions are confirmed by name (v2). With a sheet, only sentences are. */
		namedNormals?: boolean;
		/** Rows skipped (finding checks) or marked not assessed (referral rows): folded, nothing stated. */
		skipped?: string[];
		/** The value cluster (template sessions): the template's required values; open and "stated?" ones block Confirm. */
		values?: ValueChip[];
		onEnterValue?: (item: string, text: string) => void;
		onValueNa?: (item: string) => void;
		onValuesRestNa?: () => void;
		/** A "stated?" chip kept as stated. */
		onKeepValue?: (item: string) => void;
		/** A number tapped from a dictation clause on a chip: picked (never stated as a typed answer), with the clause. */
		onPickValue?: (item: string, value: string, clause: string) => void;
		/** The end-of-dictation review is running / will run when dictation stops. */
		reviewing?: boolean;
		reviewWaiting?: boolean;
		/** The review failed: no finding checks this time, and the radiologist is told. */
		reviewFailed?: boolean;
		/** The assumed check has answered: a region with nothing left to assume leaves the normal section. */
		assumedReady?: boolean;
		/** The assumed check failed (P2c): say so in the tray — nothing is assumed, never "nothing to assume". */
		assumedFailed?: boolean;
		/** The review of the current dictation has run: rows offer their answers. Before that a referral row is only
		 *  a reminder (hand read 2026-10-12: buttons at setup invited fiddling instead of dictating). */
		actionsReady?: boolean;
		/** The mic, for the inline "Dictate finding" field. */
		recording?: boolean;
		onToggleMic?: () => void;
		conclusion?: ConclusionState;
		conclusionNote?: ConclusionNote | null;
		/** Dictation checks placed on their sentences (an unfinished sentence blocks Confirm; the rest are advisory). */
		checks?: CheckFlag[];
		checkAnswers?: Record<string, CheckAnswer>;
		onCheckAnswer?: (key: string, how: CheckAnswer) => void;
		gateConfirmed?: boolean;
		/** Guideline cards still unresolved (Copilot on, spec §7.12 item 5): they block Confirm; [] changes nothing. */
		guidelinesUnresolved?: { key: string; name: string }[];
		/** The "N guidelines unresolved" chip: open the first such card in the rail. */
		onOpenGuideline?: (key: string) => void;
		/** A voice "delete the X line": the region whose lines wait for a Delete click (null: none). */
		deleteRegion?: string | null;
		/** Dictation for the field open for editing: inserted at its caret / over its selection. */
		incoming?: { seq: number; text: string } | null;
		onMove: (id: number, group: string) => void;
		onEditLine: (unitId: number, part: number | null, text: string) => void;
		/** Whether a line or the draft is open for editing (dictation then goes there). */
		onEditing?: (active: boolean) => void;
		/** A row answered with a tap: its listed sentences are added as the radiologist's answer. */
		onAnswer?: (id: string) => void;
		/** Yes or No on a template row: the template's own sentence for that answer is added. */
		onAnswerTemplate?: (id: string, which: 'yes' | 'no') => void;
		/** A row sentence or an assumed normal removed (×): never stated. */
		onRemoveSentence?: (sentence: string) => void;
		/** "Dictate" on a row: the next words go under that region. */
		onDictateInto?: (region: string) => void;
		/** Skip a finding check, or mark a referral question not assessed: folded, nothing stated. */
		onSkip?: (id: string) => void;
		/** "Abnormal…" in a row: the finding typed or dictated into it is added as said, and the row folds. */
		onAbnormal?: (id: string, text: string) => void;
		/** A pre-written normal edited: the original is never stated; the edited text is added as the radiologist's own
		 *  words (empty: removed). */
		onEditAssumed?: (original: string, text: string) => void;
		onDraftEdit?: (text: string) => void;
		onDraftRefresh?: () => void;
		/** The conclusion note: ask for a suggested redraft, use it, or keep the radiologist's own. */
		onNoteSuggest?: () => void;
		onNoteAccept?: () => void;
		onNoteDismiss?: () => void;
		onConfirm: () => void;
		/** The walkthrough's last step: Confirm, then Generate. Absent: the last step only confirms. */
		onConfirmGenerate?: (() => void) | null;
		onDeleteRegion?: (region: string, confirmed: boolean) => void;
		/** A finding typed into the new-line field (Enter): appended to the dictation as said. */
		onAppend?: (text: string) => void;
		/** The grouping has not caught up with the text yet: Confirm waits (the block must match what is shown). */
		syncing?: boolean;
		/** The model check (sides, conflicts, garbles) is running on this text: Confirm and the walk wait for its flags
		 *  (bounded by the check's own timeout; it fails open). */
		checking?: boolean;
	} = $props();

	const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	const ms = reduced ? 0 : 280;
	// Sentences newly placed in a region: highlighted briefly, then the highlight fades (no motion between places).
	// Keyed by sentence and text, so a sentence placed again after a rewording also glows (hand read 2026-10-12).
	let fresh: string[] = $state([]);
	let seenKeys = new Set<string>();
	$effect(() => {
		const placed = units.filter((x) => x.group !== null && !x.heading).map((x) => `${x.id}|${x.text}`);
		const added = placed.filter((k) => !seenKeys.has(k));
		seenKeys = new Set(placed);
		if (!added.length) return;
		fresh = [...fresh, ...added];
		setTimeout(() => (fresh = fresh.filter((k) => !added.includes(k))), 1400);
	});

	const view = $derived(buildView(units, groups));
	const states = $derived(regionStates(units, pillRegions));
	const shown = $derived(
		view.groups.filter(
			(g) =>
				g.members.some((m) => states.abnormal.includes(m)) ||
				(g.name === GENERAL && showsGroup(units, GENERAL)) ||
				(g.name === OTHER && showsGroup(units, OTHER))
		)
	);
	const technique = $derived(view.groups.find((g) => g.name === TECHNIQUE));
	const conclusionRows = $derived(view.groups.find((g) => g.name === CONCLUSION)?.rows ?? []);
	const dictatedNormalWords = $derived(new Map(states.dictatedNormal.map((d) => [d.region, d.words])));
	const trayRegions = $derived(pillRegions.filter((r) => !states.abnormal.includes(r)));
	// The gate never unlocks an impression nobody has seen (spec §5): a conclusion must exist (dictated,
	// drafted or typed). A failed draft never blocks: the radiologist types one or asks again.
	const hasConclusion = $derived(conclusionRows.length > 0 || (conclusion.kind === 'draft' && conclusion.text.trim().length > 0));
	const referrals = $derived(items.filter((i) => i.kind === 'referral'));
	const shownNames = $derived(new Set(shown.map((g) => g.name)));
	const covered = $derived(new Set(shown.flatMap((g) => g.members)));
	const rowsFor = (region: string) => items.filter((i) => i.kind !== 'referral' && anchorRegion(i, units) === region);
	// A joined card holds the rows and normals of the regions it spans, unless a region has its own card.
	const ownMembers = (g: { name: string; members: string[] }) => g.members.filter((m) => m === g.name || !shownNames.has(m));
	// A finding row whose region has no card (the writer named a region outside the scratchpad) shows up top.
	const looseRows = $derived(items.filter((i) => i.kind !== 'referral' && !covered.has(anchorRegion(i, units))));
	const openRows = $derived(openCount(items, tapped, removed, skipped));
	const openValues = $derived(openValueChips(values));
	const openValueCount = $derived(values.filter((v) => v.state === 'open' || v.state === 'check').length);
	// A required-value editor holding unsaved text holds Confirm (like an inline line edit)
	let valueDraft = $state(false);
	// Checks still asking: not answered, and their words still in the text (an edit that removes them resolves them).
	// A check whose words are on a line shown here is an underline with a hover card; any other is a row, in the card
	// holding its sentence or up top.
	// Against all lines joined, case and spacing aside: a check's sentence boundaries (Jev's splitter, the model's quote)
	// need not match the grouper's, and a check whose words are still there must never drop out (review 2026-10-12).
	const squash = (t: string) => t.toLowerCase().replace(/\s+/g, ' ').trim();
	const allText = $derived(squash(units.flatMap((u) => [u.text, ...(u.parts ?? []).map((x) => x.text)]).join(' ')));
	const inText = (q: string) => allText.includes(squash(q));
	const liveChecks = $derived(checks.filter((c) => !checkAnswers[c.key] && (c.unitId === null || inText(c.quote))));
	const blockingChecks = $derived(liveChecks.filter((c) => c.blocking).length);
	const flatRows = (rows: ViewRow[]): ViewRow[] => rows.flatMap((r) => [r, ...flatRows(r.children)]);
	// Lines in the order they are shown, for the walkthrough's top-to-bottom order.
	const shownLines = $derived(flatRows([...(technique?.rows ?? []), ...shown.flatMap((g) => g.rows), ...conclusionRows]));
	const onLine = (c: CheckFlag, r: ViewRow) => r.text.includes(c.quote) || (!!c.other && r.text.includes(c.other));
	/** The line a check's card opens on: its quote's line, else the other half's. */
	const cardLine = (c: CheckFlag) => shownLines.find((r) => r.text.includes(c.quote)) ?? shownLines.find((r) => onLine(c, r)) ?? null;
	const underlined = $derived(new Set(liveChecks.filter((c) => cardLine(c)).map((c) => c.key)));
	const rowChecks = $derived(liveChecks.filter((c) => !underlined.has(c.key)));
	const unitIds = (rows: ViewRow[]): number[] => rows.flatMap((r) => [r.unitId, ...unitIds(r.children)]);
	const checksIn = (rows: ViewRow[]) => {
		const ids = new Set(unitIds(rows));
		return rowChecks.filter((c) => c.unitId !== null && ids.has(c.unitId));
	};
	const shownUnitIds = $derived(new Set(shown.flatMap((g) => unitIds(g.rows))));
	const looseChecks = $derived(rowChecks.filter((c) => c.unitId === null || !shownUnitIds.has(c.unitId)));
	/** "Dictate correction": the sentence opens for editing and the mic starts. */
	function correct(c: CheckFlag) {
		const find = (rows: ViewRow[]): ViewRow | null => {
			for (const r of rows) {
				if (r.unitId === c.unitId) return r;
				const k = find(r.children);
				if (k) return k;
			}
			return null;
		};
		const r = find(view.groups.flatMap((g) => g.rows));
		if (!r) return;
		open(r);
		if (!recording) onToggleMic();
	}
	const unanswered = $derived(unansweredChecks(items, tapped, removed, skipped));

	// ── dictation checks: hover card and walkthrough ───────────────────────────────────────────────
	let hoverKey: string | null = $state(null);
	let pinnedKey: string | null = $state(null);
	// Hover intent (hand read 2026-10-12: the card vanished the moment the pointer left the words): leaving starts a
	// short grace period that entering the card cancels.
	let hoverTimer: ReturnType<typeof setTimeout> | null = null;
	function hoverOn(key: string) {
		if (walking) return;
		if (hoverTimer) clearTimeout(hoverTimer);
		hoverKey = key;
	}
	function hoverOff() {
		if (hoverTimer) clearTimeout(hoverTimer);
		hoverTimer = setTimeout(() => (hoverKey = null), 350);
	}
	const hoverHold = () => hoverTimer && clearTimeout(hoverTimer);
	/** The card is placed against the window (fixed), so no panel clips it: under its words when it fits, above them
	 *  otherwise, kept inside the window sideways; it follows its words on scroll and resize. */
	function placeCard(node: HTMLElement, key: string) {
		const anchor = () => node.parentElement?.querySelector<HTMLElement>(`[data-stop="${CSS.escape(`check:${key}`)}"]`) ?? node.parentElement;
		const place = () => {
			const a = anchor()?.getBoundingClientRect();
			if (!a) return;
			const h = node.offsetHeight, w = node.offsetWidth, gap = 6, pad = 8;
			const below = a.bottom + gap + h <= window.innerHeight - pad || a.top - gap - h < pad;
			node.style.top = `${below ? a.bottom + gap : a.top - gap - h}px`;
			node.style.left = `${Math.max(pad, Math.min(a.left, window.innerWidth - w - pad))}px`;
		};
		place();
		window.addEventListener('scroll', place, true);
		window.addEventListener('resize', place);
		return {
			destroy() {
				window.removeEventListener('scroll', place, true);
				window.removeEventListener('resize', place);
			}
		};
	}
	let walking = $state(false);
	let walkSkipped: string[] = $state([]);
	let walkTotal = $state(0);
	// What blocks Confirm, top to bottom: open referral rows, open or "stated?" required values, then each blocking
	// check by its line's position.
	const stops = $derived.by(() => {
		const rows = referrals.filter((i) => waiting(i, tapped, removed, skipped)).map((i) => `row:${i.id}`);
		const pos = (c: CheckFlag) => {
			const r = cardLine(c);
			return r ? shownLines.indexOf(r) : Number.MAX_SAFE_INTEGER;
		};
		const blocking = liveChecks.filter((c) => c.blocking).sort((a, b) => pos(a) - pos(b)).map((c) => `check:${c.key}`);
		const valueStops = values.filter((v) => v.state === 'open' || v.state === 'check').map((v) => `value:${v.item}`);
		// unresolved guideline cards (Copilot spec §7.12 item 5): last, each opened in the rail when it is the current stop
		const guides = guidelinesUnresolved.map((g) => `guideline:${g.key}`);
		const all = [...rows, ...valueStops, ...blocking, ...guides];
		return [...all.filter((x) => !walkSkipped.includes(x)), ...all.filter((x) => walkSkipped.includes(x))];
	});
	const current = $derived(walking ? (stops[0] ?? null) : null);
	const currentCheck = $derived(current?.startsWith('check:') ? (liveChecks.find((c) => `check:${c.key}` === current) ?? null) : null);
	const currentValue = $derived(current?.startsWith('value:') ? (values.find((v) => `value:${v.item}` === current) ?? null) : null);
	const currentGuide = $derived(current?.startsWith('guideline:') ? (guidelinesUnresolved.find((g) => `guideline:${g.key}` === current) ?? null) : null);
	$effect(() => {
		if (currentGuide) onOpenGuideline(currentGuide.key);
	});
	const cardOpen = (c: CheckFlag) => (walking ? currentCheck?.key === c.key : pinnedKey === c.key || hoverKey === c.key);
	$effect(() => {
		walkTotal = Math.max(walkTotal, stops.length);
	});
	$effect(() => {
		if (!current || typeof document === 'undefined') return;
		document.querySelector(`[data-stop="${CSS.escape(current)}"]`)?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' });
	});
	function startWalk() {
		if (!stops.length || checking) return;
		walkSkipped = [];
		walkTotal = stops.length;
		hoverKey = pinnedKey = null;
		walking = true;
		// The Confirm button that started the walk is gone: focus goes to the walkthrough bar (Tab there moves to the next
		// stop while there is one, else through the buttons)
		void tick().then(() => document.querySelector<HTMLElement>('[data-testid="walkthrough"]')?.focus());
	}
	function nextStop() {
		if (current && stops.length > 1) walkSkipped = [...walkSkipped.filter((x) => x !== current), current];
	}
	/** The line a check acts on: its card's line, else (a row check) its unit's line holding the words; with `whole`,
	 *  the unit itself when the words span lines (Edit only). */
	function target(c: CheckFlag, whole = false): { unitId: number; part: number | null; text: string } | null {
		const r = cardLine(c);
		if (r) return { unitId: r.unitId, part: partIndex(r), text: r.text };
		const u = units.find((x) => x.id === c.unitId);
		if (!u) return null;
		const k = (u.parts ?? []).findIndex((x) => x.text.includes(c.quote));
		if (k >= 0) return { unitId: u.id, part: k, text: u.parts![k].text };
		// The whole unit only when it is drawn as one line (a split unit or a tray line has no editor at part null)
		const drawn = whole && !u.parts?.length && shownUnitIds.has(u.id);
		return u.text.includes(c.quote) || drawn ? { unitId: u.id, part: null, text: u.text } : null;
	}
	function replaceCheck(c: CheckFlag) {
		const t = target(c);
		if (!t || !c.suggestion) return;
		onEditLine(t.unitId, t.part, replaced(t.text, c));
		onCheckAnswer(c.key, 'replaced');
		pinnedKey = hoverKey = null;
	}
	function deleteSentence(c: CheckFlag) {
		const t = target(c);
		if (!t) return;
		onEditLine(t.unitId, t.part, withoutQuote(t.text, c));
		pinnedKey = hoverKey = null;
	}
	function keepCheck(c: CheckFlag) {
		onCheckAnswer(c.key, c.blocking ? 'as_dictated' : 'skip');
		pinnedKey = hoverKey = null;
	}
	function editCheck(c: CheckFlag) {
		const t = target(c, true);
		if (!t) return;
		commit();
		editing = { unitId: t.unitId, part: t.part };
		editValue = t.text;
		onEditing(true);
	}
	function walkKey(e: KeyboardEvent) {
		if (!walking || editing || e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;   // browser shortcuts stay theirs
		const t = e.target as HTMLElement | null;
		if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
		const onControl = !!t && (t.tagName === 'BUTTON' || t.tagName === 'A');
		const c = currentCheck;
		if (e.key === 'Escape') walking = false;
		else if (e.key === 'Tab' && c && !e.shiftKey && !onControl && stops.length > 1) nextStop();   // otherwise Tab moves focus
		else if (c && e.key === 'Enter' && c.suggestion && !onControl) replaceCheck(c);
		else if (c && c.tier === 1 && target(c) && (e.key === 'd' || e.key === 'D')) deleteSentence(c);
		else if (c && (e.key === 'e' || e.key === 'E')) editCheck(c);
		else if (c && (e.key === 'k' || e.key === 'K')) keepCheck(c);
		else return;
		e.preventDefault();
	}
	function finishWalk() {
		walking = false;
		if (onConfirmGenerate) onConfirmGenerate();
		else onConfirm();
	}
	const FLAG_TITLE = 'May conflict with your dictation: confirm or remove';
	// Keyed by region and normalised text (round 1): the same words in another region carry no marker.
	const isFlagged = (regions: string[], s: string) => flaggedIn(flagged, regions, s);
	const keptAssumed = (region: string) => {
		const gone = new Set(removed.map((r) => r.trim().toLowerCase().replace(/\.$/, '')));
		return (assumed[region] ?? []).filter((s) => !gone.has(s.trim().toLowerCase().replace(/\.$/, '')));
	};
	// Dictated-normal regions split by structure (sub-pills): the structures the dictation answered go green, those
	// still assumed join the assumed chips.
	const saidChipNames = (r: string) => {
		const done = assumedReady ? coveredStructures(assumed[r] ?? [], removed, structures[r]) : [];
		return done.length ? done : [r];
	};
	const isSplit = (r: string) => Object.keys(structures[r] ?? {}).length > 0;
	// Every statement that will be reported without being dictated: region normals, and regions confirmed by
	// name where no sentences exist yet.
	const assumedCount = $derived(
		// a dictated-normal region counts the sheet sentences it keeps (review R2), never its own name
		trayRegions.reduce((n, r) => n + (dictatedNormalWords.has(r) ? keptAssumed(r).length : namedNormals ? 1 : keptAssumed(r).length), 0) +
			states.abnormal.reduce((n, r) => n + keptAssumed(r).length, 0)
	);
	let expanded: string[] = $state([]);
	let abnormalFor: string | null = $state(null);
	let abnormalText = $state('');
	let abnormalField: HTMLInputElement | null = $state(null);
	let abnormalFocused = $state(false);
	// The dictation hotkey (hand read 2026-10-12): set in the settings popover, saved per browser, used in the box and in
	// every inline edit. Default ⌥Space.
	type Hotkey = { alt: boolean; ctrl: boolean; meta: boolean; shift: boolean; code: string };
	const HOTKEY_KEY = 'rr_dictation_hotkey';
	const DEFAULT_HOTKEY: Hotkey = { alt: true, ctrl: false, meta: false, shift: false, code: 'Space' };
	function loadHotkey(): Hotkey {
		try {
			const v = JSON.parse(localStorage.getItem(HOTKEY_KEY) ?? 'null');
			return v && typeof v.code === 'string' ? v : DEFAULT_HOTKEY;
		} catch {
			return DEFAULT_HOTKEY;
		}
	}
	let hotkey: Hotkey = $state(typeof localStorage !== 'undefined' ? loadHotkey() : DEFAULT_HOTKEY);
	let settingsOpen = $state(false);
	let capturing = $state(false);
	const keyName = (code: string) => code.replace(/^Key/, '').replace(/^Digit/, '').replace('Space', 'Space');
	const hotkeyLabel = $derived(`${hotkey.ctrl ? '⌃' : ''}${hotkey.alt ? '⌥' : ''}${hotkey.shift ? '⇧' : ''}${hotkey.meta ? '⌘' : ''}${keyName(hotkey.code)}`);
	const isHotkey = (e: KeyboardEvent) =>
		e.code === hotkey.code && e.altKey === hotkey.alt && e.ctrlKey === hotkey.ctrl && e.metaKey === hotkey.meta && e.shiftKey === hotkey.shift;
	function captureHotkey(e: KeyboardEvent) {
		if (!capturing) return;
		e.preventDefault();
		e.stopPropagation();
		if (e.key === 'Escape') {
			capturing = false;
			return;
		}
		if (['Alt', 'Control', 'Meta', 'Shift'].includes(e.key)) return; // wait for the main key
		if (!e.altKey && !e.ctrlKey && !e.metaKey && !/^F\d+$/.test(e.code)) return; // needs a modifier (or a function key)
		hotkey = { alt: e.altKey, ctrl: e.ctrlKey, meta: e.metaKey, shift: e.shiftKey, code: e.code };
		capturing = false;
		try {
			localStorage.setItem(HOTKEY_KEY, JSON.stringify(hotkey));
		} catch {
			/* kept for this session */
		}
	}
	function resetHotkey() {
		hotkey = DEFAULT_HOTKEY;
		try {
			localStorage.removeItem(HOTKEY_KEY);
		} catch {
			/* ignore */
		}
	}
	// Global: the hotkey starts and stops dictation anywhere in the scratchpad (inline edits handle it themselves).
	$effect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (capturing || !isHotkey(e)) return;
			e.preventDefault();
			onToggleMic();
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});
	// "Dictate finding": opening it starts the mic (the radiologist asked to dictate); closing stops it if it started it.
	let micByField = false;
	function openAbnormal(id: string) {
		abnormalFor = id;
		abnormalText = '';
		micByField = !recording;
		if (!recording) onToggleMic();
	}
	function closeAbnormal() {
		abnormalFor = null;
		abnormalText = '';
		if (micByField && recording) onToggleMic();
		micByField = false;
	}
	let assumedEditing: string | null = $state(null);
	let assumedText = $state('');
	let assumedField: HTMLTextAreaElement | null = $state(null);
	let assumedFocused = $state(false);
	function openAssumed(s: string) {
		commit();
		assumedEditing = s;
		assumedText = s;
	}
	function commitAssumed() {
		if (assumedEditing === null) return;
		const original = assumedEditing;
		assumedEditing = null;
		assumedFocused = false;
		onEditing(editing !== null || draftFocused || newFocused);
		if (assumedText.trim() !== original.trim()) onEditAssumed(original, assumedText.trim());
	}
	/** The unit (or part of a split unit) holding a dictated sentence, so a normal quoted from the dictation edits in place. */
	function sourceOf(text: string): { unitId: number; part: number | null } | null {
		for (const x of units) {
			if (x.heading) continue;
			if (x.text === text) return { unitId: x.id, part: null };
			const k = x.parts?.findIndex((p) => p.text === text) ?? -1;
			if (k >= 0 && x.parts && x.parts.length > 1) return { unitId: x.id, part: k };
		}
		return null;
	}
	let openPill: string | null = $state(null);

	// ── editing: one field at a time (a line, or the draft) ─────────────────────────────────────────
	let editing: { unitId: number; part: number | null } | null = $state(null);
	let editValue = $state('');
	let field: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
	let draftField: HTMLTextAreaElement | null = $state(null);
	let draftFocused = $state(false);
	let newLine = $state('');
	let newField: HTMLInputElement | null = $state(null);
	let newFocused = $state(false);
	function appendNew() {
		const t = newLine.trim();
		if (t) onAppend(t);
		newLine = '';
	}
	let lastSeq = -1;

	function partIndex(r: ViewRow): number | null {
		if (r.partOf === null) return null;
		const u = units.find((x) => x.id === r.unitId);
		const k = u?.parts?.findIndex((p) => p.text === r.text) ?? -1;
		return k >= 0 ? k : null;
	}
	function rowText(unitId: number, part: number | null): string {
		const u = units.find((x) => x.id === unitId);
		if (!u) return '';
		return part === null ? u.text : (u.parts?.[part]?.text ?? '');
	}
	function open(r: ViewRow) {
		commit();
		editing = { unitId: r.unitId, part: partIndex(r) };
		editValue = r.text;
		onEditing(true);
	}
	function commit() {
		if (!editing) return;
		const e = editing;
		editing = null;
		onEditing(draftFocused || newFocused);
		if (editValue.trim() !== rowText(e.unitId, e.part).trim()) onEditLine(e.unitId, e.part, editValue.trim());
	}
	const isEditing = (r: ViewRow) => editing !== null && editing.unitId === r.unitId && editing.part === partIndex(r);

	/** Dictated words into a field: over the selection, or at the caret, with spaces at the joins. */
	function insertInto(el: HTMLInputElement | HTMLTextAreaElement, value: string, text: string): { value: string; caret: number } {
		const from = el.selectionStart ?? value.length;
		const to = el.selectionEnd ?? from;
		const before = value.slice(0, from);
		const after = value.slice(to);
		const lead = before && !/\s$/.test(before) ? ' ' : '';
		const trail = after && !/^[\s.,;:?!]/.test(after) ? ' ' : '';
		return { value: before + lead + text.trim() + trail + after, caret: (before + lead + text.trim()).length };
	}
	$effect(() => {
		if (!incoming || incoming.seq === lastSeq) return;
		lastSeq = incoming.seq;
		const el = editing ? field : abnormalFocused ? abnormalField : assumedFocused ? assumedField : draftFocused ? draftField : newFocused ? newField : null;
		if (!el) return;
		const cur = editing ? editValue : abnormalFocused ? abnormalText : assumedFocused ? assumedText : newFocused ? newLine : conclusion.kind === 'draft' ? conclusion.text : '';
		const r = insertInto(el, cur, incoming.text);
		if (editing) editValue = r.value;
		else if (abnormalFocused) abnormalText = r.value;
		else if (assumedFocused) assumedText = r.value;
		else if (newFocused) newLine = r.value;
		else onDraftEdit(r.value);
		queueMicrotask(() => el.setSelectionRange(r.caret, r.caret));
	});
	/** Keeps the scratchpad box scrolled to its latest line. */
	function pinBottom(node: HTMLElement, _key?: string) {
		const pin = () => (node.scrollTop = node.scrollHeight);
		queueMicrotask(pin);
		return { update: () => queueMicrotask(pin) };
	}
	/** A textarea that is exactly as tall as its text (an inline edit keeps the sentence's shape). */
	function autosize(el: HTMLTextAreaElement, _value?: string) {
		const fit = () => {
			el.style.height = 'auto';
			el.style.height = `${el.scrollHeight}px`;
		};
		queueMicrotask(fit);
		el.addEventListener('input', fit);
		return { update: () => queueMicrotask(fit), destroy: () => el.removeEventListener('input', fit) };
	}
	function focusOnMount(el: HTMLInputElement | HTMLTextAreaElement) {
		el.focus();
	}

	let dragOver: string | null = $state(null);
	function drop(e: DragEvent, group: string) {
		e.preventDefault();
		dragOver = null;
		const id = Number(e.dataTransfer?.getData('text/plain'));
		if (Number.isFinite(id)) onMove(id, group);
	}
</script>

{#snippet row(it: StackItem, label: string | null)}
	<!-- One compact line (hand read 2026-10-12): tag, question, its sentences inline with ×, then the answer. The
	     reason sits behind ⓘ. A tap adds exactly the sentences shown. -->
	{@const listed = rowSentences(it, removed)}
	{#if skipped.includes(it.id)}
		<!-- skipped or not assessed: folded, nothing stated -->
	{:else if tapped.includes(it.id)}
		<div class="flex flex-wrap items-baseline gap-x-2 rounded-md border-l-2 border-emerald-500/60 bg-emerald-500/[0.06] px-2 py-1 text-sm" data-row="tapped">
			{#if label}<span class="text-[10px] uppercase tracking-wide text-emerald-300/70">{label}</span>{/if}
			<span class="text-emerald-200">✓ {listed.join(' ')}</span>
		</div>
	{:else if it.answered}
		<div class="flex flex-wrap items-baseline gap-x-2 rounded-md border-l-2 border-emerald-500/60 bg-emerald-500/[0.06] px-2 py-1 text-sm" data-row="answered" transition:fade={{ duration: ms }}>
			<span class="text-emerald-200">✓ {it.question}</span><span class="text-xs text-emerald-300/70">answered in your dictation</span>
		</div>
	{:else if it.kind === 'template' && actionsReady}
		<!-- A template row (a findings-triggered habit): the template's own question. Yes / No add the template's own
		     sentence for that answer; Not assessed states nothing. -->
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border-l-2 border-amber-400/80 bg-amber-500/[0.07] px-2.5 py-1.5" data-row="template" transition:fade={{ duration: ms }}>
			{#if label}<span class="text-[10px] font-semibold uppercase tracking-wide text-amber-300/90">{label}</span>{/if}
			<span class="text-sm font-medium text-amber-100">{it.question}</span>
			{#if it.why}<span class="cursor-help text-xs text-gray-500" title={it.why} aria-label="Why: {it.why}">ⓘ</span>{/if}
			<span class="ml-auto flex gap-1">
				<button type="button" class="focus-ring rounded-md border border-amber-300/40 bg-amber-400/15 px-2.5 py-0.5 text-xs font-medium text-amber-100 transition-colors hover:bg-amber-400/25"
					title="Add: {it.yes}" onclick={() => onAnswerTemplate(it.id, 'yes')}>Yes</button>
				<button type="button" class="focus-ring rounded-md border border-amber-300/40 bg-amber-400/15 px-2.5 py-0.5 text-xs font-medium text-amber-100 transition-colors hover:bg-amber-400/25"
					title="Add: {it.no}" onclick={() => onAnswerTemplate(it.id, 'no')}>No</button>
				<button type="button" class="focus-ring rounded-md px-2 py-0.5 text-xs text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-300" title="Nothing is stated"
					onclick={() => onSkip(it.id)}>Not assessed</button>
			</span>
		</div>
	{:else if listed.length && !actionsReady}
		<!-- Before the review: a reminder of the question only, no buttons. -->
		<div class="flex flex-wrap items-center gap-x-2 rounded-md border-l-2 border-amber-400/50 bg-amber-500/[0.05] px-2 py-1" data-row="waiting">
			{#if label}<span class="text-[10px] font-semibold uppercase tracking-wide text-amber-300/80">{label}</span>{/if}
			<span class="text-sm text-amber-100/90">{it.question}</span>
			<span class="text-xs text-gray-500">answer it in your dictation</span>
		</div>
	{:else if listed.length}
		<!-- Compact (hand read 2026-10-12): the question, then the normal wordings with "✓ Normal" in line; "Abnormal…"
		     opens a box in the row to type or dictate the finding; Skip. -->
		<div class="space-y-1 rounded-md border-l-2 border-amber-400/80 bg-amber-500/[0.07] px-2 py-1.5" data-row="open" transition:fade={{ duration: ms }}>
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				{#if label}<span class="text-[10px] font-semibold uppercase tracking-wide text-amber-300/90">{label}</span>{/if}
				<span class="text-sm font-medium text-amber-100">{it.question}</span>
				{#if it.why}<span class="cursor-help text-xs text-gray-500" title={it.why} aria-label="Why: {it.why}">ⓘ</span>{/if}
				<span class="ml-auto flex gap-1">
					<button type="button" class="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/[0.06]"
						onclick={() => (abnormalFor === it.id ? closeAbnormal() : openAbnormal(it.id))}>
						<svg viewBox="0 0 24 24" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
						Dictate finding</button>
					<button type="button" class="rounded-md px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300"
						title={it.kind === 'referral' ? 'The scan cannot answer it: nothing is stated' : 'Not relevant: nothing is stated'}
						onclick={() => onSkip(it.id)}>{it.kind === 'referral' ? 'Not assessed' : 'Skip'}</button>
				</span>
			</div>
			<div class="flex flex-wrap items-center gap-1.5">
				{#each listed as s (s)}
					<span class="inline-flex items-center gap-0.5 rounded bg-white/[0.04] px-1.5 py-0.5 text-xs text-gray-200">
						{s}
						<button type="button" class="px-0.5 text-gray-500 hover:text-rose-300" title="Remove: never stated"
							aria-label="Remove {s}" onclick={() => onRemoveSentence(s)}>×</button>
					</span>
				{/each}
				<button type="button" class="rounded-md border border-amber-300/40 bg-amber-400/15 px-2 py-0.5 text-xs font-medium text-amber-100 hover:bg-amber-400/25"
					title="Add: {listed.join(' ')}" onclick={() => onAnswer(it.id)}>{answerLabel(listed)}</button>
			</div>
			{#if abnormalFor === it.id}
				<div class="flex items-center gap-2 rounded bg-white/[0.05] px-2 py-1 ring-1 ring-amber-400/30">
					<button type="button" class="shrink-0 rounded-full p-1 {recording ? 'bg-rose-500/20 text-rose-300' : 'text-gray-400 hover:text-gray-200'}"
						title={recording ? `Stop dictating (${hotkeyLabel})` : `Start dictating (${hotkeyLabel})`} aria-label={recording ? 'Stop dictating' : 'Start dictating'}
						onmousedown={(e) => e.preventDefault()} onclick={onToggleMic}>
						<svg viewBox="0 0 24 24" class="h-3.5 w-3.5 {recording ? 'animate-pulse' : ''}" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
					</button>
					<input
						bind:this={abnormalField}
						bind:value={abnormalText}
						use:focusOnMount
						class="min-w-0 flex-1 border-0 bg-transparent p-0 text-sm text-gray-100 placeholder:text-gray-500 focus:outline-none focus:ring-0"
						placeholder={recording ? 'Listening… speak the finding' : 'Type or dictate the finding'}
						aria-label="Abnormal finding"
						onfocus={() => {
							abnormalFocused = true;
							onEditing(true);
						}}
						onblur={() => {
							abnormalFocused = false;
							onEditing(editing !== null || draftFocused || newFocused);
						}}
						onkeydown={(e) => {
							if (e.key === 'Enter' && abnormalText.trim()) {
								e.preventDefault();
								onAbnormal(it.id, abnormalText.trim());
								closeAbnormal();
							} else if (e.key === 'Escape') closeAbnormal();
						}}
					/>
					<span class="hidden shrink-0 text-[10px] text-gray-500 sm:inline">{hotkeyLabel} {recording ? 'stop' : 'start'} · Enter add · Esc cancel</span>
				</div>
			{/if}
		</div>
	{/if}
{/snippet}

{#snippet checkCard(c: CheckFlag)}
	<!-- The hover card of an underlined check (2026-10-12, Grammarly-style): what it is, the words, why, the likely
	     words when one reading is certain, and Replace / Edit / Keep. In the walkthrough it stays open on the current
	     item and the keys below act on it. -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div role="dialog" aria-label={checkLabel(c.kind)} data-card={c.key} transition:fade={{ duration: ms }} use:placeCard={c.key}
		onmouseenter={hoverHold} onmouseleave={() => { if (!walking) hoverOff(); }}
		class="fixed z-50 w-80 max-w-[calc(100vw-1rem)] space-y-2 rounded-lg border border-white/15 bg-gray-950/95 p-3 text-xs leading-5 text-gray-300 shadow-xl">
		<p class="flex items-center gap-2">
			<span class="rounded px-1.5 py-px text-[10px] font-semibold {c.blocking ? 'bg-orange-400 text-gray-950' : 'bg-white/10 text-gray-300'}">{c.blocking ? 'Blocks Confirm' : 'Advisory'}</span>
			<span class="text-sm font-medium text-gray-100">{checkLabel(c.kind)}</span>
		</p>
		<p class="text-gray-200">{`“${c.quote}”${c.other ? ` · “${c.other}”` : ''}`}</p>
		{#if c.message}<p class="text-gray-400">{c.message}</p>{/if}
		{#if c.suggestion}<p>Likely: <span class="font-semibold text-orange-300">{c.suggestion}</span></p>{/if}
		<p class="flex flex-wrap gap-1.5">
			{#if c.suggestion}<button type="button" class="rounded-md bg-orange-400 px-2.5 py-1 font-semibold text-gray-950 hover:bg-orange-300" onclick={() => replaceCheck(c)}>Replace</button>{/if}
			<button type="button" class="rounded-md border border-white/15 px-2.5 py-1 text-gray-100 hover:bg-white/[0.06]" onclick={() => editCheck(c)}>{c.tier === 1 ? 'Finish it' : 'Edit'}</button>
			{#if c.tier === 1 && target(c)}<button type="button" class="rounded-md border border-white/10 px-2.5 py-1 text-gray-400 hover:text-rose-300" onclick={() => deleteSentence(c)}>Delete sentence</button>{/if}
			<button type="button" class="rounded-md border border-white/10 px-2.5 py-1 text-gray-400 hover:text-gray-200" onclick={() => keepCheck(c)}>{c.blocking ? 'Keep as dictated' : 'Skip'}</button>
		</p>
		{#if walking}<p class="text-[10px] text-gray-500">{c.suggestion ? 'Enter replace · ' : ''}E edit · {c.tier === 1 ? 'D delete · ' : ''}K keep · Tab next · Esc exit</p>{/if}
	</div>
{/snippet}

{#snippet checkRow(c: CheckFlag)}
	<!-- A dictation check (2026-10-12), in the row language of the checklist: what it asks, the words it is about, and
	     answer-shaped buttons. The model's explanation sits behind ⓘ. -->
	<div class="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border-l-2 border-amber-400/80 bg-amber-500/[0.07] px-2 py-1.5 {currentCheck?.key === c.key ? 'ring-2 ring-orange-400/60' : ''}"
		data-check={c.kind} data-stop={`check:${c.key}`} transition:fade={{ duration: ms }}>
		<span class="text-sm font-medium text-amber-100">{checkLabel(c.kind)}</span>
		<span class="min-w-0 text-xs text-gray-300">{`“${c.quote}”${c.other ? ` · “${c.other}”` : ''}`}</span>
		<span class="cursor-help text-xs text-gray-500" title={c.message} aria-label="Why: {c.message}">ⓘ</span>
		<span class="ml-auto flex gap-1">
			{#if c.unitId !== null}
				<button type="button" class="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-0.5 text-xs text-gray-300 hover:bg-white/[0.06]" onclick={() => correct(c)}>
					<svg viewBox="0 0 24 24" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
					Dictate correction
				</button>
			{/if}
			{#if c.suggestion && target(c)}<button type="button" class="rounded-md bg-orange-400/90 px-2 py-0.5 text-xs font-semibold text-gray-950 hover:bg-orange-300" onclick={() => replaceCheck(c)}>Replace with “{c.suggestion}”</button>{/if}
			{#if !c.blocking}<button type="button" class="rounded-md px-2 py-0.5 text-xs text-gray-500 hover:text-gray-300" onclick={() => onCheckAnswer(c.key, 'skip')}>Skip</button>{/if}
			<button type="button" class="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-200 hover:bg-emerald-500/25" onclick={() => onCheckAnswer(c.key, 'as_dictated')}>✓ As dictated</button>
		</span>
	</div>
{/snippet}

{#snippet micControls(hint: string)}
	<!-- Dictation controls in any inline edit (hand read 2026-10-12): a mic toggle that keeps the cursor in place, and
	     the hotkeys. -->
	<span class="flex flex-wrap items-center gap-2 px-1 pt-0.5 text-[10px] text-gray-500">
		<button type="button" class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 {recording ? 'bg-rose-500/20 text-rose-300' : 'text-gray-400 hover:text-gray-200'}"
			title={recording ? `Stop dictating (${hotkeyLabel})` : `Start dictating (${hotkeyLabel})`} aria-label={recording ? 'Stop dictating' : 'Start dictating'}
			onmousedown={(e) => e.preventDefault()} onclick={onToggleMic}>
			<svg viewBox="0 0 24 24" class="h-3 w-3 {recording ? 'animate-pulse' : ''}" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
			{recording ? 'listening' : 'dictate'}
		</button>
		<span>{hotkeyLabel} {recording ? 'stop' : 'start'} · {hint}</span>
		{#if editGhost}<span class="italic text-gray-400" transition:fade={{ duration: ms }}>{editGhost}</span>{/if}
	</span>
{/snippet}

{#snippet sentences(list: string[], key: string, regions: string[])}
	<!-- A flagged normal is never hidden behind "+N more": the radiologist must see it to confirm or remove it. -->
	{@const q = expanded.includes(key) || list.slice(QUIET_MAX).some((s) => isFlagged(regions, s)) ? { shown: list, more: 0 } : quietLine(list)}
	{#each q.shown as s (s)}
		{#if assumedEditing === s}
			<textarea
				bind:this={assumedField}
				bind:value={assumedText}
				use:focusOnMount
				use:autosize={assumedText}
				rows="1"
				class="block w-full resize-none overflow-hidden rounded border-0 bg-white/[0.05] px-0.5 py-0 text-xs leading-6 text-gray-100 outline outline-1 outline-emerald-500/30 focus:ring-0"
				aria-label="Edit normal"
				onfocus={() => {
					assumedFocused = true;
					onEditing(true);
				}}
				onblur={commitAssumed}
				onkeydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						commitAssumed();
					} else if (e.key === 'Escape') {
						assumedEditing = null;
					}
				}}
			></textarea>
			{@render micControls('Enter save · Esc cancel')}
		{:else}
			<span class="inline-flex items-center gap-0.5">
				{#if isFlagged(regions, s)}
					<span class="rounded bg-amber-500/15 px-1 text-[10px] uppercase tracking-wide text-amber-300" title={FLAG_TITLE}
						data-flag="conflict">check</span>
				{/if}
				<!-- Click to edit (hand read 2026-10-12): an edited normal becomes the radiologist's own words. -->
				<button type="button" class="cursor-text rounded text-left text-gray-300/80 underline decoration-emerald-500/40 decoration-dashed underline-offset-4 hover:bg-white/[0.04] hover:text-gray-200"
					title="Click to edit" onclick={() => openAssumed(s)}>{s}</button>
				<button type="button" class="rounded px-0.5 text-gray-600 hover:text-rose-300" title="Remove: never stated"
					aria-label="Remove {s}" onclick={() => onRemoveSentence(s)}>×</button>
			</span>
		{/if}
	{/each}
	{#if q.more}
		<button type="button" class="text-gray-500 hover:text-gray-300" onclick={() => (expanded = [...expanded, key])}>+{q.more} more</button>
	{/if}
{/snippet}

{#snippet line(r: ViewRow, nested: boolean)}
	<!-- No sentence travels across the screen (hand read 2026-10-12: the slide back and forth read as a bug): a placed
	     sentence fades in where it belongs with a soft highlight that fades out. -->
	<li class="relative flex items-start gap-1 rounded transition-colors duration-1000 {fresh.includes(`${r.unitId}|${r.text}`) ? 'bg-purple-500/15' : ''}" in:fade={{ duration: ms }}
		onmouseleave={() => { if (!walking) hoverOff(); }}>
		<div class="min-w-0 flex-1 {nested ? 'pl-4' : ''}">
			{#if isEditing(r)}
				<!-- True inline edit (hand read 2026-10-12): same font, line height and padding as the sentence; it wraps and
				     grows instead of scrolling sideways. -->
				<textarea
					bind:this={field}
					bind:value={editValue}
					use:focusOnMount
					use:autosize={editValue}
					rows="1"
					class="block w-full resize-none overflow-hidden rounded border-0 bg-white/[0.05] px-1 py-0 text-sm leading-6 text-gray-100 outline outline-1 outline-emerald-500/30 focus:ring-0"
					aria-label="Edit line"
					onblur={commit}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === 'Escape') {
							e.preventDefault();
							commit();
						}
					}}
				></textarea>
				{@render micControls('Enter save · Esc cancel')}
			{:else}
				<!-- The grouper's structure label is a tooltip, not text: it repeated the sentence (hand read 2026-10-12). -->
				{@const marks = liveChecks.filter((c) => underlined.has(c.key) && onLine(c, r))}
				<button type="button" class="w-full rounded px-1 text-left text-sm leading-6 text-gray-200 hover:bg-white/[0.05]" onclick={() => open(r)}
					title={r.structure ? `Placed as: ${r.structure}` : undefined}>
					{#if nested}<span aria-hidden="true" class="text-gray-500">↳ </span>{/if}{#each segments(r.text, marks) as seg, k (k)}{#if seg.check}{@const c = seg.check}<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions --><span
						data-stop={`check:${c.key}`} data-check={c.kind}
						class="rounded-sm underline decoration-orange-400 decoration-2 underline-offset-4 {c.blocking ? '' : 'decoration-dotted'} {currentCheck?.key === c.key ? 'bg-orange-400/15' : ''}"
						onmouseenter={() => hoverOn(c.key)}
						onclick={(e) => { e.stopPropagation(); if (!walking) pinnedKey = pinnedKey === c.key ? null : c.key; }}>{seg.text}</span>{:else}{seg.text}{/if}{/each}
					{#if r.pinned}<span class="ml-1 text-xs text-gray-500" title="Placed by you">•</span>{/if}
				</button>
				{#each marks.filter((c) => cardOpen(c) && cardLine(c) === r) as c (c.key)}{@render checkCard(c)}{/each}
			{/if}
			{#if r.children.length}
				<ul>{#each r.children as c (c.unitId + ':' + c.text)}{@render line(c, true)}{/each}</ul>
			{/if}
		</div>
	</li>
{/snippet}

<svelte:window onkeydown={walkKey} />

<div class="space-y-3" data-testid="hybrid-stack">
	<ValueChips {values} {current} onEnter={onEnterValue} onNa={onValueNa} onRestNa={onValuesRestNa} onKeep={onKeepValue} onPick={onPickValue} onDraft={(d) => (valueDraft = d)} />
	<!-- The scratchpad box (hand read 2026-10-12): one permanent, fixed-size box for what is being said now and a line
	     to type into. It never changes size, so nothing below it jumps; longer text scrolls inside it, pinned to the
	     latest line. -->
	<section aria-label="Scratchpad" class="relative overflow-visible rounded-lg border border-white/10 bg-white/[0.025]">
		<div class="flex items-center justify-between border-b border-white/5 px-3 py-1">
			<span class="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
				Live dictation
				{#if recording}<span class="flex items-center gap-1 font-normal normal-case tracking-normal text-rose-300"><span class="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400"></span>listening</span>{/if}
			</span>
			<button type="button" class="rounded p-1 text-gray-500 hover:bg-white/[0.06] hover:text-gray-300" aria-label="Dictation settings"
				title="Dictation settings" onclick={() => (settingsOpen = !settingsOpen)}>
				<svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>
			</button>
			{#if settingsOpen}
				<!-- Dictation settings: the start/stop hotkey, recorded by pressing it; saved in this browser. -->
				<div class="absolute right-2 top-8 z-20 w-64 space-y-2 rounded-lg border border-white/10 bg-gray-950/95 p-3 text-xs text-gray-300 shadow-xl" role="dialog" aria-label="Dictation settings">
					<p class="text-[10px] font-semibold uppercase tracking-wide text-gray-500">Dictation hotkey</p>
					<div class="flex items-center justify-between gap-2">
						<span class="text-gray-400">Start / stop</span>
						<button type="button" class="rounded-md border px-2 py-0.5 font-mono {capturing ? 'border-purple-400/60 text-purple-200' : 'border-white/15 text-gray-200 hover:border-white/30'}"
							onclick={() => (capturing = true)} onkeydown={captureHotkey}>{capturing ? 'Press keys…' : hotkeyLabel}</button>
					</div>
					<p class="text-[10px] text-gray-500">{capturing ? 'Press a combination with ⌥, ⌃ or ⌘ (Esc cancels).' : 'Works in the box and in any inline edit.'}</p>
					<div class="flex justify-between">
						<button type="button" class="text-[10px] text-gray-500 hover:text-gray-300" onclick={resetHotkey}>Reset to ⌥Space</button>
						<button type="button" class="text-[10px] text-gray-400 hover:text-gray-200" onclick={() => { settingsOpen = false; capturing = false; }}>Done</button>
					</div>
				</div>
			{/if}
		</div>
		<div class="h-24 overflow-y-auto px-3 py-2" use:pinBottom={`${pending.join('|')}|${ghost}|${view.unplaced.length}`}>
			{#if !view.unplaced.length && !pending.length && !ghost}
				<!-- A hint, not a field: typing happens in the line below (hand read 2026-10-12). -->
				<p class="flex h-full items-center justify-center gap-1.5 text-xs text-gray-600">
					<svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>
					{recording ? 'Listening…' : `Press ${hotkeyLabel} or the mic to dictate`}
				</p>
			{/if}
			<ul aria-label="Just dictated">
				<!-- A sentence fades out of the box as it fades into its section, so the hand-over reads as one motion. -->
				{#each view.unplaced as r (r.text)}<li class="text-sm leading-6 text-gray-200" in:fade={{ duration: ms }} out:fade={{ duration: ms }}>{r.text}</li>{/each}
				{#each pending as text (text)}<li class="text-sm leading-6 text-gray-200" in:fade={{ duration: ms }} out:fade={{ duration: ms }}>{text}</li>{/each}
				{#if ghost}<li class="text-sm italic leading-6 text-gray-500">{ghost}</li>{/if}
			</ul>
		</div>
		<div class="flex items-center gap-2 border-t border-white/5 px-3 py-1.5">
			<input
				bind:this={newField}
				bind:value={newLine}
				class="min-w-0 flex-1 border-0 bg-transparent p-0 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-0"
				placeholder="Type a finding (Enter adds it)"
				aria-label="New line"
				onfocus={() => {
					newFocused = true;
					onEditing(true);
				}}
				onblur={() => {
					newFocused = false;
					appendNew(); // words typed or dictated into the field are never lost on blur
					onEditing(editing !== null || draftFocused);
				}}
				onkeydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						appendNew();
					}
				}}
			/>
		</div>
	</section>

	{#if referrals.length}
		<section aria-label="Referral question" class="space-y-1">{#each referrals as it (it.id)}<div data-stop={`row:${it.id}`} class="rounded-md {current === `row:${it.id}` ? 'ring-2 ring-orange-400/60' : ''}">{@render row(it, 'Referral')}</div>{/each}</section>
	{/if}
	{#if looseRows.length || looseChecks.length}
		<section aria-label="Checks" class="space-y-1">
			{#each looseRows as it (it.id)}{@render row(it, it.region || null)}{/each}
			{#each looseChecks as c (c.key)}{@render checkRow(c)}{/each}
		</section>
	{/if}



	{#if technique}
		<section aria-label={TECHNIQUE} class="text-gray-400">
			<ul>{#each technique.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		</section>
	{/if}

	<!-- Scratchpad: abnormal regions only -->
	{#each shown as g (g.name)}
		{@const mine = ownMembers(g).flatMap((m) => rowsFor(m))}
		{@const flagged = checksIn(g.rows)}
		{@const normals = ownMembers(g).flatMap((m) => keptAssumed(m))}
		<section
			animate:flip={{ duration: ms }}
			in:fade={{ duration: ms }}
			class="rounded {dragOver === g.name ? 'bg-emerald-500/10' : ''} {deleteRegion === g.name ? 'outline outline-1 outline-rose-500/60' : ''}"
			ondragover={(e) => {
				e.preventDefault();
				dragOver = g.name;
			}}
			ondragleave={() => (dragOver = null)}
			ondrop={(e) => drop(e, g.members[0])}
			aria-label={g.name}
		>
			<h3 class="text-xs font-semibold uppercase tracking-wide text-gray-400">{g.name}</h3>
			<ul>{#each g.rows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
			{#if deleteRegion === g.name}
				<div class="mt-1 flex gap-2 px-1 text-xs">
					<button type="button" class="rounded bg-rose-500/20 px-2 py-0.5 text-rose-200" onclick={() => onDeleteRegion(g.name, true)}>Delete these lines</button>
					<button type="button" class="rounded px-2 py-0.5 text-gray-400 hover:text-gray-200" onclick={() => onDeleteRegion(g.name, false)}>Keep</button>
				</div>
			{/if}
			{#if mine.length || flagged.length}
				<div class="mt-1 space-y-1 px-1" aria-label="Questions for {g.name}">
					{#each flagged as c (c.key)}{@render checkRow(c)}{/each}
					{#each mine as it (it.id)}{@render row(it, null)}{/each}
				</div>
			{/if}
			{#if normals.length}
				<p class="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-1 text-xs" data-quiet={g.name}>
					<span class="text-[10px] uppercase tracking-wide text-emerald-400/70">Will also be reported</span>
					{@render sentences(normals, g.name, ownMembers(g))}
				</p>
			{/if}
		</section>
	{/each}

	<!-- Rows over the caps (E1b): one quiet line; opened, ordinary rows with their region. -->
	{#if more.length}
		<section aria-label="More checks" class="space-y-1">
			<button type="button" class="px-1 text-xs text-gray-500 hover:text-gray-300" aria-expanded={moreOpen} onclick={onToggleMore}>
				{moreOpen ? '▾' : '▸'} {moreWaiting ? `${moreWaiting} more ${moreWaiting === 1 ? 'check' : 'checks'}` : 'More checks'}</button>
			{#if moreOpen}
				{#each more as it (it.id)}{@render row(it, it.region || null)}{/each}
			{/if}
		</section>
	{/if}

	<!-- While the end-of-dictation review runs: placeholder rows where the checks will appear, so they never arrive as a
	     shock (hand read 2026-10-12). -->
	{#if reviewing && !items.some((i) => !i.answered)}
		<section aria-label="Checking the findings" class="space-y-1.5" data-testid="review-skeleton">
			<p class="text-[10px] uppercase tracking-wide text-amber-300/70">Checking the findings…</p>
			{#each [0, 1] as k (k)}
				<div class="flex animate-pulse items-center gap-3 rounded-md border-l-2 border-amber-400/30 bg-amber-500/[0.04] px-2 py-2">
					<span class="h-3 w-40 rounded bg-white/10"></span>
					<span class="h-3 w-56 rounded bg-white/[0.06]"></span>
					<span class="ml-auto h-4 w-16 rounded bg-white/[0.06]"></span>
				</div>
			{/each}
		</section>
	{/if}

	<!-- Normal regions (hand read 2026-10-12): what the radiologist said is normal, with their words beside it (a bare
	     pill read as missed); then the assumed regions together, tap one to see what will be reported. -->
	{#if assumedFailed}
		<p role="status" data-assumed-failed class="rounded-md border border-amber-400/30 bg-amber-500/[0.06] px-2.5 py-1.5 text-xs text-amber-200">
			Couldn't check normals — they won't be assumed. Dictate the normals you want reported.
		</p>
	{/if}
	{#if trayRegions.length}
		{@const said = trayRegions.filter((r) => dictatedNormalWords.has(r))}
		<!-- A region the dictation touches with nothing left to assume is not normal: it leaves the section (hand read
		     2026-10-12), once the assumed check has answered (until then nothing is hidden, so the tray never flickers). -->
		{@const rest = trayRegions.filter((r) => !dictatedNormalWords.has(r) && (namedNormals || !assumedReady || keptAssumed(r).length > 0))}
		<!-- One chip per region, or per structure for a split template paragraph (sub-pills); a dictated-normal split
		     paragraph's structures still assumed join them. -->
		{@const chips = [...trayRegions.filter((r) => rest.includes(r) || (said.includes(r) && isSplit(r) && keptAssumed(r).length > 0))
			.flatMap((r) => (namedNormals ? [{ key: r, region: r, label: r, sentences: keptAssumed(r) }]
				: regionChips(r, keptAssumed(r), structures[r]).filter((c) => rest.includes(r) || c.sentences.length)))]}
		{@const openChip = chips.find((c) => c.key === openPill)}
		<section aria-label="Normal regions" class="space-y-2 border-t border-white/5 pt-2">
			{#if said.length}
				<div class="space-y-1">
					<p class="text-[10px] uppercase tracking-wide text-gray-500">Normal, as you said</p>
					<!-- Regions that share the same dictated words share one line. -->
					{#each [...new Set(said.map((r) => dictatedNormalWords.get(r)?.join(' ') ?? ''))] as words (words)}
						<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
							{#each said.filter((r) => (dictatedNormalWords.get(r)?.join(' ') ?? '') === words).flatMap((r) => saidChipNames(r).map((name) => ({ region: r, name }))) as c (`${c.region}\u0001${c.name}`)}
								<span class="shrink-0 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-emerald-200" data-state="dictated">{c.name}</span>
							{/each}
							{#each (said.find((r) => (dictatedNormalWords.get(r)?.join(' ') ?? '') === words) ? dictatedNormalWords.get(said.find((r) => (dictatedNormalWords.get(r)?.join(' ') ?? '') === words) ?? '') ?? [] : []) as w (w)}
								{@const src = sourceOf(w)}
								{#if src && editing && editing.unitId === src.unitId && editing.part === src.part}
									<textarea
										bind:this={field}
										bind:value={editValue}
										use:focusOnMount
										use:autosize={editValue}
										rows="1"
										class="block min-w-0 flex-1 resize-none overflow-hidden rounded border-0 bg-white/[0.05] px-0.5 py-0 text-xs leading-6 text-gray-100 outline outline-1 outline-emerald-500/30 focus:ring-0"
										aria-label="Edit line"
										onblur={commit}
										onkeydown={(e) => {
											if (e.key === 'Enter' || e.key === 'Escape') {
												e.preventDefault();
												commit();
											}
										}}
									></textarea>
									{@render micControls('Enter save · Esc cancel')}
								{:else}
									<!-- The radiologist's own normal sentence: click to edit it in the dictation, as any line. -->
									<button type="button" class="min-w-0 cursor-text truncate rounded text-left text-gray-400 hover:bg-white/[0.04] hover:text-gray-200"
										title="Click to edit: {w}" disabled={!src}
										onclick={() => {
											if (!src) return;
											commit();
											editing = { unitId: src.unitId, part: src.part };
											editValue = w;
											onEditing(true);
										}}>“{w}”</button>
								{/if}
							{/each}
						</div>
					{/each}
					<!-- The sheet sentences a dictated-normal region still reports (review R2): the radiologist's words cover
					     only what they said ("ACL intact" leaves the PCL sentence). -->
					{#each said.filter((r) => keptAssumed(r).length && !isSplit(r)) as r (r)}
						<p class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs" data-quiet={r}>
							<span class="text-[10px] uppercase tracking-wide text-emerald-400/70">{r} · will be reported</span>
							{@render sentences(keptAssumed(r), `said:${r}`, [r])}
						</p>
					{/each}
				</div>
			{/if}
			{#if chips.length}
				<div class="space-y-1.5">
					<p class="text-[10px] uppercase tracking-wide text-gray-500">{namedNormals ? 'Assumed normal (no sheet yet)' : 'Assumed normal: tap to see what will be reported'}</p>
					<div class="flex flex-wrap gap-1.5">
						{#each chips as c (c.key)}
							{@const none = !namedNormals && c.sentences.length === 0}
							{@const hot = c.sentences.some((s) => isFlagged([c.region], s))}
							<!-- No transition on pills: a fade-out with flip left removed pills in the DOM (hand read 2026-10-11). -->
							<button
								type="button"
								class="rounded-full px-2 py-0.5 text-xs {none ? 'border border-white/10 text-gray-600'
									: 'border border-dashed border-white/20 text-gray-400 hover:border-emerald-400/40'} {openPill === c.key ? 'ring-1 ring-emerald-400/40' : ''}"
								title={hot ? `${FLAG_TITLE}. Will be reported: ${c.sentences.join(' ')}`
									: c.sentences.length ? `Will be reported: ${c.sentences.join(' ')}` : none ? 'Nothing assumed: only what you dictate is reported' : 'Assumed normal (not dictated)'}
								data-state={none ? 'none' : 'assumed'}
								data-region={c.region}
								data-flagged={hot ? 'true' : undefined}
								onclick={() => (openPill = openPill === c.key ? null : c.key)}>{c.label}{#if hot}<span
									class="ml-1 text-amber-300" aria-hidden="true">●</span>{/if}</button>
						{/each}
					</div>
				</div>
			{/if}
			{#if openChip && openChip.sentences.length}
				<p class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs" data-quiet={openChip.key === openChip.region ? openChip.region : openChip.label}>
					<span class="text-[10px] uppercase tracking-wide text-emerald-400/70">{openChip.label} · will be reported</span>
					{@render sentences(openChip.sentences, `tray:${openChip.key}`, [openChip.region])}
				</p>
			{/if}
		</section>
	{/if}

	<!-- Conclusion (2026-10-12): greyed until the first findings land; then the AI draft, or a field to type or dictate
	     with a button to draft it. A conclusion the radiologist owns is never overwritten: a quiet note when the
	     findings changed under it. -->
	<section aria-label={CONCLUSION} class="border-t border-white/5 pt-2">
		<h3 class="text-xs font-semibold uppercase tracking-wide {conclusion.kind === 'waiting' && !conclusionRows.length ? 'text-gray-600' : 'text-gray-400'}">{CONCLUSION}</h3>
		{#if conclusionRows.length}
			<ul>{#each conclusionRows as r (r.unitId + ':' + r.text)}{@render line(r, false)}{/each}</ul>
		{:else if conclusion.kind === 'waiting'}
			<div class="mt-0.5 min-h-[3rem] rounded border border-dashed border-white/5 px-2 py-2 text-xs italic text-gray-600" data-testid="conclusion-waiting">
				The conclusion appears once the findings are in.
			</div>
		{:else if conclusion.kind === 'draft' || conclusion.kind === 'none'}
			{#if conclusion.kind === 'draft' && conclusion.text.trim()}
				<p class="text-[10px] uppercase tracking-wide {conclusion.typed ? 'text-gray-500' : 'text-amber-300/80'}">{conclusion.typed ? 'Typed' : `AI draft${conclusion.edited ? ' · edited' : ''}`}</p>
			{:else if conclusion.kind === 'none' && conclusion.failed}
				<p class="text-[10px] text-amber-300/80">The draft could not be made: type or dictate one, or draft it again.</p>
			{/if}
			<div class="relative mt-0.5">
				<textarea
					bind:this={draftField}
					use:autosize={conclusion.kind === 'draft' ? conclusion.text : ''}
					class="block min-h-[4.5rem] w-full resize-none overflow-hidden rounded border border-white/5 bg-white/[0.04] px-1 pr-8 text-sm leading-6 text-gray-100 focus:border-white/20 focus:outline-none focus:ring-0"
					rows="3"
					aria-label="Conclusion draft"
					value={conclusion.kind === 'draft' ? conclusion.text : ''}
					placeholder="Type or dictate a conclusion"
					oninput={(e) => onDraftEdit((e.target as HTMLTextAreaElement).value)}
					onfocus={() => {
						draftFocused = true;
						onEditing(true);
					}}
					onblur={() => {
						draftFocused = false;
						onEditing(editing !== null || newFocused);
					}}
				></textarea>
				{#if conclusion.kind === 'none' || !conclusion.text.trim()}
					<button type="button" class="absolute right-1.5 top-1.5 rounded p-1 text-gray-400 hover:bg-white/5 hover:text-amber-200"
						title="Draft with AI" aria-label="Draft with AI" onmousedown={(e) => e.preventDefault()} onclick={onDraftRefresh}>
						<svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>
					</button>
				{/if}
			</div>
			{@render micControls('type or dictate')}
		{:else}
			<p class="px-1 text-sm italic text-gray-500">Drafting a conclusion…</p>
		{/if}
		{#if conclusionNote && (conclusionRows.length || conclusion.kind === 'draft')}
			<div class="mt-1 rounded border-l-2 border-amber-400/50 bg-amber-500/[0.04] px-2 py-1 text-xs text-amber-200/90" data-testid="conclusion-note">
				{#if conclusionNote.suggestion}
					<p class="text-[10px] uppercase tracking-wide text-amber-300/70">Suggested conclusion</p>
					<p class="text-gray-200">{conclusionNote.suggestion}</p>
					<span class="mt-1 flex gap-3">
						<button type="button" class="text-amber-200 hover:text-amber-100" onclick={onNoteAccept}>Use this</button>
						<button type="button" class="text-gray-400 hover:text-gray-200" onclick={onNoteDismiss}>Keep mine</button>
					</span>
				{:else}
					<span class="flex items-start gap-2">
						<button type="button" class="text-left hover:text-amber-100" onclick={onNoteSuggest} disabled={conclusionNote.loading}>
							Findings changed: this conclusion may not cover {conclusionNote.added.length ? conclusionNote.added.join(' ') : 'them'}{conclusionNote.loading ? ' · suggesting…' : ' · suggest an update'}
						</button>
						<button type="button" class="ml-auto text-gray-500 hover:text-gray-300" aria-label="Dismiss" onclick={onNoteDismiss}>×</button>
					</span>
				{/if}
			</div>
		{/if}
	</section>

	<!-- Gate bar: the open questions and what will be assumed; Confirm takes ownership of both. With anything that
	     blocks Confirm still open, Confirm (or the "to check" chip) starts the walkthrough instead. -->
	{#if walking}
		<section aria-label="Walkthrough" data-testid="walkthrough" tabindex="-1" class="outline-none flex flex-wrap items-center justify-between gap-2 rounded-lg border border-orange-400/40 bg-orange-400/[0.07] px-2.5 py-2">
			<p class="flex flex-col text-xs">
				{#if stops.length}
					<span class="font-medium text-orange-100">Checking {walkTotal - stops.length + 1} of {walkTotal} · {current?.startsWith('row:') ? 'Referral question' : currentGuide ? `Guideline unresolved · ${currentGuide.name}` : currentValue ? (currentValue.state === 'check' ? 'Required value · needs a look' : 'Required value') : currentCheck ? checkLabel(currentCheck.kind) : ''}</span>
					<span class="text-gray-400">Each answer moves to the next item that blocks Confirm. Advisory underlines stay in the text.</span>
				{:else}
					<span class="font-medium text-emerald-200">All checked</span>
					<span class="text-gray-400">Nothing left that blocks Confirm.</span>
				{/if}
			</p>
			<span class="flex gap-1.5">
				<button type="button" class="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200" onclick={() => (walking = false)}>Exit</button>
				<!-- One explicit step for the open required values (a sequence not acquired); "stated?" ones still need a look -->
				{#if openValues}<button type="button" class="rounded-lg border border-amber-400/40 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-500/10" onclick={onValuesRestNa}>Mark {openValues} not provided</button>{/if}
				{#if stops.length > 1}<button type="button" class="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-gray-200 hover:bg-white/[0.06]" onclick={nextStop}>Next ›</button>{/if}
				{#if !stops.length}
					<button type="button" class="rounded-lg bg-purple-700 px-4 py-1.5 text-xs font-medium text-white hover:bg-purple-600 disabled:cursor-not-allowed disabled:opacity-40"
						disabled={!hasConclusion || syncing || checking || editing !== null || valueDraft || newLine.trim().length > 0} onclick={finishWalk}>{onConfirmGenerate ? 'Confirm & Generate' : 'Confirm'}</button>
				{/if}
			</span>
		</section>
	{:else}
	<section aria-label="Confirm" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2">
		<p class="flex flex-wrap gap-2 text-xs">
			<span class="rounded px-1.5 py-0.5 {openRows ? 'bg-amber-500/15 text-amber-200' : 'bg-white/5 text-gray-500'}">{openRows} referral {openRows === 1 ? 'question' : 'questions'} open</span>
			{#if openValueCount}<span class="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-200" data-gate="values">{openValueCount} required {openValueCount === 1 ? 'value' : 'values'} to resolve</span>{/if}
			{#if liveChecks.length}<button type="button" class="rounded border border-orange-400/40 bg-orange-400/15 px-1.5 py-px text-orange-100 hover:bg-orange-400/25" data-gate="checks"
				onclick={startWalk} disabled={!stops.length || checking} title={stops.length ? 'Go through what blocks Confirm' : 'Advisory only: hover the underlines'}
				>{liveChecks.length} to check{blockingChecks ? ` · ${blockingChecks} blocking` : ''}</button>{/if}
			{#if reviewing}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">checking the findings…</span>
			{:else if reviewFailed}<span class="rounded bg-rose-500/15 px-1.5 py-0.5 text-rose-200" data-review="failed">checks unavailable: review the scan as usual</span>
			{:else if reviewWaiting}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-500">checks appear when you stop dictating</span>
			{:else if unanswered}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">{unanswered} {unanswered === 1 ? 'check' : 'checks'} unanswered (not stated)</span>{/if}
			<span class="rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300/90"
				>{gateConfirmed ? 'assumptions confirmed' : namedNormals ? `${assumedCount} regions assumed normal (no sheet yet)` : `${assumedCount} assumed normal`}</span>
			{#if !hasConclusion}<span class="rounded bg-white/5 px-1.5 py-0.5 text-gray-400">no conclusion yet</span>{/if}
			{#if guidelinesUnresolved.length}<button type="button" class="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-200 hover:bg-amber-500/25" data-gate="guidelines"
					onclick={() => onOpenGuideline(guidelinesUnresolved[0].key)}>{guidelinesUnresolved.length} guideline{guidelinesUnresolved.length === 1 ? '' : 's'} unresolved</button>{/if}
			{#if confirmNote}<span class="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-200" role="status" data-gate="note">{confirmNote}</span>{/if}
		</p>
		<button
			type="button"
			class="rounded-lg px-4 py-1.5 text-xs font-medium transition-colors {gateConfirmed
				? 'bg-emerald-500/20 text-emerald-200'
				: 'bg-purple-700 text-white hover:bg-purple-600 disabled:cursor-not-allowed disabled:opacity-40'}"
			disabled={gateConfirmed || !hasConclusion || syncing || checking || newLine.trim().length > 0 || editing !== null || valueDraft}
			onclick={() => (stops.length ? startWalk() : onConfirm())}
			>{gateConfirmed ? 'Confirmed ✓' : checking ? 'Checking…' : syncing ? 'Updating…' : stops.length ? `Confirm · ${stops.length} to resolve` : 'Confirm'}</button>
	</section>
	{/if}
</div>
