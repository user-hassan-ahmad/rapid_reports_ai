import { describe, it, expect } from 'vitest';
import { locate } from './anchors';
import type { ReviewItem, Span, ItemEvidence, Edit } from './types';

function item(anchor: Span | null, evidence: ItemEvidence | null = null, edit: Edit | null = null): ReviewItem {
	return {
		id: 'i1',
		key: 'k1',
		report_id: 'r1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		kind: 'omission',
		cls: 'action',
		anchor,
		label: 'label',
		reason: 'reason',
		edit,
		evidence,
		status: 'open',
		history: [],
		engine_version: 'test'
	};
}

const DOC = 'FINDINGS:\nThe liver is normal. No ascites. The spleen is normal.';

describe('locate', () => {
	it('returns the stored span when it still holds the anchor text', () => {
		const start = DOC.indexOf('No ascites.');
		const r = locate(DOC, item({ start, end: start + 11, text: 'No ascites.' }));
		expect(r).toEqual({ from: start, to: start + 11 });
	});

	it('finds a shifted span by unique text search', () => {
		const edited = 'FINDINGS:\nThe liver is mildly enlarged. No ascites. The spleen is normal.';
		const oldStart = DOC.indexOf('No ascites.');
		const r = locate(edited, item({ start: oldStart, end: oldStart + 11, text: 'No ascites.' }));
		const k = edited.indexOf('No ascites.');
		expect(k).not.toBe(oldStart);
		expect(r).toEqual({ from: k, to: k + 11 });
	});

	it('prefers the exact span even when the text also occurs elsewhere', () => {
		const doc = 'is normal. X. is normal.';
		const start = doc.lastIndexOf('is normal.');
		expect(locate(doc, item({ start, end: start + 10, text: 'is normal.' }))).toEqual({ from: start, to: start + 10 });
	});

	it('gives null for a moved anchor whose text is ambiguous', () => {
		const r = locate(DOC, item({ start: 0, end: 10, text: 'is normal.' }));
		expect(r).toBeNull();
	});

	it('gives null when the anchor text is gone', () => {
		expect(locate(DOC, item({ start: 10, end: 20, text: 'Small effusion.' }))).toBeNull();
	});

	it('gives null for an item with no anchor', () => {
		expect(locate(DOC, item(null))).toBeNull();
	});

	it('handles out-of-range stored offsets without throwing', () => {
		const r = locate(DOC, item({ start: 500, end: 511, text: 'No ascites.' }));
		const k = DOC.indexOf('No ascites.');
		expect(r).toEqual({ from: k, to: k + 11 });
	});

	describe('zero-width (removed) anchors', () => {
		const removed = item({ start: 30, end: 30, text: '' }, { removed_text: 'No ascites.' });

		it('uses the supplied widget position', () => {
			expect(locate(DOC, removed, { widgetPos: 12 })).toEqual({ from: 12, to: 12 });
		});

		it('gives null without a widget position', () => {
			expect(locate(DOC, removed)).toBeNull();
		});

		it('gives null when the widget position is outside the document', () => {
			expect(locate(DOC, removed, { widgetPos: DOC.length + 1 })).toBeNull();
			expect(locate(DOC, removed, { widgetPos: -1 })).toBeNull();
		});

		it('accepts a live pre-applied removal (undo info, remove edit) without removed_text', () => {
			const pre = item(
				{ start: 30, end: 30, text: '' },
				{ undo: { final_span: [30, 30], original_text: ' No ascites.' } },
				{ mode: 'remove', find: 'No ascites.' }
			);
			pre.status = 'pre_applied';
			expect(locate(DOC, pre, { widgetPos: 30 })).toEqual({ from: 30, to: 30 });
		});

		it('gives null for an empty anchor that is not a removal', () => {
			const odd = item({ start: 5, end: 5, text: '' });
			expect(locate(DOC, odd, { widgetPos: 5 })).toBeNull();
		});

		it('ignores the widget position for a non-empty anchor', () => {
			const r = locate(DOC, item({ start: 0, end: 5, text: 'Gone text.' }), { widgetPos: 3 });
			expect(r).toBeNull();
		});
	});
});
