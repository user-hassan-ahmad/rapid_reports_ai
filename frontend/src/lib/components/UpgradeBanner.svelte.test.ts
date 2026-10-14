import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import type { Writable } from 'svelte/store';

// The app-wide templates and settings stores, replaced by plain writables the tests set
vi.mock('$lib/stores/templates', async () => {
	const { writable } = await import('svelte/store');
	return { templatesStore: writable({ templates: [], loading: false, error: null }) };
});
vi.mock('$lib/stores/settings', async () => {
	const { writable } = await import('svelte/store');
	const data = writable<{ settings: Record<string, unknown> | null; loading: boolean; error: null }>({ settings: null, loading: false, error: null });
	return {
		settingsStore: {
			subscribe: data.subscribe,
			set: data.set,
			loadSettings: vi.fn(async () => {}),
			updateSettings: vi.fn(async (u: Record<string, unknown>) => {
				data.update((s) => ({ ...s, settings: { ...(s.settings ?? {}), ...u } }));
				return { success: true };
			})
		}
	};
});

import { templatesStore } from '$lib/stores/templates';
import { settingsStore } from '$lib/stores/settings';
import UpgradeBanner from './UpgradeBanner.svelte';

const data = templatesStore as unknown as Writable<{ templates: unknown[]; loading: boolean; error: null }>;
const settings = settingsStore as unknown as Writable<{ settings: Record<string, unknown> | null; loading: boolean; error: null }> & {
	updateSettings: ReturnType<typeof vi.fn>;
};
const tpl = (id: string, name: string, converted: boolean) => ({ id, name, template_config: converted ? { converted_at: '2026-10-14T00:00:00Z' } : {} });
const own = (...t: unknown[]) => data.set({ templates: t, loading: false, error: null });
const dismissed = (v: boolean) => settings.set({ settings: { success: true, banner_template_upgrade_dismissed: v }, loading: false, error: null });

describe('UpgradeBanner (converted templates only, dismissed on the server)', () => {
	beforeEach(() => {
		localStorage.clear();
		own();
		dismissed(false);
		settings.updateSettings.mockClear();
	});

	it('hidden for an owner with no converted template', async () => {
		own(tpl('t1', 'Knee MRI', false));
		render(UpgradeBanner);
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	});

	it('names every converted template and dismisses on the server', async () => {
		own(tpl('t1', 'Knee MRI', true), tpl('t2', 'CT Chest', true), tpl('t3', 'Untouched', false));
		render(UpgradeBanner);
		const banner = page.getByRole('status');
		await expect.element(banner).toHaveTextContent(/Knee MRI/);
		await expect.element(banner).toHaveTextContent(/CT Chest/);
		await expect.element(banner).not.toHaveTextContent(/Untouched/);
		await expect.element(banner).toHaveTextContent(/create a fresh one/i);
		await page.getByRole('button', { name: 'Dismiss' }).click();
		expect(settings.updateSettings).toHaveBeenCalledWith({ banner_template_upgrade_dismissed: true });
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
		expect(Object.keys(localStorage).filter((k) => k.includes('banner'))).toEqual([]); // nothing per browser
	});

	it('hidden once the server says dismissed', async () => {
		own(tpl('t1', 'Knee MRI', true));
		dismissed(true);
		render(UpgradeBanner);
		await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	});
});
