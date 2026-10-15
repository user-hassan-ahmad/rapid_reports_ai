// The Recommendations section (spec 2026-10-14 §7.1, §7.4). SYNTHETIC lines.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import RecommendationsSection from './RecommendationsSection.svelte';
import type { AppliedRec } from './types';

const line = (o: Partial<AppliedRec> = {}): AppliedRec => ({ key: 'k1', finding_id: 'u1', pack: 'bts', version: 'v', bundle: 'b', source: 'BTS 2015', outcome: 'ct3', verdict: 'x', sentence: 'Solid nodule: CT at 3 months (BTS 2015).', text: 'Solid nodule: CT at 3 months (BTS 2015).', values: [], ...o });

describe('Recommendations section', () => {
	it('hidden while empty', async () => {
		render(RecommendationsSection, { lines: [], onEdit: vi.fn(), onDelete: vi.fn() });
		await expect.element(page.getByRole('region', { name: 'Recommendations' })).not.toBeInTheDocument();
	});

	it('one line per applied card, with its tags; stale lines say why', async () => {
		render(RecommendationsSection, { lines: [line(), line({ key: 'k2', text: 'Other (X).', stale: 'values', chosen_from: 3 }), line({ key: 'k3', text: 'Gone (Y).', stale: 'finding' })], onEdit: vi.fn(), onDelete: vi.fn() });
		const s = page.getByRole('region', { name: 'Recommendations' });
		await expect.element(s).toHaveTextContent('Solid nodule: CT at 3 months (BTS 2015).');
		await expect.element(s).toHaveTextContent('values changed');
		await expect.element(s).toHaveTextContent('chosen by you from 3');
		await expect.element(s).toHaveTextContent('finding removed');
	});

	it('edit saves the new text on Enter; delete removes the line', async () => {
		const onEdit = vi.fn();
		const onDelete = vi.fn();
		render(RecommendationsSection, { lines: [line()], onEdit, onDelete });
		await page.getByRole('button', { name: 'Edit recommendation 1' }).click();
		const box = page.getByRole('textbox', { name: 'Recommendation 1' });
		await box.fill('My wording.');
		await userEvent.keyboard('{Enter}');
		expect(onEdit).toHaveBeenCalledWith('k1', 'My wording.');
		await page.getByRole('button', { name: 'Delete recommendation 1' }).click();
		expect(onDelete).toHaveBeenCalledWith('k1');
	});
});
