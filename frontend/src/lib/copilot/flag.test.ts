import { describe, expect, it } from 'vitest';
import { COPILOT_KEY, copilotOn } from './flag';

const store = (v: string | null) => ({ getItem: (k: string) => (k === COPILOT_KEY ? v : null) }) as Storage;
const blocked = {
	getItem: () => {
		throw new Error('SecurityError');
	}
} as unknown as Storage;

describe('copilotOn', () => {
	it('is on only when the server allows it, the stack is on and the browser opted in', () => {
		expect(copilotOn(store('1'), true, true)).toBe(true);
	});
	it.each([
		[false, true],
		[true, false],
		[false, false]
	])('is off when serverAllows=%s, stackOn=%s even with the opt-in', (server, stack) => {
		expect(copilotOn(store('1'), server, stack)).toBe(false);
	});
	it.each([null, '0', 'true', '', ' 1'])('is off when the key is %j', (v) => {
		expect(copilotOn(store(v), true, true)).toBe(false);
	});
	it('is off when localStorage is blocked or absent', () => {
		expect(copilotOn(blocked, true, true)).toBe(false);
		expect(copilotOn(undefined, true, true)).toBe(false);
	});
	it('is off by default', () => {
		expect(copilotOn()).toBe(false);
	});
});
