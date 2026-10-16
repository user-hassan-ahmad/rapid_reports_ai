// Instruction flag, Q12 (Hassan 2026-10-16): an open instruction card blocks Confirm, and so Generate. Mounts the
// scratchpad with the stack API stubbed (pattern: scratchpadConfirm / scratchpadAssumed) and /canvas/bundle answering
// `instruction` for the command final. SYNTHETIC text.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { PACKAGE_CONFIG } from '$lib/dictation-lab/package';

const SAID = 'Delete all the other sections.';
const NORMALS = { Liver: ['No biliary dilatation.'], Peritoneum: ['No free fluid.'] };
const calls: { name: string; body?: any }[] = [];
// confirmGate: when set, the Confirm re-ask (/assumed with confirm) waits for it
const state: { confirmGate: Promise<void> | null } = { confirmGate: null };
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
		postAssumed: stub('assumed', async (b) => {
			if (b.confirm && state.confirmGate) await state.confirmGate;
			return { assumed: b.region_normals, flagged: {}, dropped: {}, ms: 1, error: null, confirm_recheck: true, rules: {} };
		}),
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

beforeEach(() => {
	calls.length = 0;
	state.confirmGate = null;
	vi.stubGlobal('fetch', vi.fn(async (u: RequestInfo | URL, init?: RequestInit) => {
		const body = typeof init?.body === 'string' ? JSON.parse(init.body) : null;
		if (String(u).includes('/api/canvas/bundle') && body?.latest_utterance === SAID) {
			return new Response(JSON.stringify({
				decision_id: 'd1', route: 'polish', reason: 'action:formatting_command', text: '', insert: '', closes_line: true,
				close_on_silence: false, clean_text: SAID, latency_ms: 1,
				stack_command: { action: 'instruction', region: null, item: null, command: 'delete', confidence: 0.5, instruction: 0.92 }
			}), { status: 200 });
		}
		return new Response(JSON.stringify({}), { status: 404 });
	}));
});
afterEach(() => vi.unstubAllGlobals());

async function mount(onStackGate: (gate: any, units: any[], groups: string[]) => void) {
	const props: any = { hybridStack: true, polishMode: 'clean', scanType: 'CT abdomen', clinicalHistory: 'Pain.', onStackGate,
		labConfig: PACKAGE_CONFIG };
	const r = render(DictationScratchpad, props);
	await r.rerender({ ...props, stackRegions: ['Liver', 'Peritoneum'].map((name) => ({ name, includes: '' })),
		stackGroups: ['Liver', 'Peritoneum', 'Other findings', 'General', 'Conclusion'], stackTemplateId: 't1',
		stackSchemaMeta: { key: 'k', source: 'template', provisional: false } });
	await expect.poll(() => calls.filter((c) => c.name === 'assumed').length, { timeout: 3000 }).toBe(1);
	(r.component as any).reset('A 2 cm liver cyst. Simple liver cyst.');
	return r;
}
const confirm = () => page.getByRole('button', { name: 'Confirm', exact: true });
const gated = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.some(([g]) => g !== null);
const held = () => page.getByTestId('held-instruction');

describe('scratchpad: an open instruction card blocks Confirm and Generate (Q12)', () => {
	it('refuses Confirm while a card is open; Discard lets it through', async () => {
		const onStackGate = vi.fn();
		const r = await mount(onStackGate);
		await expect.element(confirm(), { timeout: 8000 }).toBeEnabled();
		(r.component as any).injectTranscript(SAID, true);
		await expect.element(held(), { timeout: 5000 }).toHaveTextContent(SAID);
		await expect.element(confirm()).toBeDisabled();
		await page.getByRole('button', { name: 'Discard' }).click();
		await expect.element(confirm()).toBeEnabled();
		await confirm().click();
		await expect.poll(() => gated(onStackGate), { timeout: 3000 }).toBe(true);
	});

	it('a card that opens after Confirm withdraws the gate', async () => {
		const onStackGate = vi.fn();
		const r = await mount(onStackGate);
		await expect.element(confirm(), { timeout: 8000 }).toBeEnabled();
		await confirm().click();
		await expect.poll(() => gated(onStackGate), { timeout: 3000 }).toBe(true);
		(r.component as any).injectTranscript(SAID, true);
		await expect.element(held(), { timeout: 5000 }).toBeInTheDocument();
		expect(onStackGate.mock.calls.at(-1)![0]).toBeNull();
	});

	it('a card that opens while Confirm re-asks the rules is not confirmed past (race)', async () => {
		const onStackGate = vi.fn();
		let release!: () => void;
		state.confirmGate = new Promise<void>((res) => (release = res));
		const r = await mount(onStackGate);
		await expect.element(confirm(), { timeout: 8000 }).toBeEnabled();
		const n = calls.filter((c) => c.name === 'assumed').length;
		await confirm().click();
		await expect.poll(() => calls.filter((c) => c.name === 'assumed' && c.body.confirm).length, { timeout: 3000 }).toBe(1);
		expect(calls.length).toBeGreaterThan(n);
		(r.component as any).injectTranscript(SAID, true);   // decided while the re-ask is still running
		await expect.element(held(), { timeout: 5000 }).toBeInTheDocument();
		release();
		await new Promise((res) => setTimeout(res, 300));
		expect(gated(onStackGate)).toBe(false);
	});
});
