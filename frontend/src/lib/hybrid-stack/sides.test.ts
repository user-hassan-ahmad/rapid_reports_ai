import { describe, expect, it } from 'vitest';
import { answerPairs, carrySides, notReported, pairKey, sideChoices, sideFlags, sideRecord, type SideAsk } from './sides';
import type { AssumedSnap } from './items';

const ask = (region: string, label: string, score = 0.9): SideAsk => ({
	region, sentences: [label.replace('right/left', 'right'), label.replace('right/left', 'left')], label, choice: 'no_side', score
});
const K = 'The right/left kidney is normal.';
const H = 'No right/left hydronephrosis.';
const snapOf = (extra: Partial<AssumedSnap>): AssumedSnap => ({ dictation: 'x', abnormal: ['Kidneys'], untouched: [], assumed: {}, offered: {}, ...extra });

describe('sideFlags', () => {
	it('is one blocking "Which side?" check per region, placed by region, listing its pairs', () => {
		const flags = sideFlags([ask('Kidneys', K), ask('Kidneys', H), ask('Pleura', 'No right/left pneumothorax.')]);
		expect(flags.map((f) => [f.kind, f.region, f.blocking, f.unitId, f.quote])).toEqual([
			['side_missing', 'Kidneys', true, null, `${K} · ${H}`],
			['side_missing', 'Pleura', true, null, 'No right/left pneumothorax.']
		]);
		expect(sideFlags([])).toEqual([]);
	});
	it('keeps "Keep without side" per pair: a neighbouring pair joining later asks alone (review F4)', () => {
		const [flag] = sideFlags([ask('Kidneys', H)]);
		const answers = answerPairs(flag, 'as_dictated');
		expect(answers).toEqual({ [pairKey('Kidneys', H)]: 'as_dictated' });
		expect(sideFlags([ask('Kidneys', H)], answers)).toEqual([]);
		expect(sideFlags([ask('Kidneys', K), ask('Kidneys', H)], answers).map((f) => f.quote)).toEqual([K]);
	});
});

describe('carrySides (review F2)', () => {
	const prev = snapOf({ side_asks: [ask('Kidneys', K)] });
	const res = { assumed: { Kidneys: ['The right kidney is normal.', 'No right hydronephrosis.'] }, dropped: { Kidneys: [{ sentence: 'The left kidney is normal.', reason: 'contradicted' }] }, side_asks: [] };
	it('keeps the last open asks when the side call failed, and keeps their sentences out of the report', () => {
		expect(carrySides(prev, res, true)).toEqual({
			assumed: { Kidneys: ['No right hydronephrosis.'] },
			dropped: { Kidneys: [{ sentence: 'The left kidney is normal.', reason: 'contradicted' }, { sentence: 'The right kidney is normal.', reason: 'side' }] },
			side_asks: [ask('Kidneys', K)]
		});
	});
	it('takes a good answer as it is: an ask it no longer has is gone', () => {
		expect(carrySides(prev, res, false)).toEqual({ assumed: res.assumed, dropped: res.dropped, side_asks: [] });
	});
});

describe('sideRecord', () => {
	it('records every pair asked, its score and a distinct ending (review F5)', () => {
		const seen = Object.fromEntries([ask('Kidneys', K, 0.8), ask('Kidneys', H), ask('Lungs', 'The right/left lung is clear.'), ask('Pleura', 'No right/left pneumothorax.')]
			.map((a) => [pairKey(a.region, a.label), a]));
		const snap = snapOf({ side_asks: [ask('Lungs', 'The right/left lung is clear.')],
			side_choices: [{ ...ask('Kidneys', H), choice: 'left', applied: false }] });
		expect(sideRecord(seen, snap, { [pairKey('Kidneys', K)]: 'as_dictated' })).toEqual([
			{ region: 'Kidneys', pair: K, score: 0.8, answered_by: 'kept_without_side' },
			{ region: 'Kidneys', pair: H, score: 0.9, answered_by: 'sided' },
			{ region: 'Lungs', pair: 'The right/left lung is clear.', score: 0.9, answered_by: 'open' },
			{ region: 'Pleura', pair: 'No right/left pneumothorax.', score: 0.9, answered_by: 'gone' }
		]);
	});
});

describe('notReported', () => {
	it('groups the normals left out by why: a conflict, a side not stated, a side not checked (review F7)', () => {
		const s = snapOf({ dropped: { Kidneys: [
			{ sentence: 'The left kidney is normal.', reason: 'contradicted' },
			{ sentence: 'The right kidney is normal.', reason: 'side' },
			{ sentence: 'No right hydronephrosis.', reason: 'both' },
			{ sentence: 'No right calculus.', reason: 'side_unchecked' },
			{ sentence: 'No hydronephrosis.', reason: 'covered' },
			{ sentence: 'No calculus.', reason: 'removed' },
			{ sentence: 'No mass.', reason: 'rule' }
		] } });
		expect(notReported(s, [])).toEqual({ Kidneys: [
			{ why: 'conflicts with dictation', sentences: ['The left kidney is normal.', 'No right hydronephrosis.'] },
			{ why: 'side not stated', sentences: ['The right kidney is normal.'] },
			{ why: 'side not checked', sentences: ['No right calculus.'] }
		] });
	});
	it('never lists a sentence the radiologist removed, and nothing without an answer', () => {
		expect(notReported(snapOf({ dropped: { Kidneys: [{ sentence: 'The left kidney is normal.', reason: 'contradicted' }] } }), ['the left kidney is normal'])).toEqual({});
		expect(notReported(null, [])).toEqual({});
	});
});

describe('sideChoices', () => {
	it('records each pair Jev placed a finding for, its side and whether it dropped both', () => {
		const snap = snapOf({ side_choices: [{ ...ask('Kidneys', K), choice: 'both', applied: true }, { ...ask('Kidneys', H), choice: 'both', applied: false }] });
		expect(sideChoices(snap)).toEqual([
			{ region: 'Kidneys', pair: K, choice: 'both', applied: true },
			{ region: 'Kidneys', pair: H, choice: 'both', applied: false }
		]);
		expect(sideChoices(null)).toEqual([]);
	});
});
