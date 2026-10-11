import { describe, expect, it } from 'vitest';
import { buildView, liveTail, moveUnit, sentenceOffset } from './stackState';
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

	it('shows split parts in their own groups', () => {
		const units = [u(0, 'Kidneys normal, and a liver cyst.', 'Kidneys', {
			parts: [{ text: 'Kidneys normal,', group: 'Kidneys' }, { text: 'and a liver cyst.', group: 'Liver' }]
		})];
		const v = buildView(units, GROUPS);
		expect(v.groups.map((g) => [g.name, g.rows[0].text, g.rows[0].partOf])).toEqual([
			['Liver', 'and a liver cyst.', 0],
			['Kidneys', 'Kidneys normal,', 0]
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
});
