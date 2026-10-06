import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_URL } from '$lib/config.js';
import { token } from '$lib/stores/auth.js';
import {
	appliedChatItems,
	chatItem,
	compactOpenItems,
	failureText,
	isLocalMessage,
	loadThread,
	markApplied,
	sendChat
} from './chat';
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
		expect(reply.messageId).toBeNull();
	});

	it('returns the saved message ids', async () => {
		vi.stubGlobal('fetch', respond({ success: true, response: 'Ok', user_message_id: 'u1', message_id: 'a1' }));
		const reply = await sendChat('r1', { message: 'q', history: [], text: '', openItems: [] });
		expect(reply).toMatchObject({ userMessageId: 'u1', messageId: 'a1' });
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

describe('loadThread', () => {
	it('GETs the thread and normalises messages, edits and applied ids', async () => {
		const f = respond({
			success: true,
			messages: [
				{ id: 'u1', role: 'user', content: 'Fix it', edits: [], applied_item_ids: [] },
				{
					id: 'a1',
					role: 'assistant',
					content: 'Done.',
					edits: [
						{
							section: 'FINDINGS',
							find: 'a',
							replace: 'b',
							verified: true,
							failed: [],
							applied_detail: { from: 3, insert: 'b', removed: 'a', left: 'x ', right: '.' }
						}
					],
					applied_item_ids: ['chat:a1:0']
				}
			]
		});
		vi.stubGlobal('fetch', f);
		const thread = await loadThread('r/1');
		const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe(`${API_URL}/api/reports/r%2F1/chat`);
		expect((init.method ?? 'GET').toUpperCase()).toBe('GET');
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-1');
		expect(thread).toHaveLength(2);
		expect(thread[0]).toEqual({ id: 'u1', role: 'user', content: 'Fix it', edits: [], appliedItemIds: [], sources: [] });
		expect(thread[1].appliedItemIds).toEqual(['chat:a1:0']);
		expect(thread[1].edits[0]).toMatchObject({ find: 'a', replace: 'b', verified: true });
		expect(thread[1].edits[0].appliedDetail).toEqual({ from: 3, insert: 'b', removed: 'a', left: 'x ', right: '.' });
	});

	it('throws on success:false', async () => {
		vi.stubGlobal('fetch', respond({ success: false, error: 'Report not found' }));
		await expect(loadThread('r1')).rejects.toThrow('Report not found');
	});
});

describe('markApplied', () => {
	it('POSTs edit_index, item_id, applied and the apply detail', async () => {
		const f = respond({ success: true, applied_item_ids: ['chat:a1:0'] });
		vi.stubGlobal('fetch', f);
		const ids = await markApplied('r1', 'a1', 0, 'chat:a1:0', true, { insert: 'b' });
		const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
		expect(url).toBe(`${API_URL}/api/reports/r1/chat/a1/applied`);
		expect(init.method).toBe('POST');
		expect(JSON.parse(String(init.body))).toEqual({
			edit_index: 0,
			item_id: 'chat:a1:0',
			applied: true,
			detail: { insert: 'b' }
		});
		expect(ids).toEqual(['chat:a1:0']);
	});
});

describe('appliedChatItems', () => {
	it('rebuilds applied edits as applied lane:chat items whose history lets Undo find the text', () => {
		const items = appliedChatItems('r1', [
			{ id: 'u1', role: 'user', content: 'q', edits: [], appliedItemIds: [], sources: [] },
			{
				id: 'a1',
				role: 'assistant',
				content: 'Done.',
				edits: [
					{ section: 'FINDINGS', find: 'a', replace: 'b', verified: true, failed: [] },
					{
						section: 'FINDINGS',
						find: 'c',
						replace: 'd',
						verified: true,
						failed: [],
						appliedDetail: { from: 9, insert: 'd', removed: 'c', left: '', right: '' }
					}
				],
				appliedItemIds: ['chat:a1:0', 'chat:a1:1'],
				sources: []
			}
		]);
		expect(items.map((i) => [i.id, i.status, i.lane])).toEqual([
			['chat:a1:0', 'applied', 'chat'],
			['chat:a1:1', 'applied', 'chat']
		]);
		expect(items[0].history[0]).toMatchObject({ event: 'apply', detail: { insert: 'b', removed: 'a' } });
		expect(items[1].history[0].detail).toEqual({ from: 9, insert: 'd', removed: 'c', left: '', right: '' });
	});
});

describe('isLocalMessage', () => {
	it('is true for ids the thread made up before (or without) a saved id', () => {
		expect(isLocalMessage('local-3')).toBe(true);
		expect(isLocalMessage('2f0c2a5e-0000-4000-8000-000000000000')).toBe(false);
	});
});
