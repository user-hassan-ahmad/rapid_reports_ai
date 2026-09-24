import { describe, expect, it } from 'vitest';
import { applyBoundary, backstopDelay, derivePlacement, flushBuffer, lastNonEmptyLine } from './frontDoor';

describe('applyBoundary', () => {
	it('buffers on continues', () => {
		expect(applyBoundary(['there is a'], '10 mm nodule', 'continues')).toEqual({
			sends: [],
			buffer: ['there is a', '10 mm nodule']
		});
	});
	it('sends the merged statement on complete and clears the buffer', () => {
		expect(applyBoundary(['there is a', '10 mm nodule'], 'in the right upper lobe', 'complete')).toEqual({
			sends: ['there is a 10 mm nodule in the right upper lobe'],
			buffer: []
		});
	});
	it('sends a command alone when nothing is buffered', () => {
		expect(applyBoundary([], 'scratch that', 'command')).toEqual({ sends: ['scratch that'], buffer: [] });
	});
	it('flushes the buffer as its own statement before a command', () => {
		expect(applyBoundary(['in the right upper lobe', 'which is spiculated'], 'new paragraph', 'command')).toEqual({
			sends: ['in the right upper lobe which is spiculated', 'new paragraph'],
			buffer: []
		});
	});
});

describe('flushBuffer', () => {
	it('sends whatever is buffered, or nothing', () => {
		expect(flushBuffer(['a', 'b'])).toEqual({ sends: ['a b'], buffer: [] });
		expect(flushBuffer([])).toEqual({ sends: [], buffer: [] });
	});
});

describe('lastNonEmptyLine', () => {
	it('returns the last non-blank line, trimmed', () => {
		expect(lastNonEmptyLine('- a\n- b  \n\n')).toBe('- b');
		expect(lastNonEmptyLine('')).toBe('');
	});
});

describe('backstopDelay', () => {
	it('waits longer after a confident continues', () => {
		expect(backstopDelay(0.99)).toBe(4000);
		expect(backstopDelay(0.5)).toBe(4000);
		expect(backstopDelay(0.49)).toBe(1500);
		expect(backstopDelay(null)).toBe(1500);
		expect(backstopDelay(undefined)).toBe(1500);
	});
});

describe('derivePlacement', () => {
	it('extends when the last line grew', () => {
		expect(derivePlacement('- a nodule', '- a nodule which is spiculated')).toBe('extend_previous_line');
	});
	it('new line when a line was added without a blank', () => {
		expect(derivePlacement('- a', '- a\n- b')).toBe('new_line');
	});
	it('new paragraph when a blank line precedes the new text', () => {
		expect(derivePlacement('- a', '- a\n\n- b')).toBe('new_paragraph');
	});
	it('first line into an empty scratchpad is a new paragraph (empty last line)', () => {
		expect(derivePlacement('', '- a')).toBe('new_paragraph');
	});
	it('null when nothing changed', () => {
		expect(derivePlacement('- a', '- a')).toBeNull();
	});
});
