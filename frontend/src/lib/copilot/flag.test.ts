import { describe, expect, it } from 'vitest';
import { copilotOn } from './flag';

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
