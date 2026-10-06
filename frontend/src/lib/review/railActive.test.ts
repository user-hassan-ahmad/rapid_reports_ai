import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mem = new Map<string, string>();
vi.stubGlobal('sessionStorage', {
	getItem: (k: string) => mem.get(k) ?? null,
	setItem: (k: string, v: string) => void mem.set(k, v),
	removeItem: (k: string) => void mem.delete(k)
});

const mod = await import('./railActive');

beforeEach(() => mod.resetRailMemory());

describe('holdsAside', () => {
	it('holds while a rail shows, or before the report settles unless the session knows there is no rail', () => {
		expect(mod.holdsAside(true, false, 'none')).toBe(true);
		expect(mod.holdsAside(false, null, undefined)).toBe(true); // first-ever load: wait
		expect(mod.holdsAside(false, true, undefined)).toBe(true); // rail expected
		expect(mod.holdsAside(false, false, undefined)).toBe(false); // known: no rail
		expect(mod.holdsAside(false, true, 'none')).toBe(false); // settled without a rail
		expect(mod.holdsAside(false, true, 'rail')).toBe(true); // settled on a rail: held even while it is re-set up
	});
});

describe('rail memory', () => {
	it('remembers the mode in sessionStorage and per-report outcomes', () => {
		expect(get(mod.reviewRailExpected)).toBeNull();
		mod.rememberRailMode(true);
		expect(get(mod.reviewRailExpected)).toBe(true);
		expect(mem.get('rr_review_rail')).toBe('1');
		const holds = mod.reviewRailHoldsAside('r1');
		expect(get(holds)).toBe(true);
		mod.recordRailOutcome('r1', 'none');
		expect(get(holds)).toBe(false);
		mod.setReviewRailActive({}, true);
		expect(get(holds)).toBe(true);
	});

	it('no report id never holds the aside unless a rail is active', () => {
		mod.rememberRailMode(true);
		expect(get(mod.reviewRailHoldsAside(null))).toBe(false);
	});
});
