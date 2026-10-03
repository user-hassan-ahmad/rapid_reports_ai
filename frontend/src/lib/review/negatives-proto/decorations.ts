/**
 * Negatives prototype (dev only): how the items in `negField` are drawn.
 *
 * - default / implicated items: mark decorations (green / amber), clickable → inline popover
 *   with the label, the pointer and "exclude".
 * - removed / excluded / option items: widgets at their anchor. Widgets are display only, so
 *   copy and export never see them.
 *
 * Colours are CSS custom properties (--neg-*) defined by the page for light and dark themes.
 */
import { Decoration, EditorView, WidgetType, showTooltip, keymap, type DecorationSet, type Tooltip } from '@codemirror/view';
import { StateEffect, StateField, type Extension, type Range } from '@codemirror/state';
import type { NegClass } from './bundle';
import {
	excludeMark,
	includeOption,
	negField,
	negItems,
	restoreExcluded,
	restoreRemoved,
	type WidgetItem
} from './state';

export const LABELS = {
	dictated: 'Your dictation.',
	default: 'Assumed normal: not mentioned in your dictation, so stated as normal.',
	implicated: 'Assumed normal · confirm: not mentioned, but your findings make this uncertain. Confirm or remove.',
	removed: 'Removed: contradicts your dictation. Restore if needed.',
	removedNumber: 'Removed: carries a measurement you did not dictate. Restore if needed.',
	excluded: 'Removed by you. Restore if needed.',
	option: 'Suggested · not included. Add if relevant.'
} as const;

/** Small non-colour markers, shared by the legend and the editor. */
export const ICONS = {
	dictated: '✎',
	default: '+',
	implicated: '?',
	removed: '✕',
	excluded: '⊘',
	option: '◌'
} as const;

function clsLabel(cls: NegClass): string {
	return cls === 'default' ? LABELS.default : LABELS.implicated;
}

// ---- widgets ----

function button(label: string, title: string, onClick: () => void): HTMLButtonElement {
	const b = document.createElement('button');
	b.type = 'button';
	b.className = 'cm-neg-btn';
	b.textContent = label;
	b.title = title;
	b.addEventListener('mousedown', (e) => e.preventDefault()); // keep editor focus/selection
	b.addEventListener('click', (e) => {
		e.preventDefault();
		e.stopPropagation();
		onClick();
	});
	return b;
}

class ItemWidget extends WidgetType {
	constructor(readonly item: WidgetItem) {
		super();
	}
	eq(other: ItemWidget) {
		const a = this.item;
		const b = other.item;
		return a.id === b.id && a.kind === b.kind && a.text === b.text;
	}
	toDOM(view: EditorView) {
		const it = this.item;
		const wrap = document.createElement('span');
		wrap.className = `cm-neg-widget cm-neg-${it.kind}`;
		wrap.setAttribute('data-neg-widget', it.id);
		const icon = document.createElement('span');
		icon.className = 'cm-neg-icon';
		icon.setAttribute('aria-hidden', 'true');
		const text = document.createElement('span');
		text.className = 'cm-neg-wtext';
		text.textContent = it.text;
		let title: string;
		let btn: HTMLButtonElement;
		if (it.kind === 'removed') {
			icon.textContent = ICONS.removed;
			title = it.reason === 'number' ? LABELS.removedNumber : LABELS.removed;
			if (it.pointer) title += ` (dictated: “${it.pointer}”)`;
			btn = button('restore', 'Put this statement back into the report', () => {
				const spec = restoreRemoved(view.state, it.id);
				if (spec) view.dispatch(spec);
			});
		} else if (it.kind === 'excluded') {
			icon.textContent = ICONS.excluded;
			title = LABELS.excluded;
			btn = button('restore', 'Put this statement back into the report', () => {
				const spec = restoreExcluded(view.state, it.id);
				if (spec) view.dispatch(spec);
			});
		} else {
			icon.textContent = ICONS.option;
			title = LABELS.option + (it.reason ? ` (${it.reason})` : '');
			btn = button('include', 'Add this statement to the report', () => {
				const spec = includeOption(view.state, it.id);
				if (spec) view.dispatch(spec);
			});
		}
		wrap.title = title;
		wrap.append(' ', icon, text, btn);
		return wrap;
	}
	ignoreEvent() {
		return true;
	}
}

// ---- marks + widgets ----

const negDecorations = EditorView.decorations.compute([negField], (state): DecorationSet => {
	const items = negItems(state);
	const ranges: Range<Decoration>[] = [];
	for (const m of items.marks) {
		ranges.push(
			Decoration.mark({
				class: `cm-neg-mark cm-neg-${m.cls}`,
				attributes: { 'data-neg-id': m.id, title: clsLabel(m.cls) + ' · click for options' }
			}).range(m.from, m.to)
		);
	}
	for (const w of items.widgets) {
		ranges.push(Decoration.widget({ widget: new ItemWidget(w), side: 1 }).range(w.pos));
	}
	return Decoration.set(ranges, true);
});

// ---- popover for a clicked mark ----

export const openPopover = StateEffect.define<string | null>();

