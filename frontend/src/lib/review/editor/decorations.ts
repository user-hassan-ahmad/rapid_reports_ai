/**
 * How the review field is drawn (plan Task C2), generalised from the negatives prototype
 * (`lib/review/negatives-proto/decorations.ts`, which stays for /dev/negatives-proto).
 *
 * - Marks: their class plus `data-rv-id` and an accessible name; hovering (or the keyboard caret, or a tap) opens
 *   the item's hover chip.
 * - Widgets (removed / option / excluded): display only at their anchor, never document text (the copy invariant);
 *   their actions are on the chip too.
 * - The hover chip (`showTooltip`, closed with Escape or on leave): one line, icon + a rationale built by code
 *   (editor/chip.ts) + icon buttons; ⏎ previews its fix inline. The old click popover is gone; Edit and Ask in chat
 *   live on the rail card.
 * - Gutter markers: one per line with items, keyed by the highest cls on the line.
 *
 * Every chip button goes through review commands: it calls the `onReviewCommand` callbacks with
 * (command name, item id, args) and nothing else. The host runs the command (lib/review/commands.ts), dispatches
 * `commandTransaction` and posts the event. The prototype's local toggles are never used here.
 */
import {
	EditorSelection,
	Facet,
	RangeSet,
	StateEffect,
	StateField,
	type EditorState,
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
import { CHIP_ICONS, chipActions, chipRationale, chipType, type ChipAction, type ChipTarget } from './chip';
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

/** The legend's compact labels (one row under the editor title); the full meaning is the entry's `title`. */
const LEGEND_SHORT = {
	dictated: 'Dictated',
	normal: 'Assumed normal',
	check: 'Check',
	removed: 'Removed',
	excluded: 'Removed by you',
	option: 'Suggested'
} as const;

/** The legend, in order: "E · meaning". */
export const LEGEND: { key: Meaning; icon: string; label: string; title: string }[] = (
	['dictated', 'normal', 'check', 'removed', 'excluded', 'option'] as const
).map((key) => ({ key, icon: ICONS[key], label: LEGEND_SHORT[key], title: LABELS[key] }));

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
	toDOM(): HTMLElement {
		const it = this.item;
		const wrap = el('span', `rv-widget rv-${it.kind}`);
		wrap.setAttribute('data-rv-widget', it.id);
		wrap.setAttribute('role', 'group');
		const label = widgetLabel(it);
		wrap.setAttribute('aria-label', `${label}: ${it.text}`);
		const icon = el(
			'span',
			'rv-icon',
			it.kind === 'removed' ? ICONS.removed : it.kind === 'excluded' ? ICONS.excluded : ICONS.option
		);
		icon.setAttribute('aria-hidden', 'true');
		wrap.append(' ', icon, el('span', 'rv-wtext', it.text));
		return wrap;
	}
	ignoreEvent(e: Event): boolean {
		// let hover / click reach the editor's handlers (the chip), but keep the widget out of selection
		return !(e.type === 'mouseover' || e.type === 'mouseout' || e.type === 'click');
	}
}

// ---- marks + widgets ----

function markLabel(m: LiveMark): string {
	const meaning = MARK_MEANING[m.mark];
	let t: string = LABELS[meaning];
	if (m.mark === 'rv-check') t += ` · ${checkReason({ check_reason: m.reason }).line}`;
	return `${t} · hover for actions`;
}

const reviewDecorations = EditorView.decorations.compute([reviewField], (state): DecorationSet => {
	const items = reviewItems(state);
	const ranges: Range<Decoration>[] = [];
	for (const m of items.marks) {
		const label = markLabel(m);
		ranges.push(
			Decoration.mark({
				class: `rv-mark ${m.mark}`,
				attributes: { 'data-rv-id': m.id, 'aria-label': label }
			}).range(m.from, m.to)
		);
	}
	for (const w of items.widgets)
		ranges.push(Decoration.widget({ widget: new ItemWidget(w), side: 1 }).range(w.pos));
	return Decoration.set(ranges, true);
});

