import { describe, expect, it } from 'vitest';
import { textHash } from './hash';

// Vectors from the backend: rapid_reports_ai.review_engine.items.text_hash (sha256(text)[:16]).
describe('textHash', () => {
	it('matches the backend for a sentence', async () => {
		expect(await textHash('No ascites.')).toBe('47597f087ff5d076');
	});

	it('matches the backend for the empty string', async () => {
		expect(await textHash('')).toBe('e3b0c44298fc1c14');
	});
});
