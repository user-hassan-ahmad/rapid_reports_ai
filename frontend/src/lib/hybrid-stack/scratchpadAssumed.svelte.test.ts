// P2c Task 5: the scratchpad in stack mode. A failed /assumed is a state ("couldn't check normals"), never "nothing
// assumed"; no legacy coverage review, no checklist on /canvas/bundle; the slim sheet is asked by the session token.
// Mounts the scratchpad with the stack API stubbed (pattern: scratchpadConfirm.svelte.test.ts). SYNTHETIC text.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { PACKAGE_CONFIG } from '$lib/dictation-lab/package';

const NORMALS = { Liver: ['The liver is normal.'], Peritoneum: ['No free fluid.'] };
const calls: { name: string; body?: any }[] = [];
const state = { assumedFails: true };
vi.mock('$lib/hybrid-stack/api', async (orig) => {
	const real: any = await orig();
	const stub = (name: string, reply: (body: any) => any) => vi.fn(async (_t: unknown, body?: any) => {
		calls.push({ name, body });
		return reply(body);
	});
	const unit = (id: number, text: string, group: string, abnormal = false) => ({
		id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
	});
	return {
		...real,
		postSlimSheet: stub('slim', () => ({ ready: true, id: 's1', status: 'ok', not_assessable: '', region_normals: NORMALS, level_groups: {}, structure_key: 'tok.minted' })),
		postAssumed: stub('assumed', (b) => {
			if (state.assumedFails) throw new Error('stack assumed 500');
			return { assumed: b.region_normals, flagged: {}, dropped: {}, ms: 1, error: null };
		}),
		postItems: stub('items', () => ({ items: [], capped: [], contradicted: [], cached: false, ms: 1, error: null })),
		postGroup: stub('group', (b) => ({
			units: b.text.trim() ? [unit(0, 'A 2 cm liver cyst.', 'Liver', true)] : [],
			new_ids: [], pills: [], timings_ms: {}, error: null
		})),
		postClose: stub('close', (b) => ({ units: b.units, new_ids: [], pills: [], timings_ms: {}, error: null })),
		postUnfinished: stub('unfinished', () => ({ flags: [] })),
		postDictationCheck: stub('check', () => ({ flags: [] })),
		postChanged: stub('changed', () => ({ material: false, score: 0 })),
		postConclusionCheck: stub('stale', () => ({ stale: false, score: 0 })),
		postDraft: stub('draft', () => ({ text: '', ms: 1, error: null })),
		postLog: stub('log', () => ({}))
	};
});
import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';

const fetched: { url: string; body: any }[] = [];
beforeEach(() => {
	calls.length = 0;
	fetched.length = 0;
	vi.stubGlobal('fetch', vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => {
		let body: any = null;
		try { body = typeof init?.body === 'string' ? JSON.parse(init.body) : null; } catch { /* not JSON */ }
		fetched.push({ url: String(u), body });
		return new Response(JSON.stringify({}), { status: 404 });
	}));
});
afterEach(() => vi.unstubAllGlobals());

async function mount(extra: Record<string, unknown> = {}) {
	const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'CT abdomen', clinicalHistory: 'Pain.',
		checklistSections: ['Liver', 'Peritoneum'], structureKey: 'tok.session', ...extra };
	const r = render(DictationScratchpad, props);
	await r.rerender({ ...props, stackRegions: ['Liver', 'Peritoneum'].map((name) => ({ name, includes: '' })),
		stackGroups: ['Liver', 'Peritoneum', 'Other findings', 'General', 'Conclusion'],
		stackSchemaMeta: { key: 'k', source: 'generic', provisional: false } });
	return r;
}

describe('scratchpad in stack mode (P2c)', () => {
	it('test_assumed_error_is_a_state', async () => {
		state.assumedFails = true;
		await mount();
		await expect.poll(() => calls.filter((c) => c.name === 'assumed').length, { timeout: 3000 }).toBeGreaterThan(0);
		await expect.element(page.getByText(/Couldn't check normals/)).toBeVisible();
	});

	it('a working /assumed shows no failure', async () => {
		state.assumedFails = false;
		await mount();
		await expect.poll(() => calls.filter((c) => c.name === 'assumed').length, { timeout: 3000 }).toBeGreaterThan(0);
		await new Promise((r) => setTimeout(r, 200));
		expect(page.getByText(/Couldn't check normals/).elements()).toHaveLength(0);
	});

	it('the slim sheet is asked by the session token; a re-minted key reaches the host', async () => {
		state.assumedFails = false;
		const onStructureKey = vi.fn();
		await mount({ onStructureKey });
		await expect.poll(() => calls.filter((c) => c.name === 'slim').length, { timeout: 3000 }).toBe(1);
		expect(calls.find((c) => c.name === 'slim')!.body.structure_key).toBe('tok.session');
		await expect.poll(() => onStructureKey.mock.calls.some(([k]) => k === 'tok.minted'), { timeout: 3000 }).toBe(true);
		expect(onStructureKey).toHaveBeenLastCalledWith('tok.minted');
	});

	it('no /canvas/review coverage call and no checklist on /canvas/bundle', async () => {
		state.assumedFails = false;
		const r = await mount({ labConfig: PACKAGE_CONFIG });
		(r.component as any).reset('A 2 cm liver cyst.');
		(r.component as any).injectTranscript('The spleen is normal.', true);
		await expect.poll(() => fetched.some((f) => f.url.includes('/api/canvas/bundle')), { timeout: 5000 }).toBe(true);
		await new Promise((res) => setTimeout(res, 1500)); // past the review debounce
		expect(fetched.filter((f) => f.url.includes('/api/canvas/review'))).toHaveLength(0);
		for (const f of fetched.filter((x) => x.url.includes('/api/canvas/bundle'))) expect(f.body).not.toHaveProperty('checklist');
		expect(fetched.filter((f) => f.url.includes('/api/canvas/process') && f.body?.mode === 'structured')).toHaveLength(0);
	});
});
