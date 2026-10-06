/**
 * How the review field is drawn (plan Task C2), generalised from the negatives prototype
 * (`lib/review/negatives-proto/decorations.ts`, which stays for /dev/negatives-proto).
 *
 * - Marks: their class plus `data-rv-id` and an accessible name; clicking one opens the popover.
 * - Widgets (removed / option / excluded): display only at their anchor, never document text (the copy invariant).
 * - The popover (`showTooltip`, opened on click, closed with Escape): label, reason, `source_line`, the edit as a
 *   diff, and the item's actions.
 * - Gutter markers: one per line with items, keyed by the highest cls on the line.
 *
 * Every button (popover and widgets) goes through review commands: it calls the `onReviewCommand` callbacks with
 * (command name, item id, args) and nothing else. The host runs the command (lib/review/commands.ts), dispatches
 * `commandTransaction` and posts the event. The prototype's local toggles are never used here.
 */
import {
	Facet,
	RangeSet,
	StateEffect,
	StateField,
	type Extension,
	type Range
} from '@codemirror/state';
import {
	Decoration,
	EditorView,
	GutterMarker,
	WidgetType,
	gutter,
	keymap,
	showTooltip,
	type DecorationSet,
	type Tooltip
} from '@codemirror/view';
import type { CommandName } from '../commands';
import type { Cls, ReviewItem } from '../types';
import {
	checkReason,
	reviewField,
	reviewItems,
	type LiveMark,
	type MarkClass,
	type ReviewFieldState,
	type WidgetItem
} from './field';

// ---- labels and icons (label set "E · meaning"; shared with the rail legend) ----

export const LABELS = {
	dictated: 'Your dictation',
	normal: 'Assumed normal',
	check: 'Check',
	removed: 'Removed · contradicts your dictation',
	removedNumber: 'Removed · a measurement you did not dictate',
	excluded: 'Removed by you',
	option: 'Suggested · not included',
	preapplied: 'Added from your dictation',
	action: 'Needs action',
	minor: 'Worth a look',
	info: 'For information'
} as const;

/** Longer explanations, used when an item has no reason of its own. */
export const DESCRIPTIONS = {
	normal: 'Not mentioned in your dictation, so stated as normal.',
	preapplied: 'Changed to match your dictation. Undo if needed.',
	removed: 'Taken out because it contradicts your dictation. Restore if needed.',
	removedNumber:
		'Taken out because it carries a measurement you did not dictate. Restore if needed.',
	option: 'Not in the report. Include it if relevant.'
} as const;

/** Small non-colour markers, shared by the legend, the editor and the gutter. */
export const ICONS = {
	dictated: '✎',
	normal: '+',
	check: '?',
	removed: '✕',
	excluded: '⊘',
	option: '◌',
	preapplied: '↺',
	action: '!',
	minor: '•',
	info: 'i'
} as const;

export type Meaning = keyof typeof ICONS;

/** The legend, in order: "E · meaning". */
export const LEGEND: { key: Meaning; icon: string; label: string }[] = (
	['dictated', 'normal', 'check', 'removed', 'excluded', 'option'] as const
).map((key) => ({ key, icon: ICONS[key], label: LABELS[key] }));

const MARK_MEANING: Record<MarkClass, Meaning> = {
	'rv-normal': 'normal',
	'rv-check': 'check',
	'rv-preapplied': 'preapplied',
	'rv-action': 'action',
	'rv-minor': 'minor',
	'rv-info': 'info'
};

// ---- the host's hooks ----

export type ReviewCommandCallback = (
	name: CommandName,
	itemId: string,
	args?: Record<string, unknown>
) => void;

/** Called by every popover and widget button. The host runs the command and dispatches its transaction. */
export const onReviewCommand = Facet.define<ReviewCommandCallback>();

/** The store item behind a mark or widget, for the popover's label, reason, dictation line and edit. */
export const reviewItemLookup = Facet.define<
	(id: string) => ReviewItem | undefined,
	(id: string) => ReviewItem | undefined
>({
	combine: (fns) => (id) => {
		for (const f of fns) {
			const it = f(id);
			if (it) return it;
		}
		return undefined;
	}
});

export const openPopover = StateEffect.define<string | null>();

function send(
	view: EditorView,
	name: CommandName,
	id: string,
	args?: Record<string, unknown>
): void {
	for (const cb of view.state.facet(onReviewCommand)) cb(name, id, args);
	if (view.state.field(popoverField, false)) view.dispatch({ effects: openPopover.of(null) });
}

