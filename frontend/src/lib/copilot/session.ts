// The Copilot session store: turns grouping rounds into /match calls (stable findings only, once per distinct text),
// owns each card's /open state, and fails open. The card components render its state; nothing here touches the
// report, the editor or Generate.
import { writable, type Readable } from 'svelte/store';
import type { StackUnit } from '$lib/hybrid-stack/types';
import * as defaultApi from './api';
import { CopilotError, CopilotOff, MAX_CONCLUSION_CARDS, MAX_FINDINGS } from './api';
import { closedView, type CardView, type ColumnView } from './cards/view';
import { significant, targets, verdictKey } from './gate';
import {
	abnormalFindings,
	cardRef,
	groupCards,
	kindOf,
	markSent,
	planMatch,
	NOT_STATED,
	quiet,
	stableFindings,
	valuesShown,
	type CardKind,
	type Finding,
	type Group
} from './state';
import type {
	CalculateBody,
	CalculateResult,
	Card,
	ConclusionCategory,
	ConclusionCheckBody,
	ConclusionCheckResult,
	MatchBody,
	MatchResult,
	OpenBody,
	OpenResult
} from './types';

export interface CopilotContext { scanType: string; history: string }
export type OtherState = 'idle' | 'loading' | 'done' | 'failed';
export interface CopilotState {
	on: boolean;
	groups: Group[];
	views: Record<string, CardView>;
	matching: boolean;
	matchFailed: boolean;
	otherState: OtherState;
	/** "Seen, leave as is" (§7.12 item 5): gate key → the verdictKey it was tapped on (a changed verdict re-opens). */
	seen: Record<string, string>;
	/** The conclusion check per gate key: what the conclusion recommends for that card's finding; null: not checked. */
	concl: Record<string, ConclusionCategory | null>;
}
/** The stack log's `copilot` record: pack keys, card kinds, counts and ms; never finding or dictation text. */
export type CopilotLog = {
	matched: string[];
	kinds: Record<string, CardKind>;
	opened: string[];
	quiet: string[];
	failed: Record<string, number>;
	ms: Record<string, number>;
};
export interface CopilotSession {
	state: Readable<CopilotState>;
	/** After each successful /group: units as placed, whether dictation runs, and the findings text Generate would
	 *  send (findingsText(units, groups)), sent as /match `dictation` AND /open `findings` (contract R4). */
	round(units: StackUnit[], recording: boolean, findingsText: string): void;
	/** A change resets the sent cache and the cards: at once while nothing was sent, else after CONTEXT_DEBOUNCE_MS
	 *  of no further change (history keystrokes must not abort and reset on every key). */
	setContext(ctx: CopilotContext): void;
	open(ref: string): void;
	close(ref: string): void;
	/** A card ref, or `<cardRef>#<pack key>` for one sibling column (split on the LAST '#'). */
	retry(ref: string): void;
	/** Slice B2: answer or change one value on a card. Re-previews the card (the engine only); a value carrying a
	 *  shared patient fact also re-previews every other card with that fact. Clears the card's Calculate result. */
	edit(ref: string, input: string, value: string): void;
	/** Slice B2: Calculate over exactly the values the card shows (valuesShown). Never Applies. */
	calculate(ref: string): void;
	retryMatch(): void;
	other(): void;
	/** "Seen, leave as is" on a card or sibling column (gate key): held until its verdict changes. */
	seen(ref: string): void;
	/** The conclusion as the confirm bar reads it: checked against the significant cards after
	 *  CONCLUSION_DEBOUNCE_MS of no change (and again when a card turns significant). A failure stores null. */
	checkConclusion(conclusion: string): void;
	/** Keys, counts and ms only (no text): for the stack log. */
	log(): CopilotLog;
	destroy(): void;
}
export interface CopilotApi {
	match(b: MatchBody, signal?: AbortSignal): Promise<MatchResult>;
	matchOther(b: MatchBody, signal?: AbortSignal): Promise<MatchResult>;
	open(b: OpenBody, signal?: AbortSignal): Promise<OpenResult>;
	preview(b: OpenBody, signal?: AbortSignal): Promise<OpenResult>;
	calculate(b: CalculateBody, signal?: AbortSignal): Promise<CalculateResult>;
	conclusionCheck(b: ConclusionCheckBody, signal?: AbortSignal): Promise<ConclusionCheckResult>;
}

