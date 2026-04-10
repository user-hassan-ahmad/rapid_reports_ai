import { describe, it, expect } from 'vitest';
import { splitIntoBlocks, diffReports, hash } from './reportDiff.js';

describe('splitIntoBlocks', () => {
	it('returns empty array for empty input', () => {
		expect(splitIntoBlocks('')).toEqual([]);
	});

	it('splits by headings when present', () => {
		const report = '## FINDINGS\nfoo\n\n## IMPRESSION\nbar';
		expect(splitIntoBlocks(report)).toEqual(['## FINDINGS\nfoo', '## IMPRESSION\nbar']);
	});

	it('preserves text before the first heading as its own block', () => {
		const report = 'intro line\n\n## FINDINGS\nfoo';
		expect(splitIntoBlocks(report)).toEqual(['intro line', '## FINDINGS\nfoo']);
	});

	it('falls back to paragraph splits when no headings are present', () => {
		const report = 'first paragraph\n\nsecond paragraph\n\nthird';
		expect(splitIntoBlocks(report)).toEqual(['first paragraph', 'second paragraph', 'third']);
	});

	it('handles a single block', () => {
		expect(splitIntoBlocks('one block')).toEqual(['one block']);
	});
});

describe('hash', () => {
	it('produces stable hashes for the same input', () => {
		expect(hash('hello')).toBe(hash('hello'));
	});

	it('produces different hashes for different input', () => {
		expect(hash('a')).not.toBe(hash('b'));
	});
});

describe('diffReports', () => {
	it('first generation has no badge and no flashes', () => {
		const result = diffReports('', '## A\nfoo\n\n## B\nbar');
		expect(result.badge).toBeNull();
		expect(result.blocks.every((b) => !b.flash)).toBe(true);
		expect(result.blocks).toHaveLength(2);
	});

	it('identical regeneration shows "no changes"', () => {
		const report = '## A\nfoo\n\n## B\nbar';
		const result = diffReports(report, report);
		expect(result.badge).toBe('no changes');
		expect(result.blocks.every((b) => !b.flash)).toBe(true);
	});

	it('single section change reports "1 section changed"', () => {
		const prev = '## A\nfoo\n\n## B\nbar';
		const next = '## A\nfoo\n\n## B\nbaz';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('1 section changed');
		expect(result.blocks[0].flash).toBe(false);
		expect(result.blocks[1].flash).toBe(true);
	});

	it('multi-section change reports plural form', () => {
		const prev = '## A\nfoo\n\n## B\nbar\n\n## C\nbaz\n\n## D\nqux\n\n## E\nquux';
		const next = '## A\nFOO\n\n## B\nBAR\n\n## C\nbaz\n\n## D\nqux\n\n## E\nquux';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('2 sections changed');
	});

	it('majority change reports "regenerated"', () => {
		const prev = '## A\nfoo\n\n## B\nbar\n\n## C\nbaz';
		const next = '## A\nFOO\n\n## B\nBAR\n\n## C\nBAZ';
		const result = diffReports(prev, next);
		expect(result.badge).toBe('regenerated');
		expect(result.blocks.every((b) => b.flash)).toBe(true);
	});

	it('block ids are unique even when block text repeats', () => {
		const result = diffReports('', 'same\n\nsame');
		const ids = result.blocks.map((b) => b.id);
		expect(new Set(ids).size).toBe(ids.length);
	});
});
