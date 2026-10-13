import { afterEach, describe, expect, it, vi } from 'vitest';
import { postRouterCard, postRouterUndo } from './api';
import { isProposal } from './types';

afterEach(() => vi.unstubAllGlobals());

const turn = { success: true, skill_sheet: 'S', response: 'Undone.', behavioral_claim: '', applied: true };

describe('chat-router api', () => {
	it('posts an undo with the token and returns the turn', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(turn)));
		vi.stubGlobal('fetch', fetchMock);
		const r = await postRouterUndo('tok', { skill_sheet: 's', decisions: [], changes: [{ type: 'ledger' }], changes_sig: 'S', turn_id: null });
		expect(r.response).toBe('Undone.');
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/refine/undo')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
		expect(JSON.parse(init.body as string)).toMatchObject({ changes: [{ type: 'ledger' }], changes_sig: 'S' });
	});

	it('posts a card answer and throws on an HTTP error', async () => {
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(turn)));
		vi.stubGlobal('fetch', fetchMock);
		await postRouterCard(null, { skill_sheet: 's', decisions: [], answer: { proposal: { kind: 'layout' } } });
		const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(url.endsWith('/api/templates/skill-sheet/refine/card')).toBe(true);
		expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
		expect(JSON.parse(init.body as string).answer).toEqual({ proposal: { kind: 'layout' } });
		vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
		await expect(postRouterCard(null, { skill_sheet: 's', decisions: [], answer: { proposal: {} } })).rejects.toThrow('refine card 500');
	});

	it('tells a proposal card from a decision card', () => {
		expect(isProposal({ id: 'p', kind: 'proposal', title: 't', apply: {} })).toBe(true);
	});
});
