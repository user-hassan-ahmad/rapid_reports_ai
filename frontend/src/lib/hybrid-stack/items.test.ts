import { describe, expect, it } from 'vitest';
import { abnormalAll, anchorRegion, answerLabel, assumedFrom, moreRows, openCount, quietLine, rowSentences, splitRecheck, unansweredChecks } from './items';
import type { StackItem, StackUnit } from './types';

const item = (id: string, sentences: string[], extra: Partial<StackItem> = {}): StackItem => ({
	id, kind: 'finding', region: 'Pelvic organs', question: 'Ovarian torsion?', why: '', sentences, answered: false, ...extra
});

describe('checklist rows', () => {
	it('labels the answer "✓ Normal" however many wordings sit beside it', () => {
		expect(answerLabel(['No features of torsion.'])).toBe('✓ Normal');
		expect(answerLabel(['No torsion.', 'No rupture.', 'No haemorrhage.'])).toBe('✓ Normal');
	});
	it('anchors a finding check under the region of the sentence that set it off', () => {
		const unit = (id: number, text: string, group: string): StackUnit => ({
			id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: true, pinned: false, heading: false
		});
		const units = [unit(0, 'A 3 cm hypoenhancing mass in the pancreatic head.', 'Pancreas'), unit(1, 'It abuts the SMV.', 'Vessels')];
		expect(anchorRegion(item('a', ['x.'], { region: 'Pancreas', source_text: 'abuts the SMV' }), units)).toBe('Vessels');
		expect(anchorRegion(item('b', ['x.'], { region: 'Liver', source_text: 'not dictated' }), units)).toBe('Liver');
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
		const snap = { offered: {}, dictation: 'x', abnormal: ['Spleen'], untouched: ['Liver', 'Bowel'],
			assumed: { Liver: ['The liver is normal.'], Bowel: [], Spleen: ['The spleen is normal.', 'No splenic lesion.'] } };
		expect(assumedFrom(snap, ['Spleen'], ['Liver', 'Bowel', 'Appendix'], ['no splenic lesion']))
			.toEqual({ Spleen: ['The spleen is normal.'], Liver: ['The liver is normal.'] });
		// Liver turned abnormal since the answer: its untouched normals are no longer assumed
		expect(assumedFrom(snap, ['Spleen', 'Liver'], ['Bowel'], [])).toEqual({ Spleen: ['The spleen is normal.', 'No splenic lesion.'] });
		expect(assumedFrom(null, ['Spleen'], [], [])).toEqual({});
	});
	it('rows over the cap wait behind "more checks": never twice, never once skipped', () => {
		const capped = [item('c1', ['No free fluid.']), item('c2', ['No collection.']), item('c3', ['No fistula.'])];
		// c1 was promoted onto the checklist by a later reply; c3 was skipped
		expect(moreRows(capped, [item('a', ['x']), item('c1', ['No free fluid.'])], ['c3']).map((r) => r.id)).toEqual(['c2']);
		expect(moreRows([], [item('a', ['x'])], [])).toEqual([]);
	});
	it('a re-check reply is split back by origin: answered capped rows fold as rows, the rest stay capped', () => {
		const res = {
			items: [item('a', ['No torsion.']), item('c1', [], { answered: true }), item('c2', ['No collection.'])], // c2 promoted by the caps
			capped: [item('c3', ['No fistula.'])]
		};
		const out = splitRecheck(res, ['c1', 'c2', 'c3']);
		expect(out.items.map((r) => r.id)).toEqual(['a', 'c1']);
		expect(out.capped.map((r) => r.id)).toEqual(['c2', 'c3']);
		expect(splitRecheck({ items: [item('a', ['x'])], capped: [] }, [])).toEqual({ items: [item('a', ['x'])], capped: [] });
	});
});
