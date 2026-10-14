// E6 (e2e 2026-10-13): the assumed normals are checked once the slim sheet loads, before any dictation, so the tray
// shows every region's normal straight after Set up workspace. Mounts the scratchpad with the stack API stubbed.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';

const calls: { name: string; body?: any; at: number; done?: number }[] = [];
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
vi.mock('$lib/hybrid-stack/api', async (orig) => {
	const real: any = await orig();
	const stub = (name: string, reply: (body: any) => any, ms = 0) => vi.fn(async (_t: unknown, body?: any) => {
		const c: { name: string; body?: any; at: number; done?: number } = { name, body, at: performance.now() };
		calls.push(c);
		await wait(ms);
		c.done = performance.now();
		return reply(body);
	});
	return {
		...real,
		// The sheet arrives after the /items reply, as live: only the sheet load can trigger the first check.
		postSlimSheet: stub('slim', () => ({ ready: true, id: 's1', status: 'ok', not_assessable: '',
			region_normals: { Cord: ['Normal cord signal.'], Alignment: ['Normal alignment.'], 'Lumbar levels': ['The lumbar discs are normal.'] },
			level_groups: { 'Lumbar levels': ['L4/5'] } }), 400),
		postAssumed: stub('assumed', (b) => ({ assumed: b.region_normals, dropped: {}, ms: 1, rules: { 'no previous study is available': 0.1 }, error: null })),
		postItems: stub('items', () => ({ items: [], capped: [], contradicted: [], ms: 1, error: null })),
		postGroup: stub('group', () => ({ units: [], new_ids: [], pills: [] })),
		postLog: stub('log', () => ({}))
	};
});
import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';

describe('scratchpad: assumed normals before any dictation (E6)', () => {
	it('checks the normals once when the sheet loads, with an empty dictation, and the tray shows every region', async () => {
		const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'MRI Whole spine' };
		const { rerender } = render(DictationScratchpad, props);
		await rerender({ ...props, stackRegions: ['Alignment', 'Cord', 'Lumbar levels', 'L4/5'].map((name) => ({ name, includes: '' })),
			stackGroups: ['Alignment', 'Cord', 'Lumbar levels', 'L4/5', 'Other findings', 'General', 'Conclusion'], stackQuiet: ['L4/5'],
			stackSchemaMeta: { key: 'k', source: 'library', provisional: false },
			stackProtocol: { id: 'MWS', phases: [], laterality: null, displayName: 'MRI Whole spine', line: 'No contrast' } });
		await expect.poll(() => calls.filter((c) => c.name === 'assumed').length, { timeout: 3000 }).toBe(1);
		// Straight from the sheet load, not the 1.2 s re-arm timer.
		const slim = calls.find((c) => c.name === 'slim')!;
		const first = calls.find((c) => c.name === 'assumed')!;
		expect(first.at - slim.done!).toBeLessThan(500);
		const sent = first.body;
		expect(sent.dictation).toBe('');
		expect(sent.rules).toBeNull(); // R5: the workspace load decides the session's context rules (one call)
		expect(sent.confirm).toBe(false);
		expect(Object.keys(sent.region_normals).sort()).toEqual(['Alignment', 'Cord']); // segments are never sent (E1)
		await expect.poll(() => document.body.innerText, { timeout: 3000 }).toContain('3 assumed normal');
		await wait(1600); // past the 1.2 s re-arm timer: the empty-dictation answer is current, so nothing re-runs
		expect(calls.filter((c) => c.name === 'assumed').length).toBe(1);
		expect(calls.map((c) => c.name).indexOf('assumed')).toBeGreaterThan(calls.map((c) => c.name).indexOf('slim'));
	});
});
