import { describe, expect, it } from 'vitest';
import { coveredStructures, regionChips } from './subPills';

const S = {
	'Cardiac chambers': ['Normal appearance of the cardiac chambers.'],
	Lungs: ['No suspicious parenchymal nodules.'],
	Effusions: ['No pleural or pericardial effusion.']
};
const ALL = ['Normal appearance of the cardiac chambers.', 'No suspicious parenchymal nodules.', 'No pleural or pericardial effusion.', 'No incidental finding of note.'];

describe('regionChips', () => {
	it('a region with no structure split is one chip, as today', () => {
		expect(regionChips('Liver', ['Normal liver.'], undefined)).toEqual([{ key: 'Liver', region: 'Liver', label: 'Liver', sentences: ['Normal liver.'] }]);
	});

	it('splits kept sentences by structure; an unbound sentence stays on the paragraph chip, once', () => {
		const chips = regionChips('Other Findings', ALL, S);
		expect(chips.map((c) => [c.label, c.sentences])).toEqual([
			['Cardiac chambers', ['Normal appearance of the cardiac chambers.']],
			['Lungs', ['No suspicious parenchymal nodules.']],
			['Effusions', ['No pleural or pericardial effusion.']],
			['Other Findings', ['No incidental finding of note.']]
		]);
		expect(new Set(chips.map((c) => c.key)).size).toBe(4);
		expect(chips.flatMap((c) => c.sentences).sort()).toEqual([...ALL].sort());
	});

	it('a structure with nothing left to assume has no chip; matching ignores case and a final stop', () => {
		const chips = regionChips('Other Findings', ['no suspicious parenchymal nodules'], S);
		expect(chips.map((c) => c.label)).toEqual(['Lungs']);
	});

	it('nothing kept at all: the paragraph chip alone, empty (the caller decides whether it shows)', () => {
		expect(regionChips('Other Findings', [], S)).toEqual([{ key: 'Other Findings', region: 'Other Findings', label: 'Other Findings', sentences: [] }]);
	});
});

describe('coveredStructures', () => {
	it('a structure whose sentences the dictation dropped is covered; one removed by the radiologist is not', () => {
		const assumed = ['Normal appearance of the cardiac chambers.'];
		expect(coveredStructures(assumed, ['No pleural or pericardial effusion'], S)).toEqual(['Lungs']);
	});

	it('no split: nothing', () => {
		expect(coveredStructures([], [], undefined)).toEqual([]);
	});
});
