import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import Legend from './Legend.svelte';

const legend = () => document.querySelector<HTMLElement>('[data-testid="review-legend"]')!;
const pills = () => [...legend().querySelectorAll<HTMLButtonElement>('button[data-rv-filter]')];

describe('Legend', () => {
	it('labels: Dictated · Removed by you | AI-generated · Recommendations · Removed (contradicts dictation)', async () => {
		render(Legend, {});
		await expect.element(page.getByText('AI-generated')).toBeInTheDocument();
		expect(pills().map((b) => b.querySelector('.rv-legend-label')!.textContent)).toEqual([
			'Dictated',
			'Removed by you',
			'AI-generated',
			'Recommendations',
			'Removed (contradicts dictation)'
		]);
		expect(legend().textContent).not.toContain('(AI)');
		// the separator sits between the radiologist's own and the AI's
		const sep = legend().querySelector('.rv-legend-sep')!;
		expect(pills()[1].compareDocumentPosition(sep) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(sep.compareDocumentPosition(pills()[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		// the AI-generated pill carries the layer's three colours; its title names them
		expect(pills()[2].querySelectorAll('.rv-swatches i').length).toBe(3);
		expect(pills()[2].title).toMatch(/assumed normal.*check.*synthesis/i);
	});

	it('defaults: AI-generated off, Recommendations on', async () => {
		render(Legend, {});
		await expect.element(page.getByRole('button', { name: /AI-generated/ })).toHaveAttribute('aria-pressed', 'false');
		await expect
			.element(page.getByRole('button', { name: /Recommendations/ }))
			.toHaveAttribute('aria-pressed', 'true');
	});

	it('pills are toggles: several may be on, a second click turns one off', async () => {
		const onFilter = vi.fn();
		render(Legend, { onFilter });
		const ai = page.getByRole('button', { name: /AI-generated/ });
		await ai.click();
		await expect.element(ai).toHaveAttribute('aria-pressed', 'true');
		expect(onFilter).toHaveBeenLastCalledWith(['ai', 'rec']);
		await page.getByRole('button', { name: /Recommendations/ }).click();
		expect(onFilter).toHaveBeenLastCalledWith(['ai']);
		await ai.click();
		expect(onFilter).toHaveBeenLastCalledWith([]);
	});

	it('wraps onto new lines when narrow, never scrolling sideways', async () => {
		const host = document.createElement('div');
		host.style.width = '220px';
		document.body.append(host);
		render(Legend, { target: host });
		await expect.element(page.getByText('AI-generated')).toBeInTheDocument();
		const tops = new Set(pills().map((b) => Math.round(b.getBoundingClientRect().top)));
		expect(tops.size).toBeGreaterThan(1);
		expect(legend().scrollWidth).toBeLessThanOrEqual(legend().clientWidth + 1);
		for (const b of pills())
			expect(b.getBoundingClientRect().right).toBeLessThanOrEqual(host.getBoundingClientRect().right + 1);
		host.remove();
	});
});
