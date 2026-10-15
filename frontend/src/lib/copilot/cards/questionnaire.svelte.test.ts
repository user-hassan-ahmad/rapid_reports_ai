// The four-zone card (spec 2026-10-14 §4). SYNTHETIC previews rendered through PackBody.
import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import PackBody from './PackBody.svelte';
import { card, draft, outcome, preview, result } from './fixtures';
import type { Candidate, Preview } from '../types';

const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
const reached = (over: Partial<Preview> = {}) =>
	preview({
		proposal: null,
		draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.', headline: 'Solid nodule', action: 'CT at 3 months', category: 'surveillance' }),
		trace: { outcome: 'ct3' },
		draft: [
			draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm', quote: '7 mm' }),
			draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, options: ['solid', 'subsolid', 'Not stated'] })
		],
		...over
	});
function show(p: Preview, props: Record<string, unknown> = {}) {
	const h = { onEdit: vi.fn(), onTick: vi.fn(), onPick: vi.fn(), onApply: vi.fn() };
	render(PackBody, { result: result(bts, p), guideline: 'BTS 2015', applyOn: true, ...h, ...props });
	return h;
}

describe('the questionnaire card', () => {
	it('Check holds the decisive pre-filled value; ✓ ticks it; Apply waits for it', async () => {
		const h = show(reached());
		await expect.element(page.getByTestId('cp-status')).toHaveTextContent('Check 1 value to apply');
		await expect.element(page.getByTestId('cp-check-item')).toHaveTextContent('Type: solid');
		await expect.element(page.getByRole('button', { name: 'Apply' })).toBeDisabled();
		await page.getByRole('button', { name: 'Confirm Type solid' }).click();
		expect(h.onTick).toHaveBeenCalledWith('kind', 'solid');
	});

	it('ticked: "confirmed by you", Apply enabled and sends', async () => {
		const h = show(reached(), { ticks: { kind: 'solid' } });
		await expect.element(page.getByTestId('cp-check-item')).toHaveTextContent('confirmed by you');
		await page.getByRole('button', { name: 'Apply' }).click();
		expect(h.onApply).toHaveBeenCalled();
	});

	it('a scope doubt keeps Confirm (an answer) and Change', async () => {
		const h = show(reached({ scope_doubt: ['kind'] }));
		await expect.element(page.getByTestId('cp-scope-doubt')).toHaveTextContent('would make BTS 2015 not apply');
		await page.getByRole('button', { name: 'Confirm Type solid' }).click();
		expect(h.onEdit).toHaveBeenCalledWith('kind', 'solid');
		expect(h.onTick).not.toHaveBeenCalled();
	});

	it('one question at a time, with "Not known" and what it decides between', async () => {
		const p = preview({ proposal: null, asks: [{ input: 'g', label: 'Growth', options: ['Yes', 'No'], decides_between: [{ outcome: 'a', classification: 'CT at 3 months', citation: {} }, { outcome: 'b', classification: 'PET-CT', citation: {} }] }, { input: 's', label: 'Smoker', options: ['Yes', 'No'] }], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] });
		const h = show(p);
		await expect.element(page.getByTestId('cp-question')).toHaveTextContent('Growth');
		await expect.element(page.getByTestId('cp-question')).toHaveTextContent('Decides between: CT at 3 months · PET-CT');
		await expect.element(page.getByTestId('cp-status')).toHaveTextContent('2 questions to a recommendation');
		await page.getByRole('button', { name: 'Not known' }).click();
		expect(h.onEdit).toHaveBeenCalledWith('g', 'Not stated');
		await page.getByRole('button', { name: 'Yes' }).click();
		expect(h.onEdit).toHaveBeenCalledWith('g', 'Yes');
	});

	it('an incomplete pick asks for the missing answer', async () => {
		const cands: Candidate[] = [{ outcome: 'ct3', headline: 'CT at 3 months', category: 'surveillance', proposal: outcome() }, { outcome: 'pet', headline: 'PET-CT', category: 'workup', proposal: null }];
		const p = preview({ proposal: null, candidates: cands, asks: [{ input: 'g', label: 'Growth', options: ['Yes', 'No'] }], draft: [draft({ input: 'g', label: 'Growth', state: 'asked', options: ['Yes', 'No', 'Not stated'] })] });
		const h = show(p, { edits: { g: 'Not stated' }, pick: 'pet' });
		await expect.element(page.getByTestId('cp-pick')).toHaveTextContent('2 outcomes still possible');
		await page.getByRole('radio', { name: 'CT at 3 months' }).click();
		expect(h.onPick).toHaveBeenCalledWith('ct3');
		await page.getByRole('button', { name: 'Answer Growth to apply' }).click();
		await expect.element(page.getByRole('combobox', { name: 'Answer for Growth' })).toBeInTheDocument();
	});

	it('applied for this outcome: "Applied · in Recommendations"; Apply off: no Apply at all', async () => {
		const p = reached();
		const { verdictKey } = await import('../gate');
		show(p, { ticks: { kind: 'solid' }, applied: { key: 'k', finding_id: 'u1', pack: bts.key, version: 'v', bundle: 'b', source: 'BTS 2015', outcome: 'ct3', verdict: verdictKey(p), sentence: 's', text: 's', values: [] } });
		await expect.element(page.getByTestId('cp-apply')).toHaveTextContent('Applied · in Recommendations');
		cleanup();
		show(p, { ticks: { kind: 'solid' }, applyOn: false });
		await expect.element(page.getByTestId('cp-apply')).not.toBeInTheDocument();
	});

	it('the values wait behind "Based on"', async () => {
		show(reached());
		const t = page.getByRole('button', { name: /^Based on: Size 7 mm/ });
		await expect.element(t).toHaveAttribute('aria-expanded', 'false');
		await t.click();
		await expect.element(t).toHaveAttribute('aria-expanded', 'true');
	});

	it('Apply off: no ✓, no pick buttons, the status line only counts questions', async () => {
		show(reached(), { applyOn: false });
		await expect.element(page.getByRole('button', { name: 'Confirm Type solid' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Change Type' })).toBeInTheDocument();
		await expect.element(page.getByTestId('cp-status')).not.toBeInTheDocument();
		cleanup();
		const cands: Candidate[] = [{ outcome: 'ct3', headline: 'CT at 3 months', category: 'surveillance', proposal: outcome() }, { outcome: 'pet', headline: 'PET-CT', category: 'workup', proposal: null }];
		show(preview({ proposal: null, candidates: cands, asks: [], draft: [] }), { applyOn: false });
		await expect.element(page.getByTestId('cp-pick')).toHaveTextContent('PET-CT');
		await expect.element(page.getByRole('radio')).not.toBeInTheDocument();
	});

	it('Applied only names the outcome on screen: applied A, picked B shows Apply', async () => {
		const { verdictKey } = await import('../gate');
		const cands: Candidate[] = [{ outcome: 'A', headline: 'CT at 3 months', category: 'surveillance', proposal: outcome() }, { outcome: 'B', headline: 'PET-CT', category: 'workup', proposal: outcome() }];
		const p = preview({ proposal: null, candidates: cands, asks: [], draft: [] });
		const rec = { key: 'k', finding_id: 'u1', pack: bts.key, version: 'v', bundle: 'b', source: 'BTS 2015', outcome: 'A', verdict: verdictKey(p), sentence: 's', text: 's', values: [] };
		show(p, { pick: 'B', applied: rec });
		await expect.element(page.getByRole('button', { name: 'Apply' })).toBeInTheDocument();
		cleanup();
		show(p, { pick: 'A', applied: rec });
		await expect.element(page.getByTestId('cp-apply')).toHaveTextContent('Applied · in Recommendations');
	});

	it('an excluded card keeps its scope-doubt banner', async () => {
		const p = preview({ state: 'does_not_apply', proposal: null, scope_doubt: ['kind'], draft: [draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', options: ['solid', 'subsolid'] })] });
		show(p);
		await expect.element(page.getByTestId('cp-scope-doubt')).toHaveTextContent('would make');
	});

	it('a read-only column never says "Check N values to apply" without a ✓', async () => {
		show(reached(), { onTick: null });
		await expect.element(page.getByTestId('cp-status')).not.toBeInTheDocument();
	});
});
