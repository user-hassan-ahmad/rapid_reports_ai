// "Which side?" (side brief 2026-10-14): a quick session's /assumed answer that asks for a side shows a blocking check
// in the region card and holds Confirm; once the dictation gives the side, the next answer no longer asks and Confirm
// gates, recording the ask beside jev_dropped. The normals left out show struck through. Mounts the scratchpad with
// the stack API stubbed (pattern: scratchpadConfirm.svelte.test.ts). SYNTHETIC text.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';

const R = 'The right kidney is normal.';
const L = 'The left kidney is normal.';
const NORMALS = { Kidneys: [R, L], Liver: ['The liver is normal.'] };
const SIDELESS = 'A simple cyst in the kidney.';
const SIDED = 'A simple cyst in the left kidney.';
const calls: { name: string; body?: any }[] = [];
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
		postSlimSheet: stub('slim', () => ({ ready: true, id: 's1', status: 'ok', not_assessable: '', region_normals: NORMALS, level_groups: {} })),
		postAssumed: stub('assumed', (b) => {
			const sideless = b.dictation.includes(SIDELESS);
			const sided = b.dictation.includes(SIDED);
			return {
				assumed: { Kidneys: sideless ? [] : sided ? [R] : [R, L], Liver: ['The liver is normal.'] }, flagged: {},
				dropped: { Kidneys: sideless ? [{ sentence: R, reason: 'side' }, { sentence: L, reason: 'contradicted' }]
					: sided ? [{ sentence: L, reason: 'contradicted' }] : [] },
				side_asks: sideless ? [{ region: 'Kidneys', sentences: [R, L], label: 'The right/left kidney is normal.', score: 0.9 }] : [],
				ms: 1, error: null
			};
		}),
		postItems: stub('items', () => ({ items: [], capped: [], contradicted: [], cached: false, ms: 1, error: null })),
		postGroup: stub('group', (b) => ({
			units: b.text.trim() ? [unit(0, b.text.split('. ')[0].replace(/\.?$/, '.'), 'Kidneys', true), unit(1, 'Renal cyst.', 'Conclusion')] : [],
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

const assumedCalls = () => calls.filter((c) => c.name === 'assumed');

describe('scratchpad: "Which side?" on a quick session', () => {
	it('holds Confirm while the side is missing, clears itself once a side is dictated, and is recorded on the gate', async () => {
		calls.length = 0;
		const onStackGate = vi.fn();
		const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'CT abdomen', clinicalHistory: 'Pain.', onStackGate };
		const r = render(DictationScratchpad, props);
		await r.rerender({ ...props, stackRegions: ['Kidneys', 'Liver'].map((name) => ({ name, includes: '' })),
			stackGroups: ['Kidneys', 'Liver', 'Other findings', 'General', 'Conclusion'],
			stackSchemaMeta: { key: 'k', source: 'library', provisional: false } });
		await expect.poll(() => assumedCalls().length, { timeout: 3000 }).toBe(1);
		(r.component as any).reset(`${SIDELESS} Renal cyst.`);
		const card = page.getByRole('region', { name: 'Kidneys' });
		await expect.element(card.getByText('Which side?'), { timeout: 8000 }).toBeInTheDocument();
		await expect.element(card.getByText('Not reported (conflicts with dictation)')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Confirm · 1 to resolve' }), { timeout: 8000 }).toBeEnabled();
		expect(onStackGate.mock.calls.some(([g]) => g !== null)).toBe(false);
		// the side is dictated: the next answer no longer asks; Confirm gates by itself, no "keep" needed
		(r.component as any).reset(`${SIDED} Renal cyst.`);
		await expect.element(page.getByText('Which side?'), { timeout: 8000 }).not.toBeInTheDocument();
		const confirm = page.getByRole('button', { name: 'Confirm', exact: true });
		await expect.element(confirm, { timeout: 8000 }).toBeEnabled();
		await confirm.click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const gate = onStackGate.mock.calls.find(([g]) => g !== null)![0];
		expect(gate.side_asks).toEqual([{ region: 'Kidneys', pairs: ['The right/left kidney is normal.'], answered_by: 'dictated' }]);
		expect(gate.jev_dropped.Kidneys).toEqual([{ sentence: L, reason: 'contradicted' }]);
		expect(gate.assumed.Kidneys).toEqual([R]);
	});
});
