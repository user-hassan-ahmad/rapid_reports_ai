import { describe, expect, it } from 'vitest';
import { buildFindingsBlock, conclusionText, findingsHash, findingsText, regionStates, showsGroup } from './regionState';
import type { GateRecord, StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});
const PILLS = ['Liver', 'Kidneys', 'Spleen', 'Bowel'];
const GROUPS = ['Technique', 'Liver', 'Kidneys', 'Spleen', 'Bowel', 'Other findings', 'General', 'Conclusion'];

describe('regionStates', () => {
	it('abnormal regions rise, dictated normals go solid with their words, the rest are assumed normal', () => {
		const units = [
			u(0, 'An 8 mm liver cyst.', 'Liver', { abnormal: true, covers: ['Liver'] }),
			u(1, 'The kidneys are normal.', 'Kidneys', { covers: ['Kidneys'] }),
			u(2, 'The solid organs are otherwise unremarkable.', 'General', { covers: ['Spleen'] })
		];
		const s = regionStates(units, PILLS);
		expect(s.abnormal).toEqual(['Liver']);
		expect(s.dictatedNormal).toEqual([
			{ region: 'Kidneys', words: ['The kidneys are normal.'] },
			{ region: 'Spleen', words: ['The solid organs are otherwise unremarkable.'] }
		]);
		expect(s.assumedNormal).toEqual(['Bowel']);
		expect(s.remainder).toEqual(['Liver']);
	});

	it('a mixed region with a dictated normal needs no remainder line; parts count separately', () => {
		const units = [
			u(0, 'Kidneys are normal, and there is a 3 cm liver cyst.', 'Kidneys', {
				abnormal: true, covers: ['Kidneys', 'Liver'],
				parts: [{ text: 'Kidneys are normal,', group: 'Kidneys', abnormal: false }, { text: 'and there is a 3 cm liver cyst.', group: 'Liver', abnormal: true }]
			}),
			u(1, 'The rest of the liver is normal.', 'Liver', { covers: ['Liver'] })
		];
		const s = regionStates(units, PILLS);
		expect(s.abnormal).toEqual(['Liver']);
		expect(s.dictatedNormal.map((d) => d.region)).toEqual(['Kidneys']);
		expect(s.remainder).toEqual([]);
	});
});

describe('findings block', () => {
	const units = [
		u(0, 'Portal venous phase.', 'Technique'),
		u(1, 'Sigmoid diverticulitis.', 'Bowel', { abnormal: true }),
		u(2, 'It is 10 cm long.', 'Bowel', { abnormal: true, attach_to: 1 }),
		u(3, 'No free gas.', 'Bowel'),
		u(4, 'Liver, spleen and kidneys are normal.', 'General', { covers: ['Liver', 'Spleen', 'Kidneys'] }),
		u(5, 'Conclusion.', 'Conclusion', { heading: true }),
		u(6, 'Acute diverticulitis.', 'Conclusion'),
		u(7, 'Just said.', null)
	];
	it('groups the dictated sentences, keeps general lines and unplaced words', () => {
		expect(findingsText(units, GROUPS)).toBe(
			'Portal venous phase.\n\nBowel: Sigmoid diverticulitis. It is 10 cm long. No free gas.\nLiver, spleen and kidneys are normal.\nJust said.'
		);
		expect(showsGroup(units, 'General')).toBe(false);
		expect(conclusionText(units)).toBe('Acute diverticulitis.');
	});
	it('adds the confirmed normals and conclusion', () => {
		const gate: GateRecord = {
			confirmed_at: 't', conclusion_text: 'Acute diverticulitis.', conclusion_source: 'dictated', assumed_normal: ['Pelvis'],
			remainder_normal: ['Bowel'], dictated_normal: [], accepted_chips: [], units_hash: 'h'
		};
		const block = buildFindingsBlock(units, GROUPS, gate);
		expect(block).toContain('Confirmed normal (not dictated; confirmed by the radiologist): Pelvis; remainder of Bowel.');
		expect(block.endsWith('Conclusion (confirmed by the radiologist): Acute diverticulitis.')).toBe(true);
	});
	it('the findings hash ignores the conclusion and changes with the findings', () => {
		const h = findingsHash(units);
		expect(findingsHash([...units, u(8, 'Recommend follow-up.', 'Conclusion')])).toBe(h);
		expect(findingsHash(units.map((x) => (x.id === 3 ? { ...x, text: 'Small free gas.' } : x)))).not.toBe(h);
	});
});
