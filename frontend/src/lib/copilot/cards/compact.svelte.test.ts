// The calmer card: guidelines that may not apply collapse behind one row, one gate note at the foot, grid Check rows,
// a category pill, less repetition. SYNTHETIC previews.
import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import PackBody from './PackBody.svelte';
import PackCard from './PackCard.svelte';
import SiblingColumns from './SiblingColumns.svelte';
import { card, draft, outcome, preview, result } from './fixtures';
import { columnRef } from './format';
import { closedView } from './view';
import { cardRef } from '../state';

const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
const decided = (over = {}) =>
	preview({
		proposal: null,
		draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.', headline: 'Solid nodule', action: 'CT at 3 months', category: 'surveillance' }),
		trace: { outcome: 'ct3' },
		draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm', quote: '7 mm' })],
		...over
	});
const doubtful = (over = {}) =>
	decided({
		state: 'check_first',
		scope_doubt: ['kind'],
		draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' }), draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', options: ['solid', 'subsolid'] })],
		...over
	});
const excluded = () =>
	preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ headline: 'Outside the table: interval growth', classification: 'Does not apply: grown.', category: 'not_applicable' }), exclusion_reason: { input: 'g', label: 'Earlier imaging shows growth', value: 'Yes', outcome: 'x' } });
const body = (p: ReturnType<typeof preview>, props: Record<string, unknown> = {}) => render(PackBody, { result: result(bts, p), guideline: 'BTS 2015', ...props });
const handlers = () => ({ onOpen: vi.fn(), onClose: vi.fn(), onRetry: vi.fn() });

describe('collapsing guidelines that may not apply', () => {
	it('an excluded card is one row with its reason; Show details opens today\'s body', async () => {
		body(excluded());
		await expect.element(page.getByTestId('cp-collapsed')).toHaveTextContent('Outside the table: interval growth');
		await expect.element(page.getByRole('region', { name: 'Verdict' })).not.toBeInTheDocument();
		await page.getByRole('button', { name: /Show details/ }).click();
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: /Hide details/ })).toBeInTheDocument();
		await page.getByRole('button', { name: /Hide details/ }).click();
		await expect.element(page.getByTestId('cp-collapsed')).toBeInTheDocument();
	});

	it('a scope doubt is one row: the reason and Confirm (an answer); +N more when several', async () => {
		const onEdit = vi.fn();
		body(doubtful({ scope_doubt: ['kind', 'size'] }), { onEdit });
		await expect.element(page.getByTestId('cp-collapsed')).toHaveTextContent('Type: solid would make BTS 2015 not apply');
		await expect.element(page.getByTestId('cp-collapsed')).toHaveTextContent('+1 more');
		await page.getByRole('button', { name: 'Confirm Type solid' }).click();
		expect(onEdit).toHaveBeenCalledWith('kind', 'solid');
	});

	it('the doubt has no Confirm without a value or without onEdit', async () => {
		body(doubtful(), {});
		await expect.element(page.getByTestId('cp-collapsed')).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Confirm Type solid' })).not.toBeInTheDocument();
	});

	it('the view owns the state: expanded shows the body; the toggle asks through onExpand', async () => {
		const onExpand = vi.fn();
		body(doubtful(), { expanded: true, onExpand });
		await expect.element(page.getByTestId('cp-collapsed')).not.toBeInTheDocument();
		await page.getByRole('button', { name: /Hide details/ }).click();
		expect(onExpand).toHaveBeenCalledWith(false);
		cleanup();
		body(doubtful(), { onExpand });
		await page.getByRole('button', { name: /Show details/ }).click();
		expect(onExpand).toHaveBeenLastCalledWith(true);
	});

	it('a card that applies is never collapsed', async () => {
		body(decided());
		await expect.element(page.getByTestId('cp-collapsed')).not.toBeInTheDocument();
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toBeInTheDocument();
	});

	it('a collapsed row marks an unresolved guideline', async () => {
		const key = cardRef(bts);
		body(doubtful(), { unresolved: { key, card: key, name: 'BTS 2015' } });
		await expect.element(page.getByTestId('cp-collapsed-unresolved')).toBeInTheDocument();
	});

	it('siblings: the applicable column shows in full, the doubtful one is a row; its toggle uses the column ref', async () => {
		const fl = card({ siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const onExpand = vi.fn();
		const columns = {
			'fleischner-pulmonary-nodule': { loading: false, error: null, result: result(fl, decided()) },
			'bts-pulmonary-nodule': { loading: false, error: null, result: result(bts, doubtful()) }
		};
		render(SiblingColumns, { card: fl, view: { ...closedView, open: true, columns }, layout: 'stacked', onExpand, ...handlers() });
		expect(document.querySelectorAll('[data-testid="cp-collapsed"]')).toHaveLength(1);
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toBeInTheDocument();
		await page.getByRole('button', { name: /Show details/ }).click();
		expect(onExpand).toHaveBeenCalledWith(columnRef(fl, 'bts-pulmonary-nodule'), true);
	});
});

