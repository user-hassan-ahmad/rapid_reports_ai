import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import { getReview, postEvent, probe, reprepare, rerun } from './api';

function respond(body: unknown, status = 200) {
	return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

function call(fetchMock: ReturnType<typeof vi.fn>) {
	const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
	return { url, init, headers: init.headers as Record<string, string> };
}

beforeEach(() => token.set('tok-1' as never));
afterEach(() => {
	vi.unstubAllGlobals();
	token.set(null);
});

describe('getReview', () => {
	it('GETs the review with normals and the bearer header, and returns data on success', async () => {
		const body = { success: true, mode: 'live', rail: true, run: null, lanes: {}, items: [] };
		const f = respond(body);
		vi.stubGlobal('fetch', f);
		const data = await getReview('r1');
		const { url, init, headers } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/review?include=normals`);
		expect(init.method ?? 'GET').toBe('GET');
		expect(headers.Authorization).toBe('Bearer tok-1');
		expect(data).toEqual(body);
	});

	it('throws on success:false', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'Report not found' }));
		await expect(getReview('r1')).rejects.toThrow('Report not found');
	});
});

describe('postEvent', () => {
	it('POSTs {command, text_hash, detail} and returns the item', async () => {
		const item = { id: 'i1', status: 'applied' };
		const f = respond({ success: true, item });
		vi.stubGlobal('fetch', f);
		const out = await postEvent('r1', 'i1', 'apply', 'abc', { via: 'rail' });
		const { url, init, headers } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/review/items/i1/events`);
		expect(init.method).toBe('POST');
		expect(headers.Authorization).toBe('Bearer tok-1');
		expect(headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(init.body as string)).toEqual({ command: 'apply', text_hash: 'abc', detail: { via: 'rail' } });
		expect(out).toEqual(item);
	});

	it('defaults text_hash to null and detail to {}', async () => {
		const f = respond({ success: true, item: { id: 'i1' } });
		vi.stubGlobal('fetch', f);
		await postEvent('r1', 'i1', 'dismiss');
		expect(JSON.parse(call(f).init.body as string)).toEqual({ command: 'dismiss', text_hash: null, detail: {} });
	});

	it('surfaces a 422 as an error', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'command not allowed: stale' }, 422));
		await expect(postEvent('r1', 'i1', 'apply')).rejects.toThrow('command not allowed: stale');
	});
});

describe('probe, reprepare, rerun', () => {
	it('probe POSTs text, text_hash and changed_ranges', async () => {
		const f = respond({ success: true, text_hash: 'h', addressed: [], reprepare: [], new_items: [], error: null });
		vi.stubGlobal('fetch', f);
		const out = await probe('r1', 'text', 'h', [[0, 4]]);
		const { url, init } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/review/probe`);
		expect(JSON.parse(init.body as string)).toEqual({ text: 'text', text_hash: 'h', changed_ranges: [[0, 4]] });
		expect(out.addressed).toEqual([]);
	});

	it('reprepare POSTs item_ids, text and text_hash', async () => {
		const f = respond({ success: true, text_hash: 'h', items: [] });
		vi.stubGlobal('fetch', f);
		await reprepare('r1', ['i1'], 'text', 'h');
		const { url, init } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/review/reprepare`);
		expect(JSON.parse(init.body as string)).toEqual({ item_ids: ['i1'], text: 'text', text_hash: 'h' });
	});

	it('rerun POSTs the optional text', async () => {
		const f = respond({ success: true, status: 'running' });
		vi.stubGlobal('fetch', f);
		await rerun('r1', 'text');
		const { url, init } = call(f);
		expect(url).toBe(`${API_URL}/api/reports/r1/review/rerun`);
		expect(JSON.parse(init.body as string)).toEqual({ text: 'text' });
	});

	it('rerun surfaces the engine-off response as an error', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'review engine off' }));
		await expect(rerun('r1')).rejects.toThrow('review engine off');
	});
});
