// The Copilot session store: turns grouping rounds into /match calls (stable findings only, once per distinct text),
// owns each card's /open state, and fails open. The card components render its state; nothing here touches the
// report, the editor or Generate.
import { writable, type Readable } from 'svelte/store';
import type { StackUnit } from '$lib/hybrid-stack/types';
import * as defaultApi from './api';
import { CopilotError, CopilotOff, MAX_FINDINGS } from './api';
import { closedView, type CardView, type ColumnView } from './cards/view';
import {
	abnormalFindings,
	cardRef,
	groupCards,
	kindOf,
	markSent,
	planMatch,
	quiet,
	stableFindings,
	type CardKind,
	type Finding,
	type Group
} from './state';
import type { Card, MatchBody, MatchResult, OpenBody, OpenResult } from './types';

export interface CopilotContext { scanType: string; history: string }
export type OtherState = 'idle' | 'loading' | 'done' | 'failed';
export interface CopilotState {
	on: boolean;
	groups: Group[];
	views: Record<string, CardView>;
	matching: boolean;
	matchFailed: boolean;
	otherState: OtherState;
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
	retryMatch(): void;
	other(): void;
	/** Keys, counts and ms only (no text): for the stack log. */
	log(): CopilotLog;
	destroy(): void;
}
export interface CopilotApi {
	match(b: MatchBody, signal?: AbortSignal): Promise<MatchResult>;
	matchOther(b: MatchBody, signal?: AbortSignal): Promise<MatchResult>;
	open(b: OpenBody, signal?: AbortSignal): Promise<OpenResult>;
}

/** Exam cards re-open this long after recording stops with changed findings text. */
export const EXAM_REOPEN_MS = 1500;
/** A context change (history keystrokes) settles this long before it resets the cards. */
export const CONTEXT_DEBOUNCE_MS = 600;
/** After a failed /match, rounds make no call for this long (Retry bypasses it): a down endpoint costs one
 *  timeout per window, not one per grouping round. */
export const MATCH_BACKOFF_MS = 15_000;
const MAX_COLUMNS = 3;

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
	let matching = false;
	let matchFailed = false;
	let otherState: OtherState = 'idle';
	let otherAc: AbortController | null = null;
	const openSeq = new Map<string, number>(); // per card ref or column ref; values from one monotonic counter, so a
	let openCounter = 0; // response from before a reset can never match a later request's number
	const openAc = new Map<string, AbortController>();
	const examText = new Map<string, string>(); // exam ref → the findings text its last /open carried
	let examTimer: ReturnType<typeof setTimeout> | null = null;

	const log: CopilotLog = { matched: [], kinds: {}, opened: [], quiet: [], failed: {}, ms: {} };
	const fail = (k: string) => (log.failed[k] = (log.failed[k] ?? 0) + 1);

	const store = writable<CopilotState>(snapshot());
	function all(): Card[] {
		const refs = new Set(cards.map(cardRef));
		return [...cards, ...others.filter((c) => !refs.has(cardRef(c)))];
	}
	function snapshot(): CopilotState {
		return { on, groups: on ? groupCards(all(), findings) : [], views: { ...views }, matching, matchFailed, otherState };
	}
	const publish = () => !dead && store.set(snapshot());
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
		otherAc?.abort();
		for (const ac of openAc.values()) ac.abort();
		matchAc = otherAc = null;
		openAc.clear();
		openSeq.clear();
		queued = false;
		matchSeq++;
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
		patient: {}
	});
	const openBody = (card: Card): OpenBody => ({
		card, // echoed whole: needs_modality and siblings intact (the server trusts them)
		finding: card.finding_id === 'exam' ? text : card.finding,
		findings: text,
		clinical_history: ctx.history,
		answered: {},
		patient: {}
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
	async function request(seqKey: string, body: OpenBody, set: (p: Partial<ColumnView>) => void): Promise<OpenResult | null> {
		openAc.get(seqKey)?.abort();
		const seq = ++openCounter;
		openSeq.set(seqKey, seq);
		const ac = new AbortController();
		openAc.set(seqKey, ac);
		set({ loading: true, error: null });
		publish();
		const t0 = Date.now();
		try {
			const res = await api.open(body, ac.signal);
			if (openSeq.get(seqKey) !== seq || !live()) return null;
			set({ loading: false, error: null, result: res });
			log.ms[body.card.key] = res.ms ?? Date.now() - t0;
			if (!log.opened.includes(body.card.key)) log.opened.push(body.card.key);
			return res;
		} catch (e) {
			if (openSeq.get(seqKey) === seq && failed(e)) {
				set({ loading: false, error: reason(e) });
				fail(body.card.key);
			}
			return null;
		} finally {
			if (openAc.get(seqKey) === ac) openAc.delete(seqKey);
			publish();
		}
	}

	async function fetchCard(card: Card) {
		if (!live() || card.needs_modality) return;
		const ref = cardRef(card);
		const body = openBody(card);
		const res = await request(ref, body, (p) => patch(ref, p));
		if (res && card.finding_id === 'exam') {
			examText.set(ref, body.finding);
			if (quiet(card, res.preview) && !log.quiet.includes(card.key)) log.quiet.push(card.key);
		}
	}

	const columnKeys = (card: Card) => [card.key, ...card.siblings].slice(0, MAX_COLUMNS);
	function fetchColumn(card: Card, key: string) {
		const ref = cardRef(card);
		const colCard = key === card.key ? card : { ...card, key, name: key };
		return request(`${ref}#${key}`, openBody(colCard), (p) => patchCol(ref, key, p));
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
		publish();
		plan();
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
		retryMatch() {
			if (!live() || matchAc) return;
			matchFailed = false;
			backoffUntil = 0;
			if (stable.length || hasText) void runMatch(stable.slice(0, MAX_FINDINGS));
		},
		async other() {
			if (!live() || otherState === 'loading') return;
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
		log: () => structuredClone(log),
		destroy() {
			abortAll();
			dead = true;
		}
	};
}
