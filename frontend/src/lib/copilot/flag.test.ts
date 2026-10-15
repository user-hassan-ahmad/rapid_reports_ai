import { describe, expect, it } from 'vitest';
import { applyOn, copilotOn } from './flag';

// D24: the Copilot ships on for everyone — on whenever the server allows it (stack_copilot) and the stack is latched.
describe('copilotOn', () => {
	it('is on when the server allows it and the stack is on (no per-browser opt-in)', () => {
		expect(copilotOn(true, true)).toBe(true);
	});
	it('is off when the server says off', () => {
		expect(copilotOn(false, true)).toBe(false);
	});
	it('is off when the stack is off', () => {
		expect(copilotOn(true, false)).toBe(false);
		expect(copilotOn(false, false)).toBe(false);
	});
});

describe('applyOn (spec 2026-10-14 §7.6)', () => {
	it('on only when the browser opted in; a throwing or missing storage is off', () => {
		expect(applyOn({ getItem: (k: string) => (k === 'rr_copilot_apply' ? '1' : null) })).toBe(true);
		expect(applyOn({ getItem: () => null })).toBe(false);
		expect(applyOn({ getItem: () => '0' })).toBe(false);
		expect(
			applyOn({
				getItem: () => {
					throw new Error('denied');
				}
			})
		).toBe(false);
		expect(applyOn(null)).toBe(false);
	});
});
