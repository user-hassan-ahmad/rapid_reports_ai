import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import Legend from './Legend.svelte';

const legend = () => document.querySelector<HTMLElement>('[data-testid="review-legend"]')!;
const toggles = () => [...legend().querySelectorAll<HTMLButtonElement>('button[data-rv-filter]')];
const labels = () =>
	[...legend().querySelectorAll<HTMLElement>('[data-rv-label], button[data-rv-filter]')].map(
		(e) => e.querySelector('.rv-legend-label')!.textContent
	);

describe('Legend', () => {
	it('labels: Dictated · Removed by you | AI-generated · Removed (contradicts dictation); no Recommendations pill', async () => {
		render(Legend, {});
		await expect.element(page.getByText('AI-generated')).toBeInTheDocument();
		expect(labels()).toEqual(['Dictated', 'Removed by you', 'AI-generated', 'Removed (contradicts dictation)']);
		expect(legend().textContent).not.toContain('Recommendations');
		const sep = legend().querySelector('.rv-legend-sep')!;
		const removedByYou = legend().querySelector('[data-rv-label="excluded"]')!;
		expect(removedByYou.compareDocumentPosition(sep) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(sep.compareDocumentPosition(toggles()[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});

	it('only AI-generated is a toggle; Dictated and the removed entries are static labels', async () => {
		render(Legend, {});
		await expect.element(page.getByText('Dictated')).toBeInTheDocument();
		expect(toggles().map((b) => b.dataset.rvFilter)).toEqual(['ai']);
		for (const key of ['dictated', 'excluded', 'removed']) {
			const el = legend().querySelector<HTMLElement>(`[data-rv-label="${key}"]`)!;
			expect(el.tagName, key).toBe('SPAN');
			expect(el.closest('button'), key).toBeNull();
			expect(el.hasAttribute('aria-pressed'), key).toBe(false);
			expect(el.tabIndex, key).toBe(-1);
			expect(getComputedStyle(el).cursor, key).toBe('default');
		}
	});

	it('AI-generated is on by default and its breakdown is shown inline: Normals, Bears on your finding, Synthesis', async () => {
		render(Legend, {});
		await expect.element(page.getByRole('button', { name: /^AI-generated$/ })).toHaveAttribute('aria-pressed', 'true');
		const items = [...legend().querySelectorAll<HTMLElement>('[data-rv-breakdown] [data-rv-form]')];
		expect(items.map((i) => i.textContent?.trim())).toEqual(['Normals', 'Bears on your finding', 'Synthesis']);
		expect(items.map((i) => i.dataset.rvForm)).toEqual(['normal', 'negative', 'synthesis']);
		const sw = items.map((i) => getComputedStyle(i.querySelector('.rv-swatch')!).backgroundColor);
		expect(new Set(sw).size).toBe(3); // green, amber, violet swatches
		expect(legend().textContent).not.toContain('Needs checking');
	});

	it('the breakdown collapses and expands', async () => {
		render(Legend, {});
		const more = page.getByRole('button', { name: /AI-generated breakdown/ });
		await expect.element(more).toHaveAttribute('aria-expanded', 'true');
		await more.click();
		await expect.element(more).toHaveAttribute('aria-expanded', 'false');
		expect(legend().querySelector('[data-rv-breakdown]')).toBeNull();
		await more.click();
		expect(legend().querySelector('[data-rv-breakdown]')).not.toBeNull();
	});

	it('the AI-generated toggle turns the layer off and on', async () => {
		const onFilter = vi.fn();
		render(Legend, { onFilter });
		const ai = page.getByRole('button', { name: /^AI-generated$/ });
		await ai.click();
		await expect.element(ai).toHaveAttribute('aria-pressed', 'false');
		expect(onFilter).toHaveBeenLastCalledWith([]);
		await ai.click();
		expect(onFilter).toHaveBeenLastCalledWith(['ai']);
	});

	it('wraps onto new lines when narrow, never scrolling sideways', async () => {
		const host = document.createElement('div');
		host.style.width = '220px';
		document.body.append(host);
		render(Legend, { target: host });
		await expect.element(page.getByText('AI-generated')).toBeInTheDocument();
		const parts = [...legend().querySelectorAll<HTMLElement>('[data-rv-label], button, [data-rv-form]')];
		const tops = new Set(parts.map((b) => Math.round(b.getBoundingClientRect().top)));
		expect(tops.size).toBeGreaterThan(1);
		expect(legend().scrollWidth).toBeLessThanOrEqual(legend().clientWidth + 1);
		for (const b of parts)
			expect(b.getBoundingClientRect().right).toBeLessThanOrEqual(host.getBoundingClientRect().right + 1);
		host.remove();
	});
});
