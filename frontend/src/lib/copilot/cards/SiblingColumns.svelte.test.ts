// SiblingColumns (Task A5, plan Q5). SYNTHETIC fixtures.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import SiblingColumns from './SiblingColumns.svelte';
import { card, preview, result } from './fixtures';
import { columnRef } from './format';
import type { CardView } from './view';

const c = card({ siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS guideline 2015' });
const view = (over: Partial<CardView> = {}): CardView => ({
	open: true,
	loading: false,
	error: null,
	result: null,
	columns: {
		[c.key]: { loading: false, error: null, result: result(c, preview()) },
		[bts.key]: { loading: false, error: 'timeout', result: null }
	},
	...over
});
const base = (over: Record<string, unknown> = {}) => ({ card: c, view: view(), onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn(), ...over });

describe('SiblingColumns', () => {
	it('closed: the head names both guidelines from sibling_names before any column opens', async () => {
		render(SiblingColumns, base({ view: { open: false, loading: false, error: null, result: null } }));
		await expect.element(page.getByText('Fleischner 2017 · BTS 2015')).toBeInTheDocument();
	});

	it('a column title expands that column to full width and back; a failed column retries by its ref', async () => {
		const p = base();
		render(SiblingColumns, { ...p, layout: 'columns' });
		await expect.element(page.getByRole('button', { name: 'Fleischner 2017', exact: true })).toBeInTheDocument();
		expect(document.querySelectorAll('.cp-col').length).toBe(2);
		await page.getByRole('button', { name: 'Fleischner 2017', exact: true }).click();
		expect(document.querySelectorAll('.cp-col').length).toBe(1);
		await expect.element(page.getByRole('button', { name: 'Fleischner 2017', exact: true })).toHaveAttribute('aria-pressed', 'true');
		await page.getByRole('button', { name: 'Fleischner 2017', exact: true }).click();
		expect(document.querySelectorAll('.cp-col').length).toBe(2);
		await page.getByRole('button', { name: 'Retry' }).click();
		expect(p.onRetry).toHaveBeenCalledWith(columnRef(c, bts.key));
	});

	it('stacked: both guidelines at full width, each with its own name and state line, nothing chosen', async () => {
		const v = view();
		v.columns![bts.key] = {
			loading: false,
			error: null,
			result: result(bts, preview({ state: 'check_first', proposal: null, missing: ['e'], asks: [{ input: 'e', label: 'Known cancer', role: 'eligibility' }] }))
		};
		render(SiblingColumns, { ...base({ view: v }), layout: 'stacked' });
		await expect.element(page.getByText('BTS guideline 2015', { exact: true })).toBeInTheDocument();
		expect(document.querySelectorAll('[role="tab"]').length).toBe(0);
		expect(document.body.textContent).not.toContain('Choose a guideline');
		const cols = [...document.querySelectorAll('.cp-col--stacked')];
		expect(cols).toHaveLength(2);
		expect(cols.map((c) => c.querySelector('.cp-col-name')!.textContent)).toEqual(['Fleischner 2017', 'BTS guideline 2015']);
		expect(cols[0].querySelector('.cp-col-line')!.textContent).toContain('applies');
		expect(cols[1].querySelector('.cp-col-line')!.textContent).toContain('⚠ 1 check assumed');
		expect(document.querySelectorAll('[aria-pressed="true"], [aria-selected="true"]').length).toBe(0);
		// full bodies, not the outcome-only column
		await expect.element(page.getByText('Follow-up as per the guideline table.')).toBeInTheDocument();
		await expect.element(page.getByText('Guideline (2017), p. 3')).toBeInTheDocument();
	});

	it('auto stacks unless each column gets ~200 px, and returns to columns when wide enough', async () => {
		const host = document.createElement('div');
		host.style.width = '394px'; // the 420 px Copilot rail's list width: two columns would be ~180 px
		document.body.appendChild(host);
		render(SiblingColumns, { target: host, props: base() });
		await expect.poll(() => document.querySelectorAll('.cp-col--stacked').length).toBe(2);
		host.style.width = '480px'; // wide enough for two readable columns
		await expect.element(page.getByRole('button', { name: 'BTS 2015', exact: true })).toBeInTheDocument();
		await expect.poll(() => document.querySelectorAll('.cp-col--stacked').length).toBe(0);
		host.remove();
	});
});
