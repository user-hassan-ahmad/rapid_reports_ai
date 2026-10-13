import { describe, expect, it, beforeEach } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import UpgradeBanner from './UpgradeBanner.svelte';

describe('UpgradeBanner', () => {
	beforeEach(() => localStorage.clear());

	it('shows the upgrade message until dismissed', async () => {
		render(UpgradeBanner);
		await expect
			.element(page.getByText('Your templates have been upgraded to the new workflow.', { exact: false }))
			.toBeInTheDocument();
		await page.getByRole('button', { name: 'Dismiss' }).click();
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
		expect(localStorage.getItem('rr_banner_template_upgrade_2026_10')).toBe('1');
	});

	it('renders nothing once dismissed before', async () => {
		localStorage.setItem('rr_banner_template_upgrade_2026_10', '1');
		render(UpgradeBanner);
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	});
});
