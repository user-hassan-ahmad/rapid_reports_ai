import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import Legend from './Legend.svelte';
import { AI_MODE_STORAGE_KEY } from '../editor/aiMode';

const legend = () => document.querySelector<HTMLElement>('[data-testid="review-legend"]')!;
const group = () => legend().querySelector<HTMLElement>('[role="radiogroup"]')!;
const radios = () => [...group().querySelectorAll<HTMLButtonElement>('[role="radio"]')];
const checked = () => radios().find((r) => r.getAttribute('aria-checked') === 'true')?.dataset.rvMode;
const labels = () =>
	[...legend().querySelectorAll<HTMLElement>('[data-rv-label], .rv-ai-group')].map(
		(e) => e.querySelector('.rv-legend-label')!.textContent
	);
const swatches = () =>
	[...legend().querySelectorAll<HTMLElement>('[data-rv-breakdown] [data-rv-form]')].map((i) => i.dataset.rvForm);

beforeEach(() => localStorage.removeItem(AI_MODE_STORAGE_KEY));

describe('Legend', () => {
	it('labels: AI highlights only; the removed entry appears only while the report has a removal', async () => {
		render(Legend, {});
		await expect.element(page.getByText('AI highlights')).toBeInTheDocument();
		expect(labels()).toEqual(['AI highlights']);
		for (const gone of ['Dictated', 'Removed by you', 'Removed (contradicts'])
			expect(legend().textContent).not.toContain(gone);
	});

	it('showRemoved adds Removed (contradicts dictation) as a static label after the control', async () => {
		render(Legend, { showRemoved: true });
		await expect.element(page.getByText('Removed (contradicts dictation)')).toBeInTheDocument();
		expect(labels()).toEqual(['AI highlights', 'Removed (contradicts dictation)']);
		const el = legend().querySelector<HTMLElement>('[data-rv-label="removed"]')!;
		expect(el.tagName).toBe('SPAN');
		expect(el.closest('button')).toBeNull();
		expect(el.hasAttribute('aria-pressed')).toBe(false);
		expect(el.tabIndex).toBe(-1);
		expect(getComputedStyle(el).cursor).toBe('default');
	});

	it('is an accessible radiogroup Off · Key · All, Key by default', async () => {
		render(Legend, {});
		await expect.element(page.getByRole('radiogroup', { name: 'AI highlights: Off · Key · All' })).toBeInTheDocument();
		expect(radios().map((r) => r.textContent?.trim())).toEqual(['Off', 'Key', 'All']);
		expect(checked()).toBe('key');
		expect(radios().map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
	});

	it('the breakdown shows only what the mode draws: Key amber and violet, All adds green normals, Off none', async () => {
		render(Legend, {});
		await expect.element(page.getByRole('radio', { name: 'Key' })).toBeInTheDocument();
		const items = [...legend().querySelectorAll<HTMLElement>('[data-rv-breakdown] [data-rv-form]')];
		expect(items.map((i) => i.textContent?.trim())).toEqual(['Pertinent negatives', 'AI synthesis', 'Recommendations']);
		expect(items.map((i) => i.title)).toEqual([
			'Negatives the AI added because they bear on a dictated finding: worth a glance',
			"Conclusions or details the AI added that aren't in your dictation: check them",
			'Recommendations the AI added: untick in the recommendations list to remove'
		]);
		expect(new Set(items.map((i) => getComputedStyle(i.querySelector('.rv-swatch')!).backgroundColor)).size).toBe(3);
		await page.getByRole('radio', { name: 'All' }).click();
		expect(swatches()).toEqual(['negative', 'synthesis', 'recommendation', 'normal']);
		const normal = legend().querySelector<HTMLElement>('[data-rv-form="normal"]')!;
		expect(normal.textContent?.trim()).toBe('Normals');
		expect(normal.title).toBe('Normal findings you did not dictate, stated by the AI');
		await page.getByRole('radio', { name: 'Off' }).click();
		expect(swatches()).toEqual([]);
		expect(legend().querySelector('[data-rv-breakdown]')).toBeNull();
	});

	it('the breakdown collapses and expands', async () => {
		render(Legend, {});
		const more = page.getByRole('button', { name: /AI highlights breakdown/ });
		await expect.element(more).toHaveAttribute('aria-expanded', 'true');
		await more.click();
		await expect.element(more).toHaveAttribute('aria-expanded', 'false');
		expect(legend().querySelector('[data-rv-breakdown]')).toBeNull();
		await more.click();
		expect(legend().querySelector('[data-rv-breakdown]')).not.toBeNull();
	});

	it('the segmented control switches modes and calls onFilter with the right emphasis keys', async () => {
		const onFilter = vi.fn();
		render(Legend, { onFilter });
		await page.getByRole('radio', { name: 'All' }).click();
		expect(checked()).toBe('all');
		expect(onFilter).toHaveBeenLastCalledWith(['ai', 'normals']);
		await page.getByRole('radio', { name: 'Off' }).click();
		expect(checked()).toBe('off');
		expect(onFilter).toHaveBeenLastCalledWith([]);
		await page.getByRole('radio', { name: 'Key' }).click();
		expect(checked()).toBe('key');
		expect(onFilter).toHaveBeenLastCalledWith(['ai']);
		expect(onFilter).toHaveBeenCalledTimes(3);
	});

	it('arrow keys move the choice around the group', async () => {
		const onFilter = vi.fn();
		render(Legend, { onFilter });
		radios()[0].focus();
		await page.getByRole('radio', { name: 'Key' }).element().dispatchEvent(
			new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })
		);
		expect(checked()).toBe('all');
		expect(onFilter).toHaveBeenLastCalledWith(['ai', 'normals']);
	});

	it('showInserted adds "Added from suggestions" to the breakdown (Key and All, not Off)', async () => {
		render(Legend, { showInserted: true });
		const row = () => legend().querySelector<HTMLElement>('[data-rv-form="inserted"]');
		await expect.element(page.getByText('Added from suggestions')).toBeInTheDocument();
		expect(row()!.title).toBe('Text you added by ticking a suggestion');
		await page.getByRole('radio', { name: 'All' }).click();
		expect(row()).not.toBeNull();
		await page.getByRole('radio', { name: 'Off' }).click();
		expect(row()).toBeNull();
	});

	it('the suggestions swatch is absent while no suggestion is applied', async () => {
		render(Legend, {});
		await expect.element(page.getByRole('radio', { name: 'Key' })).toBeInTheDocument();
		expect(legend().textContent).not.toContain('Added from suggestions');
	});

	it('arrow keys follow the Off · Key · All order and wrap', async () => {
		render(Legend, {});
		const press = (name: string, key: string) =>
			page.getByRole('radio', { name }).element().dispatchEvent(
				new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
			);
		await press('Key', 'ArrowLeft');
		expect(checked()).toBe('off');
		await press('Off', 'ArrowLeft');
		expect(checked()).toBe('all');
		await press('All', 'ArrowRight');
		expect(checked()).toBe('off');
	});

	it('remembers the mode (localStorage rv_ai_mode) and restores it on load', async () => {
		const first = render(Legend, {});
		await page.getByRole('radio', { name: 'Off' }).click();
		expect(localStorage.getItem(AI_MODE_STORAGE_KEY)).toBe('off');
		first.unmount();
		render(Legend, {});
		await expect.element(page.getByRole('radio', { name: 'Off' })).toHaveAttribute('aria-checked', 'true');
		expect(legend().querySelector('[data-rv-breakdown]')).toBeNull();
	});

	it('a blocked or junk store falls back to Key and never throws', async () => {
		localStorage.setItem(AI_MODE_STORAGE_KEY, 'bogus');
		render(Legend, {});
		await expect.element(page.getByRole('radio', { name: 'Key' })).toHaveAttribute('aria-checked', 'true');
	});

	it('wraps onto new lines when narrow, never scrolling sideways', async () => {
		const host = document.createElement('div');
		host.style.width = '220px';
		document.body.append(host);
		render(Legend, { target: host, props: { showRemoved: true } });
		await expect.element(page.getByText('AI highlights')).toBeInTheDocument();
		const parts = [...legend().querySelectorAll<HTMLElement>('[data-rv-label], button, [data-rv-form]')];
		const tops = new Set(parts.map((b) => Math.round(b.getBoundingClientRect().top)));
		expect(tops.size).toBeGreaterThan(1);
		expect(legend().scrollWidth).toBeLessThanOrEqual(legend().clientWidth + 1);
		for (const b of parts)
			expect(b.getBoundingClientRect().right).toBeLessThanOrEqual(host.getBoundingClientRect().right + 1);
		host.remove();
	});
});
