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
	it('answers only: tapped rows, confirmed normals, the conclusion and what was removed', () => {
		const gate: GateRecord = {
			confirmed_at: 't', conclusion_text: 'Acute diverticulitis.', conclusion_source: 'dictated', assumed_normal: ['Pelvis', 'Liver'],
			remainder_normal: ['Bowel'], dictated_normal: [], units_hash: 'h',
			items: [
				{ id: 'a', kind: 'finding', region: 'Bowel', question: 'Abscess?', sentences: ['No pericolic abscess.'], answered_by: 'tap' },
				{ id: 'b', kind: 'finding', region: 'Bowel', question: 'Gas?', sentences: ['No free gas.'], answered_by: 'dictation' },
				{ id: 'c', kind: 'referral', region: 'Appendix', question: 'Appendix?', sentences: ['The appendix is normal.'], answered_by: 'tap' }
			],
			assumed: { Bowel: ['No colonic dilatation.'], Liver: ['The liver is normal.'] },
			removed: ['No fistula.'], capped: []
		};
		const block = buildFindingsBlock(units, GROUPS, gate);
		expect(block).toContain('Bowel: Sigmoid diverticulitis. It is 10 cm long. No free gas. Answered by the radiologist: No pericolic abscess. Assumed normal (confirmed by the radiologist): No colonic dilatation.');
		expect(block).toContain('Appendix (answered by the radiologist): The appendix is normal.');
		expect(block).toContain('Assumed normal (confirmed by the radiologist): Liver: The liver is normal.');
		expect(block).toContain('Confirmed normal (not dictated; confirmed by the radiologist): Pelvis.');   // no sentences yet
		expect(block).not.toContain('remainder of Bowel');                                                   // its sentences were confirmed
		expect(block).toContain('Conclusion (confirmed by the radiologist): Acute diverticulitis.');
		expect(block.endsWith('DO NOT ASSERT (removed by the radiologist): No fistula.')).toBe(true);
	});
	it('the findings hash ignores the conclusion and changes with the findings', () => {
		const h = findingsHash(units);
		expect(findingsHash([...units, u(8, 'Recommend follow-up.', 'Conclusion')])).toBe(h);
		expect(findingsHash(units.map((x) => (x.id === 3 ? { ...x, text: 'Small free gas.' } : x)))).not.toBe(h);
	});
	it('sends a sentence spanning regions whole, once, under its joined label', () => {
		const spanning = [u(0, 'Left rib fractures with a small left pneumothorax.', 'Chest wall', {
			abnormal: true, parts: [{ text: 'Left rib fractures', group: 'Chest wall', abnormal: true },
				{ text: 'with a small left pneumothorax.', group: 'Pleura', abnormal: true }]
		})];
		expect(findingsText(spanning, ['Pleura', 'Chest wall'])).toBe('Pleura · Chest wall: Left rib fractures with a small left pneumothorax.');
	});
});
