import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { ChangeSet, Text } from '@codemirror/state';
import type { ProbeResponse, ReprepareResponse, ReviewItem } from './types';

vi.mock('./api', () => ({
	getReview: vi.fn(),
	postEvent: vi.fn(),
	rerun: vi.fn(),
	probe: vi.fn(),
	reprepare: vi.fn()
}));
// a synchronous-resolving hash keeps fake timers deterministic (crypto.subtle resolves off the timer queue)
vi.mock('./hash', () => ({ textHash: vi.fn(async (t: string) => `h:${t}`) }));
import * as api from './api';
import { createReviewStore, type ReviewStore } from './store';
import { createProbeLoop, type ProbeLoop } from './probe';

const probeApi = vi.mocked(api.probe);
const reprepareApi = vi.mocked(api.reprepare);
const postEvent = vi.mocked(api.postEvent);

let n = 0;
function item(over: Partial<ReviewItem> = {}): ReviewItem {
	n += 1;
	return {
		id: `i${n}`,
		key: `k${n}`,
		report_id: 'r1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: ['d'],
		kind: 'missing',
		cls: 'action',
		section: 'FINDINGS',
		anchor: null,
		label: `item ${n}`,
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'v1',
		...over
	};
}

function probeRes(text: string, over: Partial<ProbeResponse> = {}): ProbeResponse {
	return {
		success: true,
		text_hash: `h:${text}`,
		addressed: [],
		reprepare: [],
		new_items: [],
		...over
	};
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

/** Let pending promise chains settle without moving fake time. */
const flush = async () => {
	for (let i = 0; i < 10; i++) await Promise.resolve();
};

let doc = '';
let store: ReviewStore;
let loop: ProbeLoop;

/** Replace [from, to) with `insert` in `doc`, and tell the loop. */
function edit(from: number, to: number, insert: string) {
	const cs = ChangeSet.of({ from, to, insert }, doc.length);
	doc = cs.apply(Text.of(doc.split('\n'))).toString();
	loop.onDocChange(cs);
}

beforeEach(() => {
	vi.useFakeTimers();
	n = 0;
	probeApi.mockReset();
	reprepareApi.mockReset();
	postEvent.mockReset();
	doc = 'Liver normal. No ascites.';
	store = createReviewStore('r1');
	loop = createProbeLoop({ reportId: 'r1', store, getDoc: () => doc });
});

afterEach(() => {
	loop.dispose();
	vi.useRealTimers();
});

describe('debounce', () => {
	it('probes once, debounceMs after typing stops, with the changed range', async () => {
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(13, 13, ' X');
		await vi.advanceTimersByTimeAsync(1000);
		edit(15, 15, 'Y');
		await vi.advanceTimersByTimeAsync(1499);
		expect(probeApi).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
		const [rid, text, hash, ranges] = probeApi.mock.calls[0];
		expect(rid).toBe('r1');
		expect(text).toBe(doc);
		expect(hash).toBe(`h:${doc}`);
		expect(ranges).toEqual([[13, 16]]);
	});

	it('maps earlier ranges through later changes', async () => {
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(20, 20, 'ZZ'); // [20,22]
		edit(0, 0, 'AAA'); // [0,3], earlier range shifts to [23,25]
		await vi.advanceTimersByTimeAsync(1500);
		await flush();
		expect(probeApi.mock.calls[0][3]).toEqual([
			[0, 3],
			[23, 25]
		]);
	});

	it('a deletion yields a collapsed range at the seam', async () => {
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(0, 14, '');
		await vi.advanceTimersByTimeAsync(1500);
		await flush();
		expect(probeApi.mock.calls[0][3]).toEqual([[0, 0]]);
	});

	it('trigger() probes at once and cancels the pending debounce', async () => {
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(0, 0, 'A');
		loop.trigger();
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(3000);
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
	});

	it('honours a custom debounceMs', async () => {
		loop.dispose();
		loop = createProbeLoop({ reportId: 'r1', store, getDoc: () => doc, debounceMs: 300 });
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(0, 0, 'A');
		await vi.advanceTimersByTimeAsync(300);
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
	});
});

describe('coalescing', () => {
	it('keeps one probe in flight; later triggers fold into one follow-up with the new ranges', async () => {
		const first = deferred<ProbeResponse>();
		probeApi.mockImplementationOnce(() => first.promise);
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(0, 0, 'A');
		loop.trigger();
		await flush();
		expect(get(loop).inFlight).toBe(true);
		const sent = doc;
		edit(1, 1, 'B');
		loop.trigger();
		loop.trigger();
		await vi.advanceTimersByTimeAsync(2000);
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
		first.resolve(probeRes(sent)); // stale now (doc moved on), dropped
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(2);
		// the dropped probe's range comes back, merged with the new one
		expect(probeApi.mock.calls[1][3]).toEqual([[0, 2]]);
		await flush();
		expect(get(loop).inFlight).toBe(false);
	});

	it('a failed probe restores its ranges for the next one', async () => {
		probeApi.mockRejectedValueOnce(new Error('boom'));
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		edit(0, 0, 'A');
		loop.trigger();
		await flush();
		expect(get(loop).error).toBe('boom');
		edit(5, 5, 'B');
		loop.trigger();
		await flush();
		expect(probeApi.mock.calls[1][3]).toEqual([
			[0, 1],
			[5, 6]
		]);
		expect(get(loop).error).toBeNull();
	});
});

describe('stale answers', () => {
	it('drops a probe answer whose text_hash no longer matches the document', async () => {
		const a = item();
		store.upsert([a]);
		const d = deferred<ProbeResponse>();
		probeApi.mockImplementationOnce(() => d.promise);
		probeApi.mockImplementation(async (_r, text) => probeRes(text));
		loop.trigger();
		await flush();
		const sent = doc;
		doc = doc + ' more'; // changed without notifying yet
		d.resolve(
			probeRes(sent, { addressed: [a.id], new_items: [item({ id: 'new1' })], reprepare: [a.id] })
		);
		await flush();
		expect(get(store).items.map((i) => [i.id, i.status])).toEqual([[a.id, 'open']]);
		expect(reprepareApi).not.toHaveBeenCalled();
	});

	it('drops reprepare results when the document changed meanwhile', async () => {
		const a = item({ label: 'old' });
		store.upsert([a]);
		probeApi.mockImplementation(async (_r, text) => probeRes(text, { reprepare: [a.id] }));
		const d = deferred<ReprepareResponse>();
		reprepareApi.mockImplementationOnce(() => d.promise);
		loop.trigger();
		await flush();
		expect(reprepareApi).toHaveBeenCalledTimes(1);
		const sent = doc;
		doc = doc + '!';
		d.resolve({ success: true, text_hash: `h:${sent}`, items: [{ ...a, label: 'new' }] });
		await flush();
		expect(get(store).items[0].label).toBe('old');
		expect(get(loop).updating.size).toBe(0);
	});
});

describe('addressed and new items', () => {
	it('marks addressed open items locally (the backend already recorded the event) and upserts new_items', async () => {
		const a = item();
		const b = item();
		const done = item({ status: 'applied' });
		store.upsert([a, b, done]);
		const contra = item({ id: 'c1', lane: 'accuracy', kind: 'contradicted' });
		probeApi.mockImplementation(async (_r, text) =>
			probeRes(text, { addressed: [a.id, done.id], new_items: [contra] })
		);
		loop.trigger();
		await flush();
		const items = get(store).items;
		const byId = Object.fromEntries(items.map((i) => [i.id, i]));
		expect(byId[a.id].status).toBe('addressed');
		expect(byId[a.id].history.at(-1)).toMatchObject({
			event: 'addressed',
			actor: 'loop',
			text_hash: `h:${doc}`
		});
		expect(byId[b.id].status).toBe('open');
		expect(byId[done.id].status).toBe('applied');
		expect(byId.c1).toEqual(contra);
		expect(postEvent).not.toHaveBeenCalled(); // engine statuses are never posted as user commands
	});

	it('manual fix → addressed → Cmd-Z → the next probe re-opens the item (backend `reopened`)', async () => {
		const a = item({ anchor: { start: 14, end: 25, text: 'No ascites.', text_hash: null } });
		store.upsert([a]);
		probeApi.mockImplementation(async (_r, text) =>
			probeRes(text, text.includes('No ascites.') ? { reopened: [a.id] } : { addressed: [a.id] })
		);
		edit(14, 25, 'Small ascites.'); // the manual fix
		await vi.advanceTimersByTimeAsync(1500);
		await flush();
		expect(get(store).items[0].status).toBe('addressed');
		edit(14, 28, 'No ascites.'); // Cmd-Z
		await vi.advanceTimersByTimeAsync(1500);
		await flush();
		const got = get(store).items[0];
		expect(got.status).toBe('open');
		expect(got.history.at(-1)).toMatchObject({
			event: 'reopened',
			actor: 'loop',
			text_hash: `h:${doc}`
		});
		expect(postEvent).not.toHaveBeenCalled();
	});

	it('re-opens only items that are addressed locally', async () => {
		const done = item({ status: 'applied' });
		store.upsert([done]);
		probeApi.mockImplementation(async (_r, text) => probeRes(text, { reopened: [done.id] }));
		loop.trigger();
		await flush();
		expect(get(store).items[0].status).toBe('applied');
	});

	it('records a partial probe error without dropping the answer', async () => {
		const a = item();
		store.upsert([a]);
		probeApi.mockImplementation(async (_r, text) =>
			probeRes(text, { addressed: [a.id], error: 'jev timeout' })
		);
		loop.trigger();
		await flush();
		expect(get(store).items[0].status).toBe('addressed');
		expect(get(loop).error).toBe('jev timeout');
	});
});

describe('reprepare flow', () => {
	it('shows updating on the ids, calls reprepare with the probed text, upserts results, then clears updating', async () => {
		const a = item({ label: 'old a' });
		const b = item({ label: 'old b' });
		store.upsert([a, b]);
		probeApi.mockImplementation(async (_r, text) => probeRes(text, { reprepare: [a.id, b.id] }));
		const d = deferred<ReprepareResponse>();
		reprepareApi.mockImplementationOnce(() => d.promise);
		loop.trigger();
		await flush();
		expect([...get(loop).updating].sort()).toEqual([a.id, b.id]);
		expect(reprepareApi).toHaveBeenCalledWith('r1', [a.id, b.id], doc, `h:${doc}`);
		// the probe itself is done: another probe may run while reprepare is pending
		expect(get(loop).inFlight).toBe(false);
		d.resolve({ success: true, text_hash: `h:${doc}`, items: [{ ...a, label: 'new a' }] });
		await flush();
		expect(get(store).items.map((i) => i.label)).toEqual(['new a', 'old b']);
		expect(get(loop).updating.size).toBe(0);
	});

	it('does not re-request ids already updating', async () => {
		const a = item();
		store.upsert([a]);
		probeApi.mockImplementation(async (_r, text) => probeRes(text, { reprepare: [a.id] }));
		const d = deferred<ReprepareResponse>();
		reprepareApi.mockImplementationOnce(() => d.promise);
		loop.trigger();
		await flush();
		loop.trigger();
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(2);
		expect(reprepareApi).toHaveBeenCalledTimes(1);
		d.resolve({ success: true, text_hash: `h:${doc}`, items: [] });
		await flush();
	});

	it('clears updating and records the error when reprepare fails', async () => {
		const a = item();
		store.upsert([a]);
		probeApi.mockImplementation(async (_r, text) => probeRes(text, { reprepare: [a.id] }));
		reprepareApi.mockRejectedValueOnce(new Error('adjudicator down'));
		loop.trigger();
		await flush();
		expect(get(loop).updating.size).toBe(0);
		expect(get(loop).error).toBe('adjudicator down');
		expect(get(store).items[0]).toEqual(a);
	});
});

describe('dispose', () => {
	it('cancels the debounce and ignores answers in flight', async () => {
		const a = item();
		store.upsert([a]);
		const d = deferred<ProbeResponse>();
		probeApi.mockImplementationOnce(() => d.promise);
		loop.trigger();
		await flush();
		edit(0, 0, 'A');
		loop.dispose();
		await vi.advanceTimersByTimeAsync(3000);
		d.resolve(probeRes(doc, { addressed: [a.id] }));
		await flush();
		expect(probeApi).toHaveBeenCalledTimes(1);
		expect(get(store).items[0].status).toBe('open');
	});
});
