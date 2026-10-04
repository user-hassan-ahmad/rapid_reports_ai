// The per-report review item store (Plan 3 B4, spec §12.1). A plain Svelte `writable` contract so Svelte 4
// components ($store) and Svelte 5 runes code both consume it. The rail and the editor overlays read this one
// store; every change goes through it (commands → setStatus / upsert / markStale).
import { derived, get, writable, type Readable } from 'svelte/store';
import { getReview, postEvent, rerun as postRerun } from './api';
import type {
	Cls,
	EngineMode,
	HistoryEntry,
	ItemStatus,
	LaneState,
	LiveWrite,
	ReviewItem,
	ReviewRun,
	UserCommand
} from './types';

export const UNANCHORED = 'Unanchored';
/** Editor-only rows (?include=normals): decorations use them, the rail never shows them. */
export const NORMAL_KIND = 'assumed_normal';
const FINISHED_LANES = new Set(['done', 'failed', 'skipped']);
const FOLDED_STATUSES = new Set<ItemStatus>(['dismissed', 'addressed']);

export interface ReviewState {
	mode: EngineMode;
	rail: boolean;
	run: ReviewRun | null;
	lanes: Record<string, LaneState>;
	items: ReviewItem[];
	/** run.live_write: the background write of pre-applied edits (C5 re-fetches the report when applied). */
	liveWrite: LiveWrite | null;
	loading: boolean;
	error: string | null;
}

export interface ItemGroup {
	section: string;
	items: ReviewItem[];
}

export interface StatusEvent {
	command: UserCommand;
	textHash?: string | null;
	detail?: Record<string, unknown>;
}

export type PollOutcome = 'done' | 'timeout' | 'stopped' | 'failed';

export interface PollOptions {
	intervalMs?: number;
	maxMs?: number;
}

export interface StoreOptions {
	/** First retry delay for a failed event post; doubles each retry. */
	retryDelayMs?: number;
	/** Retries after the first failed post of an event. */
	maxRetries?: number;
}

/** Rail rows (not folded) per cls, plus `open`: open action + minor rows (what still needs the radiologist). */
export type ReviewCounts = Record<Cls, number> & { open: number };

export interface ReviewStore extends Readable<ReviewState> {
	load(): Promise<void>;
	/** Reload until every lane has finished (or the run recorded errors). */
	pollUntilDone(opts?: PollOptions): Promise<PollOutcome>;
	/** Ask for a fresh run on `text`, then poll until a run other than the current one has finished. */
	rerun(text?: string, opts?: PollOptions): Promise<PollOutcome>;
	stopPolling(): void;
	upsert(items: ReviewItem[]): void;
	/** Optimistic: applies at once and never rolls back (the document has already changed). Each item's events post
	 * in order, one at a time; a failed post is retried with backoff (maxRetries), then the item keeps its local
	 * status with `syncError` set and null is returned. The server's item is taken once all its events are answered. */
	setStatus(id: string, status: ItemStatus, event: StatusEvent): Promise<ReviewItem | null>;
	/** Mark items stale (open items only: an applied, pre-applied or answered item keeps its status). */
	markStale(ids: string[]): void;
	/** The report's section order (artifacts.sections). Without it, sections follow their first anchor. */
	setSectionOrder(order: string[]): void;
	/** Rail rows by section, in report order, "Unanchored" last; folded items left out. */
	groups: Readable<ItemGroup[]>;
	/** "▸ N other checks passed": suppress, dismissed and addressed items. */
	folded: Readable<ReviewItem[]>;
	/** Rail rows (not folded) per cls, and open action + minor rows. */
	counts: Readable<ReviewCounts>;
	openActions: Readable<ReviewItem[]>;
	liveWriteApplied: Readable<boolean>;
}

const initial = (): ReviewState => ({
	mode: 'off',
	rail: false,
	run: null,
	lanes: {},
	items: [],
	liveWrite: null,
	loading: false,
	error: null
});

const isRailItem = (i: ReviewItem) => i.kind !== NORMAL_KIND;
const isFolded = (i: ReviewItem) => i.cls === 'suppress' || FOLDED_STATUSES.has(i.status);
const startOf = (i: ReviewItem) => i.anchor?.start ?? Number.POSITIVE_INFINITY;

