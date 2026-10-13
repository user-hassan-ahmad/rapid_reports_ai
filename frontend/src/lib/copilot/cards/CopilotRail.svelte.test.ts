// CopilotRail (Task A5): RailFrame + one Guidelines tab + CopilotCards. SYNTHETIC fixtures.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import CopilotRail from './CopilotRail.svelte';
import { card } from './fixtures';

const f = { id: 'u1', unitId: 1, text: 'Solid pulmonary nodule', region: 'LUNGS' };
const props = (layout: 'wide' | 'narrow') => ({
	layout,
	groups: [{ finding: f, cards: [card({ finding: f.text }), card({ key: 'bta-x', name: 'BTA U grading', needs_modality: 'US', finding: f.text })] }],
	views: {},
	matching: false,
	matchFailed: false,
	otherState: 'idle' as const,
	onOpen: vi.fn(),
	onClose: vi.fn(),
	onRetry: vi.fn(),
	onRetryMatch: vi.fn(),
	onOther: vi.fn()
});

describe('CopilotRail', () => {
	it('wide: one "Guidelines" tab, selected, over the cards', async () => {
		render(CopilotRail, props('wide'));
		await expect.element(page.getByRole('tab', { name: 'Guidelines' })).toHaveAttribute('aria-selected', 'true');
		expect(page.getByRole('tab').elements().length).toBe(1);
		await expect.element(page.getByRole('tabpanel', { name: 'Guidelines' })).toBeInTheDocument();
		await expect.element(page.getByText('Fleischner 2017')).toBeInTheDocument();
	});

	it('narrow: the strip reads "<n> guidelines" and opens the overlay', async () => {
		render(CopilotRail, props('narrow'));
		const strip = page.getByRole('button', { name: 'Copilot: 2 guidelines' });
		await expect.element(strip).toBeInTheDocument();
		await strip.click();
		await expect.element(page.getByRole('dialog', { name: 'Copilot' })).toBeInTheDocument();
		await expect.element(page.getByText('Fleischner 2017')).toBeInTheDocument();
	});
});
