import { describe, expect, it } from 'vitest';
import { abnormalAll, answerLabel, assumedFrom, openCount, quietLine, rowSentences } from './items';
import type { StackItem, StackUnit } from './types';

const item = (id: string, sentences: string[], extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'finding', region: 'Pelvic organs', question: 'Ovarian torsion?', why: '', sentences, answered: false, ...extra
});

describe('checklist rows', () => {
	it('labels the answer by its sentence, or "Both normal" for two', () => {
		expect(answerLabel(['No features of torsion.'])).toBe('No features of torsion');
		expect(answerLabel(['No torsion.', 'No rupture.'])).toBe('Both normal');
	});
	it('a row lists only the sentences the radiologist has not removed', () => {
		expect(rowSentences(item('a', ['No torsion.', 'No rupture.']), ['no rupture'])).toEqual(['No torsion.']);
	});
	it('counts open rows: not answered by the dictation, not tapped, with sentences left', () => {
		const items = [item('a', ['x.']), item('b', [], { answered: true }), item('c', ['y.']), item('d', ['z.'])];
		expect(openCount(items, ['c'], ['z.'])).toBe(1);
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
	it('assumes only what /assumed answered: an emptied or missing region assumes nothing, removed sentences never', () => {
		const checked = { Liver: ['The liver is normal.'], Bowel: [], Spleen: ['The spleen is normal.', 'No splenic lesion.'] };
		expect(assumedFrom(checked, ['Spleen'], ['Liver', 'Bowel', 'Appendix'], ['no splenic lesion']))
			.toEqual({ Spleen: ['The spleen is normal.'], Liver: ['The liver is normal.'] });
	});
});