/** Exam cards re-open this long after recording stops with changed findings text. */
export const EXAM_REOPEN_MS = 1500;
/** A context change (history keystrokes) settles this long before it resets the cards. */
export const CONTEXT_DEBOUNCE_MS = 600;
/** After a failed /match, rounds make no call for this long (Retry bypasses it): a down endpoint costs one
 *  timeout per window, not one per grouping round. */
export const MATCH_BACKOFF_MS = 15_000;
/** Background previews after /match (checkpoint 4: the verdict upfront), at most this many in flight. The server
 *  prewarmed every card's settlement, so each is cheap; a click still opens at once (it jumps the queue). */
export const MAX_PREFETCH = 4;
const MAX_COLUMNS = 3;
/** The conclusion check waits this long after the last change to the conclusion. */
export const CONCLUSION_DEBOUNCE_MS = 800;

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';
const reason = (e: unknown) => (e instanceof CopilotError ? e.reason : 'failed');

export function createCopilotSession(api: CopilotApi = defaultApi): CopilotSession {
	let on = true;
	let dead = false;
	let ctx: CopilotContext = { scanType: '', history: '' };
	const ctxKey = () => `${ctx.scanType}\n${ctx.history}`;

	// matching
	let prev = new Map<string, string>(); // last round's finding id → text
	let findings: Finding[] = []; // current abnormal findings (groups follow these: a deleted or edited finding drops its cards)
	let stable: Finding[] = [];
	let hasText = false;
	let text = ''; // findingsText of the latest round
	let sent = new Set<string>();
	let sentCtx: string | null = null;
	let matchSeq = 0;
	let matchAc: AbortController | null = null;
	let queued = false; // a round planned a call while one was in flight: re-plan when it lands
	let backoffUntil = 0;
	let ctxTimer: ReturnType<typeof setTimeout> | null = null;

	// cards
	let cards: Card[] = [];
	let others: Card[] = [];
	let views: Record<string, CardView> = {};
	const patient: Record<string, string> = {}; // case-level shared patient answers by fact (§7.4 "once per case")
	// What a revert goes back to: per card/column, the answers its last successful preview carried; per fact, the
	// patient answer a successful preview confirmed (a second edit during a flight never becomes the fallback).
	const previewed = new Map<string, Record<string, string>>();
	const patientConfirmed: Record<string, string> = {};
	let matching = false;
	let matchFailed = false;
	let otherState: OtherState = 'idle';
	let otherAc: AbortController | null = null;
	const openSeq = new Map<string, number>(); // per card ref or column ref; values from one monotonic counter, so a
	let openCounter = 0; // response from before a reset can never match a later request's number
	const openAc = new Map<string, AbortController>();
	const examText = new Map<string, string>(); // exam ref → the findings text its last /open carried
	let examTimer: ReturnType<typeof setTimeout> | null = null;

	// confirm gate (§7.12 item 5)
	let seen: Record<string, string> = {};
	let concl: Record<string, ConclusionCategory | null> = {};
	let conclusion = ''; // the latest conclusion text
	let conclFor: string | null = null; // the conclusion `concl` answers
	let conclFinding: Record<string, string> = {}; // gate key → the finding text its answer was computed for
	let conclTimer: ReturnType<typeof setTimeout> | null = null;
	let conclAc: AbortController | null = null;
	let conclSeq = 0;
	let conclAsked = false; // checkConclusion was called: the host reads a conclusion

	const log: CopilotLog = { matched: [], kinds: {}, opened: [], quiet: [], failed: {}, ms: {} };
	const fail = (k: string) => (log.failed[k] = (log.failed[k] ?? 0) + 1);

	const store = writable<CopilotState>(snapshot());
	function all(): Card[] {
		const refs = new Set(cards.map(cardRef));
		return [...cards, ...others.filter((c) => !refs.has(cardRef(c)))];
	}
	function snapshot(): CopilotState {
		const base: CopilotState = { on, groups: on ? groupCards(all(), findings) : [], views: { ...views }, matching, matchFailed, otherState, seen: { ...seen }, concl: {} };
		// only answers for the CURRENT conclusion and the card's current finding text ever clear a card (review I-1, M-1)
		if (conclFor === conclusion)
			for (const t of targets(base)) if (t.key in concl && conclFinding[t.key] === findingOf(t.card)) base.concl[t.key] = concl[t.key];
		return base;
	}
	const publish = () => {
		if (dead) return;
		const snap = snapshot();
		store.set(snap);
		// a card that turned significant under an already checked conclusion is checked too (never a retry of a null),
		// and after a new case context the current conclusion is checked again
		if (conclAsked && !conclTimer && !conclAc && (conclFor !== conclusion ? significantNow(snap) : pendingChecks(snap)).length) scheduleCheck();
	};
	const live = () => on && !dead;
	const patch = (ref: string, p: Partial<CardView>) => (views[ref] = { ...(views[ref] ?? closedView), ...p });
	const patchCol = (ref: string, key: string, p: Partial<ColumnView>) => {
		const v = views[ref] ?? closedView;
		const cols = { ...(v.columns ?? {}) };
		cols[key] = { ...(cols[key] ?? { loading: false, error: null, result: null }), ...p };
		views[ref] = { ...v, columns: cols };
	};
	const find = (ref: string) => all().find((c) => cardRef(c) === ref);

	function abortAll() {
		matchAc?.abort();
		conclAc?.abort();
		conclAc = null;
		conclSeq++;
		if (conclTimer) clearTimeout(conclTimer);
		conclTimer = null;
		otherAc?.abort();
		for (const ac of openAc.values()) ac.abort();
		matchAc = otherAc = null;
		openAc.clear();
		openSeq.clear();
		queued = false;
		matchSeq++;
		prefetchQueue = [];
		if (examTimer) clearTimeout(examTimer);
		examTimer = null;
		if (ctxTimer) clearTimeout(ctxTimer);
		ctxTimer = null;
	}
	function turnOff() {
		on = false;
		abortAll();
		matching = false;
		publish();
	}
	/** Shared failure handling: off on CopilotOff, silent on abort; true when the caller should record a failure. */
	function failed(e: unknown): boolean {
		if (e instanceof CopilotOff) {
			turnOff();
			return false;
		}
		return !isAbort(e) && live();
	}

	const matchBody = (fs: Finding[]): MatchBody => ({
		scan_type: ctx.scanType,
		clinical_history: ctx.history,
		findings: fs.map((f) => ({ id: f.id, text: f.text })),
		dictation: text,
		patient: { ...patient }
	});
	const openBody = (card: Card, edits: Record<string, string> = views[cardRef(card)]?.edits ?? {}): OpenBody => ({
		card, // echoed as received: the server trusts needs_modality (CardIn has no siblings or reference: dropped)
		finding: card.finding_id === 'exam' ? text : card.finding,
		findings: text,
		clinical_history: ctx.history,
		answered: { ...edits },
		patient: { ...patient }
	});

	// ── /match ──
	function plan() {
		if (!live() || Date.now() < backoffUntil) return;
		const p = planMatch(sent, ctxKey(), sentCtx, stable, hasText);
		if (!p.call) return;
		if (matchAc) {
			queued = true;
			return;
		}
		void runMatch(p.findings);
	}

	async function runMatch(fs: Finding[]) {
		const seq = ++matchSeq;
		const key = ctxKey();
		const ac = new AbortController();
		matchAc = ac;
		matching = true;
		publish();
		const t0 = Date.now();
		try {
			const res = await api.match(matchBody(fs), ac.signal);
			if (seq !== matchSeq || !live()) return; // stale: superseded by a context change, off or destroy
			if (sentCtx !== key) {
				sent = new Set();
				sentCtx = key;
			}
			markSent(sent, fs);
			cards = res.cards;
			matchFailed = false;
			for (const c of cards) if (views[cardRef(c)]?.fromOther) patch(cardRef(c), { fromOther: false }); // matched now
			log.ms.match = res.ms ?? Date.now() - t0;
			log.matched = [...new Set([...log.matched, ...cards.map((c) => c.key)])];
			for (const c of cards) log.kinds[c.key] = kindOf(c);
			const refs = new Set(all().map(cardRef));
			views = Object.fromEntries(Object.entries(views).filter(([r]) => refs.has(r)));
			for (const c of cards) if (c.finding_id === 'exam' && !c.needs_modality && !examText.has(cardRef(c)) && !views[cardRef(c)]?.loading) void fetchCard(c);
			prefetchPacks();
		} catch (e) {
			if (seq === matchSeq && failed(e)) {
				matchFailed = true;
				backoffUntil = Date.now() + MATCH_BACKOFF_MS;
				fail('match');
			}
		} finally {
			if (matchAc === ac) {
				matchAc = null;
				matching = false;
				publish();
				if (queued) {
					queued = false;
					plan();
				}
			}
		}
	}

	// ── /open ──
	// ── background previews (checkpoint 4): every pack card and sibling column gets its verdict without opening ──
	let prefetchQueue: { ref: string; job: () => Promise<unknown> }[] = [];
	// a background preview that failed is not retried on every /match: only on open, or after the /match backoff
	const prefetchFailedAt = new Map<string, number>();
	const wanted = new Set<string>(); // refs the radiologist opened: a background preview's failure then shows
	let prefetching = 0;
	function pump() {
		while (prefetching < MAX_PREFETCH && prefetchQueue.length && live()) {
			const { job } = prefetchQueue.shift()!;
			prefetching++;
			void job().finally(() => {
				prefetching--;
				pump();
			});
		}
	}
	/** Queue a quiet /open for every pack card (finding or exam) and sibling column with no preview yet; never a
	 *  needs-modality, reference, TNM or "other" card. Cards still expand only on click. */
	function prefetchPacks() {
		// cards a later /match removed drop their queued previews
		const present = new Set(cards.map(cardRef));
		prefetchQueue = prefetchQueue.filter((q) => present.has(q.ref));
		const queued = new Set(prefetchQueue.map((q) => q.ref));
		const due = (seqKey: string) => !queued.has(seqKey) && Date.now() - (prefetchFailedAt.get(seqKey) ?? -Infinity) >= MATCH_BACKOFF_MS;
		for (const c of cards) {
			if (c.needs_modality) continue;
			const kind = kindOf(c);
			if (kind !== 'finding' && kind !== 'exam') continue;
			const ref = cardRef(c);
			const v = views[ref] ?? closedView;
			if (c.siblings.length) {
				for (const key of columnsToFetch(c, v, false))
					if (due(`${ref}#${key}`)) prefetchQueue.push({ ref, job: () => fetchColumn(c, key, true) });
			} else if (kind === 'finding' && !v.result && !v.loading && !v.error && due(ref)) prefetchQueue.push({ ref, job: () => fetchCard(c, true) });
		}
		pump();
	}

	async function request(
		seqKey: string,
		body: OpenBody,
		set: (p: Partial<ColumnView>) => void,
		route: 'open' | 'preview' = 'open',
		background = false
	): Promise<OpenResult | null> {
		// a background preview never replaces one already there or under way (a click got there first)
		if (background && openAc.has(seqKey)) return null;
		openAc.get(seqKey)?.abort();
		const seq = ++openCounter;
		openSeq.set(seqKey, seq);
		const ac = new AbortController();
		openAc.set(seqKey, ac);
		set({ loading: true, error: null });
		publish();
		const t0 = Date.now();
		try {
			const res = await api[route](body, ac.signal);
			if (openSeq.get(seqKey) !== seq || !live()) return null;
			set({ loading: false, error: null, result: res });
			previewed.set(seqKey, { ...body.answered });
			prefetchFailedAt.delete(seqKey);
			log.ms[body.card.key] = res.ms ?? Date.now() - t0;
			if (!log.opened.includes(body.card.key)) log.opened.push(body.card.key);
			return res;
		} catch (e) {
			if (openSeq.get(seqKey) === seq && failed(e)) {
				const silent = background && !wanted.has(seqKey);
				set(silent ? { loading: false, error: null } : { loading: false, error: reason(e) }); // fail open: a background preview that fails just leaves the card to its click
				if (silent) prefetchFailedAt.set(seqKey, Date.now());
				fail(body.card.key);
			}
			return null;
		} finally {
			if (openAc.get(seqKey) === ac) openAc.delete(seqKey);
			publish();
		}
	}

	async function fetchCard(card: Card, background = false) {
		if (!live() || card.needs_modality) return;
		const ref = cardRef(card);
		if (background && views[ref]?.result) return;
		const body = openBody(card);
		const res = await request(ref, body, (p) => patch(ref, p), 'open', background);
		if (res && card.finding_id === 'exam') {
			examText.set(ref, body.finding);
			if (quiet(card, res.preview) && !log.quiet.includes(card.key)) log.quiet.push(card.key);
		}
	}

	// ── Slice B2: edits, shared patient answers, Calculate ──
	// A target is a single card, or one sibling column (`<cardRef>#<pack key>`): each has its own answers, preview
	// and Calculate result; the case's patient answers flow to all of them.
	interface Target {
		seqKey: string;
		card: Card; // the card the request echoes (a column's key swapped in)
		get(): CardView | ColumnView | undefined;
		set(p: Partial<CardView & ColumnView>): void;
	}
	function targetOf(ref: string): Target | null {
		const i = ref.lastIndexOf('#');
		if (i >= 0) {
			const base = ref.slice(0, i);
			const key = ref.slice(i + 1);
			const card = find(base);
			if (card && columnKeys(card).includes(key)) {
				const colCard = key === card.key ? card : { ...card, key, name: key };
				// an exam card's primary column lives in the top-level view until a column entry exists
				const fallback = (): ColumnView | undefined => {
					const v = views[base];
					return key === card.key && v?.result ? { loading: v.loading, error: v.error, result: v.result } : undefined;
				};
				return {
					seqKey: `${base}#${key}`,
					card: colCard,
					get: () => views[base]?.columns?.[key] ?? fallback(),
					set: (p) => {
						if (!views[base]?.columns?.[key]) patchCol(base, key, fallback() ?? {});
						patchCol(base, key, p);
					}
				};
			}
		}
		const card = find(ref);
		return card ? { seqKey: ref, card, get: () => views[ref], set: (p) => patch(ref, p) } : null;
	}
	/** Every card and sibling column that has a preview (patient answers re-preview these). */
	function allTargets(): Target[] {
		const out: Target[] = [];
		for (const c of all()) {
			if (c.needs_modality) continue;
			const keys = c.siblings.length ? columnKeys(c).map((k) => `${cardRef(c)}#${k}`) : [cardRef(c)];
			for (const k of keys) {
				const t = targetOf(k);
				if (t?.get()?.result) out.push(t);
			}
		}
		return out;
	}
	/** Re-preview after an edit or a patient answer: the engine only, over the target's answers (no new settle). The
	 *  last preview stays on screen while it runs. If an edit's re-preview fails (`edit`), the answers go back to the
	 *  last ones previewed, a shared patient fact it set goes back to the last confirmed answer (and the other cards
	 *  that received it are re-previewed), and the card says so, rather than silently keeping an answer the card
	 *  does not reflect. */
	async function repreview(t: Target, edit: { fact: string | null } | null) {
		openAc.get(t.seqKey)?.abort();
		const seq = ++openCounter;
		openSeq.set(t.seqKey, seq);
		const ac = new AbortController();
		openAc.set(t.seqKey, ac);
		t.set({ loading: true, editError: null });
		publish();
		const body = openBody(t.card, t.get()?.edits ?? {});
		const sentFact = edit?.fact ? body.patient[edit.fact] : undefined;
		try {
			const res = await api.preview(body, ac.signal);
			if (openSeq.get(t.seqKey) !== seq || !live()) return;
			t.set({ loading: false, error: null, result: res, editError: null });
			previewed.set(t.seqKey, { ...body.answered });
			if (edit?.fact) {
				if (sentFact === undefined) delete patientConfirmed[edit.fact];
				else patientConfirmed[edit.fact] = sentFact;
			}
		} catch (e) {
			if (openSeq.get(t.seqKey) === seq && failed(e)) {
				t.set({
					loading: false,
					...(edit ? { edits: { ...(previewed.get(t.seqKey) ?? {}) } } : {}),
					editError: edit ? "Couldn't apply that change; it was undone" : "Couldn't update for the patient answer"
				});
				fail(`${t.card.key}:preview`);
				if (edit?.fact) rollbackFact(edit.fact, t.seqKey);
			}
		} finally {
			if (openAc.get(t.seqKey) === ac) openAc.delete(t.seqKey);
			publish();
		}
	}
	/** A shared patient answer whose edit failed goes back to the last confirmed one; every other card and column
	 *  carrying the fact re-previews with it. */
	function rollbackFact(fact: string, from: string) {
		if (patient[fact] === patientConfirmed[fact]) return;
		if (fact in patientConfirmed) patient[fact] = patientConfirmed[fact];
		else delete patient[fact];
		for (const o of allTargets()) {
			if (o.seqKey === from || !draftOf(o).some((d) => d.fact === fact)) continue;
			dropCalc(o);
			void repreview(o, null);
		}
	}
	/** Any edit clears the target's Calculate result, and an answer still in flight is dropped. */
	function dropCalc(t: Target) {
		const key = `${t.seqKey}@calc`;
		openAc.get(key)?.abort();
		openAc.delete(key);
		openSeq.set(key, ++openCounter);
		if (t.get()?.calc) t.set({ calc: undefined });
	}
	const draftOf = (t: Target) => t.get()?.result?.preview?.draft ?? [];

	function editValue(ref: string, input: string, value: string) {
		if (!live()) return;
		const t = targetOf(ref);
		if (!t || t.card.needs_modality) return;
		const row = draftOf(t).find((d) => d.input === input);
		if (!row || row.state === 'not_applicable') return;
		dropCalc(t);
		t.set({ edits: { ...(t.get()?.edits ?? {}), [input]: value } });
		// a shared patient fact (age, sex, history): one answer per case, every card and column that carries it follows
		if (row.fact) {
			if (value === NOT_STATED) delete patient[row.fact];
			else patient[row.fact] = value;
		}
		void repreview(t, { fact: row.fact || null });
		if (row.fact) {
			for (const o of allTargets()) {
				if (o.seqKey === t.seqKey || !draftOf(o).some((d) => d.fact === row.fact)) continue;
				dropCalc(o);
				void repreview(o, null);
			}
		}
		publish();
	}

	// Kept for the future Apply (Calculate is not on the card since the simplified card; Apply stays off).
	async function calculateCard(ref: string) {
		if (!live()) return;
		const t = targetOf(ref);
		const v = t?.get();
		// never on a stale card: a re-preview after an edit must land first (its values are what Calculate sends)
		if (!t || t.card.needs_modality || !v?.result?.preview || v.loading) return;
		const key = `${t.seqKey}@calc`;
		openAc.get(key)?.abort();
		const seq = ++openCounter;
		openSeq.set(key, seq);
		const ac = new AbortController();
		openAc.set(key, ac);
		const body: CalculateBody = { ...openBody(t.card, v.edits ?? {}), values: valuesShown(v.result.preview, v.edits) };
		t.set({ calc: { loading: true, error: null, result: null } });
		publish();
		try {
			const res = await api.calculate(body, ac.signal);
			if (openSeq.get(key) !== seq || !live()) return;
			t.set({ calc: { loading: false, error: res.error, result: res.calculation } });
			log.ms[`${t.card.key}:calc`] = res.ms;
		} catch (e) {
			if (openSeq.get(key) === seq && failed(e)) {
				t.set({ calc: { loading: false, error: reason(e), result: null } });
				fail(`${t.card.key}:calc`);
			}
		} finally {
			if (openAc.get(key) === ac) openAc.delete(key);
			publish();
		}
	}

	const columnKeys = (card: Card) => [card.key, ...card.siblings].slice(0, MAX_COLUMNS);
	function fetchColumn(card: Card, key: string, background = false) {
		const ref = cardRef(card);
		if (background && views[ref]?.columns?.[key]?.result) return Promise.resolve(null);
		const colCard = key === card.key ? card : { ...card, key, name: key };
		return request(`${ref}#${key}`, openBody(colCard, views[ref]?.columns?.[key]?.edits ?? {}), (p) => patchCol(ref, key, p), 'open', background);
	}

	/** The sibling columns still worth a request: not loading and no result. An exam card's primary column is its
	 *  auto-opened top-level view (SiblingColumns falls back to it), so it is skipped while that has or awaits one.
	 *  `failedToo` includes columns that failed (retry); a plain open leaves them to their Retry. */
	function columnsToFetch(card: Card, v: CardView, failedToo: boolean): string[] {
		return columnKeys(card).filter((key) => {
			const col = v.columns?.[key];
			if (!col && key === card.key && (v.result || v.loading)) return false;
			return !col || (!col.loading && !col.result && (failedToo || !col.error));
		});
	}

	function open(ref: string) {
		if (!live()) return;
		const card = find(ref);
		if (!card || card.needs_modality) return;
		patch(ref, { open: true });
		wanted.add(ref);
		for (const key of columnKeys(card)) wanted.add(`${ref}#${key}`);
		const v = views[ref];
		if (card.siblings.length) for (const key of columnsToFetch(card, v, false)) void fetchColumn(card, key);
		else if (!v.loading && !v.result && !v.error) void fetchCard(card);
		publish();
	}

	function retry(ref: string) {
		if (!live()) return;
		const i = ref.lastIndexOf('#');
		const base = i >= 0 ? ref.slice(0, i) : ref;
		const col = find(base);
		if (col && i >= 0 && columnKeys(col).includes(ref.slice(i + 1))) {
			void fetchColumn(col, ref.slice(i + 1));
			return;
		}
		const card = find(ref);
		if (!card || card.needs_modality) return;
		if (card.siblings.length) for (const key of columnsToFetch(card, views[ref] ?? closedView, true)) void fetchColumn(card, key);
		else void fetchCard(card);
	}

	function applyContext(next: CopilotContext) {
		if (!live()) return;
		ctx = { ...next };
		backoffUntil = 0; // a new context is a new chance, even after a failed /match
		// a new case context starts without its answers
		for (const k of Object.keys(patient)) delete patient[k];
		for (const k of Object.keys(patientConfirmed)) delete patientConfirmed[k];
		previewed.clear();
		wanted.clear();
		prefetchFailedAt.clear();
		abortAll();
		sent = new Set();
		sentCtx = null;
		cards = [];
		others = [];
		views = {};
		examText.clear();
		matching = false;
		matchFailed = false;
		otherState = 'idle';
		seen = {};
		concl = {};
		conclFinding = {};
		conclFor = null;
		publish();
		plan();
	}

	// ── confirm gate: the conclusion check (§7.12 item 5) ──
	const significantNow = (snap: CopilotState) => targets(snap).filter((t) => significant(t.preview, t.card));
	/** Significant cards with no answer yet under the current conclusion. */
	const pendingChecks = (snap: CopilotState) =>
		significantNow(snap).filter((t) => !(t.key in concl) || conclFinding[t.key] !== findingOf(t.card));
	/** What the check reads as the card's finding: as /open sends it (an exam card: the current findings text). */
	function findingOf(card: Card): string {
		return card.finding_id === 'exam' ? text : card.finding;
	}
	function scheduleCheck() {
		if (conclTimer) clearTimeout(conclTimer);
		conclTimer = setTimeout(() => {
			conclTimer = null;
			void runCheck();
		}, CONCLUSION_DEBOUNCE_MS);
	}
	async function runCheck() {
		if (!live()) return;
		const text = conclusion;
		const fresh = conclFor !== text; // a new conclusion re-checks every significant card
		const due = fresh ? significantNow(snapshot()) : pendingChecks(snapshot());
		const sentFinding = Object.fromEntries(due.map((t) => [t.key, findingOf(t.card)]));
		const answer = (got: Record<string, ConclusionCategory | null>) => {
			concl = fresh ? got : { ...concl, ...got };
			conclFinding = fresh ? sentFinding : { ...conclFinding, ...sentFinding };
			conclFor = text;
			publish();
		};
		if (!due.length) {
			if (fresh) answer({});
			return;
		}
		const nulls = () => Object.fromEntries(due.map((t) => [t.key, null]));
		if (!text.trim()) return answer(nulls()); // nothing to check: nothing clears
		// one entry per distinct finding (siblings on one finding share it): the key is an opaque id the reply echoes
		// (at most MAX_CONCLUSION_CARDS: a card past the cap is answered null, so its note says the check did not run)
		const ids = new Map<string, string>();
		for (const t of due) if (!ids.has(sentFinding[t.key]) && ids.size < MAX_CONCLUSION_CARDS) ids.set(sentFinding[t.key], `f${ids.size}`);
		const seq = ++conclSeq;
		conclAc?.abort();
		const ac = new AbortController();
		conclAc = ac;
		try {
			const res = await api.conclusionCheck({ conclusion: text, cards: [...ids].map(([finding, key]) => ({ key, finding })) }, ac.signal);
			if (seq !== conclSeq || !live()) return;
			conclAc = null;
			answer(Object.fromEntries(due.map((t) => { const id = ids.get(sentFinding[t.key]); return [t.key, id ? (res.results?.[id] ?? null) : null]; })));
		} catch (e) {
			if (seq !== conclSeq) return;
			conclAc = null;
			if (failed(e)) {
				fail('conclusion');
				answer(nulls());
			}
		}
	}

	// ── public ──
	return {
		state: { subscribe: store.subscribe },
		round(units, recording, findingsText) {
			if (!live()) return;
			const now = abnormalFindings(units);
			const placed = units.filter((u) => !u.heading && u.group !== null).map((u) => u.id);
			const lastUnitId = placed.length ? Math.max(...placed) : -1;
			stable = stableFindings(prev, now, lastUnitId, recording);
			prev = new Map(now.map((f) => [f.id, f.text]));
			findings = now;
			text = findingsText;
			hasText = findingsText.trim() !== '';
			if (examTimer) clearTimeout(examTimer);
			examTimer = null;
			if (!recording) {
				examTimer = setTimeout(() => {
					examTimer = null;
					for (const c of cards) {
						const r = cardRef(c);
						if (c.finding_id === 'exam' && examText.has(r) && examText.get(r) !== text && !views[r]?.loading) void fetchCard(c);
					}
				}, EXAM_REOPEN_MS);
			}
			publish();
			plan();
		},
		setContext(next) {
			if (!live()) return;
			if (ctxTimer) clearTimeout(ctxTimer);
			ctxTimer = null;
			if (next.scanType === ctx.scanType && next.history === ctx.history) return;
			const fresh = sentCtx === null && !matchAc && !cards.length; // nothing to lose: apply now
			if (fresh) applyContext(next);
			else ctxTimer = setTimeout(() => ((ctxTimer = null), applyContext(next)), CONTEXT_DEBOUNCE_MS);
		},
		open,
		close(ref) {
			if (!views[ref]) return;
			patch(ref, { open: false });
			publish();
		},
		retry,
		edit: editValue,
		calculate: (ref) => void calculateCard(ref),
		retryMatch() {
			if (!live() || matchAc) return;
			matchFailed = false;
			backoffUntil = 0;
			if (stable.length || hasText) void runMatch(stable.slice(0, MAX_FINDINGS));
		},
		async other() {
			// nothing dictated yet: nothing to ask about
			if (!live() || otherState === 'loading' || (!stable.length && !hasText)) return;
			otherState = 'loading';
			const ac = new AbortController();
			otherAc = ac;
			publish();
			const t0 = Date.now();
			try {
				const res = await api.matchOther(matchBody(stable), ac.signal);
				if (otherAc !== ac || !live()) return;
				const known = new Set(all().map(cardRef));
				for (const c of res.cards) {
					const r = cardRef(c);
					if (known.has(r)) continue;
					known.add(r);
					others.push(c);
					log.kinds[c.key] = kindOf(c, true);
					patch(r, { fromOther: true });
				}
				otherState = 'done';
				log.ms.other = res.ms ?? Date.now() - t0;
			} catch (e) {
				if (otherAc === ac && failed(e)) {
					otherState = 'failed';
					fail('other');
				}
			} finally {
				if (otherAc === ac) otherAc = null;
				publish();
			}
		},
		seen(ref) {
			if (!live()) return;
			const t = targets(snapshot()).find((x) => x.key === ref);
			if (!t) return;
			seen = { ...seen, [ref]: verdictKey(t.preview) };
			publish();
		},
		checkConclusion(text) {
			if (!live() || (text === conclusion && (conclTimer || conclAc || conclFor === text))) return;
			conclusion = text;
			conclAsked = true;
			scheduleCheck();
			publish(); // the old text's answers stop clearing cards at once (review I-1)
		},
		log: () => structuredClone(log),
		destroy() {
			abortAll();
			dead = true;
		}
	};
}
