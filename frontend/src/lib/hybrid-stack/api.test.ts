import { afterEach, describe, expect, it, vi } from 'vitest';
import { postGroup } from './api';

afterEach(() => vi.unstubAllGlobals());

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

describe('postValues', () => {
	it('posts the dictation and the template id to /values', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ values: [], ms: 1, error: null })));
		vi.stubGlobal('fetch', fetchMock);
		const { postValues } = await import('./api');
		await postValues('tok', { dictation: 'LVEF 45%.', template_id: 't1' });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/canvas/stack/values')).toBe(true);
		expect(JSON.parse(init.body as string)).toEqual({ dictation: 'LVEF 45%.', template_id: 't1' });
	});
});
