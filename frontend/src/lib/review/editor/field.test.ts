import { describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { history, undo, redo } from '@codemirror/commands';
import type { ReviewItem } from '../types';
import {
	checkReason,
	createReviewState,
	excludeMark,
	fromItems,
	includeOption,
	onReviewStale,
	restoreExcluded,
	restoreRemoved,
	reviewCounts,
	reviewField,
	reviewItems,
	staleItems,
	syncItems
} from './field';

// Tiny SYNTHETIC report: dictated finding, one green, one amber, one removed, one option.
const DICTATED = 'Simple cyst in the left kidney.';
const GREEN = 'The liver is normal.';
const AMBER = 'No hydronephrosis.';
const REMOVED = 'The kidneys are normal.';
const OPTION = 'No free fluid.';
const report = `${DICTATED} ${GREEN} ${AMBER}`;
const gStart = report.indexOf(GREEN);
const aStart = report.indexOf(AMBER);

function item(over: Partial<ReviewItem> & Pick<ReviewItem, 'id' | 'kind' | 'cls'>): ReviewItem {
	return {
		key: over.id,
		report_id: 'rep1',
		run_id: 'run1',
		lane: 'coverage',
		detectors: [],
		label: '',
		reason: '',
		status: 'open',
		history: [],
		engine_version: 'test',
		...over
	};
}

function span(text: string, start = report.indexOf(text)) {
	return { start, end: start + text.length, text };
}

const ITEMS: ReviewItem[] = [
	item({ id: 'm1', kind: 'assumed_normal', cls: 'info', anchor: span(GREEN) }),
	item({
		id: 'm2',
		kind: 'check',
		cls: 'minor',
		anchor: span(AMBER),
		evidence: { check_reason: 'uncertain', pointer: 'simple cyst left kidney' }
	}),
	item({
		id: 'r1',
		kind: 'removed',
		cls: 'action',
		anchor: { start: DICTATED.length, end: DICTATED.length, text: '' },
		evidence: { removed_text: REMOVED }
	}),
	item({
		id: 'o1',
		kind: 'option',
		cls: 'minor',
		lane: 'additions',
		edit: { mode: 'insert', after: AMBER, replace: OPTION }
	})
];

function load(items: ReviewItem[] = ITEMS) {
	return createReviewState(report, items, [history()]);
}

describe('review field (ported from the negatives prototype)', () => {
	it('loading items yields a document equal to the report', () => {
		const s = load();
		expect(s.doc.toString()).toBe(report);
		const items = reviewItems(s);
		expect(items.marks.map((m) => [m.from, m.to])).toEqual([
			[gStart, gStart + GREEN.length],
			[aStart, aStart + AMBER.length]
		]);
		expect(items.marks.map((m) => m.mark)).toEqual(['rv-normal', 'rv-check']);
		expect(items.widgets.map((w) => w.kind).sort()).toEqual(['option', 'removed']);
	});

	it('a selection spanning the removed widget copies no removed text', () => {
		const s = load();
		const anchor = DICTATED.length;
		const copied = s.sliceDoc(Math.max(0, anchor - 10), Math.min(s.doc.length, anchor + 10));
		expect(copied).not.toContain(REMOVED);
		expect(s.sliceDoc(0, s.doc.length)).not.toContain(REMOVED);
		expect(s.doc.toString()).not.toContain(OPTION);
	});

	it('exclude then restore round-trips the document exactly', () => {
		const s0 = load();
		const s1 = s0.update(excludeMark(s0, 'm1')!).state;
		expect(s1.doc.toString()).toBe(`${DICTATED} ${AMBER}`);
		expect(s1.doc.toString()).not.toMatch(/ {2}/);
		const w = reviewItems(s1).widgets.find((x) => x.id === 'm1');
		expect(w?.kind).toBe('excluded');
		const s2 = s1.update(restoreExcluded(s1, 'm1')!).state;
		expect(s2.doc.toString()).toBe(report);
		const m = reviewItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
		expect(m?.mark).toBe('rv-normal');
		expect(reviewItems(s2).widgets.some((x) => x.id === 'm1')).toBe(false);
	});

	it('excluding an amber mark restores it as amber', () => {
		const s0 = load();
		const s1 = s0.update(excludeMark(s0, 'm2')!).state;
		expect(s1.doc.toString()).toBe(`${DICTATED} ${GREEN}`);
		const s2 = s1.update(restoreExcluded(s1, 'm2')!).state;
		expect(s2.doc.toString()).toBe(report);
		const m = reviewItems(s2).marks.find((x) => x.id === 'm2');
		expect(m?.mark).toBe('rv-check');
		expect(m?.reason).toBe('uncertain');
	});

	it('undo of an exclude restores the doc and the mark; redo re-excludes', () => {
		const s0 = load();
		const s1 = s0.update(excludeMark(s0, 'm1')!).state;
		let s2 = s1;
		undo({ state: s1, dispatch: (tr) => (s2 = tr.state) });
		expect(s2.doc.toString()).toBe(report);
		const m = reviewItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
		expect(reviewItems(s2).widgets.some((x) => x.id === 'm1')).toBe(false);
		let s3 = s2;
		redo({ state: s2, dispatch: (tr) => (s3 = tr.state) });
		expect(s3.doc.toString()).toBe(`${DICTATED} ${AMBER}`);
		expect(reviewItems(s3).widgets.find((x) => x.id === 'm1')?.kind).toBe('excluded');
	});

	it('include of an option inserts " " + text at the anchor as plain text', () => {
		const s0 = load();
		const s1 = s0.update(includeOption(s0, 'o1')!).state;
		expect(s1.doc.toString()).toBe(`${report} ${OPTION}`);
		const items = reviewItems(s1);
		expect(items.widgets.some((w) => w.id === 'o1')).toBe(false);
		expect(items.marks.some((m) => s1.sliceDoc(m.from, m.to) === OPTION)).toBe(false);
	});

	it('restore of a removed item inserts it (space-separated) as a normal mark', () => {
		const s0 = load();
		const s1 = s0.update(restoreRemoved(s0, 'r1')!).state;
		expect(s1.doc.toString()).toBe(`${DICTATED} ${REMOVED} ${GREEN} ${AMBER}`);
		const m = reviewItems(s1).marks.find((x) => x.id === 'r1');
		expect(m?.mark).toBe('rv-normal');
		expect(m && s1.sliceDoc(m.from, m.to)).toBe(REMOVED);
		expect(reviewItems(s1).widgets.some((w) => w.id === 'r1')).toBe(false);
		// later marks moved with the insertion
		const g = reviewItems(s1).marks.find((x) => x.id === 'm1')!;
		expect(s1.sliceDoc(g.from, g.to)).toBe(GREEN);
	});

	it('typing inside a green mark drops the mark; undo brings it back', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: gStart + 4, insert: 'X' }, userEvent: 'input.type' }).state;
		expect(reviewItems(s1).marks.some((m) => m.id === 'm1')).toBe(false);
		expect(reviewItems(s1).marks.some((m) => m.id === 'm2')).toBe(true);
		let s2 = s1;
		undo({ state: s1, dispatch: (tr) => (s2 = tr.state) });
		expect(s2.doc.toString()).toBe(report);
		const m = reviewItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
	});

	it('typing at a mark boundary does not drop it or extend it', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: gStart + GREEN.length, insert: ' Extra.' } }).state;
		const m = reviewItems(s1).marks.find((x) => x.id === 'm1');
		expect(m && s1.sliceDoc(m.from, m.to)).toBe(GREEN);
	});

	it('marks and widgets map correctly after an insertion before them', () => {
		const s0 = load();
		const ins = 'Comparison: none. ';
		const s1 = s0.update({ changes: { from: 0, insert: ins } }).state;
		const items = reviewItems(s1);
		for (const m of items.marks) {
			expect(s1.sliceDoc(m.from, m.to)).toBe(m.text);
		}
		expect(items.widgets.find((w) => w.id === 'r1')?.pos).toBe(DICTATED.length + ins.length);
		expect(items.widgets.find((w) => w.id === 'o1')?.pos).toBe(report.length + ins.length);
	});

	it('a widget whose anchor sentence is deleted stays at the mapped position', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: 0, to: DICTATED.length + 1 } }).state;
		const w = reviewItems(s1).widgets.find((x) => x.id === 'r1');
		expect(w?.pos).toBe(0);
		// and can still be restored there
		const s2 = s1.update(restoreRemoved(s1, 'r1')!).state;
		expect(s2.doc.toString()).toBe(`${REMOVED} ${GREEN} ${AMBER}`);
	});

	it('the field is registered', () => {
		expect(load().field(reviewField, false)).toBeTruthy();
		expect(EditorState.create({ doc: 'x' }).field(reviewField, false)).toBeUndefined();
	});

	// Prototype: "the synthetic sample bundle parses cleanly and loads as its report". The field now loads
	// ReviewItems, so the equivalent is: every anchored item is placed and none is stale.
	it('well-anchored items place cleanly with no stale ids', () => {
		const { items, stale } = fromItems(report, ITEMS);
		expect(stale).toEqual([]);
		expect(items.marks.length + items.widgets.length).toBe(ITEMS.length);
	});

	// Prototype: "parseBundle rejects a wrong version". The equivalent is an item whose anchor no longer
	// matches the document: it is not placed, and it is reported stale.
	it('an item whose anchor cannot be located is reported stale, not placed', () => {
		const lost = item({ id: 'x1', kind: 'assumed_normal', cls: 'info', anchor: { start: 0, end: 5, text: 'Gone.' } });
		const { items, stale } = fromItems(report, [...ITEMS, lost]);
		expect(stale).toEqual(['x1']);
		expect(items.marks.some((m) => m.id === 'x1')).toBe(false);
	});
});

