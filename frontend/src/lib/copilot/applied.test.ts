// Applied recommendations (spec 2026-10-14 §7): the item Apply writes, and when it goes stale. SYNTHETIC.
import { describe, expect, it } from 'vitest';
import { card, draft, outcome, preview } from './cards/fixtures';
import { buildApplied, CHANGED, recommendationsForGate, recommendationsKey, staleBlocks, staleOf } from './applied';
import type { Calculation } from './types';

const bts = card({ key: 'bts-pulmonary-nodule', name: 'BTS 2015' });
const p = preview({ proposal: null, draft_outcome: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.', headline: 'Solid nodule', category: 'surveillance' }), trace: { outcome: 'ct3' } });
const calc = (o: Partial<Calculation> = {}): Calculation => ({
	outcome: 'ct3', result: outcome({ classification: 'BTS 2015 · Solid nodule 6-8 mm', recommendation: 'CT at 3 months.' }), exclusion: null, possible: [], needed: [], assumptions: [], trace: null, pack: 'bts@1', bundle: 'b7',
	values: [draft({ input: 'size', state: 'read', value: '7 mm', quote: '7 mm' }), draft({ input: 'kind', state: 'prefilled', value: 'solid' }), draft({ input: 'g', state: 'asked' }), draft({ input: 'side', state: 'not_applicable' })], ...o
});
const x = (o = {}) => ({ key: 'k', card: bts, source: 'BTS 2015', preview: p, calc: calc(), pick: null, ticks: { kind: 'solid' }, ...o });

describe('buildApplied', () => {
	it('writes the reached outcome with its values; a ticked guess is "confirmed"', () => {
		const r = buildApplied(x());
		expect(r).toMatchObject({ key: 'k', pack: 'bts-pulmonary-nodule', version: 'bts@1', bundle: 'b7', source: 'BTS 2015', outcome: 'ct3', sentence: 'Solid nodule 6-8 mm: CT at 3 months (BTS 2015).' });
		expect(typeof r !== 'string' && r.values).toEqual([{ input: 'size', value: '7 mm', state: 'read', quote: '7 mm' }, { input: 'kind', value: 'solid', state: 'confirmed' }]);
		expect(typeof r !== 'string' && r.text).toBe(typeof r !== 'string' && r.sentence);
	});
	it('Calculate disagreeing with the card, or with nothing to write, is refused', () => {
		expect(buildApplied(x({ calc: calc({ outcome: 'pet' }) }))).toBe(CHANGED);
		expect(buildApplied(x({ calc: calc({ result: null }) }))).toBe(CHANGED);
	});
	it('a picked candidate: its own sentence, chosen_from N; an incomplete one is refused', () => {
		const cands = [{ outcome: 'ct3', headline: 'CT', proposal: outcome({ classification: 'X · Solid nodule', recommendation: 'CT at 3 months' }) }, { outcome: 'pet', headline: 'PET', proposal: null }];
		const open = calc({ outcome: null, result: null, candidates: cands });
		expect(buildApplied(x({ calc: open, pick: 'ct3' }))).toMatchObject({ outcome: 'ct3', chosen_from: 2, text: 'Solid nodule: CT at 3 months (BTS 2015).' });
		expect(buildApplied(x({ calc: open, pick: 'pet' }))).toBe(CHANGED);
	});
});

describe('staleOf', () => {
	const rec = buildApplied(x()) as Exclude<ReturnType<typeof buildApplied>, string>;
	it('values: a value behind the line changed; finding: the finding is gone; else current', () => {
		const same = preview({ ...p, draft: [draft({ input: 'size', state: 'read', value: '7 mm' }), draft({ input: 'kind', state: 'prefilled', value: 'solid' })] });
		expect(staleOf(rec, same, true)).toBeUndefined();
		expect(staleOf(rec, preview({ ...same, draft: [draft({ input: 'size', state: 'read', value: '9 mm' }), same.draft![1]] }), true)).toBe('values');
		expect(staleOf(rec, null, true)).toBe('values'); // the card is no longer grouped (its finding's text changed)
		expect(staleOf(rec, null, false)).toBe('finding');
		expect(staleOf(rec, same, false)).toBe('finding'); // the finding went first, whatever the old card still shows
	});
	it('the card outcome moving makes it stale even when every recorded value is unchanged', () => {
		const draftSame = [draft({ input: 'size', state: 'read', value: '7 mm' }), draft({ input: 'kind', state: 'prefilled', value: 'solid' })];
		const moved = preview({ proposal: null, draft_outcome: outcome({ classification: 'BTS 2015 · Other', recommendation: 'PET-CT.', headline: 'Other', category: 'workup' }), trace: { outcome: 'pet' }, draft: draftSame });
		expect(staleOf(rec, moved, true)).toBe('values');
		expect(staleOf(rec, preview({ ...p, state: 'does_not_apply', draft: draftSame }), true)).toBe('values');
	});
	it('only with the flag on does the gate record carry them', () => {
		expect(recommendationsForGate(false, { k: rec })).toEqual([]);
		expect(recommendationsForGate(true, { k: rec })).toEqual([rec]);
		expect(recommendationsForGate(true, undefined)).toEqual([]);
	});
	it('the gate key follows the lines: text, removal and addition change it; order and spacing do not', () => {
		const a = { ...rec, key: 'a', text: 'One.' };
		const b = { ...rec, key: 'b', text: 'Two.' };
		const k = recommendationsKey([a, b]);
		expect(recommendationsKey([{ ...a, text: 'One changed.' }, b])).not.toBe(k);
		expect(recommendationsKey([a])).not.toBe(k);
		expect(recommendationsKey([a, b, { ...rec, key: 'c', text: 'Three.' }])).not.toBe(k);
		expect(recommendationsKey([b, a])).toBe(k);
		expect(recommendationsKey([{ ...a, text: '  One. ' }, b])).toBe(k);
		expect(recommendationsKey([])).toBe(recommendationsKey(recommendationsForGate(false, { k: rec })));
	});
	it('the key follows a line going amber or being re-applied with a new outcome', () => {
		const a = { ...rec, key: 'a' };
		expect(recommendationsKey([{ ...a, stale: 'values' as const }])).not.toBe(recommendationsKey([a]));
		expect(recommendationsKey([{ ...a, outcome: 'pet' }])).not.toBe(recommendationsKey([a]));
	});
	it('staleBlocks: one gate item per amber line, named for why', () => {
		expect(staleBlocks([rec])).toEqual([]);
		expect(staleBlocks([{ ...rec, key: 'a', stale: 'values' }, { ...rec, key: 'b', stale: 'finding' }])).toEqual([
			{ key: 'rec:a', name: 'BTS 2015 recommendation (values changed)' },
			{ key: 'rec:b', name: 'BTS 2015 recommendation (finding removed)' }
		]);
	});
});
