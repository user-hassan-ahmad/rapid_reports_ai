// Round 1 (review of the four normals fixes): the template's context rules are decided once (the sheet load) and sent
// back on every refresh; Confirm re-asks every rule with the dictation, gates only on that Confirm answer, and shows
// (never gates) a normal the Confirm answer adds. Mounts the scratchpad with the stack API stubbed.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';

const RULE = 'no previous study is available';
const PORTAL = 'The portal vein is patent.';
const NORMALS = { Liver: ['No biliary dilatation.', PORTAL], Peritoneum: ['No free fluid.'] };
const calls: { name: string; body?: any }[] = [];
const state = { confirmAdds: true };
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
		// Live: the session's rule hides the portal vein sentence. At Confirm: the dictation un-hides it (when confirmAdds).
		postAssumed: stub('assumed', (b) => ({
			assumed: b.confirm && state.confirmAdds ? b.region_normals : { ...b.region_normals, Liver: ['No biliary dilatation.'] },
			flagged: { Liver: ['No biliary dilatation.'] }, dropped: {}, ms: 1, error: null, confirm_recheck: true, rules: { [RULE]: 0.9 }
		})),
		postItems: stub('items', () => ({ items: [], capped: [], contradicted: [], cached: false, ms: 1, error: null })),
		postGroup: stub('group', (b) => ({
			units: b.text.trim() ? [unit(0, 'A 2 cm liver cyst.', 'Liver', true), unit(1, 'Simple liver cyst.', 'Conclusion')] : [],
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
import { findingsHash } from '$lib/hybrid-stack/regionState';

const assumedCalls = () => calls.filter((c) => c.name === 'assumed');

async function mount(onStackGate: (gate: any, units: any[], groups: string[]) => void) {
	const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'CT abdomen', clinicalHistory: 'Pain.', onStackGate };
	const r = render(DictationScratchpad, props);
	await r.rerender({ ...props, stackRegions: ['Liver', 'Peritoneum'].map((name) => ({ name, includes: '' })),
		stackGroups: ['Liver', 'Peritoneum', 'Other findings', 'General', 'Conclusion'], stackTemplateId: 't1',
		stackSchemaMeta: { key: 'k', source: 'template', provisional: false } });
	await expect.poll(() => assumedCalls().length, { timeout: 3000 }).toBe(1);
	return r;
}

describe('scratchpad: session rules and the Confirm re-ask (round 1)', () => {
	it('sends the kept rules on the next refresh; a Confirm answer that adds a normal is shown, the next press gates', async () => {
		calls.length = 0;
		state.confirmAdds = true;
		const onStackGate = vi.fn();
		const r = await mount(onStackGate);
		expect(assumedCalls()[0].body.rules).toBeNull();
		(r.component as any).reset('A 2 cm liver cyst. Simple liver cyst.');
		await expect.poll(() => assumedCalls().length, { timeout: 5000 }).toBeGreaterThan(1);
		expect(assumedCalls()[1].body.rules).toEqual({ [RULE]: 0.9 }); // the session's decision, not asked again
		expect(assumedCalls()[1].body.confirm).toBe(false);
		const confirm = page.getByRole('button', { name: 'Confirm', exact: true });
		await expect.element(confirm, { timeout: 8000 }).toBeEnabled();
		const live = assumedCalls().length;
		await confirm.click();
		// the Confirm re-ask un-hid the portal vein sentence: shown, with a status, and not gated
		await expect.poll(() => assumedCalls().length, { timeout: 3000 }).toBe(live + 1);
		expect(assumedCalls()[live].body.confirm).toBe(true);
		await expect.element(page.getByRole('status')).toHaveTextContent(/added: review, then confirm again/);
		expect(onStackGate.mock.calls.some(([g]) => g !== null)).toBe(false);
		// the next press gates on that same Confirm answer: no further call
		await page.getByRole('button', { name: 'Confirm', exact: true }).click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const gate = onStackGate.mock.calls.find(([g]) => g !== null)![0];
		expect(gate.assumed.Liver).toContain(PORTAL);
		expect(assumedCalls().length).toBe(live + 1);
	});

	it('a Confirm answer that only removes gates on the first press', async () => {
		calls.length = 0;
		state.confirmAdds = false;
		const onStackGate = vi.fn();
		const r = await mount(onStackGate);
		(r.component as any).reset('A 2 cm liver cyst. Simple liver cyst.');
		const confirm = page.getByRole('button', { name: 'Confirm', exact: true });
		await expect.element(confirm, { timeout: 8000 }).toBeEnabled();
		const live = assumedCalls().length;
		await confirm.click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		expect(assumedCalls()[live].body.confirm).toBe(true);
		const gate = onStackGate.mock.calls.find(([g]) => g !== null)![0];
		expect(gate.assumed.Liver).not.toContain(PORTAL);
		expect(gate.flagged).toEqual({ Liver: ['No biliary dilatation.'] }); // R1 evidence on the gate record
	});

	it('P2c: Confirm hands the host the gate, the units and the groups (no findings text); the gate records findings_hash', async () => {
		calls.length = 0;
		state.confirmAdds = false;
		const onStackGate = vi.fn();
		const r = await mount(onStackGate);
		(r.component as any).reset('A 2 cm liver cyst. Simple liver cyst.');
		const confirm = page.getByRole('button', { name: 'Confirm', exact: true });
		await expect.element(confirm, { timeout: 8000 }).toBeEnabled();
		await confirm.click();
		await expect.poll(() => onStackGate.mock.calls.some(([g]) => g !== null), { timeout: 3000 }).toBe(true);
		const [gate, units, groups] = onStackGate.mock.calls.find(([g]) => g !== null)!;
		expect(Array.isArray(units)).toBe(true);
		expect(units.map((u: any) => u.text)).toContain('A 2 cm liver cyst.');
		expect(groups).toEqual(['Liver', 'Peritoneum', 'Other findings', 'General', 'Conclusion']);
		expect(gate.findings_hash).toBe(findingsHash(units));
	});
});
