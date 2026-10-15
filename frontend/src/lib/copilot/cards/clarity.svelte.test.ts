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

	it('the Check rows are grouped by where the value came from (heading and count)', async () => {
		const p = reached({
			draft: [
				draft({ input: 'a', label: 'Age', state: 'assumed', value: '18 or over', decisive: true }),
				draft({ input: 'k', label: 'Type', state: 'prefilled', value: 'solid', decisive: true }),
				draft({ input: 'g', label: 'Growth', state: 'prefilled', value: 'No', decisive: true, basis: 'from the CT of 12 Mar 2025' })
			]
		});
		show(p);
		const heads = [...document.querySelectorAll('[data-testid="cp-check-group-label"]')].map((e) => e.textContent!.trim());
		expect(heads).toEqual(['NOT DICTATED · 1', 'PROBABLY FROM YOUR DICTATION · 1', 'WORKED OUT · 1']);
		const t = document.querySelector('[data-testid="cp-check"]')!.textContent!;
		expect(t).toContain('from the CT of 12 Mar 2025'); // the basis, muted after the answer
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
		await expect.element(page.getByTestId('cp-check')).toHaveTextContent('4 months (since Mar 2025)');
		cleanup();
		show(reached({ draft: [row('45 days')] }));
		await expect.element(page.getByTestId('cp-check')).toHaveTextContent('45 days');
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

describe('clarity polish', () => {
	const ask = (input: string, label: string) => ({ input, label, options: ['Yes', 'No'] });
	const twoAsks = () => preview({ proposal: null, asks: [ask('g', 'Growth'), ask('s', 'Smoker')], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] });

	it('provisional says "confirm" only when the values can be ticked; otherwise it rests on them', async () => {
		show(reached(), { onTick: null });
		await expect.element(page.getByTestId('cp-provisional')).toHaveTextContent('Rests on 1 value not stated in your dictation — check them below');
	});

	it('"No recommendation yet" is provisional too: the line and the cue', async () => {
		show(twoAsks());
		await expect.element(page.getByTestId('cp-provisional')).toHaveTextContent('Provisional — answer the question above to settle it');
		expect(document.querySelector('.cp-no-rec.cp-rec-provisional')).not.toBeNull();
	});

	it('the counter advances on a real answer: 1 OF 2, then 2 OF 2; unbounded reads OF UP TO', async () => {
		const r = render(PackBody, { result: result(bts, twoAsks()), guideline: 'BTS 2015', onEdit: vi.fn() });
		expect(labels()).toContain('QUESTION 1 OF 2');
		const one = preview({ proposal: null, asks: [ask('s', 'Smoker')], draft: [draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' }), draft({ input: 's', label: 'Smoker', state: 'asked' })] });
		await r.rerender({ result: result(bts, one), edits: { g: 'Yes' } });
		expect(labels()).toContain('QUESTION 2 OF 2');
		cleanup();
		render(PackBody, { result: result(bts, { ...twoAsks(), bounded: false }), guideline: 'BTS 2015', onEdit: vi.fn() });
		expect(labels()).toContain('QUESTION 1 OF UP TO 2');
	});

	it('a Check-row edit never adds a QUESTION block above the recommendation', async () => {
		const edited = reached({ draft: [draft({ input: 'kind', label: 'Type', state: 'edited', value: 'subsolid', decisive: true })] });
		show(edited, { edits: { kind: 'subsolid' } });
		expect(labels().some((l) => l.startsWith('QUESTION'))).toBe(false);
		await expect.element(page.getByTestId('cp-answers')).not.toBeInTheDocument();
		expect(labels()[0]).toBe('RECOMMENDATION');
	});

	it('answering the last question keeps the slot: the recommendation does not move', async () => {
		const asks = preview({ proposal: null, draft_outcome: rec(), trace: { outcome: 'ct3' }, asks: [ask('g', 'Growth')], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' })] });
		const r = render(PackBody, { result: result(bts, asks), guideline: 'BTS 2015', onEdit: vi.fn() });
		await expect.element(page.getByTestId('cp-question')).toBeInTheDocument();
		const top = () => (document.querySelector('[aria-label="Recommendation"]') as HTMLElement).offsetTop;
		const before = top();
		const done = preview({ proposal: null, draft_outcome: rec(), trace: { outcome: 'ct3' }, asks: [], draft: [draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' })] });
		await r.rerender({ result: result(bts, done), edits: { g: 'Yes' } });
		await expect.element(page.getByTestId('cp-answers')).toBeInTheDocument();
		expect(Math.abs(top() - before)).toBeLessThanOrEqual(4);
	});

	it('candidates with no likeliest line: the section points to the picker instead of staying empty', async () => {
		const cands = [{ outcome: 'a', headline: 'CT at 3 months', category: 'surveillance' as const, proposal: rec() }, { outcome: 'b', headline: 'PET-CT', category: 'workup' as const, proposal: rec() }];
		show(preview({ proposal: null, candidates: cands, asks: [], draft: [] }));
		await expect.element(page.getByLabelText('Recommendation')).toHaveTextContent('Choose the outcome that fits below');
	});

	it('the collapsed row\'s buttons have unique names, no chevron on Show details', async () => {
		show(reached({ state: 'check_first', scope_doubt: ['g'], draft: [draft({ input: 'g', label: 'Growth', state: 'prefilled', value: 'Yes', quote: 'x', options: ['Yes', 'No'] })] }));
		await expect.element(page.getByRole('button', { name: 'Correct: Growth' })).toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: "That's not right — apply BTS 2015" })).toHaveAttribute('aria-label', "That's not right — apply BTS 2015");
		expect(page.getByRole('button', { name: 'Show details' }).element().querySelector('svg')).toBeNull();
	});

	it('the values toggle has two lines: read from the dictation, then the non-decisive guesses', async () => {
		const p = reached({
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' }),
				draft({ input: 'phase', label: 'Phase', state: 'prefilled', value: 'unenhanced', by: 'exam', decisive: false }),
				draft({ input: 'sm', label: 'Smoker', state: 'prefilled', value: 'No', decisive: false }),
				draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true })
			]
		});
		show(p);
		const t = page.getByRole('button', { name: /^Read from your dictation/ }).element();
		const lines = [...t.querySelectorAll('.cp-based-line')].map((e) => e.textContent!.trim());
		expect(lines).toEqual(['Read from your dictation: Size 7 mm; Set by the exam: Phase unenhanced', 'Also used (not decisive): Smoker No']);
		cleanup();
		show(reached({ draft: [draft({ input: 'sm', label: 'Smoker', state: 'prefilled', value: 'No', decisive: false })] }));
		await expect.element(page.getByRole('button', { name: /^Also used \(not decisive\): Smoker No/ })).toBeInTheDocument();
	});

	it('notes, sources and Reference share one wrapping row', async () => {
		show(reached({ draft_outcome: outcome({ ...rec(), caveats: ['A note'], citations: [{ source: 'S1', title: 'Guideline', edition: '2017', page: 3 }] }) }), { ticks: { kind: 'solid' } });
		const aux = document.querySelector('.cp-aux') as HTMLElement;
		expect(getComputedStyle(aux).flexDirection).toBe('row');
		expect(getComputedStyle(aux).flexWrap).toBe('wrap');
	});
});

describe('the Check rows', () => {
	const rowsP = (extra: ReturnType<typeof draft>[] = [], over = {}) =>
		reached({
			draft: [
				draft({ input: 'a', label: 'Age', state: 'assumed', value: '18 or over', decisive: true }),
				draft({ input: 'k', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, quote: 'a solid nodule', options: ['solid', 'subsolid'] }),
				draft({ input: 'p', label: 'Phase', state: 'prefilled', value: 'unenhanced', decisive: true, by: 'exam' }),
				...extra
			],
			...over
		});

	it('groups with counts, in order: not dictated, probably from your dictation, set by the exam', async () => {
		show(rowsP([draft({ input: 'k2', label: 'Margin', state: 'prefilled', value: 'smooth', decisive: true })]));
		const heads = [...document.querySelectorAll('[data-testid="cp-check-group-label"]')].map((e) => e.textContent!.trim());
		expect(heads).toEqual(['NOT DICTATED · 1', 'PROBABLY FROM YOUR DICTATION · 2', 'SET BY THE EXAM · 1']);
	});

	it('a row is its question and its answer in separate elements; no per-row tag', async () => {
		show(rowsP());
		const li = document.querySelectorAll('[data-testid="cp-check-item"]')[1];
		expect(li.querySelector('.cp-check-q')!.textContent).toBe('Type');
		expect(li.querySelector('.cp-check-answer')!.textContent).toBe('solid');
		expect(li.textContent).not.toContain('probably from your dictation');
	});

	it('↗ shows the quote under the answer', async () => {
		show(rowsP());
		await expect.element(page.getByTestId('cp-check-quote')).not.toBeInTheDocument();
		await page.getByRole('button', { name: 'Show the quote for Type' }).click();
		await expect.element(page.getByTestId('cp-check-quote')).toHaveTextContent('“a solid nodule”');
	});

	it('a confirmed row shows "Confirmed" in place of ✓ and stays in its group', async () => {
		show(rowsP(), { ticks: { k: 'solid' } });
		await expect.element(page.getByTestId('cp-confirmed')).toHaveTextContent('Confirmed');
		await expect.element(page.getByRole('button', { name: 'Confirm Type solid' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Change Type' })).toBeInTheDocument();
		const heads = [...document.querySelectorAll('[data-testid="cp-check-group-label"]')].map((e) => e.textContent!.trim());
		expect(heads).toContain('PROBABLY FROM YOUR DICTATION · 1');
	});

	it('Apply off: the same rows with the edit button only', async () => {
		show(rowsP(), { applyOn: false });
		await expect.element(page.getByRole('button', { name: 'Confirm Type solid' })).not.toBeInTheDocument();
		await expect.element(page.getByRole('button', { name: 'Change Type' })).toBeInTheDocument();
		expect(document.querySelectorAll('[data-testid="cp-check-group"]').length).toBe(3);
	});

	it('scope-doubt rows come first, outside the groups', async () => {
		show(rowsP([], { state: 'check_first', scope_doubt: ['k'] }), { expanded: true, onExpand: vi.fn() });
		const doubt = document.querySelector('[data-testid="cp-scope-doubt"]')!;
		const group = document.querySelector('[data-testid="cp-check-group"]')!;
		expect(doubt.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
		expect(group.contains(doubt)).toBe(false);
	});
});

describe('clarity round 2', () => {
	it('the values toggle puts "Answered by you" first, never under "Also used (not decisive)"', async () => {
		const p = reached({
			draft: [
				draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' }),
				draft({ input: 'sm', label: 'Smoker', state: 'prefilled', value: 'No', decisive: false }),
				draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' })
			]
		});
		show(p);
		const lines = [...page.getByRole('button', { name: /^Answered by you/ }).element().querySelectorAll('.cp-based-line')].map((e) => e.textContent!.trim());
		expect(lines).toEqual(['Answered by you: Growth Yes', 'Read from your dictation: Size 7 mm', 'Also used (not decisive): Smoker No']);
	});

	it('the toggle\'s chevron stays inline at the end of its last line', async () => {
		show(reached({ draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' })] }));
		const caret = page.getByRole('button', { name: /^Read from your dictation/ }).element().querySelector('.cp-caret')!;
		expect(caret.parentElement!.classList.contains('cp-based-line')).toBe(true);
	});

	it('a pack card with no preview still shows its Reference', async () => {
		const ref = { summary: [{ id: 's1', text: 'A summary line', citation: {} as never }], definitions: [], tables: [], pitfalls: [] };
		render(PackBody, { result: result(bts, null, { reference: ref as never }), guideline: 'BTS 2015' });
		await expect.element(page.getByRole('button', { name: 'Reference' })).toBeInTheDocument();
	});

	it('a tall question leaves no permanent gap: the held height resets when the answers clear', async () => {
		const ask = (input: string, label: string) => ({ input, label, options: ['Yes', 'No'], definition: { text: 'A long definition. '.repeat(12), citation: {} as never } });
		const open = preview({ proposal: null, asks: [ask('g', 'Growth')], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' })] });
		const r = render(PackBody, { result: result(bts, open), guideline: 'BTS 2015', onEdit: vi.fn() });
		await expect.element(page.getByTestId('cp-question')).toBeInTheDocument();
		const tall = (document.querySelector('.cp-qslot') as HTMLElement).offsetHeight;
		const cleared = reached({ asks: [], draft: [draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm' })] });
		await r.rerender({ result: result(bts, cleared), edits: {} });
		await new Promise((res) => setTimeout(res, 50));
		const answered = preview({ proposal: null, draft_outcome: rec(), trace: { outcome: 'ct3' }, asks: [], draft: [draft({ input: 'g', label: 'Growth', state: 'answered', value: 'Yes' })] });
		await r.rerender({ result: result(bts, answered), edits: { g: 'Yes' } });
		await expect.element(page.getByTestId('cp-answers')).toBeInTheDocument();
		expect((document.querySelector('.cp-qslot') as HTMLElement).offsetHeight).toBeLessThan(tall);
	});

	it('no empty footer row when there is nothing to put in it', async () => {
		show(reached({ draft_outcome: outcome({ ...rec(), citations: [], caveats: [] }) }));
		expect(document.querySelector('.cp-aux')).toBeNull();
	});

	it('a read-only column still shows "Confirmed" for a ticked value', async () => {
		render(PackBody, { result: result(bts, reached()), guideline: 'BTS 2015', applyOn: true, ticks: { kind: 'solid' } });
		await expect.element(page.getByTestId('cp-confirmed')).toHaveTextContent('Confirmed');
	});
});