// ---- hover chip (replaces the click popover) ----
//
// Trigger: hovering a mark or widget (~200 ms), the caret moving into a mark by keyboard, or a click / tap. The chip
// is a one-line tooltip anchored at the end of the mark, above the line (never over the next one), with a fade and
// slight rise. It stays open while the pointer is on it and closes on leave or Escape. Tab from the editor while a
// chip is open moves focus onto its buttons. Hovering ⏎ previews the fix inline (old struck, new as ghost text);
// after an action the mark's range flashes once (a tick and fade), no toast.

/** The chip's anchor, wherever it is: a mark (report text) or a widget (removed / option). */
type ChipAnchor = { id: string; pos: number; target: ChipTarget; from: number; to: number };

function anchorOf(state: EditorState, id: string): ChipAnchor | null {
	const items = reviewItems(state);
	const m = items.marks.find((x) => x.id === id);
	if (m)
		return {
			id,
			pos: m.to,
			from: m.from,
			to: m.to,
			target: { on: 'mark', mark: m.mark, kind: m.kind, pointer: m.pointer, reason: m.reason }
		};
	const w = items.widgets.find((x) => x.id === id);
	if (w && w.kind !== 'excluded')
		return {
			id,
			pos: w.pos,
			from: w.pos,
			to: w.pos,
			target: {
				on: 'widget',
				kind: w.kind,
				pointer: w.kind === 'removed' ? w.pointer : undefined,
				reason: w.reason
			}
		};
	return null;
}

/** The host's "show this item in the rail" (the chip's ›). */
export const onRevealItem = Facet.define<(id: string) => void>();

/** Inline apply preview: the item whose fix is drawn into the text (old struck, new as ghost), or null. */
export const setPreview = StateEffect.define<string | null>();
const previewField = StateField.define<string | null>({
	create: () => null,
	update(id, tr) {
		for (const e of tr.effects) if (e.is(setPreview)) id = e.value;
		if (tr.docChanged) id = null;
		return id;
	}
});

class GhostWidget extends WidgetType {
	constructor(readonly text: string) {
		super();
	}
	eq(o: GhostWidget): boolean {
		return o.text === this.text;
	}
	toDOM(): HTMLElement {
		const e = el('span', 'rv-preview-ins', this.text);
		e.setAttribute('aria-label', `Will read: ${this.text}`);
		return e;
	}
}

/** Where the fix of `it` lands: the edit's `find` near the mark, else the mark itself. */
function previewDecorations(state: EditorState, id: string, it: ReviewItem): Range<Decoration>[] {
	const a = anchorOf(state, id);
	const e = it.edit;
	if (!a || !e) return [];
	const out: Range<Decoration>[] = [];
	const strike = Decoration.mark({ class: 'rv-preview-del' });
	if (e.mode === 'insert') {
		if (e.replace) out.push(Decoration.widget({ widget: new GhostWidget(` ${e.replace}`), side: 1 }).range(a.to));
		return out;
	}
	let from = a.from;
	let to = a.to;
	if (e.find) {
		const lo = Math.max(0, a.from - 200);
		const hay = state.doc.sliceString(lo, Math.min(state.doc.length, a.to + 200));
		let best = -1;
		for (let at = hay.indexOf(e.find); at >= 0; at = hay.indexOf(e.find, at + 1))
			if (best < 0 || Math.abs(lo + at - a.from) < Math.abs(lo + best - a.from)) best = at;
		if (best >= 0) {
			from = lo + best;
			to = from + e.find.length;
		}
	}
	if (to > from) out.push(strike.range(from, to));
	if (e.mode !== 'remove' && e.replace)
		out.push(Decoration.widget({ widget: new GhostWidget(e.replace), side: 1 }).range(to));
	return out;
}

const previewDecos = EditorView.decorations.compute([previewField, reviewField], (state) => {
	const id = state.field(previewField);
	const it = id ? state.facet(reviewItemLookup)(id) : undefined;
	return id && it ? Decoration.set(previewDecorations(state, id, it), true) : Decoration.none;
});

