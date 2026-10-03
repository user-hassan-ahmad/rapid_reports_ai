/**
 * Negatives prototype (dev only): the editor state for generated normal/negative statements.
 *
 * The CM6 document IS the report. Green/amber items are ranges over document text; removed
 * items, excluded items and options are widgets (display only, never document text), so copy,
 * select-all and export only ever see what the radiologist will sign.
 *
 * All items live in one StateField and map through every change. Toggles (exclude, restore,
 * include) are ordinary transactions carrying a `setItems` snapshot in POST-change coordinates;
 * `invertedEffects` records the pre-transaction snapshot, so history() undo/redo restores both
 * the text and the items.
 */
import { EditorState, StateEffect, StateField, type ChangeDesc, type Extension, type TransactionSpec } from '@codemirror/state';
import { invertedEffects } from '@codemirror/commands';
import type { NegativesBundle, NegClass } from './bundle';

export interface LiveMark {
	id: string;
	cls: NegClass;
	from: number;
	to: number;
	text: string;
	pointer?: string;
}

export type WidgetItem =
	| { kind: 'removed'; id: string; pos: number; text: string; reason: 'contradicted' | 'number'; pointer?: string }
	| { kind: 'option'; id: string; pos: number; text: string; reason?: string }
	| {
			kind: 'excluded';
			id: string;
			pos: number;
			text: string;
			cls: NegClass;
			pointer?: string;
			lead: string; // whitespace trimmed before the text on exclude (restored verbatim)
			trail: string; // whitespace trimmed after it
	  };

export interface NegItems {
	marks: LiveMark[];
	widgets: WidgetItem[];
}

const EMPTY: NegItems = { marks: [], widgets: [] };

/** Map items through a change. With `dropTouched`, a mark whose interior was edited is dropped
 * (the text became the radiologist's own). Widgets always survive at their mapped position. */
export function mapItems(items: NegItems, changes: ChangeDesc, dropTouched = false): NegItems {
	if (changes.empty) return items;
	const marks: LiveMark[] = [];
	for (const m of items.marks) {
		if (dropTouched && touchesInterior(changes, m.from, m.to)) continue;
		const from = changes.mapPos(m.from, 1);
		const to = changes.mapPos(m.to, -1);
		if (to <= from) continue;
		marks.push({ ...m, from, to });
	}
	const widgets = items.widgets.map((w) => ({ ...w, pos: changes.mapPos(w.pos, -1) }));
	return { marks, widgets };
}

function touchesInterior(changes: ChangeDesc, from: number, to: number): boolean {
	let hit = false;
	changes.iterChangedRanges((fromA, toA) => {
		if (hit) return;
		if (fromA === toA) hit = fromA > from && fromA < to; // pure insertion strictly inside
		else hit = fromA < to && toA > from; // deletion/replacement overlapping the text
	});
	return hit;
}

export const setItems = StateEffect.define<NegItems>({ map: (v, mapping) => mapItems(v, mapping) });

export const negField = StateField.define<NegItems>({
	create: () => EMPTY,
	update(items, tr) {
		let next = tr.docChanged ? mapItems(items, tr.changes, true) : items;
		for (const e of tr.effects) if (e.is(setItems)) next = e.value;
		return next;
	}
});

/** Undo/redo support: whenever a transaction set the items or dropped a mark, the inverse
 * transaction restores the snapshot from before it. */
const negHistory = invertedEffects.of((tr) => {
	const before = tr.startState.field(negField, false);
	if (!before) return [];
	const explicit = tr.effects.some((e) => e.is(setItems));
	const after = tr.state.field(negField);
	const dropped = after.marks.length < before.marks.length;
	return explicit || dropped ? [setItems.of(before)] : [];
});

export function negItems(state: EditorState): NegItems {
	return state.field(negField, false) ?? EMPTY;
}

export function itemsFromBundle(b: NegativesBundle): NegItems {
	return {
		marks: b.marked.map((m) => ({ id: m.id, cls: m.cls, from: m.start, to: m.end, text: m.text, pointer: m.pointer })),
		widgets: [
			...b.removed.map(
				(r): WidgetItem => ({ kind: 'removed', id: r.id, pos: r.anchor, text: r.text, reason: r.reason, pointer: r.pointer })
			),
			...b.options.map((o): WidgetItem => ({ kind: 'option', id: o.id, pos: o.anchor, text: o.text, reason: o.reason }))
		]
	};
}

export function createNegState(b: NegativesBundle, extra: Extension[] = []): EditorState {
	return EditorState.create({
		doc: b.report,
		extensions: [negField.init(() => itemsFromBundle(b)), negHistory, ...extra]
	});
}

/** Parse and sanity-check a bundle loaded from disk. Throws with a readable message. Returns
 * warnings for marks whose offsets do not match their text (they are still loaded). */
