/**
 * The review field (plan Task C1): the editor state for review items, generalised from the negatives prototype
 * (`lib/review/negatives-proto/state.ts`, which stays for /dev/negatives-proto).
 *
 * The CM6 document IS the report. Anchored items are marks over document text; removed text, options and
 * excluded items are widgets (display only, never document text), so copy, select-all and export only ever see
 * what the radiologist will sign (the copy invariant).
 *
 * All items live in one StateField and map through every change. Toggles (exclude, restore, include) are
 * ordinary transactions carrying a `setItems` snapshot in POST-change coordinates; `invertedEffects` records the
 * pre-transaction snapshot, so history() undo/redo restores both the text and the items. Editing inside a mark
 * drops it (the text became the radiologist's own) and reports the item stale: a `staleEffect` on the
 * transaction, delivered to `onReviewStale` callbacks by the view's update listener.
 */
import {
	EditorState,
	Facet,
	StateEffect,
	StateField,
	Transaction,
	type ChangeDesc,
	type Extension,
	type TransactionSpec
} from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { invertedEffects } from '@codemirror/commands';
import { locate } from '../anchors';
import { toChanges } from '../edits';
import type { Cls, ItemEvidence, ItemLane, ReviewItem } from '../types';

/** How a mark is presented. */
export type MarkClass = 'rv-normal' | 'rv-check' | 'rv-preapplied' | 'rv-action' | 'rv-minor' | 'rv-info';

/** Why an amber (check) item needs a check (evidence.check_reason; absent = uncertain). */
export type CheckReasonCode = 'uncertain' | 'conflict' | 'number';

/** What a mark carries besides its range. */
export interface MarkMeta {
	id: string;
	kind: string;
	cls: Cls;
	lane: ItemLane;
	mark: MarkClass;
	pointer?: string;
	reason?: string; // check items: evidence.check_reason
}

export interface LiveMark extends MarkMeta {
	from: number;
	to: number;
	text: string;
}

export type WidgetItem =
	| {
			kind: 'removed';
			id: string;
			lane: ItemLane;
			pos: number;
			text: string;
			reason: 'contradicted' | 'number';
			pointer?: string;
			preApplied: boolean;
	  }
	| { kind: 'option'; id: string; lane: ItemLane; pos: number; text: string; reason?: string }
	| {
			kind: 'excluded';
			id: string;
			pos: number;
			text: string;
			mark: MarkMeta; // restored verbatim
			lead: string; // whitespace trimmed before the text on exclude (restored verbatim)
			trail: string; // whitespace trimmed after it
	  };

export interface ReviewFieldState {
	marks: LiveMark[];
	widgets: WidgetItem[];
}

const EMPTY: ReviewFieldState = { marks: [], widgets: [] };

// ---- check reasons ----

export function checkReason(evidence: Pick<ItemEvidence, 'check_reason'> | null | undefined): {
	line: string;
	evidenceLabel: string;
} {
	switch (evidence?.check_reason) {
		case 'conflict':
			return { line: 'Likely conflicts with your dictation; could not be removed automatically.', evidenceLabel: 'Your dictation' };
		case 'number':
			return { line: 'Contains a measurement you did not dictate.', evidenceLabel: 'Not in your dictation' };
		default:
			return { line: 'Assumed normal, but one of your findings makes it uncertain.', evidenceLabel: 'Your finding' };
	}
}

// ---- building the field from review items ----

export interface FromItemsOptions {
	/** Where the field currently holds each removed widget (item id → position), mapped through edits. */
	widgetPos?: Record<string, number>;
	/** Ids to leave out entirely (neither placed nor stale), e.g. items the user has excluded locally. */
	skip?: ReadonlySet<string>;
}

function isShown(it: ReviewItem): boolean {
	return it.cls !== 'suppress' && (it.status === 'open' || it.status === 'pre_applied');
}

function isRemovalWidget(it: ReviewItem): boolean {
	if (!it.anchor || it.anchor.text) return false; // a removal still in the text is an ordinary mark
	return it.kind === 'removed' || (it.status === 'pre_applied' && it.edit?.mode === 'remove');
}

