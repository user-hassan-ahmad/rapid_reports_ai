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

	it('stacked (narrow): a switcher with neither chosen, then the chosen column only', async () => {
		render(SiblingColumns, { ...base(), layout: 'stacked' });
		const tabs = page.getByRole('tab');
		await expect.element(tabs.first()).toBeInTheDocument();
		expect(tabs.elements().map((t) => t.getAttribute('aria-selected'))).toEqual(['false', 'false']);
		await expect.element(page.getByText('Choose a guideline to read')).toBeInTheDocument();
		expect(document.querySelectorAll('.cp-col').length).toBe(0);
		await page.getByRole('tab', { name: 'BTS 2015' }).click();
		expect(document.querySelectorAll('.cp-col').length).toBe(1);
		await expect.element(page.getByText("Couldn't open")).toBeInTheDocument();
	});

	it('auto stacks below 300 px of card width and returns to columns above it', async () => {
		const host = document.createElement('div');
		host.style.width = '260px';
		document.body.appendChild(host);
		render(SiblingColumns, { target: host, props: base() });
		await expect.element(page.getByRole('tab').first()).toBeInTheDocument();
		host.style.width = '316px'; // the 340 px rail's list width: side by side
		await expect.element(page.getByRole('button', { name: 'BTS 2015', exact: true })).toBeInTheDocument();
		await expect.poll(() => document.querySelectorAll('[role="tab"]').length).toBe(0);
		host.remove();
	});
});
