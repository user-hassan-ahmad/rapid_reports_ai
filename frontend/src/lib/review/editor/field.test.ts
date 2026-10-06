import { describe, expect, it, vi } from 'vitest';
import { EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { history, undo, redo } from '@codemirror/commands';
import type { ReviewItem } from '../types';
import { runCommand } from '../commands';
import {
	checkReason,
	commandTransaction,
	createReviewState,
	onReviewHistory,
	replaceDoc,
	reviewCommand,
	widgetPosOf,
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
		status: 'pre_applied',
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

/** live.rebase_items' evidence.undo for the span [j1, j2) of the written text. */
function undoOf(written: string, j1: number, j2: number, original_text: string) {
	return {
		final_span: [j1, j2] as [number, number],
		original_text,
		final_text: written.slice(j1, j2),
		left: written.slice(Math.max(0, j1 - 16), j1),
		right: written.slice(j2, j2 + 16)
	};
}

/** Run the view's update listeners for `tr` (no DOM). */
function notify(tr: import('@codemirror/state').Transaction) {
	for (const l of tr.state.facet(EditorView.updateListener)) l({ transactions: [tr], state: tr.state } as never);
}

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
				evidence: { undo: undoOf(DOC, start, start + ADDED.length, '') }
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
				evidence: { undo: undoOf(report, DICTATED.length, DICTATED.length, REMOVED) }
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

	it('fromItems keeps an engine pre-applied item marked even when relabelled suppress (Gate G)', () => {
		const { items } = fromItems(report, [
			item({
				id: 'pa',
				kind: 'absent',
				cls: 'suppress',
				status: 'open',
				anchor: span(AMBER),
				history: [{ event: 'pre_applied', actor: 'post_check' }, { event: 'undo', actor: 'user' }]
			})
		]);
		expect(items.marks.map((m) => m.id)).toEqual(['pa']);
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

describe('removal widgets and undone live edits (C-1, I-5, I-6)', () => {
	const LIVE = 'FINDINGS:\nLiver normal. Spleen normal. Kidneys fine.';
	const p = LIVE.indexOf('Spleen');
	const ORIG = 'FINDINGS:\nLiver normal. No ascites. Spleen normal. Kidneys fine.';
	const rm = (over: Partial<ReviewItem> = {}) =>
		item({
			id: 'w',
			kind: 'removed',
			cls: 'action',
			lane: 'accuracy',
			status: 'pre_applied',
			anchor: { start: p, end: p, text: '', text_hash: 'h1' },
			edit: { mode: 'remove', find: 'No ascites.' },
			evidence: {
				removed_text: 'No ascites.',
				undo: undoOf(LIVE, p, p, 'No ascites. '),
				original_anchor: { start: ORIG.indexOf('No ascites.'), end: ORIG.indexOf('No ascites.') + 11, text: 'No ascites.' }
			},
			...over
		});

	it('a live removal widget is seeded by context, not by a stale final_span', () => {
		const edited = 'Comparison: none.\n' + LIVE;
		const { items, stale } = fromItems(edited, [rm()]);
		expect(stale).toEqual([]);
		expect(items.widgets[0]).toMatchObject({ id: 'w', pos: edited.indexOf('Spleen'), preApplied: true });
	});

	it('a live removal with no context is placed only on the written text (hash match), else stale', () => {
		const bare = rm({ evidence: { removed_text: 'No ascites.', undo: { final_span: [p, p], original_text: 'No ascites. ' } } });
		expect(fromItems(LIVE, [bare]).stale).toEqual(['w']);
		expect(fromItems(LIVE, [bare], { textHash: 'h1' }).items.widgets[0]).toMatchObject({ pos: p });
	});

	it('only a pre_applied removal is a widget: once restored (open) it is a mark on its original text', () => {
		const { items, stale } = fromItems(ORIG, [rm({ status: 'open' })]);
		expect(stale).toEqual([]);
		expect(items.widgets).toEqual([]);
		expect(items.marks).toEqual([expect.objectContaining({ id: 'w', from: ORIG.indexOf('No ascites.'), text: 'No ascites.' })]);
	});

	it('an undone pre-applied insert (open, anchor text gone, no original anchor) is rail-only, not stale', () => {
		const DOC = 'FINDINGS:\nLiver normal. Spleen normal.';
		const ins = item({
			id: 'c',
			kind: 'missing',
			cls: 'minor',
			status: 'open',
			anchor: { start: 24, end: 35, text: 'No ascites.' },
			edit: { mode: 'insert', after: 'Liver normal.', replace: 'No ascites.' },
			evidence: { undo: { final_span: [23, 35], original_text: '', final_text: ' No ascites.', left: '', right: '' } }
		});
		const { items, stale } = fromItems(DOC, [ins]);
		expect(stale).toEqual([]);
		expect(items.marks).toEqual([]);
	});
});

describe('sections (I-7)', () => {
	const DOC = 'Findings:\nLiver normal.\nImpression:\nNormal.';
	const opt = item({ id: 'f', kind: 'option', cls: 'minor', edit: { mode: 'insert', replace: 'No ascites.', section: 'Findings' } });
	it('options in mixed-case sections place when the report sections are passed through', () => {
		expect(fromItems(DOC, [opt]).stale).toEqual(['f']);
		const sections = ['Findings', 'Impression'];
		expect(fromItems(DOC, [opt], { sections }).items.widgets).toEqual([expect.objectContaining({ id: 'f', pos: DOC.indexOf('\nImpression') })]);
		const s0 = createReviewState(DOC, [opt], [], { sections });
		expect(reviewItems(s0).widgets).toHaveLength(1);
		expect(reviewItems(s0.update(syncItems(s0, [opt], { sections })).state).widgets).toHaveLength(1);
		expect(reviewItems(s0.update(replaceDoc(s0, DOC, [opt], { sections })).state).widgets).toHaveLength(1);
	});
});

describe('command transactions (I-1, I-2)', () => {
	const DOC = 'FINDINGS:\nThe liver measures 15 cm. Spleen normal.\n';
	const s0 = DOC.indexOf('15 cm');
	const it_ = item({ id: 'a', kind: 'wrong_number', cls: 'action', lane: 'accuracy', anchor: { start: s0, end: s0 + 5, text: '15 cm' }, edit: { mode: 'replace', find: '15 cm', replace: '13 cm' } });
	const APPLIED = DOC.replace('15 cm', '13 cm');

	function setup() {
		const cb = vi.fn();
		const st = createReviewState(DOC, [it_], [history(), onReviewHistory.of(cb)]);
		return { st, cb };
	}
	function step(st: EditorState, fn: typeof undo) {
		let tr: import('@codemirror/state').Transaction | null = null;
		fn({ state: st, dispatch: (t) => (tr = t) });
		return tr!;
	}

	it("an applied item's own edit is not reported stale; its mark goes in the same transaction", () => {
		const { st } = setup();
		const r = runCommand('apply', { doc: DOC, items: [it_], item: it_ });
		const tr = st.update(commandTransaction(st, r, [it_]));
		expect(staleItems(tr)).toEqual([]);
		expect(tr.state.doc.toString()).toBe(APPLIED);
		expect(reviewItems(tr.state).marks).toEqual([]);
		expect(tr.annotation(reviewCommand)).toMatchObject({ command: 'apply', items: [{ id: 'a', before: 'open', after: 'applied' }] });
	});

	it('a plain transaction with the reviewCommand annotation is never reported stale', () => {
		const { st } = setup();
		const tr = st.update({ changes: { from: s0 + 1, insert: 'X' }, annotations: reviewCommand.of({ command: 'edit', items: [] }) });
		expect(staleItems(tr)).toEqual([]);
	});

	it('Apply → Cmd-Z reverts the text, brings the item back open and reports undo to the viewer', () => {
		const { st, cb } = setup();
		const r = runCommand('apply', { doc: DOC, items: [it_], item: it_ });
		const s1 = st.update(commandTransaction(st, r, [it_])).state;
		const u = step(s1, undo);
		notify(u);
		expect(u.state.doc.toString()).toBe(DOC);
		expect(reviewItems(u.state).marks.map((m) => m.id)).toEqual(['a']);
		expect(cb).toHaveBeenCalledTimes(1);
		expect(cb).toHaveBeenCalledWith({ itemId: 'a', kind: 'undo', command: 'apply', status: 'open' });
		expect(staleItems(u)).toEqual([]);
	});

	it('Apply → rail Undo converges with Apply → Cmd-Z', () => {
		const { st } = setup();
		const r = runCommand('apply', { doc: DOC, items: [it_], item: it_ });
		const s1 = st.update(commandTransaction(st, r, [it_])).state;
		const applied = { ...it_, status: 'applied' as const, history: [{ event: 'apply', detail: r.event!.detail }] };
		const ru = runCommand('undo', { doc: s1.doc.toString(), items: [applied], item: applied });
		const viaRail = s1.update(commandTransaction(s1, ru, [applied])).state;
		const viaKey = step(s1, undo).state;
		expect(viaRail.doc.toString()).toBe(viaKey.doc.toString());
		expect(reviewItems(viaRail).marks).toEqual(reviewItems(viaKey).marks);
	});

	it('Apply → Cmd-Z → redo re-applies and reports redo (applied)', () => {
		const { st, cb } = setup();
		const r = runCommand('apply', { doc: DOC, items: [it_], item: it_ });
		const s1 = st.update(commandTransaction(st, r, [it_])).state;
		const s2 = step(s1, undo).state;
		const rd = step(s2, redo);
		notify(rd);
		expect(rd.state.doc.toString()).toBe(APPLIED);
		expect(reviewItems(rd.state).marks).toEqual([]);
		expect(cb).toHaveBeenLastCalledWith({ itemId: 'a', kind: 'redo', command: 'apply', status: 'applied' });
		// and undo again after the redo
		const u2 = step(rd.state, undo);
		notify(u2);
		expect(u2.state.doc.toString()).toBe(DOC);
		expect(cb).toHaveBeenLastCalledWith({ itemId: 'a', kind: 'undo', command: 'apply', status: 'open' });
	});

	it('other items keep their places through a command transaction', () => {
		const other = item({ id: 'n', kind: 'assumed_normal', cls: 'info', anchor: { start: DOC.indexOf('Spleen normal.'), end: DOC.indexOf('Spleen normal.') + 14, text: 'Spleen normal.' } });
		const st = createReviewState(DOC, [it_, other], [history()]);
		const r = runCommand('apply', { doc: DOC, items: [it_, other], item: it_ });
		const s1 = st.update(commandTransaction(st, r, [it_, other])).state;
		const m = reviewItems(s1).marks;
		expect(m.map((x) => x.id)).toEqual(['n']);
		expect(s1.sliceDoc(m[0].from, m[0].to)).toBe('Spleen normal.');
	});
});

describe('replaceDoc (I-3) and helpers', () => {
	const DOC = 'FINDINGS:\nLiver normal. Spleen normal. Kidneys fine.';
	const p = DOC.indexOf('Kidneys');
	const m = item({ id: 'm', kind: 'assumed_normal', cls: 'info', anchor: { start: DOC.indexOf('Liver'), end: DOC.indexOf('Liver') + 13, text: 'Liver normal.' } });
	const rm = item({
		id: 'w',
		kind: 'removed',
		cls: 'action',
		status: 'pre_applied',
		anchor: { start: p, end: p, text: '' },
		edit: { mode: 'remove', find: 'No ascites.' },
		evidence: { removed_text: 'No ascites.', undo: undoOf(DOC, p, p, 'No ascites. ') }
	});

	it('a full-document reload reseeds items from the new text: no stale, widgets not collapsed, not undoable', () => {
		const st = createReviewState(DOC, [m, rm], [history()]);
		const tr = st.update(replaceDoc(st, DOC, [m, rm]));
		expect(staleItems(tr)).toEqual([]);
		expect(reviewItems(tr.state).marks.map((x) => x.id)).toEqual(['m']);
		expect(reviewItems(tr.state).widgets).toEqual([expect.objectContaining({ id: 'w', pos: p })]);
		expect(undo({ state: tr.state, dispatch: () => {} })).toBe(false);

		const doc2 = DOC.replace('FINDINGS:\n', 'FINDINGS:\nComparison none. ');
		const tr2 = tr.state.update(replaceDoc(tr.state, doc2, [m, rm]));
		expect(tr2.state.doc.toString()).toBe(doc2);
		expect(reviewItems(tr2.state).widgets[0].pos).toBe(doc2.indexOf('Kidneys'));
		expect(widgetPosOf(tr2.state)(rm)).toBe(doc2.indexOf('Kidneys'));
		expect(widgetPosOf(tr2.state)(m)).toBeNull();
	});

	it('Discard after a removal: reloading the saved text never throws on the undo history (and Cmd-Z stays safe)', () => {
		// a command that shortened the report, then a full reload (Discard / a save) onto the longer saved text
		const REC = ' Suggest MRI of the liver for characterisation.';
		const saved = DOC + REC;
		const at = saved.indexOf(REC) + 1;
		const rec = item({
			id: 'r',
			kind: 'recommendation',
			cls: 'minor',
			lane: 'additions',
			anchor: { start: at, end: saved.length, text: REC.trim() },
			edit: { mode: 'remove', find: REC.trim() }
		});
		const st = createReviewState(saved, [m, rec], [history()]);
		const res = runCommand('remove', { doc: saved, items: [m, rec], item: rec });
		const s1 = st.update(commandTransaction(st, res, [m, rec])).state;
		expect(s1.doc.toString()).toBe(DOC);
		const removed = [m, { ...rec, status: 'applied' as const }];
		let s2!: EditorState;
		expect(() => (s2 = s1.update(replaceDoc(s1, saved, removed)).state)).not.toThrow();
		expect(s2.doc.toString()).toBe(saved);
		// a later reload onto a shorter text, then Cmd-Z, does not throw either
		const s3 = s2.update(replaceDoc(s2, 'FINDINGS:\nShort.', removed)).state;
		expect(() => undo({ state: s3, dispatch: () => {} })).not.toThrow();
	});

	it('warns once when the loaded text is not the text the anchors were made on', () => {
		const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
		const hashed = { ...m, anchor: { ...m.anchor!, text_hash: 'h1' } };
		createReviewState(DOC, [hashed], [], { textHash: 'h1' });
		expect(warn).not.toHaveBeenCalled();
		createReviewState(DOC, [hashed], [], { textHash: 'h2' });
		expect(warn).toHaveBeenCalledTimes(1);
		warn.mockRestore();
	});
});

describe('inline classification / guideline suggestions (additions inserts as ghosts)', () => {
	const DOC = 'FINDINGS:\nA 32 mm pancreatic head mass. The spleen is normal.\nIMPRESSION:\nPancreatic mass.';
	const MASS = 'A 32 mm pancreatic head mass.';
	const grade = (over: Partial<ReviewItem> = {}) =>
		item({
			id: 'g',
			kind: 'grade',
			cls: 'minor',
			lane: 'additions',
			reason: 'NCCN',
			edit: { mode: 'insert', after: MASS, replace: 'Borderline resectable.', section: 'FINDINGS' },
			...over
		});

	it('an open minor additions insert renders as a ghost option after its finding', () => {
		const { items, stale } = fromItems(DOC, [grade()]);
		expect(stale).toEqual([]);
		expect(items.widgets).toEqual([
			expect.objectContaining({ kind: 'option', id: 'g', pos: DOC.indexOf(MASS) + MASS.length, text: 'Borderline resectable.' })
		]);
	});

	it('is never a ghost unless an open minor additions insert', () => {
		for (const it_ of [
			grade({ cls: 'action' }),
			grade({ status: 'applied' }),
			grade({ edit: null }),
			grade({ lane: 'accuracy' }),
			grade({ edit: { mode: 'replace', find: MASS, replace: 'x' } })
		]) {
			expect(fromItems(DOC, [it_]).items.widgets).toEqual([]);
		}
	});

	it('including it inserts the text and drops the ghost', () => {
		const s0 = createReviewState(DOC, [grade()]);
		const s1 = s0.update(includeOption(s0, 'g')!).state;
		expect(s1.doc.toString()).toContain(`${MASS} Borderline resectable. The spleen`);
		expect(reviewItems(s1).widgets).toEqual([]);
	});

	it("the rail apply (Guidelines' Add to report) inserts it once after its finding and the ghost disappears", () => {
		const g = grade();
		const s0 = createReviewState(DOC, [g]);
		expect(reviewItems(s0).widgets).toHaveLength(1);
		const r = runCommand('apply', { doc: DOC, items: [g], item: g });
		const s1 = s0.update(commandTransaction(s0, r, [g])).state;
		const out = s1.doc.toString();
		expect(out).toContain(`${MASS} Borderline resectable. The spleen`);
		expect(out.split('Borderline resectable.')).toHaveLength(2);
		expect(reviewItems(s1).widgets).toEqual([]);
	});
});
