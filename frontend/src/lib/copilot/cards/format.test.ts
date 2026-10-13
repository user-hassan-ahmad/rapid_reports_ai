import { describe, expect, it } from 'vitest';
import { card, outcome, preview, result } from './fixtures';
import { assumptionsOf, citeText, columnRef, columnTitles, issuerSlug, missingLabels, openQuestions, outcomeHint, setByExam, stateBadge, valueRows } from './format';

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

	it('missingLabels uses the ask label, else the input id', () => {
		const p = preview({ missing: ['a', 'b'], asks: [{ input: 'a', label: 'Label A' }] });
		expect(missingLabels(p)).toEqual(['Label A', 'b']);
	});

	it('stateBadge and outcomeHint follow the preview', () => {
		expect(stateBadge(null)).toBeNull();
		expect(stateBadge(preview())?.text).toBe('applies');
		expect(stateBadge(preview({ state: 'check_first' }))).toBeNull(); // shown as eligible; the checks are a chip
		expect(stateBadge(preview({ state: 'does_not_apply' }))?.text).toBe('does not apply');
		expect(outcomeHint(preview({ proposal: outcome({ classification: 'X' }) }))).toBe('on these values · X');
		expect(outcomeHint(preview({ proposal: null }))).toBeNull();
		expect(outcomeHint(preview({ proposal: null, draft_outcome: outcome({ classification: 'Y' }) }))).toBe('on these values · Y');
	});

	it('assumptionsOf: Task 3 assumptions when sent, else the missing eligibility inputs; openQuestions: the rest', () => {
		const asks = [
			{ input: 'e1', label: 'Known cancer', role: 'eligibility' },
			{ input: 'c1', label: 'Growth on prior imaging', role: 'clinical' }
		];
		const p = preview({ state: 'check_first', missing: ['e1', 'c1', 'x'], asks });
		expect(assumptionsOf(p)).toEqual(['Known cancer']);
		expect(openQuestions(p)).toEqual(['Growth on prior imaging', 'x']);
		expect(assumptionsOf(preview({ ...p, assumptions: ['From the backend'] }))).toEqual(['From the backend']);
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
			{ input: 'size', label: 'Size', value: '2.2 cm', quote: '2.2 cm nodule', byExam: false },
			{ input: 'age', label: 'Patient age', value: '65', quote: '', byExam: true },
			{ input: 'unenhanced_hu', label: 'Unenhanced hu', value: '8 HU', quote: '', byExam: false }
		]);
	});

	it('setByExam reads Settled.by', () => {
		expect(setByExam(preview())).toBe(false);
		expect(setByExam(preview({ settled: [{ input: 'i', value: 'v', quote: '', fact: '', by: 'exam' }] }))).toBe(true);
	});
});
