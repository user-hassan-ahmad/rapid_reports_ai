// "Which side?" (side brief 2026-10-14): a quick session's /assumed answer that asks for a side shows a blocking check
// in the region card and holds Confirm; once the dictation gives the side, the next answer no longer asks and Confirm
// gates, recording the ask beside jev_dropped. The normals left out show struck through. A failed side call keeps
// the open ask (review F2), holds what it could not check (re-review N1) and is re-asked (N4); a failed check holds
// nothing (N4). Mounts the scratchpad with the stack API stubbed (pattern: scratchpadConfirm.svelte.test.ts). SYNTHETIC.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';

const R = 'The right kidney is normal.';
const L = 'The left kidney is normal.';
const LABEL = 'The right/left kidney is normal.';
const NORMALS = { Kidneys: [R, L], Liver: ['The liver is normal.'] };
const SIDELESS = 'A simple cyst in the kidney.';
const SIDED = 'A simple cyst in the left kidney.';
const calls: { name: string; body?: any }[] = [];
// ok: Jev answers; side_fail: the side call failed twice, as the server returns it (the touched pair dropped,
// side_unchecked; `hold` regions held); error: the whole check failed; throw: the request failed
const state: { mode: 'ok' | 'side_fail' | 'error' | 'throw'; hold: string[] } = { mode: 'ok', hold: [] };
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
			if (state.mode === 'throw') throw new Error('stack assumed 500');
			if (state.mode === 'error') return { assumed: {}, flagged: {}, dropped: {}, ms: 1, error: 'TimeoutError: jev' };
			if (state.mode === 'side_fail') return { assumed: { Kidneys: [], Liver: ['The liver is normal.'] }, flagged: {},
				dropped: { Kidneys: [{ sentence: R, reason: 'side_unchecked' }, { sentence: L, reason: 'contradicted' }] },
				side_asks: [], side_choices: [], side_failed: true, side_hold: state.hold, ms: 1, error: null };
			return {
				assumed: { Kidneys: sideless ? [] : sided ? [R] : [R, L], Liver: ['The liver is normal.'] }, flagged: {},
				dropped: { Kidneys: sideless ? [{ sentence: R, reason: 'side' }, { sentence: L, reason: 'contradicted' }]
					: sided ? [{ sentence: L, reason: 'contradicted' }] : [] },
				side_asks: sideless ? [{ region: 'Kidneys', sentences: [R, L], label: LABEL, choice: 'no_side', score: 0.9 }] : [],
				side_choices: [{ region: 'Kidneys', sentences: [R, L], label: LABEL, choice: sideless ? 'no_side' : 'left',
					score: 0.9, action: sideless ? 'ask' : 'none' }],
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
const card = () => page.getByRole('region', { name: 'Kidneys' });
const confirmBtn = () => page.getByRole('button', { name: 'Confirm', exact: true });

/** Mounts a quick session and dictates the side-less finding: the "Which side?" ask is showing. */
async function mountAsked(onStackGate = vi.fn()) {
	calls.length = 0;
	state.mode = 'ok';
	state.hold = [];
	const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'CT abdomen', clinicalHistory: 'Pain.', onStackGate };
	const r = render(DictationScratchpad, props);
	await r.rerender({ ...props, stackRegions: ['Kidneys', 'Liver'].map((name) => ({ name, includes: '' })),
		stackGroups: ['Kidneys', 'Liver', 'Other findings', 'General', 'Conclusion'],
		stackSchemaMeta: { key: 'k', source: 'library', provisional: false } });
	await expect.poll(() => assumedCalls().length, { timeout: 3000 }).toBe(1);
	(r.component as any).reset(`${SIDELESS} Renal cyst.`);
	await expect.element(card().getByText('Which side?'), { timeout: 8000 }).toBeInTheDocument();
	return r;
}
const gateOf = (onStackGate: ReturnType<typeof vi.fn>) => onStackGate.mock.calls.find(([g]) => g !== null)![0];

