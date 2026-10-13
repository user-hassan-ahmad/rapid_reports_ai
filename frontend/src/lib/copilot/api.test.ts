import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { token } from '$lib/stores/auth.js';
import { calculate, CopilotError, CopilotOff, match, matchOther, open, preview, TIMEOUT_MS } from './api';
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
const matchBody: MatchBody = { scan_type: 'CT chest', clinical_history: '', findings: [{ id: 'u1', text: 'a 6 mm solid nodule' }], dictation: 'a 6 mm solid nodule', patient: {} };
const openBody: OpenBody = { card, finding: card.finding, findings: card.finding, clinical_history: '', answered: {}, patient: {} };

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
		expect(Object.keys(call(f).body).sort()).toEqual(['clinical_history', 'dictation', 'findings', 'patient', 'scan_type']);
	});
	it('an open body holds exactly the OpenBody keys (lesion only when given)', async () => {
		const f = ok({});
		vi.stubGlobal('fetch', f);
		await open({ ...openBody, extra: 1 } as OpenBody);
		await open({ ...openBody, lesion: 'L1' });
		const keys = ['answered', 'card', 'clinical_history', 'finding', 'findings', 'patient'];
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
	it('caps answered at 20 inputs', async () => {
		const f = ok({});
		vi.stubGlobal('fetch', f);
		const answered = Object.fromEntries(Array.from({ length: 25 }, (_, i) => [`in${i}`, 'yes']));
		await open({ ...openBody, answered });
		expect(Object.keys(call(f).body.answered)).toHaveLength(20);
	});
});

describe('errors', () => {
	it('a 404 throws CopilotOff', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"Not Found"}', { status: 404 })));
		await expect(match(matchBody)).rejects.toBeInstanceOf(CopilotOff);
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
