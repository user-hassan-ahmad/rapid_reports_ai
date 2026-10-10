import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import HybridStackView from './HybridStackView.svelte';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false, ...extra
});

describe('HybridStackView', () => {
	it('renders groups, structure labels and just-dictated lines; a click selects the sentence', async () => {
		const onSelect = vi.fn();
		render(HybridStackView, {
			units: [u(0, 'A liver cyst.', 'Liver', { structure: 'liver' }), u(1, 'Just said.', null)],
			groups: ['Technique', 'Liver', 'General', 'Conclusion'],
			onSelect,
			onMove: vi.fn()
		});
		await expect.element(page.getByRole('heading', { name: 'Liver' })).toBeInTheDocument();
		await expect.element(page.getByText('· liver')).toBeInTheDocument();
		await expect.element(page.getByText('Just dictated')).toBeInTheDocument();
		await page.getByText('A liver cyst.').click();
		expect(onSelect).toHaveBeenCalledWith(0);
	});
});
