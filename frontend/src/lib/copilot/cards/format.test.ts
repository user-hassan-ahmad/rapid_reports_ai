import { describe, expect, it } from 'vitest';
import { assumption, card, outcome, preview, result } from './fixtures';
import type { DraftValue } from '../types';

const dv = (o: Partial<DraftValue>): DraftValue => ({
	input: 'x', label: 'X', role: 'clinical', scope: 'lesion', fact: '', state: 'read', value: '', quote: '', why: [], needed: false, waiting: false, options: [], by: '', ...o
});
import { assumptionsOf, citeText, columnRef, columnTitles, issuerSlug, openQuestions, setByExam, valueRows } from './format';

// SYNTHETIC fixtures only.
describe('card text helpers', () => {
	it('citeText mirrors the backend cite_text', () => {
		expect(citeText({ title: 'Guideline', edition: '2017', page: 3, section: 'Nodules', table: 'Table 1' })).toBe(
			'Guideline (2017), p. 3, Nodules, Table 1'
		);
		expect(citeText({ source: 'S1' })).toBe('S1');
		expect(citeText({})).toBe('');
		expect(citeText(null)).toBe('');
	});

	it('issuerSlug: short slugs upper-case, long ones capitalised', () => {
		expect(issuerSlug('bts-pulmonary-nodule')).toBe('BTS');
		expect(issuerSlug('fleischner-pulmonary-nodule')).toBe('Fleischner');
	});

	it('columnTitles: entry name, then sibling_names, then the issuer slug; primary first, at most three', () => {
		const c = card({ siblings: ['bts-pulmonary-nodule', 'acr-x', 'extra-y'], sibling_names: ['BTS 2015'] });
		expect(columnTitles(c).map((x) => x.title)).toEqual(['Fleischner 2017', 'BTS 2015', 'ACR']);
		const opened = { 'bts-pulmonary-nodule': result(card({ name: 'BTS guideline 2015' }), null) };
		expect(columnTitles(c, opened)[1].title).toBe('BTS guideline 2015');
		expect(columnRef(c, 'acr-x')).toBe('fleischner-pulmonary-nodule|solid pulmonary nodule#acr-x');
	});

	it('assumptionsOf: Task 3 assumptions when sent, else the missing eligibility inputs; openQuestions: the rest', () => {
		const asks = [
			{ input: 'e1', label: 'Known cancer', role: 'eligibility' },
			{ input: 'c1', label: 'Growth on prior imaging', role: 'clinical' }
		];
		const p = preview({ state: 'check_first', missing: ['e1', 'c1', 'x'], asks });
		expect(assumptionsOf(p)).toEqual(['Known cancer']);
		expect(openQuestions(p)).toEqual(['Growth on prior imaging', 'x']);
		expect(assumptionsOf(preview({ ...p, assumptions: [assumption('x', 'From the backend')] }))).toEqual(['From the backend: No']);
		expect(assumptionsOf(preview({ ...p, assumptions: [assumption('s', 'Calcification', 'Absent', { kind: 'sign' })] }))).toEqual(['Calcification: assumed absent']);
		expect(assumptionsOf(null)).toEqual([]);
	});

	it('valueRows: settled values labelled from the entry inputs, else the ask, else the id', () => {
		const c = card();
		const r = result(c, preview({
			settled: [
				{ input: 'size', value: '2.2 cm', quote: '2.2 cm nodule', fact: '', by: '' },
				{ input: 'age', value: '65', quote: '', fact: 'age', by: 'exam' },
				{ input: 'unenhanced_hu', value: '8 HU', quote: '', fact: '', by: '' }
			],
			asks: [{ input: 'age', label: 'Patient age' }]
		}));
		r.entry!.content.branches = [{ name: 'Pack', rule: '', inputs: [{ id: 'size', question: 'Size', options: [] }] }];
		expect(valueRows(r)).toEqual([
			{ input: 'size', label: 'Size', value: '2.2 cm', quote: '2.2 cm nodule', byExam: false, state: 'read', why: [] },
			{ input: 'age', label: 'Patient age', value: '65', quote: '', byExam: true, state: 'prefilled', why: ['set by the exam'] },
			{ input: 'unenhanced_hu', label: 'Unenhanced hu', value: '8 HU', quote: '', byExam: false, state: 'read', why: [] }
		]);
	});

	it('Task 3 draft: values, assumed ("Label: value") and asked come from draft rows; waiting rows are hidden', () => {
		const c = card();
		const p = preview({
			state: 'check_first',
			proposal: null,
			draft: [
				dv({ input: 'size', label: 'Size', state: 'read', value: '2.2 cm', quote: '2.2 cm nodule' }),
				dv({ input: 'hu', label: 'Unenhanced HU', state: 'prefilled', value: '8', quote: '8 HU', why: ['attenuation not stated as unenhanced'] }),
				dv({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No', why: ['assumed: …'] }),
				dv({ input: 'growth', label: 'Growth', state: 'asked', needed: false }),
				dv({ input: 'washout', label: 'Washout', state: 'asked', needed: true }),
				dv({ input: 'hormones', label: 'Hormone excess', role: 'eligibility', state: 'asked', needed: true }),
				dv({ input: 'later', label: 'Behind a prerequisite', state: 'asked', waiting: true }),
				dv({ input: 'side', label: 'Side', state: 'not_applicable' }),
				dv({ input: 'future', label: 'Future', state: 'reviewed' as never, value: 'x' })
			],
			assumptions: [assumption('cancer', 'Known cancer')],
			assumed_eligible: true
		});
		// an unknown state shows as a value rather than vanishing
		expect(valueRows(result(c, p)).map((r) => [r.input, r.state])).toEqual([['size', 'read'], ['hu', 'prefilled'], ['side', 'not_applicable'], ['future', 'reviewed']]);
		expect(assumptionsOf(p)).toEqual(['Known cancer: No']);
		expect(openQuestions(p)).toEqual(['Hormone excess', 'Washout']); // eligibility first; only the rows that can change the outcome (§7.12)
	});

	it('setByExam reads Settled.by', () => {
		expect(setByExam(preview())).toBe(false);
		expect(setByExam(preview({ settled: [{ input: 'i', value: 'v', quote: '', fact: '', by: 'exam' }] }))).toBe(true);
	});
});

// Spec §7.12 items 3 (the count tells the truth) and 1 (an exclusion worded by its outcome). SYNTHETIC values.
import { notNeeded, verdictOf } from './format';
describe('truthful counts and exclusion wording', () => {
	const asked = preview({
		proposal: null,
		draft: [
			dv({ input: 'age', label: 'Age', state: 'asked', needed: false }),
			dv({ input: 'smoking', label: 'Smoking history', state: 'asked', needed: false }),
			dv({ input: 'growth', label: 'Growth', state: 'asked', needed: true }),
			dv({ input: 'family', label: 'Family history', state: 'asked', needed: false }),
			dv({ input: 'emphysema', label: 'Emphysema', state: 'asked', needed: false }),
			dv({ input: 'later', label: 'Behind a prerequisite', state: 'asked', needed: false, waiting: true }),
			dv({ input: 'size', label: 'Size', state: 'read', value: '9 mm' })
		]
	});

	it('openQuestions counts only the asked rows that can change the outcome; notNeeded lists the others', () => {
		expect(openQuestions(asked)).toEqual(['Growth']);
		expect(notNeeded(asked)).toEqual(['Age', 'Smoking history', 'Family history', 'Emphysema']);
		expect(verdictOf(asked)?.pill).toBe('1 question open');
		expect(notNeeded(preview())).toEqual([]);
		expect(notNeeded(null)).toEqual([]);
	});

	it('an exclusion worded by an outcome leads with its headline and recommendation; a generic one keeps the reason', () => {
		const worded = preview({
			state: 'does_not_apply',
			proposal: null,
			exclusion: outcome({ headline: 'Outside the table: interval growth', action: 'See the other card', recommendation: 'The table covers new findings. See the other card.', classification: 'Does not apply: grown.', category: 'not_applicable' }),
			exclusion_reason: { input: 'prior_growth', label: 'Earlier imaging shows growth', value: 'Yes', outcome: 'outside_table_growth' }
		});
		expect(verdictOf(worded)).toMatchObject({ excluded: true, headline: 'Outside the table: interval growth', action: 'The table covers new findings. See the other card.' });
		const generic = preview({
			state: 'does_not_apply',
			proposal: null,
			exclusion: outcome({ headline: 'Generic exclusion', classification: 'Excluded: the list' }),
			exclusion_reason: { input: 'size', label: 'Maximum diameter', value: '38 mm', outcome: null }
		});
		expect(verdictOf(generic)).toMatchObject({ headline: 'Maximum diameter 38 mm', action: '' });
	});
});

// Controller ruling (2026-10-14): a scope doubt leads the card; the drafted outcome stays as a secondary line.
describe('scope doubt leads the card', () => {
	const drafted = outcome({ headline: 'Consider 3-month CT', action: 'CT at 3 months', category: 'workup' });
	const rows = [dv({ input: 'prior_growth', label: 'Earlier imaging shows this nodule has grown', role: 'eligibility', state: 'prefilled', value: 'Yes' })];
	it('pill "May not apply", the headline names the doubt, the drafted outcome kept as "If it applies"', () => {
		const p = preview({ proposal: null, draft_outcome: drafted, draft: rows, scope_doubt: ['prior_growth'] });
		expect(verdictOf(p)).toMatchObject({
			category: 'not_applicable',
			pill: 'May not apply',
			headline: 'Check: Earlier imaging shows this nodule has grown — Yes',
			action: '',
			tentative: true,
			ifApplies: 'If it applies: Consider 3-month CT — CT at 3 months'
		});
	});
	it('without the doubt: today\'s verdict', () => {
		const p = preview({ proposal: null, draft_outcome: drafted, draft: rows });
		expect(verdictOf(p)).toMatchObject({ category: 'workup', pill: 'CT at 3 months', headline: 'Consider 3-month CT' });
		expect(verdictOf(p)?.ifApplies).toBeUndefined();
	});
});

// Task 2 review: a number assumed as a band whose exact value an open formula branch still needs (e.g. Brock).
describe('assumed but still needed', () => {
	it('an assumed row with needed counts as one question open and is listed; needed false does not count; never "not needed"', () => {
		const p = preview({
			proposal: null,
			draft: [
				dv({ input: 'age', label: 'Age', role: 'eligibility', state: 'assumed', value: '18 or over', needed: true }),
				dv({ input: 'cancer', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No', needed: false })
			]
		});
		expect(openQuestions(p)).toEqual(['Age (exact value needed)']);
		expect(verdictOf(p)?.pill).toBe('1 question open');
		expect(notNeeded(p)).toEqual([]);
	});
});

import { shownValue } from './format';
describe('shownValue: a stored option id shown as words', () => {
	it('humanises a snake_case option id and leaves ordinary values alone', () => {
		expect(shownValue('diameter_clear_growth')).toBe('Diameter clear growth');
		expect(shownValue('7 mm')).toBe('7 mm');
		expect(shownValue('Yes')).toBe('Yes');
		expect(shownValue('solid')).toBe('solid');
		expect(shownValue('18 years or over')).toBe('18 years or over');
		expect(shownValue('')).toBe('');
	});
	it('a scope-doubt headline shows the value as words', () => {
		const rows = [{ input: 'growth', label: 'Growth', role: 'eligibility', state: 'prefilled', value: 'diameter_clear_growth' } as unknown as DraftValue];
		const p = preview({ proposal: null, draft_outcome: outcome({ headline: 'X', action: 'Y', category: 'workup' }), draft: rows, scope_doubt: ['growth'] });
		expect(verdictOf(p)?.headline).toBe('Check: Growth — Diameter clear growth');
	});
});
