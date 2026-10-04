import { describe, expect, it } from 'vitest';
import { EditorState } from '@codemirror/state';
import { history, undo, redo } from '@codemirror/commands';
import type { NegativesBundle } from './bundle';
import {
	createNegState,
	excludeMark,
	includeOption,
	negField,
	negItems,
	restoreExcluded,
	parseBundle,
	restoreRemoved
} from './state';
import sample from './sample-synthetic.json';

// Tiny SYNTHETIC report: dictated finding, one green, one amber, one removed, one option.
const DICTATED = 'Simple cyst in the left kidney.';
const GREEN = 'The liver is normal.';
const AMBER = 'No hydronephrosis.';
const REMOVED = 'The kidneys are normal.';
const OPTION = 'No free fluid.';
const report = `${DICTATED} ${GREEN} ${AMBER}`;
const gStart = report.indexOf(GREEN);
const aStart = report.indexOf(AMBER);

const bundle: NegativesBundle = {
	version: 1,
	id8: 'synth001',
	scan: 'CT abdomen (synthetic)',
	history: 'Synthetic flank pain.',
	dictation: 'simple cyst left kidney',
	report,
	marked: [
		{ id: 'm1', cls: 'default', start: gStart, end: gStart + GREEN.length, text: GREEN },
		{
			id: 'm2',
			cls: 'implicated',
			start: aStart,
			end: aStart + AMBER.length,
			text: AMBER,
			pointer: 'simple cyst left kidney'
		}
	],
	removed: [{ id: 'r1', reason: 'contradicted', anchor: DICTATED.length, text: REMOVED }],
	options: [{ id: 'o1', anchor: report.length, text: OPTION }]
};

function load() {
	return createNegState(bundle, [history()]);
}

