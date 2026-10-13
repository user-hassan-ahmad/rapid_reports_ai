import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import { createRawSnippet } from 'svelte';
import RailFrame from './RailFrame.svelte';

type Ctx = { narrow: boolean };
// SYNTHETIC head / body only.
const head = createRawSnippet((ctx: () => Ctx) => ({
	render: () => `<div class="rv-head">Head${ctx().narrow ? ' (narrow)' : ''}</div>`
}));
const body = createRawSnippet(() => ({ render: () => '<div class="rv-body">Body</div>' }));
const frame = () => document.querySelector<HTMLElement>('[data-testid="test-rail"]')!;
const base = { ariaLabel: 'Guidelines', testid: 'test-rail', stripLabel: 'guidelines', stripCount: 3, head, body };

describe('RailFrame', () => {
	it('wide: renders the head and body in a 340 px aside with the rail tokens', async () => {
		render(RailFrame, { ...base, layout: 'wide' });
		await expect.element(page.getByText('Head', { exact: true })).toBeInTheDocument();
		await expect.element(page.getByText('Body')).toBeInTheDocument();
		expect(frame().tagName).toBe('ASIDE');
		expect(frame().getAttribute('aria-label')).toBe('Guidelines');
		expect(frame().dataset.theme).toBe('dark');
		expect(frame().querySelector('.rv-strip')).toBeNull();
		const cs = getComputedStyle(frame());
		expect(cs.width).toBe('340px');
		expect(cs.getPropertyValue('--rv-accent').trim()).toBe('#9333ea');
	});

	it('narrow: a strip with the count; it opens the overlay with the head and body, × closes it', async () => {
		render(RailFrame, { ...base, layout: 'narrow' });
		const strip = page.getByRole('button', { name: 'Guidelines: 3 guidelines' });
		await expect.element(strip).toBeInTheDocument();
		expect(frame().classList.contains('rv-narrow')).toBe(true);
		expect(document.body.textContent).not.toContain('Body');
		await strip.click();
		await expect.element(page.getByRole('dialog', { name: 'Guidelines' })).toBeInTheDocument();
		await expect.element(page.getByText('Head (narrow)')).toBeInTheDocument();
		await expect.element(page.getByText('Body')).toBeInTheDocument();
		expect(strip.element().getAttribute('aria-expanded')).toBe('true');
		await page.getByRole('button', { name: 'Close guidelines' }).click();
		await expect.element(page.getByRole('dialog')).not.toBeInTheDocument();
	});

	it('expanded widens the wide rail only', async () => {
		render(RailFrame, { ...base, layout: 'wide', expanded: true });
		await expect.element(page.getByText('Body')).toBeInTheDocument();
		expect(getComputedStyle(frame()).width).toBe('560px');
	});
});
