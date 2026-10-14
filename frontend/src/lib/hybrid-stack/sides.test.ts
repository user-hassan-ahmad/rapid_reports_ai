import { describe, expect, it } from 'vitest';
import { notReported, sideFlags, sideRecord, type SideAsk } from './sides';
import type { AssumedSnap } from './items';

const ask = (region: string, label: string, score = 0.9): SideAsk => ({
	region, sentences: [label.replace('right/left', 'right'), label.replace('right/left', 'left')], label, score
});

describe('sideFlags', () => {
	it('is one blocking "Which side?" check per region, placed by region, listing its pairs', () => {
		const flags = sideFlags([ask('Kidneys', 'The right/left kidney is normal.'), ask('Kidneys', 'No right/left hydronephrosis.'), ask('Pleura', 'No right/left pneumothorax.')]);
		expect(flags.map((f) => [f.kind, f.region, f.blocking, f.unitId, f.quote])).toEqual([
			['side_missing', 'Kidneys', true, null, 'The right/left kidney is normal. · No right/left hydronephrosis.'],
			['side_missing', 'Pleura', true, null, 'No right/left pneumothorax.']
		]);
	});
	it('keys a flag on its region and pairs, so a new side-less pair there asks again', () => {
		const one = sideFlags([ask('Kidneys', 'The right/left kidney is normal.')])[0].key;
		const two = sideFlags([ask('Kidneys', 'The right/left kidney is normal.'), ask('Kidneys', 'No right/left hydronephrosis.')])[0].key;
		expect(one).not.toEqual(two);
		expect(sideFlags([])).toEqual([]);
	});
});

describe('sideRecord', () => {
	it('records every ask seen and how it ended: kept without a side, cleared by the dictation, or open', () => {
		const [a, b, c] = sideFlags([ask('Kidneys', 'The right/left kidney is normal.'), ask('Pleura', 'No right/left pneumothorax.'), ask('Lungs', 'The right/left lung is clear.')]);
		const seen = { [a.key]: a, [b.key]: b, [c.key]: c };
		expect(sideRecord(seen, [a, c], { [a.key]: 'as_dictated' })).toEqual([
			{ region: 'Kidneys', pairs: ['The right/left kidney is normal.'], answered_by: 'as_dictated' },
			{ region: 'Pleura', pairs: ['No right/left pneumothorax.'], answered_by: 'dictated' },
			{ region: 'Lungs', pairs: ['The right/left lung is clear.'], answered_by: 'open' }
		]);
	});
});

describe('notReported', () => {
	const snap = (dropped: AssumedSnap['dropped']): AssumedSnap => ({ dictation: 'x', abnormal: ['Kidneys'], untouched: [], assumed: {}, offered: {}, dropped });
	it('lists the normals left out because they conflict with the dictation: contradicted, or a side not dictated', () => {
		const s = snap({ Kidneys: [
			{ sentence: 'The left kidney is normal.', reason: 'contradicted' },
			{ sentence: 'The right kidney is normal.', reason: 'side' },
			{ sentence: 'No hydronephrosis.', reason: 'covered' },
			{ sentence: 'No calculus.', reason: 'removed' },
			{ sentence: 'No mass.', reason: 'rule' }
		] });
		expect(notReported(s, [])).toEqual({ Kidneys: ['The left kidney is normal.', 'The right kidney is normal.'] });
	});
	it('never lists a sentence the radiologist removed, and nothing without an answer', () => {
		expect(notReported(snap({ Kidneys: [{ sentence: 'The left kidney is normal.', reason: 'contradicted' }] }), ['the left kidney is normal'])).toEqual({});
		expect(notReported(null, [])).toEqual({});
	});
});
