import { describe, expect, it } from 'vitest';
import { appendSentence, buildView, closedText, heldBack, lineChange, liveTail, moveUnit, sentenceOffset } from './stackState';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false, ...extra
});
const GROUPS = ['Technique', 'Liver', 'Kidneys', 'General', 'Conclusion'];

describe('buildView', () => {
	it('orders groups by the schema, nests attached sentences, hides headings, keeps unplaced apart', () => {
		const units = [
			u(0, 'CT abdomen.', 'Technique'),
			u(1, 'Kidneys normal.', 'Kidneys'),
			u(2, 'A liver cyst.', 'Liver'),
			u(3, 'It measures 2 cm.', 'Liver', { attach_to: 2 }),
			u(4, 'Conclusion.', 'Conclusion', { heading: true }),
			u(5, 'Simple cyst.', 'Conclusion'),
			u(6, 'Just said.', null)
		];
		const v = buildView(units, GROUPS);
		expect(v.groups.map((g) => g.name)).toEqual(['Technique', 'Liver', 'Kidneys', 'Conclusion']);
		expect(v.groups[1].rows[0].children.map((c) => c.text)).toEqual(['It measures 2 cm.']);
		expect(v.groups[3].rows.map((r) => r.text)).toEqual(['Simple cyst.']);
		expect(v.unplaced.map((r) => r.text)).toEqual(['Just said.']);
	});

	it('keeps a sentence spanning regions whole, under one heading joining them, where its first region sits', () => {
		const units = [u(0, 'Kidneys normal, and a liver cyst.', 'Kidneys', {
			parts: [{ text: 'Kidneys normal,', group: 'Kidneys' }, { text: 'and a liver cyst.', group: 'Liver' }]
		}), u(1, 'A renal cyst.', 'Kidneys')];
		const v = buildView(units, GROUPS);
		expect(v.groups.map((g) => [g.name, g.members, g.rows.map((r) => [r.text, r.partOf])])).toEqual([
			['Liver · Kidneys', ['Liver', 'Kidneys'], [['Kidneys normal, and a liver cyst.', null]]],
			['Kidneys', ['Kidneys'], [['A renal cyst.', null]]]
		]);
	});
});

describe('moveUnit', () => {
	it('pins the sentence in the new group and clears its link and parts', () => {
		const units = [u(0, 'A.', 'Liver'), u(1, 'B.', 'Liver', { attach_to: 0, parts: [] })];
		const moved = moveUnit(units, 1, 'Kidneys');
		expect(moved[1]).toMatchObject({ group: 'Kidneys', pinned: true, attach_to: null, parts: null });
		expect(units[1].group).toBe('Liver');
	});
});

describe('sentenceOffset', () => {
	it('finds the nth occurrence of a sentence', () => {
		expect(sentenceOffset('A. B. A.', [u(0, 'A.', 'x'), u(1, 'B.', 'x'), u(2, 'A.', 'x')], 2)).toBe(6);
	});
});

describe('liveTail', () => {
	it('returns the sentences of the verbatim text that no unit holds yet, in order', () => {
		const units = [u(0, 'Liver normal.', 'Liver'), u(1, 'Spleen normal.', null)];
		expect(liveTail('Liver normal. Spleen normal. Kidneys normal. Pancreas', units)).toEqual(['Kidneys normal.', 'Pancreas']);
	});
	it('counts repeated sentences', () => {
		expect(liveTail('No change. No change.', [u(0, 'No change.', 'General')])).toEqual(['No change.']);
	});
	it('keeps decimals whole', () => {
		expect(liveTail('A 3.2 cm cyst.', [])).toEqual(['A 3.2 cm cyst.']);
	});
	it('never brings back a placed sentence the polish reworded', () => {
		const units = [u(0, 'There is a 3 cm mass in the pancreatic head', 'Pancreas'), u(1, 'The liver is normal.', 'Liver')];
		expect(liveTail('There is a 3 cm mass in the pancreatic head. The liver is normal. The spleen', units)).toEqual(['The spleen']);
	});
});

describe('lineChange / appendSentence', () => {
	const text = 'Liver cyst. Kidneys are normal, and a 3 cm spleen. Liver cyst.';
	const units = [
		u(0, 'Liver cyst.', 'Liver'),
		u(1, 'Kidneys are normal, and a 3 cm spleen.', 'Kidneys', {
			parts: [{ text: 'Kidneys are normal,', group: 'Kidneys' }, { text: 'and a 3 cm spleen.', group: 'Spleen' }]
		}),
		u(2, 'Liver cyst.', 'Liver')
	];
	it('edits the nth occurrence and a part in place', () => {
		expect(lineChange(text, units, 2, null, 'Liver cysts.')).toEqual({ from: 51, to: 62, insert: 'Liver cysts.' });
		const c = lineChange(text, units, 1, 1, 'and a 4 cm spleen.')!;
		expect(text.slice(0, c.from) + c.insert + text.slice(c.to)).toBe('Liver cyst. Kidneys are normal, and a 4 cm spleen. Liver cyst.');
	});
	it('removes a line with one neighbouring space', () => {
		const c = lineChange(text, units, 0, null, '')!;
		expect(text.slice(0, c.from) + text.slice(c.to)).toBe('Kidneys are normal, and a 3 cm spleen. Liver cyst.');
		const d = lineChange(text, units, 2, null, '')!;
		expect(text.slice(0, d.from) + text.slice(d.to)).toBe('Liver cyst. Kidneys are normal, and a 3 cm spleen.');
	});
	it('appends with one separator', () => {
		expect(appendSentence('A.', 'No free gas.')).toBe(' No free gas.');
		expect(appendSentence('A.\n', 'No free gas.')).toBe('No free gas.');
		expect(appendSentence('', 'No free gas.')).toBe('No free gas.');
	});
});

describe('sentenceOffset boundaries', () => {
	it('never matches a sentence inside a longer one', () => {
		const text = 'Pancreas: Unremarkable. Unremarkable.';
		const units = [u(0, 'Pancreas: Unremarkable.', 'Pancreas'), u(1, 'Unremarkable.', 'Spleen')];
		expect(sentenceOffset(text, units, 1)).toBe(24);
	});

describe('closedText', () => {
	it('holds back the sentence still being spoken', () => {
		expect(closedText('A liver cyst. The kidneys are')).toBe('A liver cyst.');
		expect(closedText('A liver cyst. The kidneys are normal.')).toBe('A liver cyst.');
		expect(closedText('A liver cyst.')).toBe('');
	});
});

	it('heldBack keeps a placed sentence the new words ran on from (live trace 2026-10-12)', () => {
		const mk = (id: number, text: string): StackUnit => ({ id, text, group: 'Kidneys', structure: null, attach_to: null, parts: null, covers: [], pinned: false, heading: false });
		const units = [mk(0, 'A 4 mm calculus at the left VUJ.'), mk(1, 'And extensive perinephric stranding')];
		const v = 'A 4 mm calculus at the left VUJ. And extensive perinephric stranding A tiny non-obstructing 2 mm calculus';
		expect(heldBack(v, units)).toBe('A 4 mm calculus at the left VUJ. And extensive perinephric stranding');
		// the sentence being spoken, with nothing placed in it, is still held back
		expect(heldBack('A 4 mm calculus at the left VUJ. Moderate hydro', units.slice(0, 1))).toBe('A 4 mm calculus at the left VUJ.');
		// a placed last sentence is never held back
		expect(heldBack('A 4 mm calculus at the left VUJ. And extensive perinephric stranding.', units)).toBe(
			'A 4 mm calculus at the left VUJ. And extensive perinephric stranding.');
	});
});
