import { describe, expect, it } from 'vitest';
import { abnormalAll, answerLabel, assumedFrom, openCount, quietLine, rowSentences, unansweredChecks } from './items';
import type { StackItem, StackUnit } from './types';

const item = (id: string, sentences: string[], extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'finding', region: 'Pelvic organs', question: 'Ovarian torsion?', why: '', sentences, answered: false, ...extra
});

describe('checklist rows', () => {
	it('labels the answer briefly; the sentences sit beside it', () => {
		expect(answerLabel(['No features of torsion.'])).toBe('✓ Normal');
		expect(answerLabel(['No torsion.', 'No rupture.'])).toBe('✓ Both normal');
	});
	it('a row lists only the sentences the radiologist has not removed', () => {
		expect(rowSentences(item('a', ['No torsion.', 'No rupture.']), ['no rupture'])).toEqual(['No torsion.']);
	});
	it('only referral rows block; finding checks left unanswered are counted, never blocking', () => {
		const ref = (id: string, s: string[], x: Partial<StackItem> = {}) => item(id, s, { kind: 'referral', ...x });
		const items = [ref('a', ['x.']), ref('b', [], { answered: true }), ref('c', ['y.']), ref('d', ['z.']), ref('e', ['w.']),
			item('f', ['v.']), item('g', ['u.'])];
		expect(openCount(items, ['c'], ['z.'], ['e'])).toBe(1);
		expect(unansweredChecks(items, [], [], ['g'])).toBe(1);
	});
	it('caps the quiet line at three with a count of the rest', () => {
		expect(quietLine(['a', 'b', 'c', 'd', 'e'])).toEqual({ shown: ['a', 'b', 'c'], more: 2 });
		expect(quietLine(['a'])).toEqual({ shown: ['a'], more: 0 });
	});
	it('collects every abnormal sentence (parts included) as the writer cache key', () => {
		const u = (id: number, text: string, extra: Partial<StackUnit>): StackUnit => ({
			id, text, group: 'Liver', structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
		});
		expect(abnormalAll([u(0, 'A cyst.', { abnormal: true }), u(1, 'Kidneys normal.', { group: 'Kidneys' }),
			u(2, 'Spleen normal and a gallstone.', { parts: [{ text: 'Spleen normal', group: 'Spleen' }, { text: 'and a gallstone.', group: 'Gallbladder', abnormal: true }] })]))
			.toEqual(['A cyst.', 'and a gallstone.']);
	});
	it('assumes only what /assumed answered for the region as it is now; removed sentences never', () => {
		const snap = { dictation: 'x', abnormal: ['Spleen'], untouched: ['Liver', 'Bowel'],
			assumed: { Liver: ['The liver is normal.'], Bowel: [], Spleen: ['The spleen is normal.', 'No splenic lesion.'] } };
		expect(assumedFrom(snap, ['Spleen'], ['Liver', 'Bowel', 'Appendix'], ['no splenic lesion']))
			.toEqual({ Spleen: ['The spleen is normal.'], Liver: ['The liver is normal.'] });
		// Liver turned abnormal since the answer: its untouched normals are no longer assumed
		expect(assumedFrom(snap, ['Spleen', 'Liver'], ['Bowel'], [])).toEqual({ Spleen: ['The spleen is normal.', 'No splenic lesion.'] });
		expect(assumedFrom(null, ['Spleen'], [], [])).toEqual({});
	});
});