function button(label: string, title: string, onClick: () => void): HTMLButtonElement {
	const b = document.createElement('button');
	b.type = 'button';
	b.className = 'rv-btn';
	b.textContent = label;
	b.title = title;
	b.setAttribute('aria-label', title);
	b.addEventListener('mousedown', (e) => e.preventDefault()); // keep editor focus and selection
	b.addEventListener('click', (e) => {
		e.preventDefault();
		e.stopPropagation();
		onClick();
	});
	return b;
}

function el(tag: string, className: string, text?: string): HTMLElement {
	const e = document.createElement(tag);
	e.className = className;
	if (text != null) e.textContent = text;
	return e;
}

// ---- widgets ----

function widgetLabel(w: WidgetItem): string {
	if (w.kind === 'removed') {
		let t = w.reason === 'number' ? LABELS.removedNumber : LABELS.removed;
		if (w.pointer) t += ` (you dictated: “${w.pointer}”)`;
		return t;
	}
	if (w.kind === 'excluded') return LABELS.excluded;
	return LABELS.option + (w.reason ? ` (${w.reason})` : '');
}

class ItemWidget extends WidgetType {
	constructor(readonly item: WidgetItem) {
		super();
	}
	eq(other: ItemWidget): boolean {
		const a = this.item;
		const b = other.item;
		return (
			a.id === b.id && a.kind === b.kind && a.text === b.text && widgetLabel(a) === widgetLabel(b)
		);
	}
	toDOM(view: EditorView): HTMLElement {
		const it = this.item;
		const wrap = el('span', `rv-widget rv-${it.kind}`);
		wrap.setAttribute('data-rv-widget', it.id);
		wrap.setAttribute('role', 'group');
		const label = widgetLabel(it);
		wrap.setAttribute('aria-label', `${label}: ${it.text}`);
		wrap.title = label;
		const icon = el(
			'span',
			'rv-icon',
			it.kind === 'removed' ? ICONS.removed : it.kind === 'excluded' ? ICONS.excluded : ICONS.option
		);
		icon.setAttribute('aria-hidden', 'true');
		wrap.append(' ', icon, el('span', 'rv-wtext', it.text));
		if (it.kind === 'removed')
			wrap.append(
				button('Restore', 'Put this statement back into the report', () =>
					send(view, 'restore', it.id)
				)
			);
		else if (it.kind === 'option')
			wrap.append(
				button('Include', 'Add this statement to the report', () => send(view, 'apply', it.id))
			);
		return wrap;
	}
	ignoreEvent(): boolean {
		return true;
	}
}

// ---- marks + widgets ----

function markLabel(m: LiveMark): string {
	const meaning = MARK_MEANING[m.mark];
	let t: string = LABELS[meaning];
	if (m.mark === 'rv-check') t += ` · ${checkReason({ check_reason: m.reason }).line}`;
	return `${t} · click for details`;
}

const reviewDecorations = EditorView.decorations.compute([reviewField], (state): DecorationSet => {
	const items = reviewItems(state);
	const ranges: Range<Decoration>[] = [];
	for (const m of items.marks) {
		const label = markLabel(m);
		ranges.push(
			Decoration.mark({
				class: `rv-mark ${m.mark}`,
				attributes: { 'data-rv-id': m.id, 'aria-label': label, title: label }
			}).range(m.from, m.to)
		);
	}
	for (const w of items.widgets)
		ranges.push(Decoration.widget({ widget: new ItemWidget(w), side: 1 }).range(w.pos));
	return Decoration.set(ranges, true);
});

// ---- popover ----

function isRemoval(it: ReviewItem | undefined, m: LiveMark): boolean {
	return m.kind === 'removed' || it?.kind === 'removed' || it?.edit?.mode === 'remove';
}

function diffOf(it: ReviewItem): HTMLElement | null {
	const e = it.edit;
	if (!e || it.status === 'pre_applied') return null;
	const find = e.mode === 'insert' ? '' : (e.find ?? '');
	const repl = e.mode === 'remove' ? '' : (e.replace ?? '');
	if (!find && !repl) return null;
	const d = el('div', 'rv-popover-diff');
	d.setAttribute('aria-label', 'Proposed change');
	if (find) d.append(el('del', '', find));
	if (find && repl) d.append(' → ');
	if (repl) d.append(el('ins', '', repl));
	return d;
}