function markClassOf(it: ReviewItem): MarkClass {
	if (it.status === 'pre_applied') return 'rv-preapplied';
	if (it.kind === 'assumed_normal') return 'rv-normal';
	if (it.kind === 'check') return 'rv-check';
	return it.cls === 'action' ? 'rv-action' : it.cls === 'minor' ? 'rv-minor' : 'rv-info';
}

function str(v: unknown): string | undefined {
	return typeof v === 'string' && v ? v : undefined;
}

function metaOf(it: ReviewItem): MarkMeta {
	const meta: MarkMeta = { id: it.id, kind: it.kind, cls: it.cls, lane: it.lane, mark: markClassOf(it) };
	const pointer = str(it.evidence?.pointer);
	if (pointer) meta.pointer = pointer;
	if (it.kind === 'check') meta.reason = str(it.evidence?.check_reason) ?? 'uncertain';
	return meta;
}

/** A pre-applied edit whose anchor is lost: live mode's undo span still marks the written text. */
function undoSpan(doc: string, it: ReviewItem): { from: number; to: number } | null {
	const fs = it.evidence?.undo?.final_span;
	if (!fs) return null;
	const [from, to] = fs;
	if (!(from >= 0 && to <= doc.length && from < to)) return null;
	const got = doc.slice(from, to);
	const want = [it.edit?.replace?.trim(), it.anchor?.text].filter(Boolean);
	return want.includes(got) ? { from, to } : null;
}

/** Place store items in `doc`. Items that should be shown but cannot be located come back in `stale`. Items
 * with neither an anchor nor a widget (rail-only) are left out and are not stale. */
export function fromItems(
	doc: string,
	items: readonly ReviewItem[],
	opts: FromItemsOptions = {}
): { items: ReviewFieldState; stale: string[] } {
	const marks: LiveMark[] = [];
	const widgets: WidgetItem[] = [];
	const stale: string[] = [];
	for (const it of items) {
		if (!isShown(it) || opts.skip?.has(it.id)) continue;

		if (it.kind === 'option') {
			const c = toChanges(doc, it.edit);
			const text = it.edit?.replace?.trim();
			if (c && text && c.from === c.to) {
				widgets.push({ kind: 'option', id: it.id, lane: it.lane, pos: c.from, text, reason: it.reason || undefined });
			} else stale.push(it.id);
			continue;
		}

		if (isRemovalWidget(it)) {
			const ev = it.evidence ?? {};
			const text = str(ev.removed_text) ?? str(ev.undo?.original_text) ?? str(it.edit?.find);
			const widgetPos = opts.widgetPos?.[it.id] ?? ev.undo?.final_span?.[0] ?? it.anchor!.start;
			const at = text ? locate(doc, it, { widgetPos }) : null;
			if (!at || !text) {
				stale.push(it.id);
				continue;
			}
			const w: WidgetItem = {
				kind: 'removed',
				id: it.id,
				lane: it.lane,
				pos: at.from,
				text,
				reason: ev.check_reason === 'number' || ev.removal_reason === 'number' ? 'number' : 'contradicted',
				preApplied: it.status === 'pre_applied'
			};
			const pointer = str(ev.pointer);
			if (pointer) w.pointer = pointer;
			widgets.push(w);
			continue;
		}

		if (!it.anchor) continue; // rail-only
		const at = locate(doc, it) ?? (it.status === 'pre_applied' ? undoSpan(doc, it) : null);
		if (!at || at.to <= at.from) {
			stale.push(it.id);
			continue;
		}
		marks.push({ ...metaOf(it), from: at.from, to: at.to, text: doc.slice(at.from, at.to) });
	}
	marks.sort((a, b) => a.from - b.from);
	return { items: { marks, widgets }, stale };
}

// ---- the field ----

/** Map items through a change. With `dropTouched`, a mark whose interior was edited is dropped (the text became
 * the radiologist's own). Widgets always survive at their mapped position. */
