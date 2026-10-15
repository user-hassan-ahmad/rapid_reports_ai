// Clarity pass: recommendation first, labelled sections, provisional line, buttons, "may not apply" as a question.
// SYNTHETIC previews rendered through PackBody.
import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from 'vitest-browser-svelte';
import { page } from '@vitest/browser/context';
import PackBody from './PackBody.svelte';
import { card, draft, outcome, preview, result } from './fixtures';
import { cardRef } from '../state';

const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
const rec = () => outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.', headline: 'Solid nodule', action: 'CT at 3 months', category: 'surveillance' });
const reached = (over = {}) =>
	preview({
		proposal: null,
		draft_outcome: rec(),
		trace: { outcome: 'ct3' },
		draft: [
			draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' }),
			draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, options: ['solid', 'subsolid'] })
		],
		...over
	});
const show = (p: ReturnType<typeof preview>, props: Record<string, unknown> = {}) => {
	const h = { onEdit: vi.fn(), onTick: vi.fn(), onPick: vi.fn(), onApply: vi.fn(), onSeen: vi.fn() };
	render(PackBody, { result: result(bts, p), guideline: 'BTS 2015', applyOn: true, ...h, ...props });
	return h;
};
const labels = () => [...document.querySelectorAll('[data-testid="cp-section-label"]')].map((e) => e.textContent!.trim());
const gate = () => ({ key: cardRef(bts), card: cardRef(bts), name: 'BTS 2015' });

