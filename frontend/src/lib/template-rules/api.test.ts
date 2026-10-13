import { afterEach, describe, expect, it, vi } from 'vitest';
import { DECIDE_EXAMPLE_MAX_CHARS, MAX_DECIDE_EXAMPLES, postApplyDecisions, postDecide } from './api';

afterEach(() => vi.unstubAllGlobals());

const ok = () =>
	new Response(JSON.stringify({ success: true, ran: true, cards: [], more: [], kept: [], defaults: [], notice: '', run: {} }));

describe('template-rules api', () => {
	it('posts the decide request with the bearer token and the study setup', async () => {
		const fetchMock = vi.fn(async () => ok());
		vi.stubGlobal('fetch', fetchMock);
		const r = await postDecide('tok', {
			scan_type: 'CT',
			examples: [{ content: 'A.' }],
			template_name: 'CT abdomen',
			protocol_notes: 'Portal venous phase'
		});
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/decide')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		const body = JSON.parse(init.body as string);
		expect(body.examples).toEqual([{ content: 'A.' }]);
		expect(body.template_name).toBe('CT abdomen');
		expect(body.protocol_notes).toBe('Portal venous phase');
		expect(r.ran).toBe(true);
	});

	it('keeps the decide request inside the server caps (5 examples, 20k characters each)', async () => {
		const fetchMock = vi.fn(async () => ok());
		vi.stubGlobal('fetch', fetchMock);
		const long = 'x'.repeat(DECIDE_EXAMPLE_MAX_CHARS + 50);
		await postDecide(null, { scan_type: 'CT', examples: Array.from({ length: 7 }, () => ({ content: long })) });
		const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		const body = JSON.parse(init.body as string);
		expect(MAX_DECIDE_EXAMPLES).toBe(5);
		expect(body.examples).toHaveLength(5);
		expect(body.examples[0].content).toHaveLength(DECIDE_EXAMPLE_MAX_CHARS);
		expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
	});

	it('posts apply-decisions and throws on an HTTP error', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		await expect(postApplyDecisions(null, { skill_sheet: 's', decisions: [], changes: [], source: 'creation' })).rejects.toThrow(
			'apply-decisions 500'
		);
	});
});
