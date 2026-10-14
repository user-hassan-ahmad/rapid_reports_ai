import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { token } from '$lib/stores/auth.js';
import { calculate, CopilotError, CopilotOff, match, matchOther, OFF_DETAIL, open, preview, TIMEOUT_MS } from './api';
import type { Card, MatchBody, OpenBody } from './types';

// SYNTHETIC: pack names and generic phrases only.
const card: Card = {
	key: 'fleischner-2017',
	name: 'Fleischner',
	version: '2017',
	finding_id: 'u1',
	why: 'solid nodule',
	branch: '',
	skeleton: [],
	publication: { title: '', body: '', year: '' },
	known: true,
	status: 'verified',
	siblings: [],
	reference: false,
	finding: 'a 6 mm solid nodule',
	needs_modality: ''
};
const units = [{ id: 1, text: 'a 6 mm solid nodule', group: 'Lungs', structure: null, attach_to: null, parts: null, covers: [], abnormal: true, pinned: false, heading: false }];
// P2c: units + groups (the server builds the findings text with the one builder), never a dictation/findings string
const matchBody: MatchBody = { scan_type: 'CT chest', clinical_history: '', findings: [{ id: 'u1', text: 'a 6 mm solid nodule' }], units, groups: ['Lungs'], patient: {} };
const openBody: OpenBody = { card, finding: card.finding, units, groups: ['Lungs'], clinical_history: '', answered: {}, patient: {} };

function ok(body: unknown = { cards: [], ms: 1 }) {
	return vi.fn(async (_url: string, _init: RequestInit) => new Response(JSON.stringify(body)));
}
const call = (m: ReturnType<typeof ok>, n = 0) => {
	const [url, init] = m.mock.calls[n] as [string, RequestInit];
	return { url, init, body: JSON.parse(init.body as string) };
};

beforeEach(() => token.set('tok' as never));
afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('routes', () => {
	it.each([
		['match', () => match(matchBody)],
		['match/other', () => matchOther(matchBody)],
		['open', () => open(openBody)],
		['preview', () => preview(openBody)],
		['calculate', () => calculate({ ...openBody, values: {} })]
	])('%s posts to its route with the bearer token', async (route, fn) => {
		const f = ok();
		vi.stubGlobal('fetch', f);
		await fn();
		const { url, init } = call(f);
		expect(url.endsWith(`/api/canvas/stack/guidelines/${route}`)).toBe(true);
		expect(init.method).toBe('POST');
		expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
	});
});

describe('bodies', () => {
	it('a match body holds exactly the MatchBody keys', async () => {
		const f = ok();
		vi.stubGlobal('fetch', f);
		await match({ ...matchBody, extra: 1 } as MatchBody);
		expect(Object.keys(call(f).body).sort()).toEqual(['clinical_history', 'findings', 'groups', 'patient', 'scan_type', 'units']);
	});
	it('an open body holds exactly the OpenBody keys (lesion only when given)', async () => {
		const f = ok({});
		vi.stubGlobal('fetch', f);
		await open({ ...openBody, extra: 1 } as OpenBody);
		await open({ ...openBody, lesion: 'L1' });
		const keys = ['answered', 'card', 'clinical_history', 'finding', 'groups', 'patient', 'units'];
		expect(Object.keys(call(f, 0).body).sort()).toEqual(keys);
		expect(Object.keys(call(f, 1).body).sort()).toEqual([...keys, 'lesion'].sort());
	});
	it('caps findings at 20 and each text at 1000 characters', async () => {
		const f = ok();
		vi.stubGlobal('fetch', f);
		const findings = Array.from({ length: 25 }, (_, i) => ({ id: `u${i}`, text: 'x'.repeat(1200) }));
		await match({ ...matchBody, findings });
		const sent = call(f).body.findings as { id: string; text: string }[];
		expect(sent).toHaveLength(20);
		expect(sent[0].id).toBe('u0');
		expect(sent.every((x) => x.text.length === 1000)).toBe(true);
	});
	it('caps an exam card\'s finding (the whole findings text) at 6000 characters', async () => {
		const f = ok({});
		vi.stubGlobal('fetch', f);
		const long = 'y'.repeat(7000);
		await open({ ...openBody, finding: long, card: { ...openBody.card, finding: long } });
		expect((call(f).body.finding as string).length).toBe(6000);
		expect((call(f).body.card as { finding: string }).finding.length).toBe(6000);
	});
	it('caps answered at 20 inputs', async () => {
		const f = ok({});
		vi.stubGlobal('fetch', f);
		const answered = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`in${i}`, 'yes']));
		await open({ ...openBody, answered });
		expect(Object.keys(call(f).body.answered)).toHaveLength(20);
	});
});

describe('errors', () => {
	it('a 404 with detail copilot_off throws CopilotOff', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: OFF_DETAIL }), { status: 404 })));
		expect(OFF_DETAIL).toBe('copilot_off');
		await expect(match(matchBody)).rejects.toBeInstanceOf(CopilotOff);
	});
	it('a bare "Not Found" 404 is a card-local CopilotError and the session stays on', async () => {
		const f = vi
			.fn()
			.mockResolvedValueOnce(new Response('{"detail":"Not Found"}', { status: 404 }))
			.mockResolvedValueOnce(new Response('not json', { status: 404 }))
			.mockResolvedValueOnce(new Response(JSON.stringify({ cards: [], ms: 1 })));
		vi.stubGlobal('fetch', f);
		const e = await open(openBody).catch((x) => x);
		expect(e).toBeInstanceOf(CopilotError);
		expect(e).not.toBeInstanceOf(CopilotOff);
		expect(e.status).toBe(404);
		expect(await calculate({ ...openBody, values: {} }).catch((x) => x)).toBeInstanceOf(CopilotError);
		await expect(match(matchBody)).resolves.toEqual({ cards: [], ms: 1 });
	});
	it('any other failure throws CopilotError with its status', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })));
		const e = await match(matchBody).catch((x) => x);
		expect(e).toBeInstanceOf(CopilotError);
		expect(e.status).toBe(500);
	});
	it('a timeout aborts the request and throws CopilotError(timeout)', async () => {
		vi.useFakeTimers();
		let seen: AbortSignal | undefined;
		vi.stubGlobal(
			'fetch',
			vi.fn(
				(_u: string, init: RequestInit) =>
					new Promise((_r, reject) => {
						seen = init.signal ?? undefined;
						seen?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
					})
			)
		);
		const p = match(matchBody).catch((x) => x);
		await vi.advanceTimersByTimeAsync(TIMEOUT_MS.match);
		const e = await p;
		expect(seen?.aborted).toBe(true);
		expect(e).toBeInstanceOf(CopilotError);
		expect(e.reason).toBe('timeout');
	});
	it("the caller's abort rethrows the AbortError (a stale request, not a failure)", async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				(_u: string, init: RequestInit) =>
					new Promise((_r, reject) => init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
			)
		);
		const ac = new AbortController();
		const p = match(matchBody, ac.signal).catch((x) => x);
		ac.abort();
		const e = await p;
		expect(e).not.toBeInstanceOf(CopilotError);
		expect((e as DOMException).name).toBe('AbortError');
	});
});
