import { describe, expect, it } from 'vitest';
import { findReading, planRevision, type Revision } from './revisions';

const rev = (over: Partial<Revision> = {}): Revision => ({
	final_seq: 1, switches: [], suggestions: [], recovered: null, spans: 1, errors: [], ms: 900, ...over
});

describe('two-pass revisions', () => {
	it('finds the heard words as whole words, case-insensitive, across hyphens', () => {
		expect(findReading('Further supplemental emboli.', 'supplemental')).toEqual({ from: 8, to: 20 });
		expect(findReading('A small wedge-shaped area', 'wedge shaped')).toEqual({ from: 8, to: 20 });
		expect(findReading('Tidal cyst', 'tidal')).toEqual({ from: 0, to: 5 });
		expect(findReading('supplementals', 'supplemental')).toBeNull();
	});

	it('a confident switch becomes an edit, keeping a leading capital', () => {
		const p = planRevision('Tidal cyst at S2.', rev({ switches: [{ from: 'tidal', to: 'tarlov', confidence: 0.95 }] }), true);
		expect(p.edits).toEqual([{ from: 0, to: 5, insert: 'Tarlov' }]);
		expect(p.underlines).toEqual([]);
	});

	it('a suggestion becomes an underline with the other reading on hover', () => {
		const p = planRevision('There is a small tidal cyst.', rev({ suggestions: [{ from: 'tidal', to: 'tarlov', confidence: 0.84 }] }), true);
		expect(p.edits).toEqual([]);
		expect(p.underlines).toEqual([{ from: 17, to: 22, message: 'Also heard as “tarlov” (0.84)' }]);
	});

	it('when the text was edited by hand, a switch is only underlined', () => {
		const p = planRevision('Further supplemental emboli.', rev({ switches: [{ from: 'supplemental', to: 'subsegmental', confidence: 0.97 }] }), false);
		expect(p.edits).toEqual([]);
		expect(p.underlines[0].message).toBe('Also heard as “subsegmental” (0.97)');
	});

	it('counts readings that are no longer in the text', () => {
		const p = planRevision('Further emboli.', rev({ switches: [{ from: 'supplemental', to: 'subsegmental', confidence: 0.97 }] }), true);
		expect(p.unmatched).toBe(1);
	});
});
