import { describe, expect, it } from 'vitest';
import { editTouches, integrityMarks } from './integrityMarks';

describe('integrityMarks', () => {
	it('marks each flag with its kind and message, and the other half of a conflict', () => {
		const marks = integrityMarks([
			{ kind: 'internal_contradiction', message: 'Effusion stated absent and present.', start: 40, end: 70, related_start: 0, related_end: 20 },
			{ kind: 'truncation', message: 'Ends mid-statement.', start: 80, end: 83 }
		]);
		expect(marks).toEqual([
			{ from: 40, to: 70, kind: 'internal_contradiction', message: 'Effusion stated absent and present.', related: false },
			{ from: 0, to: 20, kind: 'internal_contradiction', message: 'Conflicts with a later statement: Effusion stated absent and present.', related: true },
			{ from: 80, to: 83, kind: 'truncation', message: 'Ends mid-statement.', related: false }
		]);
	});

	it('drops ranges that are empty or outside the document', () => {
		expect(integrityMarks([{ kind: 'x', message: 'm', start: 5, end: 5 }], 100)).toEqual([]);
		expect(integrityMarks([{ kind: 'x', message: 'm', start: 90, end: 120 }], 100)).toEqual([]);
		const m = integrityMarks([{ kind: 'x', message: 'm', start: 0, end: 4, related_start: 90, related_end: 120 }], 100);
		expect(m.map((x) => x.related)).toEqual([false]);
	});

	it('accepts plain ranges from older callers', () => {
		expect(integrityMarks([{ from: 1, to: 3 }])).toEqual([{ from: 1, to: 3, kind: 'flag', message: '', related: false }]);
	});
});

describe('editTouches', () => {
	it('an edit inside or across a flagged span touches it', () => {
		expect(editTouches(5, 8, 0, 10)).toBe(true); // replace inside
		expect(editTouches(8, 15, 0, 10)).toBe(true); // across the end
		expect(editTouches(4, 4, 0, 10)).toBe(true); // typing inside
	});
	it('text added right after or before a span (dictation appending) does not', () => {
		expect(editTouches(10, 10, 0, 10)).toBe(false);
		expect(editTouches(0, 0, 0, 10)).toBe(false);
		expect(editTouches(12, 20, 0, 10)).toBe(false);
	});
});
