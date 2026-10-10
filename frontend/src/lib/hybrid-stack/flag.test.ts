import { describe, expect, it } from 'vitest';
import { HYBRID_STACK_KEY, hybridStackOn } from './flag';

const store = (v: string | null) => ({ getItem: (k: string) => (k === HYBRID_STACK_KEY ? v : null) }) as Storage;

describe('hybridStackOn', () => {
	it('is on when the server allows it and the user has not opted out', () => {
		expect(hybridStackOn(store(null), true)).toBe(true);
	});
	it('is off when the server does not allow it', () => {
		expect(hybridStackOn(store(null), false)).toBe(false);
	});
	it('is off when the user opted out', () => {
		expect(hybridStackOn(store('0'), true)).toBe(false);
	});
});
