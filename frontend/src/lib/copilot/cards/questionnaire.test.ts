// The questionnaire card's pure parts (spec 2026-10-14 §4, §6). SYNTHETIC previews.
import { describe, expect, it } from 'vitest';
import { NOT_STATED } from '../state';
import type { Ask, Candidate } from '../types';
import { draft, outcome, preview } from './fixtures';
import { answeredChips, basedOn, checkItems, nextAsk, readiness, remaining, sentenceOf, statusLine } from './questionnaire';

const ask = (input: string, label = input): Ask => ({ input, label, options: ['a', 'b'] });
const reached = (over = {}) =>
	preview({
		proposal: null,
		draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.' }),
		draft: [
			draft({ input: 'size', label: 'Size', state: 'read', value: '7 mm', quote: '7 mm' }),
			draft({ input: 'kind', label: 'Type', state: 'prefilled', value: 'solid', decisive: true, options: ['solid', 'subsolid', NOT_STATED] }),
			draft({ input: 'spic', label: 'Spiculation', state: 'assumed', value: 'No', decisive: false }),
			draft({ input: 'elig', label: 'Known cancer', role: 'eligibility', state: 'assumed', value: 'No', decisive: null }),
			draft({ input: 'side', label: 'Side', state: 'not_applicable' })
		],
		...over
	});

describe('checkItems', () => {
	it('lists decisive (or unweighed) pre-filled and assumed values and scope doubts; never read or non-decisive ones', () => {
		expect(checkItems(reached()).map((c) => [c.input, c.kind])).toEqual([['kind', 'prefilled'], ['elig', 'assumed']]);
		const doubt = reached({ scope_doubt: ['kind'] });
		expect(checkItems(doubt).find((c) => c.input === 'kind')).toMatchObject({ kind: 'doubt', affirmed: false });
		expect(checkItems(preview({ state: 'does_not_apply', draft: reached().draft }))).toEqual([]);
	});
	it('a tick counts only for the value it affirmed', () => {
		expect(checkItems(reached(), { kind: 'solid' }).find((c) => c.input === 'kind')?.affirmed).toBe(true);
		const reread = reached({ draft: reached().draft!.map((d) => (d.input === 'kind' ? { ...d, value: 'subsolid' } : d)) });
		expect(checkItems(reread, { kind: 'solid' }).find((c) => c.input === 'kind')?.affirmed).toBe(false);
		expect(checkItems(reached({ scope_doubt: ['kind'] }), { kind: 'solid' })[0].affirmed).toBe(false); // a doubt is never ticked
	});
});

describe('the next question and the answers so far', () => {
	const open = preview({ proposal: null, asks: [ask('growth', 'Growth'), ask('smoker', 'Smoker')], draft: [draft({ input: 'growth', label: 'Growth', state: 'asked', options: ['Yes', 'No', NOT_STATED] }), draft({ input: 'smoker', label: 'Smoker', state: 'asked' })] });
	it('asks in the order the engine sends; "Not known" moves on', () => {
		expect(nextAsk(open)?.input).toBe('growth');
		expect(nextAsk(open, { growth: NOT_STATED })?.input).toBe('smoker');
		expect(remaining(open, { growth: NOT_STATED })).toBe(1);
		expect(nextAsk(open, { growth: NOT_STATED, smoker: NOT_STATED })).toBeNull();
		expect(nextAsk(preview({ state: 'does_not_apply', asks: [ask('x')] }))).toBeNull();
	});
	it('chips list every answer with the row options, "Not known" included', () => {
		expect(answeredChips(open, { growth: NOT_STATED, gone: 'x' })).toEqual([{ input: 'growth', label: 'Growth', value: NOT_STATED, options: ['Yes', 'No', NOT_STATED] }]);
	});
	it('"Based on" holds the shown values that are not in Check', () => {
		const p = reached();
		expect(basedOn(p, checkItems(p)).map((d) => d.input)).toEqual(['size', 'spic']);
	});
});

describe('readiness and the status line', () => {
	const cand = (outcome_: string, complete: boolean): Candidate => ({ outcome: outcome_, headline: outcome_, category: 'surveillance', proposal: complete ? outcome({ classification: `X · ${outcome_}` }) : null });
	it('reached: ready once every Check item is ticked', () => {
		expect(readiness(reached())).toBe('check');
		expect(statusLine(reached())).toBe('Check 2 values to apply');
		expect(readiness(reached(), {}, { kind: 'solid', elig: 'No' })).toBeNull();
		expect(statusLine(reached(), {}, { kind: 'solid', elig: 'No' })).toBe('');
	});
	it('open: the question first, then a pick of a complete candidate', () => {
		const p = preview({ proposal: null, bounded: false, asks: [ask('g', 'Growth')], draft: [draft({ input: 'g', label: 'Growth', state: 'asked' })], candidates: [cand('ct3', true), cand('pet', false)] });
		expect(readiness(p)).toBe('question');
		expect(statusLine(p)).toBe('up to 1 question to a recommendation');
		const left = { g: NOT_STATED };
		expect(readiness(p, left)).toBe('pick');
		expect(statusLine(p, left)).toBe('Pick the outcome that fits');
		expect(readiness(p, left, {}, 'pet')).toBe('incomplete');
		expect(readiness(p, left, {}, 'ct3')).toBeNull();
		expect(readiness(p, left, {}, 'gone')).toBe('pick');
	});
	it('excluded: never ready', () => {
		expect(readiness(preview({ state: 'does_not_apply' }))).toBe('excluded');
	});
});

describe('sentenceOf', () => {
	it('classification without the guideline prefix, then the recommendation, then the source', () => {
		expect(sentenceOf(outcome({ classification: 'BTS 2015 · solid nodule 6-8 mm', recommendation: 'CT at 3 months.' }), 'BTS 2015')).toBe('Solid nodule 6-8 mm: CT at 3 months (BTS 2015).');
		expect(sentenceOf(outcome({ classification: 'Category 2', recommendation: '', action: 'No follow-up' }), 'Bosniak 2019')).toBe('Category 2: No follow-up (Bosniak 2019).');
		expect(sentenceOf(outcome({ classification: 'Benign', recommendation: '' }), 'ESE 2023')).toBe('Benign (ESE 2023).');
	});
});
