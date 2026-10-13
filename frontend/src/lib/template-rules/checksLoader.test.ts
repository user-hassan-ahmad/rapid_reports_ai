import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createChecksLoader } from './checksLoader';
import type { SheetChecksResponse } from './types';

const ok = (tag: string): SheetChecksResponse => ({
	success: true, fixed_cards: [], duplicate_cards: [], uncovered_cards: [], unmatched_cards: [], stale_quotes: [], errors: [tag],
	normal_report: []
});

function deferred<T>() {
	let resolve!: (v: T) => void, reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => ((resolve = res), (reject = rej)));
	return { promise, resolve, reject };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('createChecksLoader', () => {
	it('debounces re-runs into one request', async () => {
		const post = vi.fn(async () => ok('a'));
		const seen: (SheetChecksResponse | null)[] = [];
		const loader = createChecksLoader(post, (r) => seen.push(r), 500);
		loader.request('S1', []);
		loader.request('S2', []);
		loader.request('S3', []);
		expect(post).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(500);
		expect(post).toHaveBeenCalledTimes(1);
		expect(post.mock.calls[0]).toEqual([{ skill_sheet: 'S3', decisions: [] }]);
		expect(seen).toHaveLength(1);
	});

	it('skips a request when the sheet and ledger are unchanged since the last good run', async () => {
		const post = vi.fn(async () => ok('a'));
		const loader = createChecksLoader(post, () => {}, 500);
		loader.request('S', [], { now: true });
		await vi.advanceTimersByTimeAsync(0);
		loader.request('S', []);
		await vi.advanceTimersByTimeAsync(500);
		expect(post).toHaveBeenCalledTimes(1);
		loader.request('S', [{ kind: 'value', key: 'LVEF', choice: { need: 'every' }, by: 'r', at: 't', source: 'creation' }]);
		await vi.advanceTimersByTimeAsync(500);
		expect(post).toHaveBeenCalledTimes(2);   // a decision-only change is a new run
	});

	it('does not ask again for the key the newest run is already asking for', async () => {
		const d = deferred<SheetChecksResponse>();
		const post = vi.fn().mockReturnValueOnce(d.promise);
		const loader = createChecksLoader(post, () => {}, 500);
		loader.request('S', [], { now: true });
		loader.request('S', [], { now: true });
		d.resolve(ok('a'));
		await vi.advanceTimersByTimeAsync(0);
		expect(post).toHaveBeenCalledTimes(1);
	});

	it('an older response never overwrites a newer one, nor does an older failure', async () => {
		const first = deferred<SheetChecksResponse>();
		const second = deferred<SheetChecksResponse>();
		const post = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
		const seen: (SheetChecksResponse | null)[] = [];
		const loader = createChecksLoader(post, (r) => seen.push(r), 500);
		loader.request('S', [], { now: true });
		loader.request('S', [{ kind: 'value', key: 'X', choice: { need: 'every' }, by: 'r', at: 't', source: 'creation' }], { now: true });
		second.resolve(ok('new'));
		await vi.advanceTimersByTimeAsync(0);
		first.resolve(ok('old'));
		await vi.advanceTimersByTimeAsync(0);
		expect(seen.map((r) => r?.errors[0])).toEqual(['new']);
		const third = deferred<SheetChecksResponse>();
		post.mockReturnValueOnce(third.promise).mockReturnValueOnce(Promise.resolve(ok('newest')));
		loader.request('T', [], { now: true });
		loader.request('U', [], { now: true });
		await vi.advanceTimersByTimeAsync(0);
		third.reject(new Error('x'));
		await vi.advanceTimersByTimeAsync(0);
		expect(seen.map((r) => r?.errors[0])).toEqual(['new', 'newest']);
	});

	it('an older response does not land while a newer request waits out the debounce', async () => {
		const first = deferred<SheetChecksResponse>();
		const post = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(ok('new'));
		const seen: (SheetChecksResponse | null)[] = [];
		const loader = createChecksLoader(post, (r) => seen.push(r), 500);
		loader.request('S1', [], { now: true });
		loader.request('S2', []);
		first.resolve(ok('old'));
		await vi.advanceTimersByTimeAsync(100);
		expect(seen).toEqual([]);
		await vi.advanceTimersByTimeAsync(400);
		expect(seen.map((r) => r?.errors[0])).toEqual(['new']);
	});

	it('a failure shows no checks', async () => {
		const loader = createChecksLoader(vi.fn(async () => { throw new Error('x'); }), (r) => seen.push(r), 500);
		const seen: (SheetChecksResponse | null)[] = [];
		loader.request('S', [], { now: true });
		await vi.advanceTimersByTimeAsync(0);
		expect(seen).toEqual([null]);
	});
});