const popoverField = StateField.define<string | null>({
	create: () => null,
	update(id, tr) {
		for (const e of tr.effects) if (e.is(openPopover)) id = e.value;
		if (id && !negItems(tr.state).marks.some((m) => m.id === id)) id = null; // excluded / typed over
		return id;
	},
	provide: (f) =>
		showTooltip.compute([f, negField], (state): Tooltip | null => {
			const id = state.field(f);
			const m = id ? negItems(state).marks.find((x) => x.id === id) : null;
			if (!m) return null;
			return {
				pos: m.from,
				end: m.to,
				above: false,
				create: (view) => {
					const dom = document.createElement('div');
					dom.className = `cm-neg-popover cm-neg-popover-${m.cls}`;
					const head = document.createElement('div');
					head.className = 'cm-neg-popover-label';
					head.textContent = `${m.cls === 'default' ? ICONS.default : ICONS.implicated} ${clsLabel(m.cls)}`;
					dom.append(head);
					if (m.pointer) {
						const p = document.createElement('div');
						p.className = 'cm-neg-popover-pointer';
						p.textContent = `Dictated finding: “${m.pointer}”`;
						dom.append(p);
					}
					const row = document.createElement('div');
					row.className = 'cm-neg-popover-actions';
					row.append(
						button('exclude', 'Remove this statement from the report', () => {
							const spec = excludeMark(view.state, m.id);
							if (spec) view.dispatch(spec);
							view.focus();
						}),
						button('close', 'Close', () => view.dispatch({ effects: openPopover.of(null) }))
					);
					dom.append(row);
					return { dom };
				}
			};
		})
});

const popoverHandlers = EditorView.domEventHandlers({
	click(event, view) {
		const target = (event.target as HTMLElement | null)?.closest?.('[data-neg-id]');
		const id = target?.getAttribute('data-neg-id') ?? null;
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

const negTheme = EditorView.theme({
	'.cm-neg-mark': { borderRadius: '3px', padding: '1px 0', cursor: 'pointer' },
	'.cm-neg-default': {
		backgroundColor: 'var(--neg-green-bg)',
		borderBottom: '2px solid var(--neg-green-line)'
	},
	'.cm-neg-implicated': {
		backgroundColor: 'var(--neg-amber-bg)',
		borderBottom: '2px dashed var(--neg-amber-line)'
	},
	// Density of added normals (green): highlighted (default) | quiet (dotted underline, tint on hover) |
	// hidden (plain text, tint on hover). Amber and red are always shown.
	'&[data-density="quiet"] .cm-neg-default': {
		backgroundColor: 'transparent',
		borderBottom: '1px dotted var(--neg-green-line)'
	},
	'&[data-density="hidden"] .cm-neg-default': { backgroundColor: 'transparent', borderBottom: 'none' },
	'&[data-density="quiet"] .cm-neg-default:hover, &[data-density="hidden"] .cm-neg-default:hover': {
		backgroundColor: 'var(--neg-green-bg)'
	},
	'.cm-neg-widget': { opacity: '0.85' },
	'.cm-neg-icon': { fontSize: '0.75em', marginRight: '3px', verticalAlign: '1px' },
	'.cm-neg-wtext': { opacity: '0.7' },
	'.cm-neg-removed .cm-neg-wtext': {
		textDecoration: 'line-through',
		textDecorationColor: 'var(--neg-red-line)',
		textDecorationThickness: '2px',
		color: 'var(--neg-muted)'
	},
	'.cm-neg-removed .cm-neg-icon': { color: 'var(--neg-red-line)' },
	'.cm-neg-excluded .cm-neg-wtext': {
		textDecoration: 'line-through',
		textDecorationColor: 'var(--neg-grey-line)',
		color: 'var(--neg-muted)'
	},
	'.cm-neg-excluded .cm-neg-icon': { color: 'var(--neg-grey-line)' },
	'.cm-neg-option .cm-neg-wtext': { fontStyle: 'italic', color: 'var(--neg-ghost)' },
	'.cm-neg-option .cm-neg-icon': { color: 'var(--neg-ghost)' },
	'.cm-neg-btn': {
		font: 'inherit',
		fontSize: '0.72em',
		marginLeft: '5px',
		padding: '0 6px',
		lineHeight: '1.5',
		borderRadius: '9px',
		border: '1px solid var(--neg-border)',
		background: 'var(--neg-surface)',
		color: 'var(--neg-text)',
		cursor: 'pointer',
		verticalAlign: '1px'
	},
	'.cm-neg-btn:hover': { background: 'var(--neg-surface-hover)' },
	'.cm-tooltip.cm-tooltip:has(.cm-neg-popover)': {
		border: '1px solid var(--neg-border)',
		background: 'var(--neg-surface)',
		color: 'var(--neg-text)',
		borderRadius: '6px',
		boxShadow: '0 4px 14px rgba(0,0,0,0.18)'
	},
	'.cm-neg-popover': {
		padding: '8px 10px',
		maxWidth: '340px',
		fontSize: '0.85em',
		lineHeight: '1.4',
		background: 'var(--neg-surface)',
		color: 'var(--neg-text)',
		border: '1px solid var(--neg-border)',
		borderRadius: '6px'
	},
	'.cm-neg-popover-label': { fontWeight: '600' },
	'.cm-neg-popover-pointer': { marginTop: '4px', color: 'var(--neg-muted)' },
	'.cm-neg-popover-actions': { marginTop: '6px', display: 'flex', gap: '4px' },
	'.cm-neg-popover-actions .cm-neg-btn': { marginLeft: '0', fontSize: '0.95em' }
});

/** The drawing layer: pass as `extra` to createNegState (which owns the field + undo support). */
export function negativesDisplay(): Extension[] {
	return [negDecorations, popoverField, popoverHandlers, popoverKeys, negTheme];
}
