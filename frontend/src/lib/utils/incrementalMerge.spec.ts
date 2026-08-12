import { describe, it, expect } from 'vitest';
import { mergeIncremental, rawInsertSeparator } from './incrementalMerge';

describe('mergeIncremental', () => {
	it('separates a frozen finding from a new active statement with a newline (regression: lobe.The spleen)', () => {
		const committed = 'There is an 8 mm hypodense lesion in the right hepatic lobe.';
		const active = 'The spleen is normal in size measuring 9 cm.';
		const { content } = mergeIncremental(committed, active, []);
		expect(content).toBe(
			'There is an 8 mm hypodense lesion in the right hepatic lobe.\nThe spleen is normal in size measuring 9 cm.'
		);
		// the exact defect must be gone
		expect(content).not.toContain('lobe.The spleen');
	});

	it('applies a directed committed_edit verbatim (8 mm -> 10 mm)', () => {
		const committed = 'There is an 8 mm hypodense lesion in the right hepatic lobe.';
		const active = 'The spleen is normal in size measuring 9 cm.';
		// The model emits a grammar-aware verbatim patch (matches prod log:
		// "There is a 10 mm hypodense lesion in the right hepatic lobe.").
		const { content } = mergeIncremental(committed, active, [
			{ original: 'an 8 mm', corrected: 'a 10 mm' }
		]);
		expect(content).toContain('There is a 10 mm hypodense lesion');
		expect(content).not.toContain('8 mm');
	});

	it('drops a committed_edit whose original is not found (drop-if-not-found safety)', () => {
		const committed = 'There is an 8 mm hypodense lesion in the right hepatic lobe.';
		const active = 'The spleen is normal.';
		const { content } = mergeIncremental(committed, active, [
			{ original: 'no such text', corrected: 'X' }
		]);
		expect(content).toBe('There is an 8 mm hypodense lesion in the right hepatic lobe.\nThe spleen is normal.');
	});

	it('returns the active text unchanged with no leading separator when committed is empty', () => {
		const { content, boundary } = mergeIncremental('', 'The liver is normal.', []);
		expect(content).toBe('The liver is normal.');
		expect(boundary).toBe(0);
	});

	it('does not double the separator when committed already ends with a newline', () => {
		const committed = 'There is a lesion in the liver.\n';
		const active = 'The spleen is normal.';
		const { content } = mergeIncremental(committed, active, []);
		expect(content).toBe('There is a lesion in the liver.\nThe spleen is normal.');
	});

	it('does not append a trailing separator when the active text is empty', () => {
		const committed = 'There is a lesion in the liver.';
		const { content } = mergeIncremental(committed, '', []);
		expect(content).toBe('There is a lesion in the liver.');
	});

	it('reports a boundary that points exactly at the start of the active tail', () => {
		const committed = 'There is a lesion in the liver.';
		const active = 'The spleen is normal.';
		const { content, boundary } = mergeIncremental(committed, active, []);
		// everything after the boundary is the pure, mutable active tail
		expect(content.slice(boundary)).toBe(active);
	});
});

describe('rawInsertSeparator', () => {
	it('inserts no separator for the very first words (empty doc)', () => {
		expect(rawInsertSeparator(0, 0)).toBe('');
	});

	it('inserts a newline when starting a fresh statement after committed text', () => {
		// active tail empty (docLength === committedBoundary), committed present
		expect(rawInsertSeparator(60, 60)).toBe('\n');
	});

	it('inserts a space when continuing the current utterance', () => {
		expect(rawInsertSeparator(75, 60)).toBe(' ');
	});

	it('inserts a space for a continuing first utterance with no committed text', () => {
		expect(rawInsertSeparator(20, 0)).toBe(' ');
	});
});
