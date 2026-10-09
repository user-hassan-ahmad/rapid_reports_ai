/**
 * How the review field is drawn (plan Task C2), generalised from the negatives prototype
 * (`lib/review/negatives-proto/decorations.ts`, which stays for /dev/negatives-proto).
 *
 * - Marks: their class plus `data-rv-id` and an accessible name; hovering (or the keyboard caret, or a tap) expands
 *   the item's inline control.
 * - Widgets (removed / option / excluded): display only at their anchor, never document text (the copy invariant);
 *   their actions are on the inline control too.
 * - The inline control (a widget decoration at the END of the highlight, inside the text flow; collapsed with Escape
 *   or on leave): simple icon buttons (editor/chip.ts), no rationale; hovering an apply ✓ previews its fix inline. Edit
 *   and Ask in chat live on the rail card.
 * - Gutter markers: one per line with items, keyed by the highest cls on the line.
 *
 * Every control button goes through review commands: it calls the `onReviewCommand` callbacks with
 * (command name, item id, args) and nothing else. The host runs the command (lib/review/commands.ts), dispatches
 * `commandTransaction` and posts the event. The prototype's local toggles are never used here.
 */
import {
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
	type DecorationSet
} from '@codemirror/view';
import type { CommandName } from '../commands';
import type { Cls, ReviewItem } from '../types';
import { chipActions, chipType, type ChipAction, type ChipTarget } from './chip';
import {
	AI_LAYER_MARKS,
	checkReason,
	type AiForm,
	reviewField,
	reviewItems,
	type LiveMark,
	type MarkClass,
	type ReviewFieldState,
	type SuggestionEntry,
	type WidgetItem
} from './field';

// ---- labels and icons (label set "E · meaning"; shared with the rail legend) ----

export const LABELS = {
	dictated: 'Your dictation',
	normal: 'Assumed normal',
	check: 'Check',
	synth: 'AI synthesis',
	ai: 'AI-generated',
	rec: 'Recommendation',
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
	synth: '◆',
	ai: '✦',
	rec: '→',
	removed: '✕',
	excluded: '⊘',
	option: '◌',
	preapplied: '↺',
	action: '!',
	minor: '•',
	info: 'i'
} as const;

export type Meaning = keyof typeof ICONS;

/** The legend (under the editor title): the radiologist's own first, then the AI's. Only "AI-generated" is a toggle
 * (editor/theme.ts `setEmphasis`: the AI-generated layer's tints, on by default; off = plain text), with its breakdown
 * (AI_BREAKDOWN); the other entries are static labels for what the editor draws. The full meaning is the entry's
 * `title`. */
const LEGEND_SHORT = {
	dictated: 'Dictated',
	excluded: 'Removed by you',
	ai: 'AI-generated',
	removed: 'Removed (contradicts dictation)'
} as const;

export type LegendKey = keyof typeof LEGEND_SHORT;

const LEGEND_TITLE: Record<LegendKey, string> = {
	dictated: 'Plain text is your dictation',
	excluded: 'Struck through in grey: text you removed',
	ai: 'Text not from your dictation, tinted by kind: normals (green), pertinent negatives (amber), synthesis (violet). Show or hide',
	removed: 'Struck through in red: removed by AI because it contradicts your dictation'
};

/** The legend filters on by default: the AI-generated layer. */
export const DEFAULT_LEGEND: readonly LegendKey[] = ['ai'];

/** The legend, in order: the radiologist's own, then the AI's. `toggle`: a filter button (else a static label). */
export const LEGEND: { key: LegendKey; icon: string; label: string; title: string; ai: boolean; toggle: boolean }[] = (
	['dictated', 'excluded', 'ai', 'removed'] as const
).map((key) => ({
	key,
	icon: ICONS[key],
	label: LEGEND_SHORT[key],
	title: LEGEND_TITLE[key],
	ai: key !== 'dictated' && key !== 'excluded',
	toggle: key === 'ai'
}));

