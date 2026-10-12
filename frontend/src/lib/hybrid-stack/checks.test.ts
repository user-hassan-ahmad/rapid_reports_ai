import { describe, expect, it } from 'vitest';
import { checkLabel, replaced, segments, toChecks, unitFor } from './checks';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string): StackUnit => ({ id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false });
const units = [u(0, 'There is a 4 mm calculus at the left VUJ.', 'Kidneys'), u(1, 'Perinephric stranding of the right kidney.', 'Kidneys'), u(2, 'The bladder is distended and', 'Bladder')];
const text = units.map((x) => x.text).join(' ');

describe('dictation checks on the scratchpad', () => {
	it('places a truncation on the sentence it ends', () => {
		const end = text.length;
		const [c] = toChecks(text, [{ kind: 'truncation', severity: 'high', excerpt: 'The bladder is distended and', message: 'm', start: end - 3, end }], units);
		expect(c).toMatchObject({ blocking: true, tier: 1, unitId: 2, kind: 'truncation' });
		expect(checkLabel(c.kind)).toBe('Unfinished sentence');
	});
	it('places a conflict on its quote, with the other statement', () => {
		const a = text.indexOf('Perinephric'), b = text.indexOf('There');
		const [c] = toChecks(text, [{ kind: 'laterality_conflict', severity: 'medium', excerpt: 'x', message: 'm', start: a, end: a + units[1].text.length,
			related_start: b, related_end: b + units[0].text.length, blocking: true }], units);
		expect(c).toMatchObject({ blocking: true, tier: 2, unitId: 1, quote: units[1].text, other: units[0].text });
		expect(c.key).toBe('laterality_conflict|perinephric stranding of the right kidney');
	});
	it('a quote no unit holds stays unplaced', () => {
		expect(unitFor('An unrelated sentence entirely.', units)).toBeNull();
	});
	it('a garble carries its suggestion; the backend decides blocking', () => {
		const t = 'Upstream dilatation of the pancreatic duck.';
		const at = t.indexOf('duck');
		const [c] = toChecks(t, [{ kind: 'garbled_phrase', severity: 'medium', excerpt: 'duck', message: 'm', start: at, end: at + 4, suggestion: 'duct', blocking: false }],
			[u(0, t, 'Pancreas')]);
		expect(c).toMatchObject({ blocking: false, tier: 2, suggestion: 'duct', quote: 'duck' });
		expect(replaced(t, c)).toBe('Upstream dilatation of the pancreatic duct.');
		expect(checkLabel(c.kind)).toBe('Possible dictation error');
	});
	it('cuts a line into plain runs and underlined runs, both halves of a conflict included', () => {
		const t = 'A left renal cyst; the right kidney is normal.';
		const c = { key: 'k', kind: 'laterality_conflict', blocking: true, tier: 2 as const, message: '', quote: 'right kidney', other: 'left renal cyst', suggestion: '', unitId: 0 };
		expect(segments(t, [c]).map((x) => [x.text, !!x.check])).toEqual([
			['A ', false], ['left renal cyst', true], ['; the ', false], ['right kidney', true], [' is normal.', false]
		]);
		expect(segments('No checks here.', [])).toEqual([{ text: 'No checks here.', check: null }]);
	});
});
