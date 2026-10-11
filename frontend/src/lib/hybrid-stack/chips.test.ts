import { describe, expect, it } from 'vitest';
import { abnormalSentences, includedChips, visibleChips, withState, withoutChips } from './chips';
import type { Chip, StackUnit } from './types';

const u = (id: number, text: string, group: string, abnormal: boolean): StackUnit => ({
	id, text, group, structure: null, attach_to: null, parts: null, covers: [], abnormal, pinned: false, heading: false
});
const inc = (text: string): Chip => ({ text, state: 'included' });
const opt = (text: string): Chip => ({ text, state: 'optional' });

describe('chips', () => {
	it('always shows included chips; optional ones fill up to six', () => {
		const by = { A: [inc('a1'), opt('a2'), inc('a3'), inc('a4')], B: [inc('b1'), opt('b2'), opt('b3')], C: [opt('c1')] };
		expect(visibleChips(by, ['A', 'B', 'C']).map((c) => c.text)).toEqual(['a1', 'a2', 'a3', 'b1', 'b2', 'b3']);
		const many = { A: [inc('a1'), inc('a2'), inc('a3')], B: [inc('b1'), inc('b2'), inc('b3')], C: [inc('c1'), opt('c2')] };
		expect(visibleChips(many, ['A', 'B', 'C']).map((c) => c.text)).toEqual(['a1', 'a2', 'a3', 'b1', 'b2', 'b3', 'c1']);
		expect(includedChips(by, ['A', 'B'])).toEqual([{ region: 'A', text: 'a1' }, { region: 'A', text: 'a3' }, { region: 'B', text: 'b1' }]);
	});
	it('removes and opts in by text', () => {
		const by = { A: [inc('No free gas.'), opt('No abscess.')] };
		expect(withoutChips(by, ['no free gas.']).A.map((c) => c.text)).toEqual(['No abscess.']);
		expect(withState(by, 'No abscess.', 'included').A.map((c) => c.state)).toEqual(['included', 'included']);
	});
	it('asks for the region abnormal sentences only', () => {
		expect(abnormalSentences([u(0, 'Cyst.', 'Liver', true), u(1, 'Normal otherwise.', 'Liver', false)], 'Liver')).toEqual(['Cyst.']);
	});
});
