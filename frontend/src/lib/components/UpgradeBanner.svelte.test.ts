import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import type { Writable } from 'svelte/store';

// The app-wide templates store, replaced by a plain writable the tests set
vi.mock('$lib/stores/templates', async () => {
	const { writable } = await import('svelte/store');
	return { templatesStore: writable({ templates: [], loading: false, error: null }) };
});

import { templatesStore } from '$lib/stores/templates';
import UpgradeBanner from './UpgradeBanner.svelte';

const data = templatesStore as unknown as Writable<{ templates: unknown[]; loading: boolean; error: null }>;
const ownsOne = () => data.set({ templates: [{ id: 't1' }], loading: false, error: null });
const ownsNone = () => data.set({ templates: [], loading: false, error: null });

describe('UpgradeBanner', () => {
	beforeEach(() => {
		localStorage.clear();
		ownsNone();
	});

	it('shows the upgrade message to a template owner until dismissed', async () => {
		ownsOne();
		render(UpgradeBanner);
		await expect
			.element(page.getByText('Your templates have been upgraded to the new workflow.', { exact: false }))
			.toBeInTheDocument();
		await page.getByRole('button', { name: 'Dismiss' }).click();
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
		expect(localStorage.getItem('rr_banner_template_upgrade_2026_10')).toBe('1');
	});

	it('renders nothing once dismissed before', async () => {
		ownsOne();
		localStorage.setItem('rr_banner_template_upgrade_2026_10', '1');
		render(UpgradeBanner);
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	});

	it('renders nothing for a user with no templates (or before they load)', async () => {
		render(UpgradeBanner);
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	});
});