describe('negatives proto state', () => {
	it('loading a bundle yields a document equal to bundle.report', () => {
		const s = load();
		expect(s.doc.toString()).toBe(report);
		const items = negItems(s);
		expect(items.marks.map((m) => [m.from, m.to])).toEqual([
			[gStart, gStart + GREEN.length],
			[aStart, aStart + AMBER.length]
		]);
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
		const w = negItems(s1).widgets.find((x) => x.id === 'm1');
		expect(w?.kind).toBe('excluded');
		const s2 = s1.update(restoreExcluded(s1, 'm1')!).state;
		expect(s2.doc.toString()).toBe(report);
		const m = negItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
		expect(m?.cls).toBe('default');
		expect(negItems(s2).widgets.some((x) => x.id === 'm1')).toBe(false);
	});

	it('excluding an amber mark restores it as amber', () => {
		const s0 = load();
		const s1 = s0.update(excludeMark(s0, 'm2')!).state;
		expect(s1.doc.toString()).toBe(`${DICTATED} ${GREEN}`);
		const s2 = s1.update(restoreExcluded(s1, 'm2')!).state;
		expect(s2.doc.toString()).toBe(report);
		expect(negItems(s2).marks.find((x) => x.id === 'm2')?.cls).toBe('implicated');
	});

	it('undo of an exclude restores the doc and the mark; redo re-excludes', () => {
		const s0 = load();
		const s1 = s0.update(excludeMark(s0, 'm1')!).state;
		let s2 = s1;
		undo({ state: s1, dispatch: (tr) => (s2 = tr.state) });
		expect(s2.doc.toString()).toBe(report);
		const m = negItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
		expect(negItems(s2).widgets.some((x) => x.id === 'm1')).toBe(false);
		let s3 = s2;
		redo({ state: s2, dispatch: (tr) => (s3 = tr.state) });
		expect(s3.doc.toString()).toBe(`${DICTATED} ${AMBER}`);
		expect(negItems(s3).widgets.find((x) => x.id === 'm1')?.kind).toBe('excluded');
	});

	it('include of an option inserts " " + text at the anchor as plain text', () => {
		const s0 = load();
		const s1 = s0.update(includeOption(s0, 'o1')!).state;
		expect(s1.doc.toString()).toBe(`${report} ${OPTION}`);
		const items = negItems(s1);
		expect(items.widgets.some((w) => w.id === 'o1')).toBe(false);
		expect(items.marks.some((m) => s1.sliceDoc(m.from, m.to) === OPTION)).toBe(false);
	});

	it('restore of a removed item inserts it (space-separated) as a default mark', () => {
		const s0 = load();
		const s1 = s0.update(restoreRemoved(s0, 'r1')!).state;
		expect(s1.doc.toString()).toBe(`${DICTATED} ${REMOVED} ${GREEN} ${AMBER}`);
		const m = negItems(s1).marks.find((x) => x.id === 'r1');
		expect(m?.cls).toBe('default');
		expect(m && s1.sliceDoc(m.from, m.to)).toBe(REMOVED);
		expect(negItems(s1).widgets.some((w) => w.id === 'r1')).toBe(false);
		// later marks moved with the insertion
		const g = negItems(s1).marks.find((x) => x.id === 'm1')!;
		expect(s1.sliceDoc(g.from, g.to)).toBe(GREEN);
	});

	it('typing inside a green mark drops the mark; undo brings it back', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: gStart + 4, insert: 'X' }, userEvent: 'input.type' }).state;
		expect(negItems(s1).marks.some((m) => m.id === 'm1')).toBe(false);
		expect(negItems(s1).marks.some((m) => m.id === 'm2')).toBe(true);
		let s2 = s1;
		undo({ state: s1, dispatch: (tr) => (s2 = tr.state) });
		expect(s2.doc.toString()).toBe(report);
		const m = negItems(s2).marks.find((x) => x.id === 'm1');
		expect(m && s2.sliceDoc(m.from, m.to)).toBe(GREEN);
	});

	it('typing at a mark boundary does not drop it or extend it', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: gStart + GREEN.length, insert: ' Extra.' } }).state;
		const m = negItems(s1).marks.find((x) => x.id === 'm1');
		expect(m && s1.sliceDoc(m.from, m.to)).toBe(GREEN);
	});

	it('marks and widgets map correctly after an insertion before them', () => {
		const s0 = load();
		const ins = 'Comparison: none. ';
		const s1 = s0.update({ changes: { from: 0, insert: ins } }).state;
		const items = negItems(s1);
		for (const m of items.marks) {
			expect(s1.sliceDoc(m.from, m.to)).toBe(m.text);
		}
		expect(items.widgets.find((w) => w.id === 'r1')?.pos).toBe(DICTATED.length + ins.length);
		expect(items.widgets.find((w) => w.id === 'o1')?.pos).toBe(report.length + ins.length);
	});

	it('a widget whose anchor sentence is deleted stays at the mapped position', () => {
		const s0 = load();
		const s1 = s0.update({ changes: { from: 0, to: DICTATED.length + 1 } }).state;
		const w = negItems(s1).widgets.find((x) => x.id === 'r1');
		expect(w?.pos).toBe(0);
		// and can still be restored there
		const s2 = s1.update(restoreRemoved(s1, 'r1')!).state;
		expect(s2.doc.toString()).toBe(`${REMOVED} ${GREEN} ${AMBER}`);
	});

	it('the field is registered', () => {
		expect(load().field(negField, false)).toBeTruthy();
		expect(EditorState.create({ doc: 'x' }).field(negField, false)).toBeUndefined();
	});

	it('the synthetic sample bundle parses cleanly and loads as its report', () => {
		const { bundle: b, warnings } = parseBundle(sample);
		expect(warnings).toEqual([]);
		expect(createNegState(b).doc.toString()).toBe(b.report);
	});

	it('parseBundle rejects a wrong version', () => {
		expect(() => parseBundle({ ...bundle, version: 2 })).toThrow(/version/);
	});
});


import { checkReason } from './decorations';

describe('check reasons', () => {
	it('names why an amber item needs a check, with the matching evidence label', () => {
		expect(checkReason({}).evidenceLabel).toBe('Your finding');
		expect(checkReason({ reason: 'conflict' }).line).toMatch(/conflicts with your dictation/);
		expect(checkReason({ reason: 'number' }).evidenceLabel).toBe('Not in your dictation');
	});
});
