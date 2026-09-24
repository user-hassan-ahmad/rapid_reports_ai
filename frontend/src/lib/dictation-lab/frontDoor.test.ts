import { describe, expect, it } from 'vitest';
import { applyBoundary, flushBuffer, lastNonEmptyLine } from './frontDoor';

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