export function parseBundle(raw: unknown): { bundle: NegativesBundle; warnings: string[] } {
	const b = raw as NegativesBundle;
	if (!b || typeof b !== 'object') throw new Error('Bundle is not a JSON object');
	if (b.version !== 1) throw new Error(`Unsupported bundle version: ${String((b as { version?: unknown }).version)}`);
	if (typeof b.report !== 'string') throw new Error('Bundle has no report text');
	for (const k of ['marked', 'removed', 'options'] as const) if (!Array.isArray(b[k])) throw new Error(`Bundle.${k} must be an array`);
	const warnings: string[] = [];
	const n = b.report.length;
	for (const m of b.marked) {
		if (!(m.start >= 0 && m.end <= n && m.start < m.end)) throw new Error(`Mark ${m.id} has offsets out of range`);
		if (b.report.slice(m.start, m.end) !== m.text) warnings.push(`Mark ${m.id}: offsets do not match its text`);
	}
	for (const w of [...b.removed, ...b.options]) {
		if (!(w.anchor >= 0 && w.anchor <= n)) throw new Error(`Item ${w.id} has an anchor out of range`);
	}
	return { bundle: b, warnings };
}

// ---- toggles: each returns a TransactionSpec (or null if the item is gone) ----

function isWs(ch: string): boolean {
	return ch === '' || /\s/.test(ch);
}

/** Insert `text` at `pos` as a mark of `cls`, with a separating space where needed. */
function insertAsMark(
	state: EditorState,
	pos: number,
	text: string,
	mark: Omit<LiveMark, 'from' | 'to' | 'text'>,
	dropWidgetId: string,
	lead?: string,
	trail?: string
): TransactionSpec {
	const before = state.sliceDoc(pos - 1, pos);
	const after = state.sliceDoc(pos, pos + 1);
	const l = lead ?? (isWs(before) ? '' : ' ');
	const t = trail ?? (l === '' && !isWs(after) ? ' ' : '');
	const changes = state.changes({ from: pos, insert: l + text + t });
	const mapped = mapItems(negItems(state), changes);
	const from = pos + l.length;
	const marks = [...mapped.marks, { ...mark, from, to: from + text.length, text }].sort((a, b) => a.from - b.from);
	return {
		changes,
		effects: setItems.of({ marks, widgets: mapped.widgets.filter((w) => w.id !== dropWidgetId) }),
		userEvent: 'neg.restore'
	};
}

/** Removed (red) widget → restore as a default (green) mark. */
export function restoreRemoved(state: EditorState, id: string): TransactionSpec | null {
	const w = negItems(state).widgets.find((x) => x.id === id && x.kind === 'removed');
	if (!w || w.kind !== 'removed') return null;
	return insertAsMark(state, w.pos, w.text, { id: w.id, cls: 'default', pointer: w.pointer }, w.id);
}

/** Excluded (grey) widget → put the text back exactly, as a mark of its original class. */
export function restoreExcluded(state: EditorState, id: string): TransactionSpec | null {
	const w = negItems(state).widgets.find((x) => x.id === id && x.kind === 'excluded');
	if (!w || w.kind !== 'excluded') return null;
	return insertAsMark(state, w.pos, w.text, { id: w.id, cls: w.cls, pointer: w.pointer }, w.id, w.lead, w.trail);
}

/** Option (ghost) widget → insert " " + text at the anchor as plain (dictated-style) text. */
export function includeOption(state: EditorState, id: string): TransactionSpec | null {
	const w = negItems(state).widgets.find((x) => x.id === id && x.kind === 'option');
	if (!w) return null;
	const changes = state.changes({ from: w.pos, insert: ' ' + w.text });
	const mapped = mapItems(negItems(state), changes);
	return {
		changes,
		effects: setItems.of({ marks: mapped.marks, widgets: mapped.widgets.filter((x) => x.id !== id) }),
		userEvent: 'neg.include'
	};
}

/** Green/amber mark → remove its text (and one adjacent space) and leave an "excluded" widget. */
export function excludeMark(state: EditorState, id: string): TransactionSpec | null {
	const items = negItems(state);
	const m = items.marks.find((x) => x.id === id);
	if (!m) return null;
	let from = m.from;
	let to = m.to;
	let lead = '';
	let trail = '';
	if (state.sliceDoc(from - 1, from) === ' ') {
		from -= 1;
		lead = ' ';
	} else if (state.sliceDoc(to, to + 1) === ' ') {
		to += 1;
		trail = ' ';
	}
	const text = state.sliceDoc(m.from, m.to);
	const changes = state.changes({ from, to });
	const rest = mapItems({ marks: items.marks.filter((x) => x.id !== id), widgets: items.widgets }, changes);
	const widget: WidgetItem = { kind: 'excluded', id, pos: changes.mapPos(from, -1), text, cls: m.cls, pointer: m.pointer, lead, trail };
	return {
		changes,
		effects: setItems.of({ marks: rest.marks, widgets: [...rest.widgets, widget] }),
		userEvent: 'neg.exclude'
	};
}

export interface NegCounts {
	added: number;
	check: number;
	removed: number;
	options: number;
	excluded: number;
}

export function negCounts(items: NegItems): NegCounts {
	return {
		added: items.marks.filter((m) => m.cls === 'default').length,
		check: items.marks.filter((m) => m.cls === 'implicated').length,
		removed: items.widgets.filter((w) => w.kind === 'removed').length,
		options: items.widgets.filter((w) => w.kind === 'option').length,
		excluded: items.widgets.filter((w) => w.kind === 'excluded').length
	};
}