function lanesFinished(s: ReviewState): boolean {
	if (s.mode === 'off') return true;
	if (!s.run) return false;
	if (Object.keys(s.run.errors ?? {}).length) return true; // the run failed: nothing more is coming
	const states = Object.values(s.lanes);
	return states.length > 0 && states.every((v) => FINISHED_LANES.has(v));
}

function message(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function createReviewStore(reportId: string, opts: StoreOptions = {}): ReviewStore {
	const retryDelayMs = opts.retryDelayMs ?? 500;
	const maxRetries = opts.maxRetries ?? 3;
	const state = writable<ReviewState>(initial());
	const sectionOrder = writable<string[]>([]);
	// Local items the server has not confirmed (events in flight, or a post that failed): a reload keeps them.
	const pending = new Map<string, ReviewItem>();
	// Per item: the tail of its event queue and how many events are still unanswered.
	const queues = new Map<string, Promise<unknown>>();
	const unanswered = new Map<string, number>();
	let stopCurrent: (() => void) | null = null;

	async function load(): Promise<void> {
		state.update((s) => ({ ...s, loading: true }));
		try {
			const data = await getReview(reportId);
			const items = data.items.map((i) => pending.get(i.id) ?? i);
			state.set({
				mode: data.mode,
				rail: data.rail,
				run: data.run,
				lanes: data.lanes ?? {},
				items,
				liveWrite: data.run?.live_write ?? null,
				loading: false,
				error: null
			});
		} catch (e) {
			state.update((s) => ({ ...s, loading: false, error: message(e) }));
		}
	}

	function pollUntilDone(o: PollOptions = {}): Promise<PollOutcome> {
		return poll(o, null);
	}

	/** Poll until the lanes are finished; with `oldRunId`, also until the latest run is a different one. */
	function poll({ intervalMs = 1500, maxMs = 90000 }: PollOptions, oldRunId: string | null): Promise<PollOutcome> {
		stopPolling();
		return new Promise<PollOutcome>((resolve) => {
			const started = Date.now();
			let timer: ReturnType<typeof setTimeout> | null = null;
			let stopped = false;
			stopCurrent = () => {
				stopped = true;
				if (timer) clearTimeout(timer);
				resolve('stopped');
			};
			const finish = (outcome: PollOutcome) => {
				stopCurrent = null;
				resolve(outcome);
			};
			const tick = () => {
				if (stopped) return;
				const s = get(state);
				const fresh = oldRunId == null || s.mode === 'off' || (!!s.run && s.run.id !== oldRunId);
				if (fresh && lanesFinished(s)) return finish('done');
				if (Date.now() - started + intervalMs > maxMs) return finish('timeout');
				timer = setTimeout(async () => {
					timer = null;
					await load();
					tick();
				}, intervalMs);
			};
			tick();
		});
	}

	async function rerun(text?: string, o: PollOptions = {}): Promise<PollOutcome> {
		stopPolling();
		const oldRunId = get(state).run?.id ?? null;
		try {
			await postRerun(reportId, text);
		} catch (e) {
			state.update((s) => ({ ...s, error: message(e) }));
			return 'failed';
		}
		return poll({ ...o }, oldRunId ?? '');
	}

	function stopPolling(): void {
		const stop = stopCurrent;
		stopCurrent = null;
		stop?.();
	}

	function upsert(incoming: ReviewItem[]): void {
		state.update((s) => {
			const items = [...s.items];
			for (const it of incoming) {
				const at = items.findIndex((i) => i.id === it.id);
				if (at >= 0) items[at] = it;
				else items.push(it);
			}
			return { ...s, items };
		});
	}

	function replaceItem(item: ReviewItem): void {
		state.update((s) => ({ ...s, items: s.items.map((i) => (i.id === item.id ? item : i)) }));
	}

	async function postWithRetry(id: string, event: StatusEvent): Promise<ReviewItem> {
		let last: unknown = null;
		for (let attempt = 0; attempt <= maxRetries; attempt++) {
			if (attempt) await sleep(retryDelayMs * 2 ** (attempt - 1));
			try {
				return await postEvent(reportId, id, event.command, event.textHash ?? null, event.detail ?? {});
			} catch (e) {
				last = e;
			}
		}
		throw last;
	}

	function setStatus(id: string, status: ItemStatus, event: StatusEvent): Promise<ReviewItem | null> {
		const before = get(state).items.find((i) => i.id === id);
		if (!before) return Promise.resolve(null);
		const entry: HistoryEntry = {
			event: event.command,
			actor: 'user',
			text_hash: event.textHash ?? null,
			detail: event.detail ?? {}
		};
		const optimistic: ReviewItem = { ...before, status, history: [...before.history, entry] };
		pending.set(id, optimistic);
		replaceItem(optimistic);
		unanswered.set(id, (unanswered.get(id) ?? 0) + 1);

		const answered = (): boolean => {
			const left = (unanswered.get(id) ?? 1) - 1;
			if (left > 0) unanswered.set(id, left);
			else unanswered.delete(id);
			return left <= 0;
		};
		const send = async (): Promise<ReviewItem | null> => {
			try {
				const server = await postWithRetry(id, event);
				if (answered()) {
					pending.delete(id);
					replaceItem(server);
				}
				return server;
			} catch (e) {
				answered();
				// never roll back: the document already holds the change; keep the local status, flag the item
				const cur = get(state).items.find((i) => i.id === id) ?? optimistic;
				const kept = { ...cur, syncError: message(e) };
				pending.set(id, kept);
				replaceItem(kept);
				state.update((s) => ({ ...s, error: message(e) }));
				return null;
			}
		};
		// an idle item posts at once; otherwise after its earlier events are answered
		const prev = queues.get(id);
		const job = prev ? prev.then(send) : send();
		queues.set(id, job);
		void job.finally(() => {
			if (queues.get(id) === job) queues.delete(id);
		});
		return job;
	}

	function markStale(ids: string[]): void {
		const set = new Set(ids);
		state.update((s) => ({
			...s,
			items: s.items.map((i) => (set.has(i.id) && i.status === 'open' ? { ...i, status: 'stale' as const } : i))
		}));
	}

	const railItems = derived(state, (s) => s.items.filter(isRailItem));

	const groups = derived([railItems, sectionOrder], ([items, order]) => {
		const bySection = new Map<string, ReviewItem[]>();
		for (const it of items) {
			if (isFolded(it)) continue;
			const key = it.section || UNANCHORED;
			const list = bySection.get(key) ?? [];
			list.push(it);
			bySection.set(key, list);
		}
		const rank = (section: string): [number, number] => {
			if (section === UNANCHORED) return [2, 0];
			const at = order.indexOf(section);
			if (at >= 0) return [0, at];
			return [1, Math.min(...bySection.get(section)!.map(startOf))];
		};
		return [...bySection.entries()]
			.map(([section, list]) => ({
				section,
				items: [...list].sort((a, b) => startOf(a) - startOf(b))
			}))
			.sort((a, b) => {
				const [ra, pa] = rank(a.section);
				const [rb, pb] = rank(b.section);
				return ra - rb || pa - pb;
			});
	});

	const folded = derived(railItems, (items) => items.filter(isFolded));

	const counts = derived(railItems, (items) => {
		const out: ReviewCounts = { action: 0, minor: 0, info: 0, suppress: 0, open: 0 };
		for (const it of items) {
			if (isFolded(it)) continue;
			out[it.cls] += 1;
			if (it.status === 'open' && (it.cls === 'action' || it.cls === 'minor')) out.open += 1;
		}
		return out;
	});

	const openActions = derived(railItems, (items) =>
		items.filter((i) => i.cls === 'action' && i.status === 'open')
	);

	const liveWriteApplied = derived(state, (s) => s.liveWrite?.applied === true);

	return {
		subscribe: state.subscribe,
		load,
		pollUntilDone,
		rerun,
		stopPolling,
		upsert,
		setStatus,
		markStale,
		setSectionOrder: (order) => sectionOrder.set([...order]),
		groups,
		folded,
		counts,
		openActions,
		liveWriteApplied
	};
}
