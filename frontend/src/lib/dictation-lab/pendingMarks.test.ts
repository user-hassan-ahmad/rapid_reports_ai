import { describe, expect, it } from 'vitest';
import { EditorState } from '@codemirror/state';
import { clearPending, markPending, pendingField, pendingRanges, replaceAndClear } from './pendingMarks';

function withTwoFinals() {
	// solid text, then final A (faded), then final B (faded)
	let s = EditorState.create({ doc: 'Solid.', extensions: [pendingField] });
	s = s.update({ changes: { from: 6, insert: ' raw final A um er' }, effects: markPending.of({ from: 6, to: 24 }) }).state;
	s = s.update({ changes: { from: 24, insert: ' New paragraph.' }, effects: markPending.of({ from: 24, to: 39 }) }).state;
	return s;
}

describe('pending (faded) marks', () => {
	it('clearing with pre-edit positions after a shorter rewrite wipes the next final (the bug)', () => {
		const s = withTwoFinals();
		const next = s.update({
			changes: { from: 6, to: 24, insert: ' A.' },
			effects: clearPending.of({ from: 6, to: 24 }) // old coordinates
		}).state;
		expect(pendingRanges(next)).toEqual([]); // 'New paragraph.' lost its mark
	});
	it('replaceAndClear keeps the next final faded', () => {
		const s = withTwoFinals();
		const next = s.update(replaceAndClear({ from: 6, to: 24, insert: ' A.' })).state;
		expect(next.doc.toString()).toBe('Solid. A. New paragraph.');
		expect(pendingRanges(next)).toEqual([{ from: 9, to: 24 }]);
	});
	it('replaceAndClear accounts for earlier edits in the same change', () => {
		const s = withTwoFinals();
		const next = s.update(
			replaceAndClear({ from: 6, to: 24, insert: ' A.' }, [{ from: 0, to: 5, insert: 'Firm' }])
		).state;
		expect(next.doc.toString()).toBe('Firm. A. New paragraph.');
		expect(pendingRanges(next)).toEqual([{ from: 8, to: 23 }]);
	});
});
