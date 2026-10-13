import { afterEach, describe, expect, it, vi } from 'vitest';
import { postAssumed, postDictationCheck, postGroup } from './api';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('postGroup', () => {
	it('posts text, regions and the previous units with the bearer token', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ units: [], new_ids: [], pills: [], gate: [], problems: [], timings_ms: {}, model: null, error: null })));
		vi.stubGlobal('fetch', fetchMock);
		await postGroup('tok', { scan_type: 'CT', text: 'A.', regions: [], previous: [] });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/canvas/stack/group')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string).text).toBe('A.');
	});
});

describe('timeouts: the dictation check and the assumed check fail open after 25 s', () => {
	const calls = [
		['postDictationCheck', () => postDictationCheck('tok', { findings: 'A.', include_semantic: true })],
		['postAssumed', () => postAssumed('tok', { dictation: 'A.', region_normals: {}, abnormal: [] })]
	] as const;
	for (const [name, call] of calls) {
		it(`${name} sends a 25 s timeout signal and rejects when it fires (the caller's catch fails open)`, async () => {
			const timeout = vi.spyOn(AbortSignal, 'timeout');
			const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
				expect(init.signal).toBeInstanceOf(AbortSignal);
				throw new DOMException('The operation timed out.', 'TimeoutError');
			});
			vi.stubGlobal('fetch', fetchMock);
			await expect(call()).rejects.toThrow();
			expect(timeout).toHaveBeenCalledWith(25000);
			expect(fetchMock).toHaveBeenCalledTimes(1);
		});
	}
	it('postAssumed no longer sends dictated_normal or touched', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ assumed: {} })));
		vi.stubGlobal('fetch', fetchMock);
		await postAssumed('tok', { dictation: 'A.', region_normals: {}, abnormal: [] });
		const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
		expect(body).not.toHaveProperty('dictated_normal');
		expect(body).not.toHaveProperty('touched');
	});
});
