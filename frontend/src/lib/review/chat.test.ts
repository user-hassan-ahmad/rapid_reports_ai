import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import { chatItem, compactOpenItems, failureText, sendChat } from './chat';
import type { ReviewItem } from './types';

function respond(body: unknown, status = 200) {
	return vi.fn(async () => new Response(JSON.stringify(body), { status }));
}

// SYNTHETIC items only.
function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'r1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		kind: 'omission',
		cls: 'action',
		label: over.id,
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

beforeEach(() => token.set('tok-1' as never));
afterEach(() => {
	vi.unstubAllGlobals();
	token.set(null);
});

describe('sendChat', () => {
	it('POSTs message, history, live text and open items with the bearer header', async () => {
		const f = respond({
			success: true,
			response: 'Done.',
			edits: [{ section: 'FINDINGS', find: 'a', replace: 'b', verified: true, failed: [] }],
			sources: []
		});
		vi.stubGlobal('fetch', f);
		const reply = await sendChat('r/1', {
			message: 'Fix it',
			history: [{ role: 'user', content: 'hi' }],
			text: 'REPORT',
			openItems: [{ id: 'i1', section: 'FINDINGS', kind: 'omission', label: 'Missing' }]
		});
		const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe(`${API_URL}/api/reports/r%2F1/chat`);
		expect(init.method).toBe('POST');
		const headers = init.headers as Record<string, string>;
		expect(headers.Authorization).toBe('Bearer tok-1');
		expect(headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(String(init.body))).toEqual({
			message: 'Fix it',
			history: [{ role: 'user', content: 'hi' }],
			text: 'REPORT',
			open_items: [{ id: 'i1', section: 'FINDINGS', kind: 'omission', label: 'Missing' }]
		});
		expect(reply.response).toBe('Done.');
		expect(reply.edits).toHaveLength(1);
	});

	it('defaults edits and sources to [] and normalises edit fields', async () => {
		vi.stubGlobal('fetch', respond({ success: true, response: 'Ok', edits: [{ find: 'x', verified: false }] }));
		const reply = await sendChat('r1', { message: 'q', history: [], text: '', openItems: [] });
		expect(reply.sources).toEqual([]);
		expect(reply.edits).toEqual([{ section: '', find: 'x', replace: '', verified: false, failed: [] }]);
	});

	it('throws on success:false', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'Report not found' }));
		await expect(sendChat('r1', { message: 'q', history: [], text: '', openItems: [] })).rejects.toThrow(
			'Report not found'
		);
	});
});

describe('compactOpenItems', () => {
	it('keeps open and stale rail items as {id, section, kind, label}; drops normals, suppressed, answered and chat', () => {
		const out = compactOpenItems([
			item({ id: 'a', section: 'FINDINGS', label: 'Missing spleen' }),
			item({ id: 'b', status: 'stale', section: null }),
			item({ id: 'c', status: 'applied' }),
			item({ id: 'd', kind: 'assumed_normal', cls: 'info' }),
			item({ id: 'e', cls: 'suppress' }),
			item({ id: 'f', lane: 'chat' })
		]);
		expect(out).toEqual([
			{ id: 'a', section: 'FINDINGS', kind: 'omission', label: 'Missing spleen' },
			{ id: 'b', section: '', kind: 'omission', label: 'b' }
		]);
	});
});

describe('chatItem', () => {
	it('builds an open, local lane:chat item carrying the edit and linked to its message', () => {
		const it = chatItem('r1', 'm2', 0, { section: 'FINDINGS', find: 'No ascites.', replace: 'Small ascites.' });
		expect(it).toMatchObject({
			id: 'chat:m2:0',
			report_id: 'r1',
			lane: 'chat',
			cls: 'minor',
			status: 'open',
			section: 'FINDINGS',
			anchor: null,
			edit: { mode: 'replace', find: 'No ascites.', replace: 'Small ascites.', section: 'FINDINGS' },
			evidence: { message_id: 'm2', edit_index: 0 }
		});
		expect(it.label).toContain('Small ascites.');
	});
});

describe('failureText', () => {
	it('explains known guard codes and falls back to the code in words', () => {
		expect(failureText('anchor_not_unique')).toMatch(/exactly once/);
		expect(failureText('some_new_code')).toBe('some new code');
	});
});
