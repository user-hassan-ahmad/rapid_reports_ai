import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import ValueChips from './ValueChips.svelte';
import type { ValueChip } from './types';

const VALUES: ValueChip[] = [
	{ item: 'LVEF', state: 'filled', value: '45%', quote: 'LVEF 45%.' },
	{ item: 'LVEDVi', state: 'entered', value: '98', quote: null },
	{ item: 'RVEF', state: 'na', value: null, quote: null },
	{ item: 'LV mass index', state: 'open', value: null, quote: null },
	{ item: 'Conus level', state: 'check', value: null, quote: null },
	{ item: 'Aortic flow', state: 'filling', value: null, quote: null }
];
const props = () => ({ values: VALUES, onEnter: vi.fn(), onNa: vi.fn(), onRestNa: vi.fn(), onKeep: vi.fn() });

describe('ValueChips', () => {
	it('one line of chips, each with its state; a filled chip shows its source on hover', async () => {
		render(ValueChips, props());
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).toHaveAttribute('data-state', 'filled');
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).toHaveAttribute('title', 'From the dictation: "LVEF 45%."');
		await expect.element(page.getByRole('button', { name: 'LVEDVi 98' })).toHaveAttribute('data-state', 'entered');
		await expect.element(page.getByRole('button', { name: 'RVEF N/A' })).toHaveAttribute('data-state', 'na');
		await expect.element(page.getByRole('button', { name: 'LV mass index —' })).toHaveAttribute('data-state', 'open');
		await expect.element(page.getByRole('button', { name: 'Conus level stated?' })).toHaveAttribute('data-state', 'check');
		await expect.element(page.getByRole('button', { name: 'Aortic flow …' })).toHaveAttribute('data-state', 'filling');
	});

	it('click an open chip to type its value; Enter saves it', async () => {
		const p = props();
		render(ValueChips, p);
		await page.getByRole('button', { name: 'LV mass index —' }).click();
		await page.getByLabelText('Value for LV mass index').fill('60 g/m²');
		await userEvent.keyboard('{Enter}');
		expect(p.onEnter).toHaveBeenCalledWith('LV mass index', '60 g/m²');
	});

	it('a "stated?" chip can be kept as stated; N/A marks one chip; Escape cancels', async () => {
		const p = props();
		render(ValueChips, p);
		await page.getByRole('button', { name: 'Conus level stated?' }).click();
		await page.getByRole('button', { name: 'Stated ✓' }).click();
		expect(p.onKeep).toHaveBeenCalledWith('Conus level');
		await page.getByRole('button', { name: 'LV mass index —' }).click();
		await expect.element(page.getByRole('button', { name: 'Stated ✓' })).not.toBeInTheDocument();   // only for "stated?"
		await page.getByRole('button', { name: 'N/A', exact: true }).click();
		expect(p.onNa).toHaveBeenCalledWith('LV mass index');
		await page.getByRole('button', { name: 'LVEF 45%' }).click();
		await expect.element(page.getByLabelText('Value for LVEF')).toHaveValue('45%');
		await userEvent.keyboard('{Escape}');
		expect(p.onEnter).not.toHaveBeenCalled();
	});

	it('Mark rest N/A shows only while a chip is open; the walkthrough\'s current chip is ringed', async () => {
		const p = props();
		const r = render(ValueChips, { ...p, current: 'value:LV mass index' });
		await expect.element(page.getByRole('button', { name: 'LV mass index —' })).toHaveClass('ring-2');
		await expect.element(page.getByRole('button', { name: 'LVEF 45%' })).not.toHaveClass('ring-2');
		await page.getByRole('button', { name: 'Mark rest N/A' }).click();
		expect(p.onRestNa).toHaveBeenCalled();
		r.rerender({ ...p, values: VALUES.map((v) => (v.state === 'open' ? { ...v, state: 'na' as const } : v)) });
		await expect.element(page.getByRole('button', { name: 'Mark rest N/A' })).not.toBeInTheDocument();
	});

	it('renders nothing without required values', async () => {
		render(ValueChips, { ...props(), values: [] });
		await expect.element(page.getByTestId('value-cluster')).not.toBeInTheDocument();
	});
});
