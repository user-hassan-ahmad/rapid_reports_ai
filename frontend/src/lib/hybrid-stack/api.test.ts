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

describe('P2c: the stack Generate client, the token and units-based draft', () => {
	const unit = { id: 1, text: 'Liver normal.', group: 'Liver', structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false }; // SYNTHETIC
	const gate = { units_hash: 'h' } as unknown as import('./types').GateRecord;
	const sse = (text: string) => new Response(new ReadableStream({
		start(c) { c.enqueue(new TextEncoder().encode(text)); c.close(); }
	}), { headers: { 'Content-Type': 'text/event-stream' } });

	it('test_generate_body_off_is_todays', async () => {
		const { stackGenerateBody, postDraft, postSlimSheet } = await import('./api');
		const quick = stackGenerateBody({ kind: 'quick', scanType: 'CT', history: 'h', structureKey: 'k', units: [unit], groups: ['Liver'], gate, variables: { FINDINGS: 'x', A: '1' } });
		expect(quick).not.toHaveProperty('variables');
		expect(quick).not.toHaveProperty('template_id');
		expect(quick).toMatchObject({ kind: 'quick', scan_type: 'CT', history: 'h', structure_key: 'k', groups: ['Liver'] });
		const tmpl = stackGenerateBody({ kind: 'template', templateId: 't1', scanType: 'CT', history: 'h', structureKey: 'k', units: [unit], groups: [], gate, variables: { FINDINGS: 'x', A: '1' } });
		expect(tmpl.variables).toEqual({ A: '1' });
		expect(tmpl.template_id).toBe('t1');

		const fetchMock = vi.fn(async () => new Response(JSON.stringify({ text: 'Normal.', ms: 1, error: null })));
		vi.stubGlobal('fetch', fetchMock);
		await postDraft('tok', { units: [unit], groups: ['Liver'], scan_type: 'CT', clinical_history: 'h' });
		const draftBody = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
		expect(draftBody.units).toHaveLength(1);
		expect(draftBody.groups).toEqual(['Liver']);
		expect(draftBody).not.toHaveProperty('findings');

		await postSlimSheet('tok', { structure_key: 'k', scan_type: 'CT', clinical_history: 'h', template_id: 't1' });
		const [slimUrl, slimInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
		expect(slimUrl.endsWith('/api/canvas/stack/slim-sheet')).toBe(true);
		expect(JSON.parse(slimInit.body as string)).toEqual({ structure_key: 'k' });
		await postSlimSheet('tok', { structure_key: null, scan_type: 'CT', clinical_history: 'h' });
		expect(JSON.parse((fetchMock.mock.calls[2] as unknown as [string, RequestInit])[1].body as string)).toEqual({ scan_type: 'CT', clinical_history: 'h' });
	});

	it('test_stack_generate_surfaces_server_error', async () => {
		const { streamStackGenerate, stackGenerateBody } = await import('./api');
		const body = stackGenerateBody({ kind: 'quick', scanType: 'CT', history: '', structureKey: 'k', units: [unit], groups: [], gate });
		const fetchMock = vi.fn(async () => sse('event: error\ndata: {"message":"The scratchpad changed after Confirm. Confirm again."}\n\n'));
		vi.stubGlobal('fetch', fetchMock);
		const on = { candidate: vi.fn(), done: vi.fn(), error: vi.fn() };
		await streamStackGenerate('tok', body, on);
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/canvas/stack/generate')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(on.error).toHaveBeenCalledWith('The scratchpad changed after Confirm. Confirm again.');
		expect(on.candidate).not.toHaveBeenCalled();

		vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"Not Found"}', { status: 404 })));
		const on404 = { candidate: vi.fn(), done: vi.fn(), error: vi.fn() };
		await streamStackGenerate('tok', body, on404);
		expect(on404.error.mock.calls[0][0]).toMatch(/switched off; your dictation is kept/);
	});

	it('streams candidate then done', async () => {
		const { streamStackGenerate, stackGenerateBody } = await import('./api');
		const body = stackGenerateBody({ kind: 'quick', scanType: 'CT', history: '', structureKey: 'k', units: [unit], groups: [], gate });
		vi.stubGlobal('fetch', vi.fn(async () => sse('event: candidate\ndata: {"content":"R","model":"m","sections":["A"]}\n\nevent: done\ndata: {"report_id":"r1","description":"d"}\n\n')));
		const on = { candidate: vi.fn(), done: vi.fn(), error: vi.fn() };
		await streamStackGenerate('tok', body, on);
		expect(on.candidate).toHaveBeenCalledWith(expect.objectContaining({ content: 'R', model: 'm' }));
		expect(on.done).toHaveBeenCalledWith(expect.objectContaining({ report_id: 'r1' }));
		expect(on.error).not.toHaveBeenCalled();
	});

	it('a refused /schema carries the server detail', async () => {
		const { fetchSchema, StackHttpError } = await import('./api');
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"This template has no usable structure."}', { status: 422 })));
		const err = await fetchSchema('tok', { scan_type: 'CT', clinical_history: '', template_id: 't1' }).catch((e) => e);
		expect(err).toBeInstanceOf(StackHttpError);
		expect(err.status).toBe(422);
		expect(err.detail).toBe('This template has no usable structure.');
	});
});
