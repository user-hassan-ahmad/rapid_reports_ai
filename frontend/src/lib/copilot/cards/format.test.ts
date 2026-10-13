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
		expect(openQuestions(p)).toEqual(['Hormone excess', 'Washout', 'Growth']); // eligibility first, then needed
	});

	it('setByExam reads Settled.by', () => {
		expect(setByExam(preview())).toBe(false);
		expect(setByExam(preview({ settled: [{ input: 'i', value: 'v', quote: '', fact: '', by: 'exam' }] }))).toBe(true);
	});
});
