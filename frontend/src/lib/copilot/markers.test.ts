import { describe, expect, it } from 'vitest';
import { activeFindingOf, findingNumbers, firstCardRef, touch, trackOpen } from './markers';
import { cardRef } from './state';
import { card } from './cards/fixtures';
import type { Group } from './state';

const f = (id: string) => ({ id, unitId: 1, text: id, region: 'R' });
const c = { key: 'k' } as unknown as Group['cards'][number];

describe('findingNumbers', () => {
	it('1, 2, 3 in rail order; the exam group and groups without cards get none', () => {
		const groups: Group[] = [{ finding: null, cards: [c] }, { finding: f('u2'), cards: [c] }, { finding: f('u3'), cards: [] }, { finding: f('u5.1'), cards: [c] }];
		expect(findingNumbers(groups)).toEqual({ u2: 1, 'u5.1': 2 });
	});
});

describe('which finding is active', () => {
	const ca = card({ key: 'bts', finding_id: 'u1' });
	const cb = card({ key: 'bosniak', finding_id: 'u4' });
	const groups: Group[] = [{ finding: f('u1'), cards: [ca] }, { finding: f('u4'), cards: [cb] }];
	it('hover wins; else the most recently opened card; else none', () => {
		expect(activeFindingOf('u1', [cardRef(cb)], groups)).toBe('u1');
		expect(activeFindingOf(null, [cardRef(ca), cardRef(cb)], groups)).toBe('u4');
		expect(activeFindingOf(null, [`${cardRef(ca)}#sibling`], groups)).toBe('u1');
		expect(activeFindingOf(null, [], groups)).toBeNull();
	});
	it('tracks opening order: closed refs drop out, newly opened go last', () => {
		expect(trackOpen(['a', 'b'], ['b', 'c'])).toEqual(['b', 'c']);
		expect(trackOpen([], ['x'])).toEqual(['x']);
	});
	it('revealing a card that is already open moves its finding to the front: touch puts the ref last', () => {
		const order = [cardRef(ca), cardRef(cb)];
		expect(activeFindingOf(null, order, groups)).toBe('u4');
		expect(activeFindingOf(null, touch(order, cardRef(ca)), groups)).toBe('u1');
		expect(touch([], 'x')).toEqual(['x']);
	});
	it('the marker opens the first card of its finding group', () => {
		expect(firstCardRef(groups, 'u4')).toBe(cardRef(cb));
		expect(firstCardRef(groups, 'u1')).toBe(cardRef(ca));
		expect(firstCardRef(groups, 'u9')).toBeNull();
	});
});
