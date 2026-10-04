// The per-report review item store (Plan 3 B4, spec §12.1). A plain Svelte `writable` contract so Svelte 4
// components ($store) and Svelte 5 runes code both consume it. The rail and the editor overlays read this one
// store; every change goes through it (commands → setStatus / upsert / markStale).
import { derived, get, writable, type Readable } from 'svelte/store';
import { getReview, postEvent } from './api';
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

export type PollOutcome = 'done' | 'timeout' | 'stopped';

export interface ReviewStore extends Readable<ReviewState> {
	load(): Promise<void>;
	pollUntilDone(opts?: { intervalMs?: number; maxMs?: number }): Promise<PollOutcome>;
	stopPolling(): void;
	upsert(items: ReviewItem[]): void;
	/** Optimistic: applies at once, posts the event, takes the server's item; rolls back (and returns null) on error. */
	setStatus(id: string, status: ItemStatus, event: StatusEvent): Promise<ReviewItem | null>;
	markStale(ids: string[]): void;
	/** The report's section order (artifacts.sections). Without it, sections follow their first anchor. */
	setSectionOrder(order: string[]): void;
	/** Rail rows by section, in report order, "Unanchored" last; folded items left out. */
	groups: Readable<ItemGroup[]>;
	/** "▸ N other checks passed": suppress, dismissed and addressed items. */
	folded: Readable<ReviewItem[]>;
	/** Rail rows (not folded) per cls. */
	counts: Readable<Record<Cls, number>>;
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
	const states = Object.values(s.lanes);
	return states.length > 0 && states.every((v) => FINISHED_LANES.has(v));
}

function message(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

export function createReviewStore(reportId: string): ReviewStore {
	const state = writable<ReviewState>(initial());
	const sectionOrder = writable<string[]>([]);
	// Optimistic items whose event is still in flight: a reload keeps the local copy until the server answers.
	const pending = new Map<string, ReviewItem>();
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

	function pollUntilDone({ intervalMs = 1500, maxMs = 90000 } = {}): Promise<PollOutcome> {
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
				if (lanesFinished(get(state))) return finish('done');
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

	async function setStatus(id: string, status: ItemStatus, event: StatusEvent): Promise<ReviewItem | null> {
		const before = get(state).items.find((i) => i.id === id);
		if (!before) return null;
		const textHash = event.textHash ?? null;
		const entry: HistoryEntry = { event: event.command, actor: 'user', text_hash: textHash, detail: event.detail ?? {} };
		const optimistic: ReviewItem = { ...before, status, history: [...before.history, entry] };
		pending.set(id, optimistic);
		replaceItem(optimistic);
		try {
			const server = await postEvent(reportId, id, event.command, textHash, event.detail ?? {});
			pending.delete(id);
			replaceItem(server);
			return server;
		} catch (e) {
			pending.delete(id);
			replaceItem(before);
			state.update((s) => ({ ...s, error: message(e) }));
			return null;
		}
	}

	function markStale(ids: string[]): void {
		const set = new Set(ids);
		state.update((s) => ({
			...s,
			items: s.items.map((i) => (set.has(i.id) ? { ...i, status: 'stale' as const } : i))
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
		const out: Record<Cls, number> = { action: 0, minor: 0, info: 0, suppress: 0 };
		for (const it of items) if (!isFolded(it)) out[it.cls] += 1;
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
