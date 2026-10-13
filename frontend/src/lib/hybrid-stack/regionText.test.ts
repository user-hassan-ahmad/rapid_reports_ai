import { describe, expect, it } from 'vitest';
import { regionText } from './regionState';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string | null, extra: Partial<StackUnit> = {}): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal: false, pinned: false, heading: false, ...extra
});

describe('regionText', () => {
	it("is each findings region's own sentences or split parts; fixed groups and unplaced units give nothing", () => {
		const units = [
			u(0, 'CT with contrast.', 'Technique'),
			u(1, 'Normal study.', 'General', { covers: ['Liver'] }),
			u(2, 'No acute abnormality.', 'Conclusion'),
			u(3, 'Liver cyst.', 'Liver', { abnormal: true }),
			u(4, 'Unplaced.', null),
			u(5, 'Liver:', 'Liver', { heading: true }),
			u(6, 'Fatty liver and normal kidneys.', 'Liver', {
				parts: [{ text: 'Fatty liver', group: 'Liver', abnormal: true }, { text: 'normal kidneys.', group: 'Kidneys' }]
			}),
			u(7, 'No hydronephrosis.', 'Kidneys')
		];
		// "Normal study." names Liver in its covers: it is said of Liver, so it may cover Liver's normals (round 1)
		expect(regionText(units)).toEqual({ Liver: 'Liver cyst. Fatty liver Normal study.', Kidneys: 'normal kidneys. No hydronephrosis.' });
	});

	it('a collective normal reaches every region it covers, once (round 1: no duplicate of a dictated normal)', () => {
		const units = [
			u(0, 'Solid organs unremarkable.', 'General', { covers: ['Spleen', 'Pancreas'] }),
			u(1, 'Liver, spleen and pancreas normal.', 'Liver', { covers: ['Liver', 'Spleen', 'Pancreas'] }),
			u(2, 'A splenic cyst.', 'Spleen', { abnormal: true, covers: ['Kidneys'] }), // abnormal: covers nothing
			u(3, 'Kidneys:', 'Kidneys', { heading: true, covers: ['Kidneys'] })
		];
		expect(regionText(units)).toEqual({
			Liver: 'Liver, spleen and pancreas normal.',
			Spleen: 'A splenic cyst. Solid organs unremarkable. Liver, spleen and pancreas normal.',
			Pancreas: 'Solid organs unremarkable. Liver, spleen and pancreas normal.'
		});
	});

	it('a bare normal grouped General covers no region', () => {
		expect(regionText([u(0, 'normal', 'General')])).toEqual({});
	});
});