function popoverDom(view: EditorView, m: LiveMark): HTMLElement {
	const it = view.state.facet(reviewItemLookup)(m.id);
	const meaning = MARK_MEANING[m.mark];
	const dom = el('div', `rv-popover rv-popover-${meaning}`);
	dom.setAttribute('role', 'dialog');

	const check =
		m.mark === 'rv-check' ? checkReason(it?.evidence ?? { check_reason: m.reason }) : null;
	const head = el('div', 'rv-popover-label');
	const icon = el('span', 'rv-icon', ICONS[meaning]);
	icon.setAttribute('aria-hidden', 'true');
	const title = it?.label || LABELS[meaning];
	head.append(icon, title);
	dom.append(head);
	dom.setAttribute('aria-label', title);

	const reason =
		it?.reason ||
		check?.line ||
		(meaning === 'normal'
			? DESCRIPTIONS.normal
			: meaning === 'preapplied'
				? DESCRIPTIONS.preapplied
				: '');
	if (reason) dom.append(el('div', 'rv-popover-reason', reason));
	if (check && it?.reason && check.line !== it.reason)
		dom.append(el('div', 'rv-popover-reason', check.line));

	const pointer = (typeof it?.evidence?.pointer === 'string' && it.evidence.pointer) || m.pointer;
	if (pointer)
		dom.append(
			el(
				'div',
				'rv-popover-pointer',
				`${check ? check.evidenceLabel : 'Dictated finding'}: “${pointer}”`
			)
		);
	if (it?.source_line)
		dom.append(el('div', 'rv-popover-source', `You dictated: “${it.source_line}”`));

	const diff = it ? diffOf(it) : null;
	if (diff) dom.append(diff);

	const row = el('div', 'rv-popover-actions');
	const id = m.id;
	if (m.mark === 'rv-preapplied') {
		if (isRemoval(it, m))
			row.append(button('Restore', 'Put the original text back', () => send(view, 'restore', id)));
		else row.append(button('Undo', 'Take this change back out', () => send(view, 'undo', id)));
	} else if (m.mark === 'rv-check') {
		row.append(
			button('Keep', 'Keep this statement as written', () => send(view, 'keep', id)),
			button('Remove', 'Remove this statement from the report', () => send(view, 'remove', id))
		);
	} else if (m.mark === 'rv-normal') {
		row.append(
			button('Remove', 'Remove this statement from the report', () => send(view, 'remove', id))
		);
	} else {
		if (it?.edit)
			row.append(button('Apply', 'Apply the suggested change', () => send(view, 'apply', id)));
		row.append(
			button('Edit', 'Write your own replacement', () =>
				startEdit(view, dom, row, id, it?.edit?.replace ?? m.text)
			),
			button('Dismiss', 'Dismiss this item', () => send(view, 'dismiss', id))
		);
	}
	const close = button('×', 'Close', () => {
		view.dispatch({ effects: openPopover.of(null) });
		view.focus();
	});
	row.append(close);
	dom.append(row);
	return dom;
}

/** Edit: swap the actions for an inline input; Enter (or Save) sends `edit` with the replacement. The verifier
 * guards are server-side; the probe loop checks the result. */
function startEdit(
	view: EditorView,
	dom: HTMLElement,
	row: HTMLElement,
	id: string,
	initial: string
): void {
	const input = document.createElement('input');
	input.type = 'text';
	input.className = 'rv-popover-input';
	input.value = initial;
	input.setAttribute('aria-label', 'Replacement text');
	const save = () => send(view, 'edit', id, { replacement: input.value });
	const cancel = () => {
		view.dispatch({ effects: openPopover.of(null) });
		view.focus();
	};
	input.addEventListener('keydown', (e) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			save();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancel();
		}
	});
	const actions = el('div', 'rv-popover-actions');
	actions.append(button('Save', 'Use this text', save), button('Cancel', 'Cancel editing', cancel));
	row.replaceWith(input, actions);
	input.focus();
}

