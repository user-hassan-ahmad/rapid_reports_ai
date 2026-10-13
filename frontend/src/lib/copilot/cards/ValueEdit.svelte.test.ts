// Inline edit (Slice B2): ValueRow's "Change", ValueEdit's menu and text box. SYNTHETIC values.
import { describe, expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from '@vitest/browser/context';
import ValueRow from './ValueRow.svelte';
import type { ValueRow as Row } from './format';

const row = (o: Partial<Row>): Row => ({ input: 'appearance', label: 'Appearance', value: 'Homogeneous', quote: '', byExam: false, state: 'read', why: [], options: ['Homogeneous', 'Heterogeneous', 'Not stated'], ...o });
const show = (r: Row, onEdit: ((i: string, v: string) => void) | null = vi.fn()) => {
	const host = document.createElement('ul');
	document.body.appendChild(host);
	render(ValueRow, { target: host, props: { row: r, uid: 't', onEdit } });
	return onEdit;
};

describe('inline edit', () => {
	it('a value with options: "Change" opens the menu (with "Not stated"); choosing saves', async () => {
		const onEdit = show(row({}));
		await page.getByRole('button', { name: 'Change Appearance' }).click();
		const select = page.getByRole('combobox', { name: 'Answer for Appearance' });
		await expect.element(select).toHaveFocus();
		expect([...(select.element() as HTMLSelectElement).options].map((o) => o.value)).toEqual(['Homogeneous', 'Heterogeneous', 'Not stated']);
		await select.selectOptions('Heterogeneous');
		expect(onEdit).toHaveBeenCalledWith('appearance', 'Heterogeneous');
		await expect.element(page.getByRole('combobox')).not.toBeInTheDocument();
	});

	it('a free value: a text box that saves on Enter; Escape cancels without saving', async () => {
		const onEdit = show(row({ input: 'size', label: 'Size', value: '2.2 cm', options: [] }));
		await page.getByRole('button', { name: 'Change Size' }).click();
		const box = page.getByRole('textbox', { name: 'Answer for Size' });
		await box.fill('2.4 cm');
		await userEvent.keyboard('{Escape}');
		expect(onEdit).not.toHaveBeenCalled();
		await page.getByRole('button', { name: 'Change Size' }).click();
		await page.getByRole('textbox', { name: 'Answer for Size' }).fill('2.4 cm');
		await userEvent.keyboard('{Enter}');
		expect(onEdit).toHaveBeenCalledWith('size', '2.4 cm');
	});

	it('N/A rows and rows without onEdit have no "Change"', async () => {
		show(row({ state: 'not_applicable', value: '' }));
		show(row({ input: 'x', label: 'Other' }), null);
		await expect.element(page.getByText('N/A')).toBeInTheDocument();
		expect(document.querySelectorAll('.cp-val-change')).toHaveLength(0);
	});

	it('an edited value is marked "changed", an answered one "answered"', async () => {
		show(row({ state: 'edited', value: 'Heterogeneous' }));
		show(row({ input: 'age', label: 'Age', state: 'answered', value: '45', options: [] }));
		await expect.element(page.getByText('changed')).toBeInTheDocument();
		await expect.element(page.getByText('answered')).toBeInTheDocument();
	});
});