/** After an action: the range flashes once (tick + fade), mapped through the action's own change. */
const flash = StateEffect.define<{ from: number; to: number } | null>();
const flashMark = Decoration.mark({ class: 'rv-flash' });
const flashWidget = Decoration.widget({
	widget: new (class extends WidgetType {
		toDOM() {
			const e = el('span', 'rv-flash-tick', '✓');
			e.setAttribute('aria-hidden', 'true');
			return e;
		}
	})(),
	side: 1
});
const flashField = StateField.define<DecorationSet>({
	create: () => Decoration.none,
	update(set, tr) {
		set = set.map(tr.changes);
		for (const e of tr.effects)
			if (e.is(flash)) {
				if (!e.value) set = Decoration.none;
				else {
					const { from, to } = e.value;
					const r: Range<Decoration>[] = [];
					if (to > from) r.push(flashMark.range(from, to));
					r.push(flashWidget.range(to));
					set = Decoration.set(r, true);
				}
			}
		return set;
	},
	provide: (f) => EditorView.decorations.from(f)
});

function act(view: EditorView, a: ChipAnchor, action: ChipAction): void {
	if (action.command === 'reveal') {
		for (const cb of view.state.facet(onRevealItem)) cb(a.id);
		return;
	}
	view.dispatch({ effects: [flash.of({ from: a.from, to: a.to }), setPreview.of(null)] });
	send(view, action.command, a.id);
	setTimeout(() => {
		if (!view.dom.isConnected) return;
		view.dispatch({ effects: flash.of(null) });
	}, 700);
}

// hover timing, per view
interface HoverState {
	openTimer: ReturnType<typeof setTimeout> | null;
	closeTimer: ReturnType<typeof setTimeout> | null;
	overChip: boolean;
}
const hover = new WeakMap<EditorView, HoverState>();
const hoverOf = (view: EditorView): HoverState => {
	let h = hover.get(view);
	if (!h) hover.set(view, (h = { openTimer: null, closeTimer: null, overChip: false }));
	return h;
};
export const CHIP_OPEN_DELAY = 200;
const CHIP_CLOSE_DELAY = 220;

function clearTimers(h: HoverState): void {
	if (h.openTimer) clearTimeout(h.openTimer);
	if (h.closeTimer) clearTimeout(h.closeTimer);
	h.openTimer = h.closeTimer = null;
}

function scheduleClose(view: EditorView): void {
	const h = hoverOf(view);
	if (h.openTimer) clearTimeout(h.openTimer);
	h.openTimer = null;
	if (h.closeTimer) clearTimeout(h.closeTimer);
	h.closeTimer = setTimeout(() => {
		h.closeTimer = null;
		if (h.overChip || !view.dom.isConnected) return;
		if (view.state.field(popoverField, false) || view.state.field(previewField, false))
			view.dispatch({ effects: [openPopover.of(null), setPreview.of(null)] });
	}, CHIP_CLOSE_DELAY);
}

function chipDom(view: EditorView, a: ChipAnchor): HTMLElement {
	const it = view.state.facet(reviewItemLookup)(a.id);
	const type = chipType(a.target, it) ?? 'info';
	const dom = el('div', `rv-chip rv-chip-${type}`);
	dom.setAttribute('role', 'toolbar');
	dom.setAttribute('data-rv-chip', a.id);
	const rationale = chipRationale(a.target, it);
	dom.setAttribute('aria-label', `${it?.label || LABELS[type]}: ${rationale}`);
	const icon = el('span', 'rv-chip-icon', CHIP_ICONS[type]);
	icon.setAttribute('aria-hidden', 'true');
	dom.append(icon, el('span', 'rv-chip-text', rationale));
	const actions = el('span', 'rv-chip-actions');
	for (const action of chipActions(a.target, it)) {
		const b = button(action.icon, action.label, () => act(view, a, action));
		b.className = `rv-chip-btn${action.command === 'reveal' ? ' rv-chip-reveal' : ''}`;
		b.setAttribute('data-rv-chip-action', action.command);
		if (action.preview) {
			const on = () => view.dispatch({ effects: setPreview.of(a.id) });
			const off = () => {
				if (view.state.field(previewField, false)) view.dispatch({ effects: setPreview.of(null) });
			};
			b.addEventListener('mouseenter', on);
			b.addEventListener('focus', on);
			b.addEventListener('mouseleave', off);
			b.addEventListener('blur', off);
		}
		actions.append(b);
	}
	dom.append(actions);
	const h = hoverOf(view);
	dom.addEventListener('mouseenter', () => {
		h.overChip = true;
		clearTimers(h);
	});
	dom.addEventListener('mouseleave', () => {
		h.overChip = false;
		scheduleClose(view);
	});
	dom.addEventListener('keydown', (e) => {
		if (e.key === 'Escape') {
			e.preventDefault();
			view.dispatch({ effects: [openPopover.of(null), setPreview.of(null)] });
			view.focus();
		} else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
			const bs = [...dom.querySelectorAll<HTMLButtonElement>('button')];
			const at = bs.indexOf(document.activeElement as HTMLButtonElement);
			if (at < 0) return;
			e.preventDefault();
			bs[(at + (e.key === 'ArrowRight' ? 1 : bs.length - 1)) % bs.length].focus();
		}
	});
	return dom;
}

