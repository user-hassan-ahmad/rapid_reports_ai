// ValueRow (Slice B1, §7.5): one style per value state. SYNTHETIC values.
import { describe, expect, it } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import ValueRow from './ValueRow.svelte';
import '$lib/rail/rail.css';
import type { ValueRow as Row } from './format';

const row = (o: Partial<Row>): Row => ({ input: 'size', label: 'Size', value: '7 mm', quote: '', byExam: false, state: 'read', why: [], ...o });
const li = () => document.querySelector('li.cp-val') as HTMLElement;
// inside a rail, so the --rv-* tokens (the amber-soft highlight) resolve
const show = (r: Row) => {
	const host = document.createElement('ul');
	host.className = 'rv-rail';
	document.body.appendChild(host);
	return render(ValueRow, { target: host, props: { row: r, uid: 't' } });
};

describe('ValueRow', () => {
	it('read: plain value, no highlight; the quote is its description and shows on focus', async () => {
		show(row({ quote: '7 mm solid nodule' }));
		await expect.element(page.getByText('7 mm', { exact: true })).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')).toBeNull();
		expect(li().querySelector('.cp-chip')).toBeNull();
		expect(document.getElementById(li().getAttribute('aria-describedby')!)!.textContent!.trim()).toBe('“7 mm solid nodule”');
		await expect.element(page.getByText('“7 mm solid nodule”')).not.toBeVisible();
		li().focus();
		await expect.element(page.getByText('“7 mm solid nodule”')).toBeVisible();
	});

	it('read with no quote is not a tab stop', async () => {
		show(row({}));
		await expect.element(page.getByText('7 mm', { exact: true })).toBeInTheDocument();
		expect(li().hasAttribute('tabindex')).toBe(false);
	});

	it('prefilled: amber-soft value, a "pre-filled" chip, and the reasons in the description', async () => {
		show(row({ state: 'prefilled', quote: '7 mm solid nodule', why: ['another number in this finding'] }));
		await expect.element(page.getByText('pre-filled', { exact: true })).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')!.textContent).toBe('7 mm');
		expect(getComputedStyle(li().querySelector('.cp-prefill')!).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
		expect(page.getByText('pre-filled', { exact: true }).element().getAttribute('title')).toBe('another number in this finding');
		const desc = document.getElementById(li().getAttribute('aria-describedby')!)!.textContent!;
		expect(desc).toContain('“7 mm solid nodule”');
		expect(desc).toContain('Pre-filled: another number in this finding');
	});

	it('an exam preset: "set by the exam", no highlight and no "pre-filled" chip', async () => {
		show(row({ state: 'prefilled', byExam: true, value: 'unenhanced CT', why: ['set by the exam'] }));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')).toBeNull();
		expect(document.body.textContent).not.toContain('pre-filled');
		expect(li().hasAttribute('tabindex')).toBe(false);
	});

	it('answered and edited render as set; not_applicable reads "N/A"', async () => {
		const r = show(row({ state: 'answered', value: 'Yes' }));
		await expect.element(page.getByText('Yes', { exact: true })).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')).toBeNull();
		await r.rerender({ row: row({ state: 'edited', value: '9 mm' }) });
		await expect.element(page.getByText('9 mm', { exact: true })).toBeInTheDocument();
		await r.rerender({ row: row({ state: 'not_applicable', value: '' }) });
		await expect.element(page.getByText('N/A')).toBeInTheDocument();
		expect(li().dataset.state).toBe('not_applicable');
	});
});