/** The AI-generated layer's categories, as the legend's breakdown shows them (swatch = the tint in the editor). */
export const AI_BREAKDOWN: { form: AiForm; label: string; title: string }[] = [
	{ form: 'normal', label: 'Normals', title: 'Normal findings you did not dictate, stated by the AI' },
	{ form: 'negative', label: 'Bears on your finding', title: 'Negatives the AI added that bear on a dictated finding: in the report, worth a glance (always shown)' },
	{ form: 'synthesis', label: 'Synthesis', title: 'Conclusions the AI drew from your findings' }
];

const MARK_MEANING: Record<MarkClass, Meaning> = {
	'rv-normal': 'normal',
	'rv-check': 'check',
	'rv-synth': 'synth',
	'rv-rec': 'rec',
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

export function markLabel(m: LiveMark): string {
	const meaning = MARK_MEANING[m.mark];
	let t: string = m.form ? AI_BREAKDOWN.find((b) => b.form === m.form)!.label : LABELS[meaning];
	if (m.mark === 'rv-check') t += ` · ${checkReason({ check_reason: m.reason }).line}`;
	if (m.form === 'negative' && m.pointer) t += ` · “${m.pointer}”`;
	return AI_LAYER_MARKS.has(m.mark) ? `${t} (AI-generated)` : `${t} · hover for actions`;
}

const reviewDecorations = EditorView.decorations.compute([reviewField], (state): DecorationSet => {
	const items = reviewItems(state);
	const ranges: Range<Decoration>[] = [];
	for (const m of items.marks) {
		const label = markLabel(m);
		ranges.push(
			Decoration.mark({
				class: `rv-mark ${m.mark}${m.form ? ` rv-form-${m.form}` : ''}`,
				attributes: { 'data-rv-id': m.id, 'aria-label': label }
			}).range(m.from, m.to)
		);
	}
	for (const w of items.widgets)
		if (w.kind !== 'option') ranges.push(Decoration.widget({ widget: new ItemWidget(w), side: 1 }).range(w.pos));
	return Decoration.set(ranges, true);
});

// ---- suggestions: a checkbox subsection under each section's body (never ghost text in the report) ----

const HEADING = /^\s*([A-Z][A-Z0-9 /&()-]{2,}):\s*$/;
const normName = (s: string) => s.trim().replace(/:$/, '').trim().toLowerCase();

/** A sign-off line (signature, name, registration, qualifications): the report's tail, never section body. */
const SIGN_OFF =
	/^\s*(?:dr\.?\s|prof\.?\s|professor\s|reported by|verified by|signed|electronically signed|gmc\b|frcr\b|mb\s?bs\b|mbchb\b)|\b(?:gmc(?:\s*(?:no\.?|number))?\s*:?\s*\d{5,}|frcr)\b/i;
/** Job titles open a sign-off only as their own paragraph ("Consultant review advised." is body text). */
const SIGN_OFF_TITLE = /^\s*(?:consultant|specialty|registrar|radiologist)\b/i;

/** Where a section's checklist goes and the section it belongs to: the end of the last non-blank line of the
 * section body holding `pos` (or the section named `section`), stopping before a trailing paragraph of sign-off
 * lines (signature, name, GMC, FRCR), which stay below the checklist; the end of the document when the report has no
 * headings. */
function sectionBodyEnd(
	state: EditorState,
	pos: number | null,
	section: string | null
): { at: number; section: string | null } {
	const doc = state.doc;
	let lineNo: number | null = null;
	if (pos != null) lineNo = doc.lineAt(Math.min(pos, doc.length)).number;
	else if (section)
		for (let n = 1; n <= doc.lines; n++) {
			const m = HEADING.exec(doc.line(n).text);
			if (m && normName(m[1]) === normName(section)) {
				lineNo = n;
				break;
			}
		}
	if (lineNo == null) return { at: doc.length, section };
	// the heading this body belongs to
	let name = section;
	for (let n = lineNo; n >= 1; n--) {
		const m = HEADING.exec(doc.line(n).text);
		if (m) {
			name = m[1];
			break;
		}
	}
	let last = lineNo;
	let blank = false;
	for (let n = lineNo + 1; n <= doc.lines; n++) {
		const text = doc.line(n).text;
		if (HEADING.test(text)) break;
		if (!text.trim()) {
			blank = true;
			continue;
		}
		if (SIGN_OFF.test(text) || (blank && SIGN_OFF_TITLE.test(text))) break; // the sign-off after the body
		blank = false;
		last = n;
	}
	return { at: doc.line(last).to, section: name };
}

const isImpression = (section: string | null) => !!section && /impression|conclusion|summary|opinion/i.test(section);

class SuggestionsWidget extends WidgetType {
	constructor(
		readonly entries: readonly SuggestionEntry[],
		readonly impression = false
	) {
		super();
	}
	eq(o: SuggestionsWidget): boolean {
		return (
			o.impression === this.impression &&
			o.entries.length === this.entries.length &&
			o.entries.every(
				(e, i) =>
					e.id === this.entries[i].id &&
					e.checked === this.entries[i].checked &&
					e.disabled === this.entries[i].disabled &&
					e.text === this.entries[i].text
			)
		);
	}
	toDOM(view: EditorView): HTMLElement {
		const box = el('div', 'rv-suggestions');
		box.contentEditable = 'false';
		box.setAttribute('role', 'group');
		box.setAttribute('data-rv-suggestions', '');
		// the impression's block is its recommendations; every other section's block is its suggestions
		const title = this.impression ? 'Recommendations' : 'Suggestions';
		if (this.impression) box.setAttribute('data-rv-impression', '');
		box.setAttribute('aria-label', title);
		box.append(el('div', 'rv-suggestions-title', title));
		// a blank line's gap above the block (padding on a wrapper: CM measures block widgets by their box)
		const block = el('div', 'rv-suggestions-block');
		block.contentEditable = 'false';
		block.append(box);
		for (const e of this.entries) {
			const row = el('label', 'rv-suggestion');
			row.setAttribute('data-rv-suggestion', e.id);
			const cb = document.createElement('input');
			cb.type = 'checkbox';
			cb.className = 'rv-check-box';
			cb.checked = e.checked;
			cb.disabled = !!e.disabled;
			row.setAttribute('data-rv-kind', e.kind);
			if (e.disabled) row.title = 'Edit in text';
			cb.setAttribute(
				'aria-label',
				e.kind === 'recommendation'
					? `${e.checked ? 'Keep' : 'Restore'} recommendation: ${e.text}`
					: `${e.checked ? 'Included' : 'Include'}: ${e.text}`
			);
			cb.addEventListener('mousedown', (ev) => ev.stopPropagation());
			cb.addEventListener('change', () => {
				// ticked: insert it at its place (apply); unticked: take it out again (undo)
				// a recommendation: unticked → remove it (its remove edit), re-ticked → undo (restores it)
				const name =
					e.kind === 'recommendation' ? (cb.checked ? 'undo' : 'remove') : cb.checked ? 'apply' : 'undo';
				for (const fn of view.state.facet(onReviewCommand)) fn(name, e.id);
				// the box shows the field, never its own click: a command that could not run (or has not run yet)
				// leaves it as it was, so the next click sends the right command again
				const now = reviewItems(view.state).suggestions?.find((x) => x.id === e.id);
				cb.checked = now ? now.checked : e.checked;
			});
			row.append(cb, el('span', 'rv-suggestion-text', e.text));
			box.append(row);
		}
		return block;
	}
	ignoreEvent(): boolean {
		return true;
	}
}

const suggestionDecos = EditorView.decorations.compute([reviewField], (state): DecorationSet => {
	const list = reviewItems(state).suggestions ?? [];
	if (!list.length) return Decoration.none;
	const groups = new Map<number, { entries: SuggestionEntry[]; section: string | null }>();
	for (const g of list) {
		const { at, section } = sectionBodyEnd(state, g.pos, g.section);
		const cur = groups.get(at) ?? { entries: [], section };
		cur.entries.push(g);
		groups.set(at, cur);
	}
	return Decoration.set(
		[...groups.entries()].map(([at, { entries, section }]) =>
			Decoration.widget({
				widget: new SuggestionsWidget(entries, isImpression(section)),
				block: true,
				side: 1
			}).range(at)
		),
		true
	);
});

// ---- inline control (replaces the floating hover chip) ----
//
// Trigger: hovering a mark or widget (~180 ms), the caret moving into a mark by keyboard, or a click / tap. A small
// control expands right at the END of that highlight, inside the text flow (a widget decoration, never a floating
// tooltip): simple icon buttons (editor/chip.ts), width and opacity animating in over ~120 ms. It stays open while the
// pointer is on the highlight or the control and collapses when it leaves both, or on Escape. Tab from the editor
// while it is open moves focus onto its buttons. Hovering an apply ✓ previews the fix inline (old struck, new as ghost
// text); after an action the highlight's range flashes once (a tick and fade), no toast.

/** The control's anchor, wherever it is: a mark (report text) or a widget (removed / option / excluded). */
type ChipAnchor = { id: string; pos: number; target: ChipTarget; from: number; to: number };

/** The item's control anchor, or null when it has no control (the AI-generated layer, info items). */
function anchorOf(state: EditorState, id: string): ChipAnchor | null {
	const a = rawAnchor(state, id);
	return a && chipActions(a.target, state.facet(reviewItemLookup)(id)).length ? a : null;
}

function rawAnchor(state: EditorState, id: string): ChipAnchor | null {
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
	if (w)
		return {
			id,
			pos: w.pos,
			from: w.pos,
			to: w.pos,
			target: {
				on: 'widget',
				kind: w.kind,
				pointer: w.kind === 'removed' ? w.pointer : undefined,
				reason: w.kind === 'excluded' ? undefined : w.reason
			}
		};
	return null;
}

/** The host's "show this item in the rail" (the control's `›`, flagged issues only). */
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
	const a = rawAnchor(state, id);
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
export const CHIP_OPEN_DELAY = 180;
const CHIP_CLOSE_DELAY = 220;

function clearTimers(h: HoverState): void {
	if (h.openTimer) clearTimeout(h.openTimer);
	if (h.closeTimer) clearTimeout(h.closeTimer);
	h.openTimer = h.closeTimer = null;
}

function close(view: EditorView): void {
	if (view.state.field(popoverField, false) || view.state.field(previewField, false))
		view.dispatch({ effects: [openPopover.of(null), setPreview.of(null)] });
}

function scheduleClose(view: EditorView): void {
	const h = hoverOf(view);
	if (h.openTimer) clearTimeout(h.openTimer);
	h.openTimer = null;
	if (h.closeTimer) clearTimeout(h.closeTimer);
	h.closeTimer = setTimeout(() => {
		h.closeTimer = null;
		if (h.overChip || !view.dom.isConnected) return;
		// keyboard focus on one of the control's buttons keeps it open
		if (view.dom.querySelector('.rv-inline')?.contains(document.activeElement)) return;
		close(view);
	}, CHIP_CLOSE_DELAY);
}

const targetId = (t: EventTarget | null): string | null => {
	const e = (t as HTMLElement | null)?.closest?.('[data-rv-id], [data-rv-widget]');
	return e?.getAttribute('data-rv-id') ?? e?.getAttribute('data-rv-widget') ?? null;
};

function controlDom(view: EditorView, a: ChipAnchor): HTMLElement {
	const it = view.state.facet(reviewItemLookup)(a.id);
	const type = chipType(a.target, it);
	const dom = el('span', `rv-inline rv-inline-${type}`);
	dom.contentEditable = 'false';
	dom.setAttribute('role', 'toolbar');
	dom.setAttribute('data-rv-inline', a.id);
	dom.setAttribute('aria-label', `Actions: ${it?.label || LABELS[type]}`);
	for (const action of chipActions(a.target, it)) {
		const b = button(action.icon, action.label, () => act(view, a, action));
		b.className = `rv-inline-btn${action.command === 'reveal' ? ' rv-inline-reveal' : ''}`;
		b.setAttribute('data-rv-action', action.command);
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
		dom.append(b);
	}
	const h = hoverOf(view);
	dom.addEventListener('mouseenter', () => {
		h.overChip = true;
		clearTimers(h);
	});
	dom.addEventListener('mouseleave', (e) => {
		h.overChip = false;
		if (targetId(e.relatedTarget) === a.id) return; // back onto its own highlight
		scheduleClose(view);
	});
	dom.addEventListener('keydown', (e) => {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			close(view);
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

class InlineControl extends WidgetType {
	constructor(
		readonly a: ChipAnchor,
		readonly sig: string
	) {
		super();
	}
	eq(o: InlineControl): boolean {
		return o.a.id === this.a.id && o.sig === this.sig;
	}
	toDOM(view: EditorView): HTMLElement {
		return controlDom(view, this.a);
	}
	ignoreEvent(): boolean {
		return true; // its buttons handle their own events; the editor never selects into it
	}
}

/** The open control's item id (null: closed). `openPopover` keeps its name for the host (focus after a command). */
export const popoverField = StateField.define<string | null>({
	create: () => null,
	update(id, tr) {
		for (const e of tr.effects) if (e.is(openPopover)) id = e.value;
		// keyboard caret into a mark opens its control; out of every mark closes it
		if (tr.selection && tr.isUserEvent('select') && !tr.isUserEvent('select.pointer')) {
			const head = tr.state.selection.main.head;
			const m = reviewItems(tr.state).marks.find(
				(x) => head >= x.from && head <= x.to && !!anchorOf(tr.state, x.id)
			);
			id = m ? m.id : null;
		}
		if (id && !anchorOf(tr.state, id)) id = null; // answered, or typed over
		return id;
	}
});

/** The control itself (at the highlight's end, after any widget there) and the lit highlight. */
const controlDecos = EditorView.decorations.compute([popoverField, reviewField], (state) => {
	const id = state.field(popoverField);
	const a = id ? anchorOf(state, id) : null;
	if (!a) return Decoration.none;
	const it = state.facet(reviewItemLookup)(a.id);
	const sig = chipActions(a.target, it)
		.map((x) => x.command)
		.join(',');
	const r: Range<Decoration>[] = [];
	if (a.to > a.from) r.push(Decoration.mark({ class: 'rv-active' }).range(a.from, a.to));
	// a mark's control comes straight after its text (before any widget there); a widget's comes after the widget
	r.push(Decoration.widget({ widget: new InlineControl(a, sig), side: a.target.on === 'mark' ? 0 : 2 }).range(a.pos));
	return Decoration.set(r, true);
});

const popoverHandlers = EditorView.domEventHandlers({
	mouseover(event, view) {
		const id = targetId(event.target);
		if (!id || !anchorOf(view.state, id)) return false;
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
		if (to && (targetId(to) === from || to.closest?.('.rv-inline'))) return false;
		scheduleClose(view);
		return false;
	},
	click(event, view) {
		// touch (tap) and click open at once
		const id = targetId(event.target);
		if (!id || !anchorOf(view.state, id)) return false;
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
			close(view);
			return true;
		}
	},
	{
		key: 'Tab',
		run: (view) => {
			if (!view.state.field(popoverField, false)) return false;
			const b = view.dom.querySelector<HTMLButtonElement>('.rv-inline button');
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
	for (const m of items.marks) if (!AI_LAYER_MARKS.has(m.mark)) add(m.from, m.cls, m.id, m.from);
	for (const w of items.widgets) if (w.kind === 'removed') add(w.pos, 'action', w.id, w.pos);
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
			const m = reviewItems(view.state).marks.find(
				(x) => x.from >= line.from && x.from <= line.to && !!anchorOf(view.state, x.id)
			);
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
		suggestionDecos,
		previewField,
		previewDecos,
		flashField,
		popoverField,
		controlDecos,
		popoverHandlers,
		popoverKeys,
		reviewGutter
	];
}
