import { describe, expect, it } from 'vitest';
import { checkLabel, toChecks, unitFor } from './checks';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string): StackUnit => ({ id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false });
const units = [u(0, 'There is a 4 mm calculus at the left VUJ.', 'Kidneys'), u(1, 'Perinephric stranding of the right kidney.', 'Kidneys'), u(2, 'The bladder is distended and', 'Bladder')];
const text = units.map((x) => x.text).join(' ');

describe('dictation checks on the scratchpad', () => {
	it('places a truncation on the sentence it ends', () => {
		const end = text.length;
		const [c] = toChecks(text, [{ kind: 'truncation', severity: 'high', excerpt: 'The bladder is distended and', message: 'm', start: end - 3, end }], units);
		expect(c).toMatchObject({ blocking: true, unitId: 2, kind: 'truncation' });
		expect(checkLabel(c.kind)).toBe('Unfinished sentence?');
	});
	it('places a conflict on its quote, with the other statement', () => {
		const a = text.indexOf('Perinephric'), b = text.indexOf('There');
		const [c] = toChecks(text, [{ kind: 'laterality_conflict', severity: 'medium', excerpt: 'x', message: 'm', start: a, end: a + units[1].text.length,
			related_start: b, related_end: b + units[0].text.length }], units);
		expect(c).toMatchObject({ blocking: false, unitId: 1, quote: units[1].text, other: units[0].text });
		expect(c.key).toBe('laterality_conflict|perinephric stranding of the right kidney');
	});
	it('a quote no unit holds stays unplaced', () => {
		expect(unitFor('An unrelated sentence entirely.', units)).toBeNull();
	});
});