export function mapItems(items: ReviewFieldState, changes: ChangeDesc, dropTouched = false): ReviewFieldState {
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

export const setItems = StateEffect.define<ReviewFieldState>({ map: (v, mapping) => mapItems(v, mapping) });

/** Item ids that became stale in this transaction (a mark dropped by an interior edit, or an item a sync could
 * not locate). */
export const staleEffect = StateEffect.define<string[]>();

/** Called with the ids of items that became stale. The store marks them `stale`. */
export const onReviewStale = Facet.define<(ids: string[]) => void>();

export const reviewField = StateField.define<ReviewFieldState>({
	create: () => EMPTY,
	update(items, tr) {
		let next = tr.docChanged ? mapItems(items, tr.changes, true) : items;
		for (const e of tr.effects) if (e.is(setItems)) next = e.value;
		return next;
	}
});

/** Undo/redo support: whenever a transaction set the items or dropped a mark, the inverse transaction restores
 * the snapshot from before it. */
const reviewHistory = invertedEffects.of((tr) => {
	const before = tr.startState.field(reviewField, false);
	if (!before) return [];
	const explicit = tr.effects.some((e) => e.is(setItems));
	const after = tr.state.field(reviewField);
	const dropped = after.marks.length < before.marks.length;
	return explicit || dropped ? [setItems.of(before)] : [];
});

/** A user edit (no `setItems`) that touches a mark's interior: tag the transaction with the dropped ids. */
const staleExtender = EditorState.transactionExtender.of((tr) => {
	if (!tr.docChanged || tr.effects.some((e) => e.is(setItems))) return null;
	const items = tr.startState.field(reviewField, false);
	if (!items) return null;
	const ids = items.marks.filter((m) => touchesInterior(tr.changes, m.from, m.to)).map((m) => m.id);
	return ids.length ? { effects: staleEffect.of(ids) } : null;
});

const staleListener = EditorView.updateListener.of((update) => {
	const callbacks = update.state.facet(onReviewStale);
	if (!callbacks.length) return;
	for (const tr of update.transactions) {
		const ids = staleItems(tr);
		if (ids.length) for (const cb of callbacks) cb(ids);
	}
});

/** The ids this transaction reported stale. */
export function staleItems(tr: Transaction): string[] {
	const ids: string[] = [];
	for (const e of tr.effects) if (e.is(staleEffect)) ids.push(...e.value);
	return ids;
}

export function reviewItems(state: EditorState): ReviewFieldState {
	return state.field(reviewField, false) ?? EMPTY;
}

/** The field, its undo support and stale reporting, initialised with `initial`. */
export function reviewFieldExtension(initial: ReviewFieldState = EMPTY): Extension {
	return [reviewField.init(() => initial), reviewHistory, staleExtender, staleListener];
}

export function createReviewState(doc: string, items: readonly ReviewItem[], extra: Extension[] = []): EditorState {
	return EditorState.create({ doc, extensions: [reviewFieldExtension(fromItems(doc, items).items), ...extra] });
}

/** Replace the field from fresh store items (a server update). Not undoable; keeps current widget positions and
 * locally excluded items; items that can no longer be located are reported stale. */
export function syncItems(state: EditorState, items: readonly ReviewItem[]): TransactionSpec {
	const cur = reviewItems(state);
	const widgetPos: Record<string, number> = {};
	const excluded = cur.widgets.filter((w) => w.kind === 'excluded');
	for (const w of cur.widgets) if (w.kind === 'removed') widgetPos[w.id] = w.pos;
	const keep = new Set(items.filter(isShown).map((i) => i.id));
	const { items: next, stale } = fromItems(state.doc.toString(), items, {
		widgetPos,
		skip: new Set(excluded.map((w) => w.id))
	});
	const effects: StateEffect<unknown>[] = [
		setItems.of({ marks: next.marks, widgets: [...next.widgets, ...excluded.filter((w) => keep.has(w.id))] })
	];
	if (stale.length) effects.push(staleEffect.of(stale));
	return { effects, annotations: Transaction.addToHistory.of(false) };
}

// ---- toggles: each returns a TransactionSpec (or null if the item is gone) ----

function isWs(ch: string): boolean {
	return ch === '' || /\s/.test(ch);
}

/** Insert `text` at `pos` as a mark, with a separating space where needed. */
function insertAsMark(
	state: EditorState,
	pos: number,
	text: string,
	meta: MarkMeta,
	dropWidgetId: string,
	userEvent: string,
	lead?: string,
	trail?: string
): TransactionSpec {
	const before = state.sliceDoc(pos - 1, pos);
	const after = state.sliceDoc(pos, pos + 1);
	const l = lead ?? (isWs(before) ? '' : ' ');
	const t = trail ?? (l === '' && !isWs(after) ? ' ' : '');
	const changes = state.changes({ from: pos, insert: l + text + t });
	const mapped = mapItems(reviewItems(state), changes);
	const from = pos + l.length;
	const marks = [...mapped.marks, { ...meta, from, to: from + text.length, text }].sort((a, b) => a.from - b.from);
	return {
		changes,
		effects: setItems.of({ marks, widgets: mapped.widgets.filter((w) => w.id !== dropWidgetId) }),
		userEvent
	};
}

/** Removed (red) widget → restore its text as a normal (green) mark. */
export function restoreRemoved(state: EditorState, id: string): TransactionSpec | null {
	const w = reviewItems(state).widgets.find((x) => x.id === id && x.kind === 'removed');
	if (!w || w.kind !== 'removed') return null;
	const meta: MarkMeta = { id: w.id, kind: 'removed', cls: 'info', lane: w.lane, mark: 'rv-normal' };
	if (w.pointer) meta.pointer = w.pointer;
	return insertAsMark(state, w.pos, w.text, meta, w.id, 'review.restore');
}

/** Excluded (grey) widget → put the text back exactly, as a mark of its original class. */
export function restoreExcluded(state: EditorState, id: string): TransactionSpec | null {
	const w = reviewItems(state).widgets.find((x) => x.id === id && x.kind === 'excluded');
	if (!w || w.kind !== 'excluded') return null;
	return insertAsMark(state, w.pos, w.text, w.mark, w.id, 'review.restore', w.lead, w.trail);
}

/** Option (ghost) widget → insert " " + text at the anchor as plain (dictated-style) text. */
export function includeOption(state: EditorState, id: string): TransactionSpec | null {
	const w = reviewItems(state).widgets.find((x) => x.id === id && x.kind === 'option');
	if (!w) return null;
	const changes = state.changes({ from: w.pos, insert: ' ' + w.text });
	const mapped = mapItems(reviewItems(state), changes);
	return {
		changes,
		effects: setItems.of({ marks: mapped.marks, widgets: mapped.widgets.filter((x) => x.id !== id) }),
		userEvent: 'review.include'
	};
}

/** A mark → remove its text (and one adjacent space) and leave an "excluded" widget. */
export function excludeMark(state: EditorState, id: string): TransactionSpec | null {
	const items = reviewItems(state);
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
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	const { from: _f, to: _t, text: _x, ...meta } = m;
	const widget: WidgetItem = { kind: 'excluded', id, pos: changes.mapPos(from, -1), text, mark: meta, lead, trail };
	return {
		changes,
		effects: setItems.of({ marks: rest.marks, widgets: [...rest.widgets, widget] }),
		userEvent: 'review.exclude'
	};
}

export interface ReviewCounts {
	normal: number;
	check: number;
	preapplied: number;
	flagged: number; // lane-group marks (rv-action / rv-minor / rv-info)
	removed: number;
	options: number;
	excluded: number;
}

export function reviewCounts(items: ReviewFieldState): ReviewCounts {
	const by = (c: MarkClass) => items.marks.filter((m) => m.mark === c).length;
	return {
		normal: by('rv-normal'),
		check: by('rv-check'),
		preapplied: by('rv-preapplied'),
		flagged: by('rv-action') + by('rv-minor') + by('rv-info'),
		removed: items.widgets.filter((w) => w.kind === 'removed').length,
		options: items.widgets.filter((w) => w.kind === 'option').length,
		excluded: items.widgets.filter((w) => w.kind === 'excluded').length
	};
}
