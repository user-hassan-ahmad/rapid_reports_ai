import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { ReviewItem, ReviewResponse, ReviewRun } from './types';

vi.mock('./api', () => ({ getReview: vi.fn(), postEvent: vi.fn() }));
import * as api from './api';
import { createReviewStore, UNANCHORED } from './store';

const getReview = vi.mocked(api.getReview);
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

function run(lanes: Record<string, string>, over: Partial<ReviewRun> = {}): ReviewRun {
	return {
		id: 'run1',
		mode: 'live',
		engine_version: 'v1',
		pathway: 'quick',
		lanes,
		timings_ms: {},
		cost: {},
		errors: {},
		created_at: null,
		...over
	};
}

function response(items: ReviewItem[], lanes: Record<string, string>, over: Partial<ReviewRun> = {}): ReviewResponse {
	return { success: true, mode: 'live', rail: true, run: run(lanes, over), lanes, items };
}

const DONE = { coverage: 'done', accuracy: 'done', additions: 'done' };

beforeEach(() => {
	n = 0;
	getReview.mockReset();
	postEvent.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('load', () => {
	it('fills mode, rail, run, lanes and items, and clears loading', async () => {
		const items = [item()];
		getReview.mockResolvedValue(response(items, DONE));
		const s = createReviewStore('r1');
		const p = s.load();
		expect(get(s).loading).toBe(true);
		await p;
		const st = get(s);
		expect(getReview).toHaveBeenCalledWith('r1');
		expect(st).toMatchObject({ mode: 'live', rail: true, lanes: DONE, loading: false, error: null });
		expect(st.run?.id).toBe('run1');
		expect(st.items).toEqual(items);
	});

	it('records the error and keeps the rail off on failure', async () => {
		getReview.mockRejectedValue(new Error('boom'));
		const s = createReviewStore('r1');
		await s.load();
		expect(get(s)).toMatchObject({ loading: false, error: 'boom', rail: false });
	});

	it('exposes run.live_write and a derived liveWriteApplied flag', async () => {
		getReview.mockResolvedValue(response([], DONE, { live_write: { applied: true, version_id: 'v9' } }));
		const s = createReviewStore('r1');
		expect(get(s.liveWriteApplied)).toBe(false);
		await s.load();
		expect(get(s).liveWrite).toEqual({ applied: true, version_id: 'v9' });
		expect(get(s.liveWriteApplied)).toBe(true);

		getReview.mockResolvedValue(response([], DONE, { live_write: { applied: false, reason: 'report_changed' } }));
		await s.load();
		expect(get(s.liveWriteApplied)).toBe(false);
	});
});

describe('groups', () => {
	it('orders groups by the report section order, with Unanchored last', async () => {
		const items = [
			item({ section: null, label: 'loose' }),
			item({ section: 'IMPRESSION', anchor: { start: 300, end: 310, text: 'x' } }),
			item({ section: 'FINDINGS', anchor: { start: 50, end: 60, text: 'y' } }),
			item({ section: 'COMPARISON', anchor: { start: 10, end: 20, text: 'z' } })
		];
		getReview.mockResolvedValue(response(items, DONE));
		const s = createReviewStore('r1');
		await s.load();
		// no explicit order: sections follow their first anchor in the report
		expect(get(s.groups).map((g) => g.section)).toEqual(['COMPARISON', 'FINDINGS', 'IMPRESSION', UNANCHORED]);
		// an explicit order (artifacts.sections) wins; unknown sections follow it
		s.setSectionOrder(['FINDINGS', 'IMPRESSION']);
		expect(get(s.groups).map((g) => g.section)).toEqual(['FINDINGS', 'IMPRESSION', 'COMPARISON', UNANCHORED]);
	});

	it('orders items within a group by anchor position', async () => {
		const a = item({ anchor: { start: 90, end: 95, text: 'a' } });
		const b = item({ anchor: { start: 5, end: 9, text: 'b' } });
		getReview.mockResolvedValue(response([a, b], DONE));
		const s = createReviewStore('r1');
		await s.load();
		expect(get(s.groups)[0].items.map((i) => i.id)).toEqual([b.id, a.id]);
	});

	it('folds suppress, dismissed and addressed items, and leaves assumed normals out of the rail', async () => {
		const keep = item();
		const items = [
			keep,
			item({ cls: 'suppress' }),
			item({ status: 'dismissed' }),
			item({ status: 'addressed' }),
			item({ kind: 'assumed_normal', cls: 'info' })
		];
		getReview.mockResolvedValue(response(items, DONE));
		const s = createReviewStore('r1');
		await s.load();
		const groups = get(s.groups);
		expect(groups).toHaveLength(1);
		expect(groups[0].items.map((i) => i.id)).toEqual([keep.id]);
		expect(get(s.folded).map((i) => i.id)).toEqual([items[1].id, items[2].id, items[3].id]);
	});

	it('drops empty groups', async () => {
		getReview.mockResolvedValue(response([item({ section: 'IMPRESSION', status: 'dismissed' })], DONE));
		const s = createReviewStore('r1');
		await s.load();
		expect(get(s.groups)).toEqual([]);
	});
});

describe('counts and openActions', () => {
	it('counts rail items per cls and lists open action items', async () => {
		const open = item({ cls: 'action' });
		const items = [
			open,
			item({ cls: 'action', status: 'applied' }),
			item({ cls: 'minor' }),
			item({ cls: 'info' }),
			item({ cls: 'action', status: 'dismissed' }),
			item({ kind: 'assumed_normal', cls: 'info' })
		];
		getReview.mockResolvedValue(response(items, DONE));
		const s = createReviewStore('r1');
		await s.load();
		expect(get(s.counts)).toEqual({ action: 2, minor: 1, info: 1, suppress: 0 });
		expect(get(s.openActions).map((i) => i.id)).toEqual([open.id]);
	});
});

describe('upsert and markStale', () => {
	it('replaces items by id and appends new ones', async () => {
		const a = item();
		getReview.mockResolvedValue(response([a], DONE));
		const s = createReviewStore('r1');
		await s.load();
		const b = item();
		s.upsert([{ ...a, label: 'changed' }, b]);
		expect(get(s).items.map((i) => [i.id, i.label])).toEqual([
			[a.id, 'changed'],
			[b.id, b.label]
		]);
	});

	it('marks items stale', async () => {
		const a = item();
		const b = item();
		getReview.mockResolvedValue(response([a, b], DONE));
		const s = createReviewStore('r1');
		await s.load();
		s.markStale([b.id]);
		expect(get(s).items.map((i) => i.status)).toEqual(['open', 'stale']);
	});
});

describe('setStatus', () => {
	it('updates optimistically, then takes the server item', async () => {
		const a = item();
		getReview.mockResolvedValue(response([a], DONE));
		const s = createReviewStore('r1');
		await s.load();
		let resolve!: (v: ReviewItem) => void;
		postEvent.mockReturnValue(new Promise((r) => (resolve = r)));
		const p = s.setStatus(a.id, 'applied', { command: 'apply', textHash: 'h1', detail: { via: 'rail' } });
		expect(get(s).items[0].status).toBe('applied');
		expect(get(s).items[0].history.at(-1)).toMatchObject({ event: 'apply', actor: 'user', text_hash: 'h1' });
		expect(postEvent).toHaveBeenCalledWith('r1', a.id, 'apply', 'h1', { via: 'rail' });
		const server = { ...a, status: 'applied' as const, history: [{ event: 'apply', at: 'now' }] };
		resolve(server);
		expect(await p).toEqual(server);
		expect(get(s).items[0]).toEqual(server);
	});

	it('rolls back on a server error and records it', async () => {
		const a = item();
		getReview.mockResolvedValue(response([a], DONE));
		const s = createReviewStore('r1');
		await s.load();
		postEvent.mockRejectedValue(new Error('bad transition'));
		const out = await s.setStatus(a.id, 'dismissed', { command: 'dismiss' });
		expect(out).toBeNull();
		expect(get(s).items[0]).toEqual(a);
		expect(get(s).error).toBe('bad transition');
	});

	it('keeps an in-flight optimistic status across a poll reload', async () => {
		const a = item();
		getReview.mockResolvedValue(response([a], DONE));
		const s = createReviewStore('r1');
		await s.load();
		let resolve!: (v: ReviewItem) => void;
		postEvent.mockReturnValue(new Promise((r) => (resolve = r)));
		const p = s.setStatus(a.id, 'applied', { command: 'apply' });
		await s.load(); // server still says open
		expect(get(s).items[0].status).toBe('applied');
		resolve({ ...a, status: 'applied' });
		await p;
	});

	it('returns null for an unknown id without calling the server', async () => {
		getReview.mockResolvedValue(response([], DONE));
		const s = createReviewStore('r1');
		await s.load();
		expect(await s.setStatus('nope', 'applied', { command: 'apply' })).toBeNull();
		expect(postEvent).not.toHaveBeenCalled();
	});
});

describe('pollUntilDone', () => {
	it('polls while a lane is unfinished and stops when every lane is done or failed', async () => {
		vi.useFakeTimers();
		getReview
			.mockResolvedValueOnce(response([], { coverage: 'done', accuracy: '', additions: '' }))
			.mockResolvedValueOnce(response([], { coverage: 'done', accuracy: 'done', additions: '' }))
			.mockResolvedValueOnce(response([item()], { coverage: 'done', accuracy: 'failed', additions: 'done' }));
		const s = createReviewStore('r1');
		await s.load();
		const p = s.pollUntilDone({ intervalMs: 1000, maxMs: 60000 });
		await vi.advanceTimersByTimeAsync(1000);
		await vi.advanceTimersByTimeAsync(1000);
		await expect(p).resolves.toBe('done');
		expect(getReview).toHaveBeenCalledTimes(3);
		expect(get(s).items).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(5000);
		expect(getReview).toHaveBeenCalledTimes(3);
	});

	it('returns at once when the lanes are already finished', async () => {
		getReview.mockResolvedValue(response([], { coverage: 'done', accuracy: 'skipped', additions: 'failed' }));
		const s = createReviewStore('r1');
		await s.load();
		await expect(s.pollUntilDone()).resolves.toBe('done');
		expect(getReview).toHaveBeenCalledTimes(1);
	});

	it('stops at maxMs', async () => {
		vi.useFakeTimers();
		getReview.mockResolvedValue(response([], { coverage: '', accuracy: '', additions: '' }));
		const s = createReviewStore('r1');
		await s.load();
		const p = s.pollUntilDone({ intervalMs: 1000, maxMs: 3500 });
		await vi.advanceTimersByTimeAsync(10000);
		await expect(p).resolves.toBe('timeout');
		expect(getReview).toHaveBeenCalledTimes(4); // initial load + 3 polls
	});

	it('stops when stopPolling is called', async () => {
		vi.useFakeTimers();
		getReview.mockResolvedValue(response([], { coverage: '' }));
		const s = createReviewStore('r1');
		await s.load();
		const p = s.pollUntilDone({ intervalMs: 1000, maxMs: 60000 });
		await vi.advanceTimersByTimeAsync(1000);
		s.stopPolling();
		await expect(p).resolves.toBe('stopped');
		await vi.advanceTimersByTimeAsync(5000);
		expect(getReview).toHaveBeenCalledTimes(2);
	});

	it('does not poll when the engine is off', async () => {
		getReview.mockResolvedValue({ success: true, mode: 'off', rail: false, run: null, lanes: {}, items: [] });
		const s = createReviewStore('r1');
		await s.load();
		await expect(s.pollUntilDone()).resolves.toBe('done');
		expect(getReview).toHaveBeenCalledTimes(1);
	});
});
