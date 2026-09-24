import { describe, expect, it } from 'vitest';
import { computeDelta } from './delta';

describe('computeDelta', () => {
	it('returns the trimmed tail when the transcript extends the last sent one', () => {
		expect(computeDelta('a b c  new words ', 'a b c')).toEqual({
			delta: 'new words',
			next: 'a b c  new words '
		});
	});
	it('returns null when nothing new', () => {
		expect(computeDelta('a b c', 'a b c').delta).toBeNull();
		expect(computeDelta('a b c   ', 'a b c').delta).toBeNull();
	});
	it('returns null and resyncs when the prefix no longer matches (window slide or reset)', () => {
		expect(computeDelta('c d e', 'a b c')).toEqual({ delta: null, next: 'c d e' });
	});
	it('treats an empty last-sent as everything new', () => {
		expect(computeDelta('first words', '').delta).toBe('first words');
	});
});