const CHIP_GAP = 4; // px between the chip and the mark's line

/** Does the viewport box [left, left+w] × [top, top+h] cover any rendered text? Samples the band every few px
 * and compares it with the text extent of the visual line under each sample. */
function coversText(view: EditorView, left: number, top: number, w: number, h: number): boolean {
	const content = view.contentDOM.getBoundingClientRect();
	for (let y = top + 1; y < top + h; y += 5) {
		if (y < content.top || y > content.bottom) continue;
		const pos = view.posAtCoords({ x: Math.max(content.left + 1, Math.min(left + w / 2, content.right - 1)), y }, false);
		const cur = EditorSelection.cursor(pos);
		const s = view.moveToLineBoundary(cur, false, true).head;
		const e = view.moveToLineBoundary(cur, true, true).head;
		if (e <= s) continue; // an empty (blank) line
		const cs = view.coordsAtPos(s, 1);
		const ce = view.coordsAtPos(e, -1);
		if (!cs || !ce) continue;
		const lineTop = Math.min(cs.top, ce.top);
		const lineBottom = Math.max(cs.bottom, ce.bottom);
		if (y < lineTop || y > lineBottom) continue; // between lines
		if (left < ce.right && cs.left < left + w) return true;
	}
	return false;
}

/** Where the open chip goes (viewport coords of its top-left): clear above the mark's FIRST line (a small gap, at
 * the mark's end horizontally), else clear below its LAST line, whichever has room and covers no text; with no
 * text-free spot, the first side with room (above first). Never over the mark's own lines. */
export function chipPlacement(
	view: EditorView,
	a: Pick<ChipAnchor, 'from' | 'to' | 'pos'>,
	width: number,
	height: number
): { left: number; top: number; height: number } | null {
	const end = view.coordsAtPos(a.to, -1) ?? view.coordsAtPos(a.pos, 1);
	const start = view.coordsAtPos(a.from, 1) ?? end;
	if (!end || !start) return null;
	const w = width || 240;
	const h = height || 28;
	const x = start.top < end.top - 2 ? Math.max(start.left, end.left) : end.left;
	const vw = window.innerWidth || document.documentElement.clientWidth;
	const left = Math.max(4, Math.min(x, vw - w - 4));
	const sc = view.scrollDOM.getBoundingClientRect();
	const minTop = Math.max(0, sc.top);
	const maxBottom = Math.min(window.innerHeight || document.documentElement.clientHeight, sc.bottom);
	const sides = [
		Math.min(start.top, end.top) - CHIP_GAP - h, // above the first line
		Math.max(start.bottom, end.bottom) + CHIP_GAP // below the last line
	];
	const room = sides.filter((t) => t >= minTop && t + h <= maxBottom);
	const top = room.find((t) => !coversText(view, left, t, w, h)) ?? room[0] ?? sides[0];
	return { left, top, height: h };
}