describe('scratchpad: "Which side?" on a quick session', () => {
	it('holds Confirm while the side is missing, clears itself once a side is dictated, and is recorded on the gate', async () => {
		const onStackGate = vi.fn();
		const r = await mountAsked(onStackGate);
		await expect.element(card().getByText('Not reported (side not stated)')).toBeInTheDocument();
		await expect.element(card().getByText('Not reported (conflicts with dictation)')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Confirm · 1 to resolve' }), { timeout: 8000 }).toBeEnabled();
		expect(onStackGate.mock.calls.some(([g]) => g !== null)).toBe(false);
		// the side is dictated: the next answer no longer asks; Confirm gates by itself, no "keep" needed
		(r.component as any).reset(`${SIDED} Renal cyst.`);
		await expect.element(page.getByText('Which side?'), { timeout: 8000 }).not.toBeInTheDocument();
		await expect.element(confirmBtn(), { timeout: 8000 }).toBeEnabled();
		await confirmBtn().click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const gate = gateOf(onStackGate);
		expect(gate.side_asks).toEqual([{ region: 'Kidneys', pair: LABEL, score: 0.9, answered_by: 'sided' }]);
		expect(gate.side_choices).toEqual([{ region: 'Kidneys', pair: LABEL, choice: 'left', action: 'none' }]);
		expect(gate.side_failed).toBe(false);
		expect(gate.jev_dropped.Kidneys).toEqual([{ sentence: L, reason: 'contradicted' }]);
		expect(gate.assumed.Kidneys).toEqual([R]);
	});

	it('a failed side call keeps the open ask and Confirm held, is re-asked, and the gate logs kept_unchecked (F2, N4)', async () => {
		const onStackGate = vi.fn();
		const r = await mountAsked(onStackGate);
		state.mode = 'side_fail';
		const before = assumedCalls().length;
		(r.component as any).reset(`${SIDELESS} The liver is normal. Renal cyst.`);   // the Kidneys text is unchanged
		await expect.element(page.getByText(/side check unavailable: open/), { timeout: 8000 }).toBeInTheDocument();
		await expect.element(card().getByText('Which side?')).toBeInTheDocument();
		// the side check is asked again for the same dictation (up to three answers), then Confirm walks to the ask
		await expect.poll(() => assumedCalls().length - before, { timeout: 10000 }).toBe(3);
		await expect.element(page.getByRole('button', { name: 'Confirm · 1 to resolve' }), { timeout: 8000 }).toBeEnabled();
		await card().getByRole('button', { name: 'Keep without side' }).click();
		await expect.element(confirmBtn(), { timeout: 8000 }).toBeEnabled();
		await confirmBtn().click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const gate = gateOf(onStackGate);
		expect(gate.side_failed).toBe(true);
		expect(gate.assumed.Kidneys ?? []).not.toContain(R);
		expect(gate.side_asks).toEqual([{ region: 'Kidneys', pair: LABEL, score: 0.9, answered_by: 'kept_unchecked' }]);
	});

	it('a side dictated while the side check fails is held, never a stale ask; a retry that answers clears it (N1, N4)', async () => {
		const onStackGate = vi.fn();
		const r = await mountAsked(onStackGate);
		state.mode = 'side_fail';
		state.hold = ['Kidneys'];
		(r.component as any).reset(`${SIDED} Renal cyst.`);
		await expect.element(card().getByText('Side check unavailable'), { timeout: 8000 }).toBeInTheDocument();
		await expect.element(card().getByText('Which side?')).not.toBeInTheDocument();   // the Kidneys text changed: not carried
		await expect.element(page.getByText('side check unavailable', { exact: true })).toBeInTheDocument();
		state.mode = 'ok';   // the next retry answers
		await expect.element(card().getByText('Side check unavailable'), { timeout: 10000 }).not.toBeInTheDocument();
		await expect.element(confirmBtn(), { timeout: 8000 }).toBeEnabled();
		await confirmBtn().click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const gate = gateOf(onStackGate);
		expect(gate.side_failed).toBe(false);
		expect(gate.side_hold).toEqual([]);
		expect(gate.assumed.Kidneys).toEqual([R]);
	});

	for (const mode of ['error', 'throw'] as const) {
		it(`a failed check (${mode}) assumes nothing and holds no side question over it (N4)`, async () => {
			const r = await mountAsked();
			state.mode = mode;
			(r.component as any).reset(`${SIDELESS} The liver is normal. Renal cyst.`);
			await expect.element(page.getByText('Which side?'), { timeout: 8000 }).not.toBeInTheDocument();
			await expect.element(confirmBtn(), { timeout: 8000 }).toBeEnabled();
			await expect.element(page.getByText(/side check unavailable/)).not.toBeInTheDocument();
			state.mode = 'ok';
		});
	}
});
