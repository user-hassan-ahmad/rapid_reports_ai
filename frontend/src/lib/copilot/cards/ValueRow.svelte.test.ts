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
		expect(li().querySelector('.cp-chip')!.textContent).toBe('read'); // its provenance badge
		expect(document.getElementById(li().getAttribute('aria-describedby')!)!.textContent!.trim()).toBe('“7 mm solid nodule”');
		await expect.element(page.getByText('“7 mm solid nodule”')).not.toBeVisible();
		li().focus();
		await expect.element(page.getByText('“7 mm solid nodule”')).toBeVisible();
	});

	it('an option id is shown as words, never raw', async () => {
		show(row({ input: 'growth', label: 'Growth', value: 'diameter_clear_growth', options: ['diameter_stable', 'diameter_clear_growth'] }));
		await expect.element(page.getByText('Diameter clear growth', { exact: true })).toBeInTheDocument();
		expect(li().textContent).not.toContain('diameter_clear_growth');
	});

	it('read with no quote is not a tab stop', async () => {
		show(row({}));
		await expect.element(page.getByText('7 mm', { exact: true })).toBeInTheDocument();
		expect(li().hasAttribute('tabindex')).toBe(false);
	});

	it('prefilled: amber-soft value, a "probably from your dictation" chip, and the reasons in the description', async () => {
		show(row({ state: 'prefilled', quote: '7 mm solid nodule', why: ['another number in this finding'] }));
		await expect.element(page.getByText('probably from your dictation', { exact: true })).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')!.textContent).toBe('7 mm');
		expect(getComputedStyle(li().querySelector('.cp-prefill')!).backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
		// no native title anywhere on the row: the bubble is the one tooltip (a title showed the quote twice)
		expect(li().querySelectorAll('[title]').length + (li().hasAttribute('title') ? 1 : 0)).toBe(0);
		const desc = document.getElementById(li().getAttribute('aria-describedby')!)!.textContent!;
		expect(desc).toContain('“7 mm solid nodule”');
		expect(desc).toContain('Not verified: another number in this finding');
	});

	it('an exam preset: "set by the exam", no highlight and no "probably from your dictation" chip', async () => {
		show(row({ state: 'prefilled', byExam: true, value: 'unenhanced CT', why: ['set by the exam'] }));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')).toBeNull();
		expect(document.body.textContent).not.toContain('probably from your dictation');
		expect(li().hasAttribute('tabindex')).toBe(false);
	});

	it('a pre-filled row with no quote or reasons is still focusable, and says why', async () => {
		show(row({ state: 'prefilled', quote: '', why: [] }));
		await expect.element(page.getByText('probably from your dictation', { exact: true })).toBeInTheDocument();
		expect(li().getAttribute('tabindex')).toBe('0');
		expect(document.getElementById(li().getAttribute('aria-describedby')!)!.textContent).toContain('Not verified: not read with certainty');
	});

	it('an exam-set row that also has a real reason shows both chips and the reason', async () => {
		show(row({ state: 'prefilled', byExam: true, value: 'unenhanced CT', why: ['set by the exam', 'the check did not run'] }));
		await expect.element(page.getByText('set by the exam')).toBeInTheDocument();
		await expect.element(page.getByText('probably from your dictation', { exact: true })).toBeInTheDocument();
		expect(document.getElementById(li().getAttribute('aria-describedby')!)!.textContent).toContain('Not verified: the check did not run');
		expect(document.getElementById(li().getAttribute('aria-describedby')!)!.textContent).not.toContain('set by the exam');
	});

	it('a state this UI does not know shows as a neutral row', async () => {
		show(row({ state: 'reviewed' as never, value: '' }));
		await expect.element(page.getByText('reviewed')).toBeInTheDocument();
		expect(li().querySelector('.cp-prefill')).toBeNull();
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

	it('assumed: a dashed value, the "assumed" badge, and a decisive tag only when the backend says', async () => {
		const r = show(row({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No' }));
		await expect.element(page.getByText('assumed', { exact: true })).toBeInTheDocument();
		expect(li().querySelector('.cp-assumed-val')!.textContent).toBe('No');
		expect(document.body.textContent).not.toMatch(/decisive|doesn't affect/);
		await r.rerender({ row: row({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No', decisive: true }) });
		await expect.element(page.getByText('decisive')).toBeInTheDocument();
		await r.rerender({ row: row({ input: 'cancer', label: 'Known cancer', state: 'assumed', value: 'No', decisive: false }) });
		await expect.element(page.getByText("doesn't affect outcome")).toBeInTheDocument();
	});

	it('a visible sign assumed absent reads "assumed absent"; decisive null shows no tag', async () => {
		show(row({ input: 'calc', label: 'Calcification', state: 'assumed', value: 'Absent', sign: true, decisive: null }));
		await expect.element(page.getByText('assumed absent')).toBeInTheDocument();
		expect(document.body.textContent).not.toMatch(/decisive|doesn't affect/);
	});

	it('a row with a basis shows it under the value (§7.12 item 4)', async () => {
		show(row({ input: 'interval', label: 'Interval', value: '216', basis: 'from the CT of 12 Mar 2025' }));
		await expect.element(page.getByText('from the CT of 12 Mar 2025')).toBeVisible();
		const value = page.getByText('216', { exact: true }).element().getBoundingClientRect();
		const basis = page.getByText('from the CT of 12 Mar 2025').element().getBoundingClientRect();
		expect(basis.top).toBeGreaterThanOrEqual(value.bottom - 1); // under it, not beside it
	});
});