/** The open chip's item id (null: closed). `openPopover` keeps its name for the host (focus after a command). */
export const popoverField = StateField.define<string | null>({
	create: () => null,
	update(id, tr) {
		for (const e of tr.effects) if (e.is(openPopover)) id = e.value;
		// keyboard caret into a mark opens its chip; out of every mark closes it
		if (tr.selection && tr.isUserEvent('select') && !tr.isUserEvent('select.pointer')) {
			const head = tr.state.selection.main.head;
			const m = reviewItems(tr.state).marks.find((x) => head >= x.from && head <= x.to);
			id = m ? m.id : null;
		}
		if (id && !anchorOf(tr.state, id)) id = null; // answered, or typed over
		return id;
	},
	provide: (f) =>
		showTooltip.compute([f, reviewField], (state): Tooltip | null => {
			const id = state.field(f);
			const a = id ? anchorOf(state, id) : null;
			if (!a) return null;
			return {
				pos: a.pos,
				// `getCoords` returns the point the chip's bottom-left sits on (chipPlacement decides above or
				// below); strictSide keeps CodeMirror from flipping it again
				above: true,
				strictSide: true,
				arrow: false,
				create: (view) => {
					const dom = chipDom(view, a);
					return {
						dom,
						getCoords: () => {
							const p = chipPlacement(view, a, dom.offsetWidth, dom.offsetHeight);
							return p ? { left: p.left, right: p.left, top: p.top + p.height, bottom: p.top + p.height }
								: { left: 0, right: 0, top: 0, bottom: 0 };
						}
					};
				}
			};
		})
});

/** The mark whose chip is open stays lit (full colour + tint) while the pointer is on the chip. */
const activeDecos = EditorView.decorations.compute([popoverField, reviewField], (state) => {
	const id = state.field(popoverField);
	const a = id ? anchorOf(state, id) : null;
	if (!a || a.to <= a.from) return Decoration.none;
	return Decoration.set([Decoration.mark({ class: 'rv-active' }).range(a.from, a.to)]);
});

const targetId = (t: EventTarget | null): string | null => {
	const e = (t as HTMLElement | null)?.closest?.('[data-rv-id], [data-rv-widget]');
	return e?.getAttribute('data-rv-id') ?? e?.getAttribute('data-rv-widget') ?? null;
};

const popoverHandlers = EditorView.domEventHandlers({
	mouseover(event, view) {
		const id = targetId(event.target);
		if (!id) return false;
		const h = hoverOf(view);
		if (h.closeTimer) clearTimeout(h.closeTimer);
		h.closeTimer = null;
		if (view.state.field(popoverField, false) === id) return false;
		if (h.openTimer) clearTimeout(h.openTimer);
		h.openTimer = setTimeout(() => {
			h.openTimer = null;
			if (view.dom.isConnected) view.dispatch({ effects: openPopover.of(id) });
		}, CHIP_OPEN_DELAY);
		return false;
	},
	mouseout(event, view) {
		const from = targetId(event.target);
		if (!from) return false;
		const to = event.relatedTarget as HTMLElement | null;
		if (to && (targetId(to) === from || to.closest?.('.rv-chip'))) return false;
		scheduleClose(view);
		return false;
	},
	click(event, view) {
		// touch (tap) and click open at once
		const id = targetId(event.target);
		if (!id) return false;
		const h = hoverOf(view);
		clearTimers(h);
		if (view.state.field(popoverField, false) !== id) view.dispatch({ effects: openPopover.of(id) });
		return false;
	}
});

const popoverKeys = keymap.of([
	{
		key: 'Escape',
		run: (view) => {
			if (!view.state.field(popoverField, false)) return false;
			view.dispatch({ effects: [openPopover.of(null), setPreview.of(null)] });
			return true;
		}
	},
	{
		key: 'Tab',
		run: (view) => {
			if (!view.state.field(popoverField, false)) return false;
			const b = view.dom.querySelector<HTMLButtonElement>('.rv-chip button');
			if (!b) return false;
			b.focus();
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

/** The drawing layer: marks, widgets, hover chip (+ apply preview, action flash), gutter. The field itself comes from
 * field.reviewFieldExtension. */
export function reviewDisplay(): Extension[] {
	return [
		reviewDecorations,
		previewField,
		previewDecos,
		flashField,
		popoverField,
		activeDecos,
		popoverHandlers,
		popoverKeys,
		reviewGutter
	];
}