export const popoverField = StateField.define<string | null>({
	create: () => null,
	update(id, tr) {
		for (const e of tr.effects) if (e.is(openPopover)) id = e.value;
		if (id && !reviewItems(tr.state).marks.some((m) => m.id === id)) id = null; // answered, or typed over
		return id;
	},
	provide: (f) =>
		showTooltip.compute([f, reviewField], (state): Tooltip | null => {
			const id = state.field(f);
			const m = id ? reviewItems(state).marks.find((x) => x.id === id) : null;
			if (!m) return null;
			return {
				pos: m.from,
				end: m.to,
				above: false,
				create: (view) => ({ dom: popoverDom(view, m) })
			};
		})
});

const popoverHandlers = EditorView.domEventHandlers({
	click(event, view) {
		const target = (event.target as HTMLElement | null)?.closest?.('[data-rv-id]');
		const id = target?.getAttribute('data-rv-id') ?? null;
		const current = view.state.field(popoverField, false) ?? null;
		if (id !== current) view.dispatch({ effects: openPopover.of(id) });
		return false;
	}
});

const popoverKeys = keymap.of([
	{
		key: 'Escape',
		run: (view) => {
			if (!view.state.field(popoverField, false)) return false;
			view.dispatch({ effects: openPopover.of(null) });
			return true;
		}
	}
]);

// ---- gutter ----

const RANK: Record<Exclude<Cls, 'suppress'>, number> = { info: 1, minor: 2, action: 3 };
const GUTTER_LABEL: Record<Exclude<Cls, 'suppress'>, string> = {
	action: LABELS.action,
	minor: LABELS.minor,
	info: LABELS.info
};

class ClsMarker extends GutterMarker {
	constructor(
		readonly cls: Exclude<Cls, 'suppress'>,
		readonly count: number,
		readonly firstId: string
	) {
		super();
	}
	eq(other: ClsMarker): boolean {
		return this.cls === other.cls && this.count === other.count && this.firstId === other.firstId;
	}
	toDOM(): HTMLElement {
		const e = el('span', `rv-gutter-marker rv-gutter-${this.cls}`, ICONS[this.cls]);
		e.setAttribute('role', 'img');
		const n = this.count === 1 ? '1 review item' : `${this.count} review items`;
		e.setAttribute('aria-label', `${GUTTER_LABEL[this.cls]}: ${n} on this line`);
		e.title = e.getAttribute('aria-label')!;
		e.setAttribute('data-rv-gutter', this.firstId);
		return e;
	}
}

const gutterCache = new WeakMap<ReviewFieldState, RangeSet<GutterMarker>>();

function gutterMarkers(view: EditorView): RangeSet<GutterMarker> {
	const items = reviewItems(view.state);
	const cached = gutterCache.get(items);
	if (cached) return cached;
	const doc = view.state.doc;
	const lines = new Map<
		number,
		{ cls: Exclude<Cls, 'suppress'>; count: number; firstId: string; firstAt: number }
	>();
	const add = (pos: number, cls: Cls, id: string, at: number) => {
		if (cls === 'suppress') return;
		const start = doc.lineAt(Math.min(pos, doc.length)).from;
		const cur = lines.get(start);
		if (!cur) lines.set(start, { cls, count: 1, firstId: id, firstAt: at });
		else {
			cur.count++;
			if (RANK[cls] > RANK[cur.cls]) cur.cls = cls;
			if (at < cur.firstAt) Object.assign(cur, { firstId: id, firstAt: at });
		}
	};
	for (const m of items.marks) add(m.from, m.cls, m.id, m.from);
	for (const w of items.widgets) {
		if (w.kind === 'removed') add(w.pos, 'action', w.id, w.pos);
		else if (w.kind === 'option') add(w.pos, 'minor', w.id, w.pos);
	}
	const set = RangeSet.of(
		[...lines.entries()]
			.sort((a, b) => a[0] - b[0])
			.map(([pos, v]) => new ClsMarker(v.cls, v.count, v.firstId).range(pos))
	);
	gutterCache.set(items, set);
	return set;
}

const reviewGutter = gutter({
	class: 'rv-gutter',
	markers: gutterMarkers,
	domEventHandlers: {
		click(view, line) {
			const m = reviewItems(view.state).marks.find((x) => x.from >= line.from && x.from <= line.to);
			if (m) view.dispatch({ effects: openPopover.of(m.id) });
			return !!m;
		}
	}
});

/** The drawing layer: marks, widgets, popover, gutter. The field itself comes from field.reviewFieldExtension. */
export function reviewDisplay(): Extension[] {
	return [reviewDecorations, popoverField, popoverHandlers, popoverKeys, reviewGutter];
}