describe('check reasons', () => {
	it('names why an amber item needs a check, with the matching evidence label', () => {
		expect(checkReason({}).evidenceLabel).toBe('Your finding');
		expect(checkReason({ check_reason: 'conflict' }).line).toMatch(/conflicts with your dictation/);
		expect(checkReason({ check_reason: 'number' }).evidenceLabel).toBe('Not in your dictation');
	});
});

describe('review field (generalised to review items)', () => {
	it('other anchored items become lane-group marks by cls', () => {
		const DOC = 'FINDINGS:\nA 5 mm nodule in the right lung. Mild atelectasis. Old rib fracture.';
		const at = (t: string) => ({ start: DOC.indexOf(t), end: DOC.indexOf(t) + t.length, text: t });
		const { items } = fromItems(DOC, [
			item({ id: 'a', kind: 'laterality', cls: 'action', lane: 'accuracy', anchor: at('right lung') }),
			item({ id: 'b', kind: 'wording', cls: 'minor', lane: 'accuracy', anchor: at('Mild atelectasis.') }),
			item({ id: 'c', kind: 'guideline', cls: 'info', lane: 'additions', anchor: at('Old rib fracture.') })
		]);
		expect(items.marks.map((m) => [m.id, m.mark, m.lane])).toEqual([
			['a', 'rv-action', 'accuracy'],
			['b', 'rv-minor', 'accuracy'],
			['c', 'rv-info', 'additions']
		]);
	});

	it('a pre-applied insert marks the inserted text, and undoing the edit text drops it', () => {
		const ADDED = 'No pleural effusion.';
		const DOC = `${DICTATED} ${ADDED}`;
		const start = DOC.indexOf(ADDED);
		const { items } = fromItems(DOC, [
			item({
				id: 'p1',
				kind: 'omission',
				cls: 'minor',
				status: 'pre_applied',
				anchor: { start, end: start + ADDED.length, text: ADDED },
				edit: { mode: 'insert', after: DICTATED, replace: ADDED },
				evidence: { undo: { final_span: [start, start + ADDED.length], original_text: '' } }
			})
		]);
		expect(items.marks).toHaveLength(1);
		expect(items.marks[0]).toMatchObject({ id: 'p1', mark: 'rv-preapplied', from: start, to: start + ADDED.length });
	});

	it('a pre-applied insert falls back to the undo span when the anchor is gone', () => {
		const ADDED = 'No pleural effusion.';
		const DOC = `${DICTATED} ${ADDED} ${ADDED}`; // ambiguous text search
		const start = DOC.lastIndexOf(ADDED);
		const { items, stale } = fromItems(DOC, [
			item({
				id: 'p1',
				kind: 'omission',
				cls: 'minor',
				status: 'pre_applied',
				anchor: { start: 0, end: 3, text: 'old' },
				edit: { mode: 'insert', after: DICTATED, replace: ADDED },
				evidence: { undo: { final_span: [start, start + ADDED.length], original_text: '' } }
			})
		]);
		expect(stale).toEqual([]);
		expect(items.marks[0]).toMatchObject({ id: 'p1', mark: 'rv-preapplied', from: start });
	});

	it('a pre-applied removal becomes a removed widget at the anchor', () => {
		const { items } = fromItems(report, [
			item({
				id: 'p2',
				kind: 'contradiction',
				cls: 'action',
				status: 'pre_applied',
				anchor: { start: DICTATED.length, end: DICTATED.length, text: '' },
				edit: { mode: 'remove', find: REMOVED },
				evidence: { undo: { final_span: [DICTATED.length, DICTATED.length], original_text: REMOVED } }
			})
		]);
		expect(items.widgets).toEqual([
			expect.objectContaining({ kind: 'removed', id: 'p2', pos: DICTATED.length, text: REMOVED })
		]);
	});

	it('a removed widget keeps the position the field supplies', () => {
		const { items } = fromItems(report, ITEMS, { widgetPos: { r1: 3 } });
		expect(items.widgets.find((w) => w.id === 'r1')?.pos).toBe(3);
	});

	it('fromItems skips suppress and dismissed items', () => {
		const { items, stale } = fromItems(report, [
			item({ id: 's', kind: 'assumed_normal', cls: 'suppress', anchor: span(GREEN) }),
			item({ id: 'd', kind: 'check', cls: 'minor', status: 'dismissed', anchor: span(AMBER) }),
			item({ id: 'o', kind: 'option', cls: 'minor', status: 'dismissed', edit: { mode: 'insert', after: AMBER, replace: OPTION } })
		]);
		expect(items.marks).toEqual([]);
		expect(items.widgets).toEqual([]);
		expect(stale).toEqual([]);
	});

	it('items with no anchor and no widget stay out of the editor and are not stale', () => {
		const { items, stale } = fromItems(report, [item({ id: 'n', kind: 'note', cls: 'info' })]);
		expect(items.marks).toEqual([]);
		expect(items.widgets).toEqual([]);
		expect(stale).toEqual([]);
	});

	it('a mark dropped by an interior edit reports stale (effect + callback); boundary typing does not', () => {
		const s0 = load();
		const tr = s0.update({ changes: { from: gStart + 4, insert: 'X' }, userEvent: 'input.type' });
		expect(staleItems(tr)).toEqual(['m1']);
		const edge = s0.update({ changes: { from: gStart + GREEN.length, insert: ' Extra.' } });
		expect(staleItems(edge)).toEqual([]);
		// a command transaction (setItems) removing a mark is not a stale report
		expect(staleItems(s0.update(excludeMark(s0, 'm1')!))).toEqual([]);
	});

	it('the onReviewStale callback fires from the view update listener', () => {
		const cb = vi.fn();
		const s0 = createReviewState(report, ITEMS, [history(), onReviewStale.of(cb)]);
		const tr = s0.update({ changes: { from: gStart + 4, insert: 'X' } });
		const listeners = tr.state.facet(EditorView.updateListener);
		for (const l of listeners) l({ transactions: [tr], state: tr.state } as never);
		expect(cb).toHaveBeenCalledWith(['m1']);
	});

	it('syncItems replaces the items from the store without entering undo history', () => {
		const s0 = load();
		const next = ITEMS.filter((i) => i.id !== 'm1');
		const s1 = s0.update(syncItems(s0, next)).state;
		expect(reviewItems(s1).marks.map((m) => m.id)).toEqual(['m2']);
		let s2 = s1;
		const did = undo({ state: s1, dispatch: (tr) => (s2 = tr.state) });
		expect(did).toBe(false);
		expect(reviewItems(s2).marks.map((m) => m.id)).toEqual(['m2']);
	});

	it('counts by presentation', () => {
		expect(reviewCounts(reviewItems(load()))).toEqual({
			normal: 1,
			check: 1,
			preapplied: 0,
			flagged: 0,
			removed: 1,
			options: 1,
			excluded: 0
		});
	});
});
