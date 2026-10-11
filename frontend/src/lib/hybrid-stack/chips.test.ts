import { describe, expect, it } from 'vitest';
import { abnormalSentences, visibleChips, withoutChips } from './chips';
import type { StackUnit } from './types';

const u = (id: number, text: string, group: string, abnormal: boolean): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
});

describe('chips', () => {
	it('caps three per region and six on screen, in region order', () => {
		const by = { A: ['a1', 'a2', 'a3', 'a4'], B: ['b1', 'b2', 'b3'], C: ['c1'] };
		expect(visibleChips(by, ['A', 'B', 'C']).map((c) => c.text)).toEqual(['a1', 'a2', 'a3', 'b1', 'b2', 'b3']);
		expect(visibleChips(withoutChips(by, ['A2', 'b1']), ['A', 'B', 'C']).map((c) => c.text)).toEqual(['a1', 'a3', 'a4', 'b2', 'b3', 'c1']);
	});
	it('asks for the region abnormal sentences only', () => {
		expect(abnormalSentences([u(0, 'Cyst.', 'Liver', true), u(1, 'Normal otherwise.', 'Liver', false)], 'Liver')).toEqual(['Cyst.']);
	});
});