describe('sections and order', () => {
	it('QUESTION (while one remains), RECOMMENDATION, WHAT THIS RESTS ON, YOUR REPORT, in that order', async () => {
		const p = reached({ asks: [{ input: 's', label: 'Smoker', options: ['Yes', 'No'] }], draft: [...(reached().draft ?? []), draft({ input: 's', label: 'Smoker', state: 'asked' })] });
		show(p, { unresolved: gate() });
		await expect.element(page.getByTestId('cp-question')).toBeInTheDocument();
		expect(labels()).toEqual(['QUESTION 1 OF 1', 'RECOMMENDATION', 'WHAT THIS RESTS ON', 'YOUR REPORT']);
	});

	it('the question label counts the questions; unbounded says "up to"', async () => {
		const asks = [{ input: 'g', label: 'Growth', options: ['Yes', 'No'] }, { input: 's', label: 'Smoker', options: ['Yes', 'No'] }];
		const draftAsks = [draft({ input: 'g', label: 'Growth', state: 'asked' }), draft({ input: 's', label: 'Smoker', state: 'asked' })];
		show(preview({ proposal: null, asks, draft: draftAsks }));
		expect(labels()).toContain('QUESTION 1 OF 2');
		cleanup();
		show(preview({ proposal: null, asks, draft: draftAsks, bounded: false }));
		expect(labels().some((l) => /^QUESTION 1 .*UP TO 2/.test(l))).toBe(true);
	});

	it('no outcome yet: "No recommendation yet", always provisional', async () => {
		const asks = [{ input: 'g', label: 'Growth', options: ['Yes', 'No'] }, { input: 's', label: 'Smoker', options: ['Yes', 'No'] }];
		show(preview({ proposal: null, asks, draft: [draft({ input: 'g', label: 'Growth', state: 'asked' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] }));
		await expect.element(page.getByText('No recommendation yet — 2 questions to answer')).toBeInTheDocument();
	});
});

describe('provisional until the values are checked', () => {
	it('Apply on: counts the unconfirmed values; ticking clears it and the muting', async () => {
		show(reached());
		await expect.element(page.getByTestId('cp-provisional')).toHaveTextContent('Provisional — confirm the 1 value below to use it');
		expect(document.querySelector('.cp-rec-provisional')).not.toBeNull();
		expect(getComputedStyle(document.querySelector('.cp-verdict')!).opacity).toBe('1'); // fully legible: a cue, not a fade
		cleanup();
		show(reached(), { ticks: { kind: 'solid' } });
		await expect.element(page.getByTestId('cp-provisional')).not.toBeInTheDocument();
		expect(document.querySelector('.cp-rec-provisional')).toBeNull();
	});

	it('Apply off: rests on the values not stated; always until they are changed', async () => {
		show(reached(), { applyOn: false });
		await expect.element(page.getByTestId('cp-provisional')).toHaveTextContent('Rests on 1 value not stated in your dictation — check them below');
		cleanup();
		show(reached({ draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' })] }), { applyOn: false });
		await expect.element(page.getByTestId('cp-provisional')).not.toBeInTheDocument();
	});

	it('the section explains itself (on / off) and the status line is gone', async () => {
		show(reached());
		await expect.element(page.getByTestId('cp-rests-note')).toHaveTextContent('Not verified in your dictation. Confirm each one, or change it.');
		await expect.element(page.getByTestId('cp-status')).not.toBeInTheDocument();
		cleanup();
		show(reached(), { applyOn: false });
		await expect.element(page.getByTestId('cp-rests-note')).toHaveTextContent('Not verified in your dictation. Change any that are wrong.');
	});

	it('provenance tags: not dictated, from your dictation, or the basis', async () => {
		const p = reached({
			draft: [
				draft({ input: 'a', label: 'Age', state: 'assumed', value: '18 or over', decisive: true }),
				draft({ input: 'k', label: 'Type', state: 'prefilled', value: 'solid', decisive: true }),
				draft({ input: 'g', label: 'Growth', state: 'prefilled', value: 'No', decisive: true, basis: 'from the CT of 12 Mar 2025' })
			]
		});
		show(p);
		const t = document.querySelector('[data-testid="cp-check"]')!.textContent!;
		expect(t).toContain('not dictated');
		expect(t).toContain('Check: probably from your dictation');
		expect(t).toContain('Check: worked out — from the CT of 12 Mar 2025');
		expect(t).not.toContain('pre-filled');
	});
});

describe('your report', () => {
	it('Apply on with a gate note: the note and Apply to report + Not in this report on one row', async () => {
		const h = show(reached(), { unresolved: gate(), ticks: { kind: 'solid' } });
		await expect.element(page.getByTestId('cp-unresolved')).toHaveTextContent('Not in your conclusion yet.');
		await page.getByRole('button', { name: 'Apply to report' }).click();
		expect(h.onApply).toHaveBeenCalled();
		await page.getByRole('button', { name: 'Not in this report' }).click();
		expect(h.onSeen).toHaveBeenCalledWith(cardRef(bts));
		await expect.element(page.getByRole('button', { name: 'Apply to report' })).toHaveClass('rv-btn-primary');
	});

	it('Apply off: Not in this report with its sentence; nothing at all without a gate note', async () => {
		show(reached(), { applyOn: false, unresolved: gate() });
		await expect.element(page.getByTestId('cp-unresolved')).toHaveTextContent('Add it to your conclusion, or choose Not in this report.');
		await expect.element(page.getByRole('button', { name: 'Apply to report' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Not in this report' })).toBeInTheDocument();
		cleanup();
		show(reached(), { applyOn: false });
		expect(labels()).not.toContain('YOUR REPORT');
	});

	it('the picker is labelled "Choose the outcome that fits"', async () => {
		const cands = [{ outcome: 'a', headline: 'CT at 3 months', category: 'surveillance' as const, proposal: rec() }, { outcome: 'b', headline: 'PET-CT', category: 'workup' as const, proposal: rec() }];
		show(preview({ proposal: null, candidates: cands, asks: [], draft: [] }));
		await expect.element(page.getByTestId('cp-pick')).toHaveTextContent('Choose the outcome that fits');
	});
});

describe('the not-applied row: fact, source, what happens next, two named answers', () => {
	const doubt = (row = {}, over = {}) =>
		reached({ state: 'check_first', scope_doubt: ['g'], draft: [draft({ input: 'g', label: 'Earlier imaging shows this nodule has grown', state: 'prefilled', value: 'Yes', quote: 'grown since 2023', options: ['Yes', 'No', 'Not stated'], ...row })], ...over });

	it('a boolean: the fact as a statement with its source; the quote behind ↗; Correct and the named alternative', async () => {
		const h = show(doubt());
		const row = page.getByTestId('cp-collapsed');
		await expect.element(row).toHaveTextContent('Earlier imaging shows this nodule has grown');
		await expect.element(page.getByTestId('cp-fact-source')).toHaveTextContent('from your dictation');
		await expect.element(page.getByTestId('cp-fact-quote')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Show the quote' }).click();
		await expect.element(page.getByTestId('cp-fact-quote')).toHaveTextContent('“grown since 2023”');
		await expect.element(row).toHaveTextContent("BTS 2015 doesn't cover this, so its recommendation won't be added.");
		expect(document.body.textContent).not.toContain('check applicability');
		await page.getByRole('button', { name: 'Correct' }).click();
		expect(h.onEdit).toHaveBeenCalledWith('g', 'Yes');
		await page.getByRole('button', { name: "That's not right — apply BTS 2015" }).click();
		expect(h.onEdit).toHaveBeenLastCalledWith('g', 'No');
	});

	it('a boolean No reads "label: No"; the source falls back to the exam, the basis, or inferred', async () => {
		show(doubt({ value: 'No', quote: '' }));
		await expect.element(page.getByTestId('cp-collapsed')).toHaveTextContent('Earlier imaging shows this nodule has grown: No');
		await expect.element(page.getByTestId('cp-fact-source')).toHaveTextContent('inferred');
		await expect.element(page.getByRole('button', { name: 'Show the quote' })).not.toBeInTheDocument();
		cleanup();
		show(doubt({ by: 'exam' }));
		await expect.element(page.getByTestId('cp-fact-source')).toHaveTextContent('from the exam');
		cleanup();
		show(doubt({ basis: 'from the CT of 12 Mar 2025' }));
		await expect.element(page.getByTestId('cp-fact-source')).toHaveTextContent('from the CT of 12 Mar 2025');
	});

	it('an enum with one other option names it; several open the options inline', async () => {
		const h = show(doubt({ label: 'Type', value: 'solid', options: ['solid', 'subsolid', 'Not stated'] }));
		await page.getByRole('button', { name: 'Subsolid — apply BTS 2015' }).click();
		expect(h.onEdit).toHaveBeenCalledWith('g', 'subsolid');
		cleanup();
		const h2 = show(doubt({ label: 'Type', value: 'solid', options: ['solid', 'subsolid', 'ground-glass', 'Not stated'] }));
		await page.getByRole('button', { name: 'Choose another value — apply BTS 2015' }).click();
		await page.getByRole('combobox').selectOptions('ground-glass');
		expect(h2.onEdit).toHaveBeenLastCalledWith('g', 'ground-glass');
	});

	it('no Mark as seen, Needs your answer or unresolved marker on the row; Show details and "+n more" expand', async () => {
		const onExpand = vi.fn();
		show(doubt({}, { scope_doubt: ['g', 'size'] }), { onExpand, unresolved: gate() });
		await expect.element(page.getByRole('button', { name: 'Not in this report' })).not.toBeInTheDocument();
		expect(document.body.textContent).not.toContain('Needs your answer');
		await page.getByRole('button', { name: '+1 more' }).click();
		expect(onExpand).toHaveBeenLastCalledWith(true);
		await page.getByRole('button', { name: 'Show details' }).click();
		expect(onExpand).toHaveBeenLastCalledWith(true);
	});

	it('an exclusion: its reason as the fact with its source, the same sentence, Show details', async () => {
		show(preview({ state: 'does_not_apply', proposal: null, exclusion: outcome({ headline: 'Outside the table', classification: 'x', category: 'not_applicable' }), exclusion_reason: { input: 'g', label: 'Growth on prior imaging', value: 'Yes', outcome: 'o' }, draft: [draft({ input: 'g', label: 'Growth on prior imaging', state: 'read', value: 'Yes', quote: 'has grown', options: ['Yes', 'No'] })] }));
		const row = page.getByTestId('cp-collapsed');
		await expect.element(row).toHaveTextContent('Growth on prior imaging');
		await expect.element(row).toHaveTextContent("BTS 2015 doesn't cover this, so its recommendation won't be added.");
		await expect.element(page.getByRole('button', { name: 'Correct' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Show details' })).toBeInTheDocument();
	});
});

describe('durations, answered slot', () => {
	it('60 days or more shows as months (with the date when the basis has one); under 60 stays in days', async () => {
		const row = (value: string, basis = '') => draft({ input: 'iv', label: 'Interval', state: 'prefilled', value, decisive: true, basis });
		show(reached({ draft: [row('120 days', 'from the CT of 12 Mar 2025')] }));
		await expect.element(page.getByTestId('cp-check')).toHaveTextContent('Interval: 4 months (since Mar 2025)');
		cleanup();
		show(reached({ draft: [row('45 days')] }));
		await expect.element(page.getByTestId('cp-check')).toHaveTextContent('Interval: 45 days');
	});

	it('answering keeps the slot: the answered line, then the next question in the same place; the recommendation follows', async () => {
		const ask = (input: string, label: string) => ({ input, label, options: ['Yes', 'No'] });
		const two = preview({ proposal: null, asks: [ask('g', 'Growth'), ask('s', 'Smoker')], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] });
		const r = render(PackBody, { result: result(bts, two), guideline: 'BTS 2015', onEdit: vi.fn() });
		await expect.element(page.getByTestId('cp-question')).toHaveTextContent('Growth');
		const one = preview({ proposal: null, asks: [ask('s', 'Smoker')], draft: [draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] });
		await r.rerender({ result: result(bts, one), edits: { g: 'Yes' } });
		await expect.element(page.getByTestId('cp-question')).toHaveTextContent('Smoker');
		await expect.element(page.getByTestId('cp-answers')).toHaveTextContent('Growth: Yes');
		const slot = page.getByTestId('cp-answers').element().closest('[data-testid="cp-section"]')!;
		expect(slot.contains(page.getByTestId('cp-question').element())).toBe(true);
		const done = reached({ asks: [], draft: [draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' })] });
		await r.rerender({ result: result(bts, done), edits: { g: 'Yes', s: 'No' } });
		await expect.element(page.getByTestId('cp-question')).not.toBeInTheDocument();
		await expect.element(page.getByTestId('cp-answers')).toBeInTheDocument(); // the answered line stays in the first slot
	});
});

describe('buttons, not bare links', () => {
	it('the toggles are buttons in the card style', async () => {
		const p = reached({ draft_outcome: outcome({ ...rec(), caveats: ['A note'], citations: [{ source: 'S1', title: 'Guideline', edition: '2017', page: 3 }] }) });
		show(p, { ticks: { kind: 'solid' } });
		for (const name of [/^Read from your dictation/, /note/, /Guideline/]) await expect.element(page.getByRole('button', { name }).first()).toHaveClass('rv-btn');
		expect(document.querySelectorAll('.cp-link').length).toBe(0);
		cleanup();
		show(preview({ ...reached(), scope_doubt: ['kind'], state: 'check_first' }));
		await expect.element(page.getByRole('button', { name: 'Show details' })).toHaveClass('rv-btn');
	});
});