describe('the calmer card', () => {
	it('the assumed chip leaves the head while the body is open and expanded; its count is the unticked assumed values', async () => {
		const p = decided({
			draft: [
				draft({ input: 'a', label: 'Age', state: 'assumed', value: '18 or over', decisive: true }),
				draft({ input: 'b', label: 'Smoker', state: 'assumed', value: 'No', decisive: true }),
				draft({ input: 'c', label: 'Cancer', state: 'assumed', value: 'No', decisive: false })
			]
		});
		const open = (v: Record<string, unknown>) => render(PackCard, { card: bts, view: { ...closedView, result: result(bts, p), ...v }, ...handlers() });
		open({ open: false });
		await expect.element(page.getByText('⚠ 2 assumed')).toBeInTheDocument();
		cleanup();
		open({ open: false, ticks: { a: '18 or over' } });
		await expect.element(page.getByText('⚠ assumes: Smoker No')).toBeInTheDocument();
		cleanup();
		open({ open: true });
		expect(document.querySelector('.cp-assumed-chip')).toBeNull();
	});

	it('one gate note, after the verdict, with the new copy; Seen still works', async () => {
		const onSeen = vi.fn();
		const key = cardRef(bts);
		render(PackCard, { card: bts, view: { ...closedView, open: true, result: result(bts, decided()) }, unresolved: { key, card: key, name: 'BTS 2015' }, onSeen, ...handlers() });
		const note = page.getByTestId('cp-unresolved');
		await expect.element(note).toHaveTextContent('Not in your conclusion yet: add it to the conclusion, or mark it seen.'); // Apply off
		const verdict = document.querySelector('[aria-label="Verdict"]')!;
		expect(verdict.compareDocumentPosition(note.element()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		await page.getByRole('button', { name: 'Seen, leave as is' }).click();
		expect(onSeen).toHaveBeenCalledWith(key);
	});

	it('Check has no label while the status line names it; with Apply off the label returns', async () => {
		const p = decided({ draft: [draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, options: ['solid', 'subsolid'] })] });
		body(p, { applyOn: true, onEdit: vi.fn(), onTick: vi.fn() });
		await expect.element(page.getByTestId('cp-status')).toBeInTheDocument();
		await expect.element(page.getByTestId('cp-check-label')).not.toBeInTheDocument();
		cleanup();
		body(p, { applyOn: false, onEdit: vi.fn() });
		await expect.element(page.getByTestId('cp-check-label')).toHaveTextContent('Check');
	});

	it('Check rows are a two-column grid; Change is an icon button that keeps its name', async () => {
		const p = decided({ draft: [draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, options: ['solid', 'subsolid'] })] });
		body(p, { applyOn: true, onEdit: vi.fn(), onTick: vi.fn() });
		const li = document.querySelector('.cp-check-item')!;
		expect(getComputedStyle(li).display).toBe('grid');
		expect(getComputedStyle(li).gridTemplateColumns.split(' ')).toHaveLength(2);
		const change = page.getByRole('button', { name: 'Change Type' });
		await expect.element(change).toHaveAttribute('title', 'Change Type');
		expect(change.element().textContent!.trim()).toBe('');
	});

	it('no "On these values" (only the busy note), no "Possible" label, no classification that restates the headline', async () => {
		const p = decided({ draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule', recommendation: 'CT at 3 months.', headline: 'Solid nodule', action: 'CT at 3 months', category: 'surveillance' }) });
		body(p);
		expect(document.body.textContent).not.toContain('On these values');
		expect(document.querySelector('.cp-classification')).toBeNull();
		cleanup();
		body(decided({ draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm in a smoker', headline: 'Solid nodule', recommendation: 'CT at 3 months.', action: 'CT at 3 months', category: 'surveillance' }) }));
		expect(document.querySelector('.cp-classification')!.textContent).toContain('in a smoker');
		cleanup();
		body(preview({ proposal: null, possible: ['Only outcome'], asks: [], draft: [] }));
		await expect.element(page.getByText('Only outcome')).toBeInTheDocument();
		expect(document.body.textContent).not.toContain('Possible');
		cleanup();
		body(decided(), { busy: true });
		await expect.element(page.getByText('Updating on the new values…')).toBeInTheDocument();
	});

	it('the open card\'s pill is the category word and the verdict carries the full action; the closed head keeps the action, cut with a title', async () => {
		render(PackCard, { card: bts, view: { ...closedView, open: true, result: result(bts, decided()) }, ...handlers() });
		await expect.poll(() => document.querySelector('.cp-pill')?.textContent ?? '').toContain('Follow-up');
		await expect.element(page.getByRole('region', { name: 'Verdict' })).toHaveTextContent('CT at 3 months');
		cleanup();
		render(PackCard, { card: bts, view: { ...closedView, open: false, result: result(bts, decided()) }, ...handlers() });
		const pill = document.querySelector('.cp-pill')!;
		expect(pill.textContent).toContain('CT at 3 months');
		expect(pill.getAttribute('title')).toBe('CT at 3 months');
		expect(pill.querySelector('.cp-pill-text')).not.toBeNull();
	});

	it('the gate note offers "apply it" only when Apply is on', async () => {
		const key = cardRef(bts);
		body(decided(), { unresolved: { key, card: key, name: 'BTS 2015' }, applyOn: true });
		await expect.element(page.getByTestId('cp-unresolved')).toHaveTextContent('Not in your conclusion yet: apply it, add it to the conclusion, or mark it seen.');
	});

	it('the collapsed row carries Seen, leave as is beside the marker', async () => {
		const onSeen = vi.fn();
		const key = cardRef(bts);
		body(doubtful(), { unresolved: { key, card: key, name: 'BTS 2015' }, onSeen });
		await page.getByRole('button', { name: 'Seen, leave as is' }).click();
		expect(onSeen).toHaveBeenCalledWith(key);
	});

	it('the Show details and Hide details toggles name the body they control', async () => {
		body(doubtful(), { expanded: true, onExpand: vi.fn() });
		const id = page.getByRole('button', { name: /Hide details/ }).element().getAttribute('aria-controls')!;
		expect(document.getElementById(id)).not.toBeNull();
	});

	it('siblings: the applicable column leads even when the primary column is the doubtful one', async () => {
		const fl = card({ siblings: ['bts-pulmonary-nodule'], sibling_names: ['BTS 2015'] });
		const columns = {
			'fleischner-pulmonary-nodule': { loading: false, error: null, result: result(fl, doubtful()) },
			'bts-pulmonary-nodule': { loading: false, error: null, result: result(bts, decided()) }
		};
		render(SiblingColumns, { card: fl, view: { ...closedView, open: true, columns }, layout: 'stacked', ...handlers() });
		const row = document.querySelector('[data-testid="cp-collapsed"]')!;
		const verdict = document.querySelector('[aria-label="Verdict"]')!;
		expect(verdict.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
	});
});
