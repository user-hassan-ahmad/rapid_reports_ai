import { describe, expect, it } from 'vitest';
import { applyBoundary, flushBuffer, lastNonEmptyLine } from './frontDoor';

describe('applyBoundary', () => {
	it('buffers on continues', () => {
		expect(applyBoundary(['there is a'], '10 mm nodule', 'continues')).toEqual({
			send: null,
			buffer: ['there is a', '10 mm nodule']
		});
	});
	it('sends the merged statement on complete and clears the buffer', () => {
		expect(applyBoundary(['there is a', '10 mm nodule'], 'in the right upper lobe', 'complete')).toEqual({
			send: 'there is a 10 mm nodule in the right upper lobe',
			buffer: []
		});
	});
	it('sends on command too', () => {
		expect(applyBoundary([], 'scratch that', 'command')).toEqual({ send: 'scratch that', buffer: [] });
	});
});

describe('flushBuffer', () => {
	it('sends whatever is buffered, or nothing', () => {
		expect(flushBuffer(['a', 'b'])).toEqual({ send: 'a b', buffer: [] });
		expect(flushBuffer([])).toEqual({ send: null, buffer: [] });
	});
});

describe('lastNonEmptyLine', () => {
	it('returns the last non-blank line, trimmed', () => {
		expect(lastNonEmptyLine('- a\n- b  \n\n')).toBe('- b');
		expect(lastNonEmptyLine('')).toBe('');
	});
});
