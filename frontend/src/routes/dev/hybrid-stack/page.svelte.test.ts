// /dev/hybrid-stack with the Copilot ticked (Task A7). SYNTHETIC dictation; the stack and Copilot APIs are mocked.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import type { StackUnit } from '$lib/hybrid-stack/types';

const stack = vi.hoisted(() => ({ fetchSchema: vi.fn(), postGroup: vi.fn(), postClose: vi.fn(), postItems: vi.fn() }));
vi.mock('$lib/hybrid-stack/api', async (orig) => ({ ...(await orig<object>()), ...stack }));
const cp = vi.hoisted(() => ({ match: vi.fn(), matchOther: vi.fn(), open: vi.fn(), preview: vi.fn() }));
vi.mock('$lib/copilot/api', async (orig) => ({ ...(await orig<object>()), ...cp }));

const { default: DevHybridStack } = await import('./+page.svelte');

const NODULE = 'A 7 mm solid nodule in the right lower lobe.';
const LIVER = 'The liver is normal.';
const unit = (id: number, text: string, group: string, abnormal: boolean): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
});
const card = {
	key: 'fleischner-pulmonary-nodule', name: 'Fleischner 2017', version: '2017', finding_id: 'u1', why: '', branch: '', skeleton: [],
	publication: { title: '', body: '', year: '' }, known: true, status: 'verified', siblings: [], reference: false, finding: NODULE, needs_modality: ''
};

beforeEach(() => {
	for (const f of [...Object.values(stack), ...Object.values(cp)]) f.mockReset();
	stack.fetchSchema.mockResolvedValue({ regions: [{ name: 'Lungs', includes: '' }, { name: 'Liver', includes: '' }], groups: ['Lungs', 'Liver'], pills: ['Lungs', 'Liver'], source: 'test', family: null, key: 'k', provisional: false });
	stack.postGroup.mockImplementation(async (_t: unknown, body: { text: string }) => {
		const units = [unit(1, NODULE, 'Lungs', true)];
		if (body.text.includes(LIVER)) units.push(unit(2, LIVER, 'Liver', false));
		return { units, new_ids: [], pills: [], gate: [], problems: [], timings_ms: {}, model: null, error: null };
	});
	stack.postClose.mockImplementation(async (_t: unknown, body: { units: StackUnit[] }) => ({ units: body.units, pills: [] }));
	stack.postItems.mockResolvedValue({ items: [] });
	cp.match.mockResolvedValue({ cards: [card], ms: 3 });
});

describe('/dev/hybrid-stack Copilot', () => {
	it('unticked: replay sends no Copilot request and shows no rail', async () => {
		render(DevHybridStack);
		await page.getByPlaceholder('Paste dictation').fill(`${NODULE} ${LIVER}`);
		await page.getByRole('button', { name: 'Replay' }).click();
		await expect.element(page.getByText(/^done/)).toBeInTheDocument();
		expect(cp.match).not.toHaveBeenCalled();
		expect(document.querySelector('[data-testid="copilot-rail"]')).toBeNull();
	});

	it('ticked: the nodule is matched only once the next sentence arrives, and its card shows in the rail', async () => {
		render(DevHybridStack);
		await page.getByRole('checkbox', { name: 'Copilot' }).click();
		await page.getByPlaceholder('Paste dictation').fill(`${NODULE} ${LIVER}`);
		await page.getByRole('button', { name: 'Replay' }).click();
		await expect.element(page.getByText(/^done/)).toBeInTheDocument();
		await expect.poll(() => cp.match.mock.calls.length).toBe(2);
		expect(cp.match.mock.calls[0][0].findings).toEqual([]); // first sentence: the nodule is still the growing unit
		expect(cp.match.mock.calls[1][0].findings).toEqual([{ id: 'u1', text: NODULE }]);
		expect(cp.match.mock.calls[1][0].scan_type).toBe('CT abdomen and pelvis with contrast');
		// the test viewport is under 1100 px, so the rail is the strip; it opens the overlay
		const strip = page.getByRole('button', { name: 'Copilot: 1 guideline', exact: true });
		await expect.element(strip).toBeInTheDocument();
		await strip.click();
		await expect.element(page.getByRole('dialog', { name: 'Copilot' }).getByText('Fleischner 2017')).toBeInTheDocument();
		expect(cp.open).not.toHaveBeenCalled(); // finding cards open on click only
	});
});
