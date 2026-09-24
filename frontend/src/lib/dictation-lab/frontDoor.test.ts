import { describe, expect, it } from 'vitest';
import {
	applyBoundary,
	derivePlacement,
	endsWithTerminalPunctuation,
	flushBuffer,
	lastNonEmptyLine,
	nextSilenceStep,
	silenceVerdict
} from './frontDoor';

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

describe('nextSilenceStep', () => {
	it('re-checks at 2 s, then the 5 s hard limit', () => {
		expect(nextSilenceStep(0)).toEqual({ delayMs: 2000, silenceS: 2 });
		expect(nextSilenceStep(1)).toEqual({ delayMs: 3000, silenceS: null });
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

describe('endsWithTerminalPunctuation', () => {
	it('detects a closed sentence', () => {
		expect(endsWithTerminalPunctuation('and adjacent foci of gas.')).toBe(true);
		expect(endsWithTerminalPunctuation('Is there a mass?')).toBe(true);
		expect(endsWithTerminalPunctuation('measuring 7 mm.  ')).toBe(true);
		expect(endsWithTerminalPunctuation('The tip is')).toBe(false);
		expect(endsWithTerminalPunctuation('as does the:')).toBe(false);
	});
});

describe('silenceVerdict', () => {
	it('sends when the words could stand alone, or at the hard limit', () => {
		expect(silenceVerdict(0.7, 2)).toBe('send');
		expect(silenceVerdict(0.3, 2)).toBe('wait');
		expect(silenceVerdict(null, 2)).toBe('wait');
		expect(silenceVerdict(0.1, 5)).toBe('send');
	});
});
