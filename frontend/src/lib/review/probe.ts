// The live probe loop (Plan 3 C6, spec §12.4). Triggers: a command or a chat edit (`trigger()`), or about 1.5 s
// after typing stops (`onDocChange`, debounced). Each probe sends the document, its text_hash and the ranges
// changed since the last answered probe; at most one probe is in flight and later triggers coalesce into one
// follow-up. An answer whose text_hash no longer matches the document is dropped (its ranges are kept for the
// next probe). The full engine never re-runs from here: Re-review is the rail's manual `rerun`.
import { get, writable, type Readable } from 'svelte/store';
import type { ChangeSet } from '@codemirror/state';
import { probe, reprepare } from './api';
import { textHash } from './hash';
import type { ReviewStore } from './store';
import type { ItemStatus, ReviewItem } from './types';

export type Range = [number, number];

export interface ProbeLoopState {
	/** A probe request is out. */
	inFlight: boolean;
	/** Item ids being re-prepared: the rail and the editor show "updating…" on them. */
	updating: Set<string>;
	/** The last probe or reprepare error (a probe's partial `error` included); cleared by the next good probe. */
	error: string | null;
}

export interface ProbeLoopOptions {
	reportId: string;
	store: ReviewStore;
	getDoc: () => string;
	debounceMs?: number;
}

export interface ProbeLoop extends Readable<ProbeLoopState> {
	/** Feed every editor transaction's changes (map tracked ranges, record new ones, restart the debounce). */
	onDocChange(changes: ChangeSet): void;
	/** Probe now (after a command or a chat edit); coalesces with one already in flight. */
	trigger(): void;
	dispose(): void;
}

/** Only the engine's open view of an item can be addressed (backend probes `open` items; `stale` is local-only). */
const ADDRESSABLE = new Set<ItemStatus>(['open', 'stale']);

/** Sort and merge overlapping or touching ranges. */
export function mergeRanges(ranges: Range[]): Range[] {
	const sorted = [...ranges].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
	const out: Range[] = [];
	for (const [from, to] of sorted) {
		const last = out[out.length - 1];
		if (last && from <= last[1]) last[1] = Math.max(last[1], to);
		else out.push([from, to]);
	}
	return out;
}

/** Map ranges through a change set, widening over insertions at their edges. */
function mapRanges(ranges: Range[], changes: ChangeSet): Range[] {
	return ranges.map(([from, to]) => {
		const a = changes.mapPos(from, -1);
		return [a, Math.max(a, changes.mapPos(to, 1))];
	});
}

function message(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

export function createProbeLoop(opts: ProbeLoopOptions): ProbeLoop {
	const { reportId, store, getDoc } = opts;
	const debounceMs = opts.debounceMs ?? 1500;
	const state = writable<ProbeLoopState>({ inFlight: false, updating: new Set(), error: null });

	let pending: Range[] = []; // changed since the last answered probe, not yet sent
	let sent: Range[] | null = null; // ranges carried by the probe in flight (mapped while it is out)
	let timer: ReturnType<typeof setTimeout> | null = null;
	let again = false;
	let disposed = false;

	const patch = (p: Partial<ProbeLoopState>) => state.update((s) => ({ ...s, ...p }));

	function clearTimer() {
		if (timer !== null) clearTimeout(timer);
		timer = null;
	}

	function onDocChange(changes: ChangeSet): void {
		if (disposed || changes.empty) return;
		pending = mapRanges(pending, changes);
		if (sent) sent = mapRanges(sent, changes);
		changes.iterChangedRanges((_fa, _ta, fromB, toB) => pending.push([fromB, toB]));
		pending = mergeRanges(pending);
		clearTimer();
		timer = setTimeout(() => {
			timer = null;
			trigger();
		}, debounceMs);
	}

	function trigger(): void {
		if (disposed) return;
		clearTimer();
		if (get(state).inFlight) {
			again = true;
			return;
		}
		void run();
	}

	/** Put the in-flight ranges back for the next probe (failed or stale answer). */
	function restoreSent() {
		if (sent) pending = mergeRanges([...pending, ...sent]);
		sent = null;
	}

	async function run(): Promise<void> {
		again = false;
		sent = pending;
		pending = [];
		patch({ inFlight: true });
		try {
			const text = getDoc();
			const hash = await textHash(text);
			const res = await probe(reportId, text, hash, sent);
			if (disposed) return;
			if (res.text_hash !== (await textHash(getDoc())) || disposed) {
				restoreSent();
				return;
			}
			sent = null;
			apply(res.addressed, res.reopened ?? [], res.new_items, hash);
			patch({ error: res.error ?? null });
			startReprepare(res.reprepare, text, hash);
		} catch (e) {
			if (disposed) return;
			restoreSent();
			patch({ error: message(e) });
		} finally {
			if (!disposed) {
				patch({ inFlight: false });
				if (again) void run();
			}
		}
	}

	function apply(addressed: string[], reopened: string[], newItems: ReviewItem[], hash: string) {
		// the backend already recorded `addressed` / `reopened` (actor loop); mirror them locally, never post them
		const ids = new Set(addressed);
		const back = new Set(reopened);
		const mark = (i: ReviewItem, status: ItemStatus, event: string): ReviewItem => ({
			...i,
			status,
			history: [...i.history, { event, actor: 'loop', text_hash: hash, detail: {} }]
		});
		const items = get(store).items;
		const marked = [
			...items
				.filter((i) => ids.has(i.id) && ADDRESSABLE.has(i.status))
				.map((i) => mark(i, 'addressed', 'addressed')),
			...items
				.filter((i) => back.has(i.id) && i.status === 'addressed')
				.map((i) => mark(i, 'open', 'reopened'))
		];
		// a new item on the same text and edit mode as an open item is a duplicate (e.g. the undo probe re-flagging a
		// re-opened removal card): the existing card stands
		const dup = (n: ReviewItem) =>
			n.edit?.mode === 'remove' &&
			!!n.anchor?.text &&
			items.some(
				(i) =>
					i.status === 'open' && i.id !== n.id && i.anchor?.text === n.anchor?.text && i.edit?.mode === n.edit?.mode
			);
		const upserts = [...marked, ...newItems.filter((n) => !dup(n))];
		if (upserts.length) store.upsert(upserts);
	}

	function startReprepare(ids: string[], text: string, hash: string) {
		const busy = get(state).updating;
		const known = new Set(get(store).items.map((i) => i.id));
		const todo = ids.filter((id) => !busy.has(id) && known.has(id));
		if (!todo.length) return;
		state.update((s) => ({ ...s, updating: new Set([...s.updating, ...todo]) }));
		const done = () =>
			state.update((s) => {
				const updating = new Set(s.updating);
				for (const id of todo) updating.delete(id);
				return { ...s, updating };
			});
		void (async () => {
			try {
				const res = await reprepare(reportId, todo, text, hash);
				if (disposed) return;
				if (res.text_hash === (await textHash(getDoc())) && !disposed) store.upsert(res.items);
			} catch (e) {
				if (!disposed) patch({ error: message(e) });
			} finally {
				if (!disposed) done();
			}
		})();
	}

	function dispose(): void {
		disposed = true;
		clearTimer();
	}

	return { subscribe: state.subscribe, onDocChange, trigger, dispose };
}
