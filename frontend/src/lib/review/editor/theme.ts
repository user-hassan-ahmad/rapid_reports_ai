/**
 * The review layer's look (plan Task C2): `--rv-*` colour tokens for light and dark, and density.
 *
 * Tokens live on the editor element (`&light` / `&dark` follow the editor's own dark-theme flag, which
 * ReportEditor sets). Meaning is never carried by colour alone: every mark has a distinct line style (normal
 * dotted, check dashed, action solid, minor dotted, pre-applied double) plus an accessible name, and widgets and
 * gutter markers carry an icon.
 *
 * Density (`view.dom.dataset.density`, Quiet by default) only changes the assumed normals (green), the most
 * numerous and least urgent marks: `full` tints them, `quiet` draws a faint dotted underline (tint on hover),
 * `hidden` leaves plain text (tint on hover) and drops their gutter markers. Checks, actions, removals and
 * options are always shown.
 */
import { StateEffect, StateField, type Extension } from '@codemirror/state';
import { EditorView } from '@codemirror/view';

export type Density = 'full' | 'quiet' | 'hidden';
export const DEFAULT_DENSITY: Density = 'quiet';

export const setDensity = StateEffect.define<Density>();

export const densityField = StateField.define<Density>({
	create: () => DEFAULT_DENSITY,
	update(d, tr) {
		for (const e of tr.effects) if (e.is(setDensity)) d = e.value;
		return d;
	},
	provide: (f) => EditorView.editorAttributes.from(f, (d) => ({ 'data-density': d }))
});

/** Density state, initialised to `density`, written to the editor element's `data-density`. */
export function densityExtension(density: Density = DEFAULT_DENSITY): Extension {
	return densityField.init(() => density);
}

const LIGHT = {
	'--rv-surface': '#ffffff',
	'--rv-surface-hover': '#f0f0ec',
	'--rv-text': '#1f2328',
	'--rv-muted': '#5f6670',
	'--rv-border': '#d6d8db',
	'--rv-green-bg': '#dcf3e2',
	'--rv-green-line': '#3f9a5d',
	'--rv-amber-bg': '#fcebc7',
	'--rv-amber-line': '#b7791f',
	'--rv-red-bg': '#fde2e2',
	'--rv-red-line': '#cf3b3b',
	'--rv-blue-bg': '#dfeafc',
	'--rv-blue-line': '#3b6fcf',
	'--rv-grey-line': '#8a9099',
	'--rv-ghost': '#6b727c',
	'--rv-del': '#b42318',
	'--rv-ins': '#1f7a3f'
};

const DARK = {
	'--rv-surface': '#1e2125',
	'--rv-surface-hover': '#292d32',
	'--rv-text': '#e6e8eb',
	'--rv-muted': '#a0a7b1',
	'--rv-border': '#3a3f46',
	'--rv-green-bg': '#1d3a28',
	'--rv-green-line': '#5cc285',
	'--rv-amber-bg': '#43341a',
	'--rv-amber-line': '#e3a94a',
	'--rv-red-bg': '#4a2222',
	'--rv-red-line': '#ff7a7a',
	'--rv-blue-bg': '#1f2d47',
	'--rv-blue-line': '#7ea6f0',
	'--rv-grey-line': '#8f969f',
	'--rv-ghost': '#9aa1ab',
	'--rv-del': '#ff8c80',
	'--rv-ins': '#6fd394'
};

const btn = {
	font: 'inherit',
	fontSize: '0.72em',
	padding: '0 7px',
	lineHeight: '1.6',
	borderRadius: '9px',
	border: '1px solid var(--rv-border)',
	background: 'var(--rv-surface)',
	color: 'var(--rv-text)',
	cursor: 'pointer'
};

export const reviewTheme = EditorView.baseTheme({
	'&light': LIGHT,
	'&dark': DARK,

	// ---- marks ----
	'.rv-mark': { borderRadius: '2px', cursor: 'pointer' },
	'.rv-normal': {
		backgroundColor: 'var(--rv-green-bg)',
		borderBottom: '2px dotted var(--rv-green-line)'
	},
	'&[data-density="quiet"] .rv-normal': {
		backgroundColor: 'transparent',
		borderBottom: '1px dotted var(--rv-green-line)'
	},
	'&[data-density="hidden"] .rv-normal': { backgroundColor: 'transparent', borderBottom: 'none' },
	'&[data-density="quiet"] .rv-normal:hover, &[data-density="hidden"] .rv-normal:hover': {
		backgroundColor: 'var(--rv-green-bg)'
	},
	'.rv-check': {
		backgroundColor: 'var(--rv-amber-bg)',
		borderBottom: '2px dashed var(--rv-amber-line)'
	},
	'.rv-action': { borderBottom: '2px solid var(--rv-red-line)' },
	'.rv-minor': { borderBottom: '2px dotted var(--rv-amber-line)' },
	'.rv-info': {}, // gutter only
	'.rv-info:hover': { backgroundColor: 'var(--rv-blue-bg)' },
	'.rv-preapplied': {
		backgroundColor: 'var(--rv-blue-bg)',
		borderBottom: '3px double var(--rv-blue-line)'
	},
	'.rv-open': { outline: '1px solid var(--rv-border)' },

	// ---- widgets (display only, never document text) ----
	'.rv-widget': { opacity: '0.9' },
	'.rv-icon': { fontSize: '0.75em', marginRight: '3px', verticalAlign: '1px' },
	'.rv-wtext': { opacity: '0.75' },
	'.rv-removed .rv-wtext': {
		textDecoration: 'line-through',
		textDecorationColor: 'var(--rv-red-line)',
		textDecorationThickness: '2px',
		color: 'var(--rv-muted)'
	},
	'.rv-removed .rv-icon': { color: 'var(--rv-red-line)' },
	'.rv-excluded .rv-wtext': {
		textDecoration: 'line-through',
		textDecorationColor: 'var(--rv-grey-line)',
		color: 'var(--rv-muted)'
	},
	'.rv-excluded .rv-icon': { color: 'var(--rv-grey-line)' },
	'.rv-option .rv-wtext': { fontStyle: 'italic', color: 'var(--rv-ghost)' },
	'.rv-option .rv-icon': { color: 'var(--rv-ghost)' },
	'.rv-btn': { ...btn, marginLeft: '5px', verticalAlign: '1px' },
	'.rv-btn:hover': { background: 'var(--rv-surface-hover)' },
	'.rv-btn:focus-visible': { outline: '2px solid var(--rv-blue-line)', outlineOffset: '1px' },

	// ---- popover ----
	'.cm-tooltip.cm-tooltip:has(.rv-popover)': {
		border: '1px solid var(--rv-border)',
		background: 'var(--rv-surface)',
		color: 'var(--rv-text)',
		borderRadius: '6px',
		boxShadow: '0 4px 14px rgba(0,0,0,0.18)'
	},
	'.rv-popover': {
		padding: '8px 10px',
		maxWidth: '360px',
		fontSize: '0.85em',
		lineHeight: '1.4',
		background: 'var(--rv-surface)',
		color: 'var(--rv-text)',
		borderRadius: '6px'
	},
	'.rv-popover-label': { fontWeight: '600' },
	'.rv-popover-reason, .rv-popover-source, .rv-popover-pointer': {
		marginTop: '4px',
		color: 'var(--rv-muted)'
	},
	'.rv-popover-diff': { marginTop: '6px', fontFamily: 'inherit' },
	'.rv-popover-diff del': { color: 'var(--rv-del)', textDecorationThickness: '2px' },
	'.rv-popover-diff ins': { color: 'var(--rv-ins)', textDecoration: 'underline' },
	'.rv-popover-actions': { marginTop: '8px', display: 'flex', gap: '4px', flexWrap: 'wrap' },
	'.rv-popover-actions .rv-btn': { marginLeft: '0', fontSize: '0.95em' },
	'.rv-popover-input': {
		font: 'inherit',
		width: '100%',
		marginTop: '6px',
		padding: '2px 6px',
		border: '1px solid var(--rv-border)',
		borderRadius: '4px',
		background: 'var(--rv-surface)',
		color: 'var(--rv-text)'
	},

	// ---- gutter ----
	'.rv-gutter': { minWidth: '14px' },
	'.rv-gutter-marker': { fontSize: '0.75em', textAlign: 'center', cursor: 'pointer' },
	'.rv-gutter-action': { color: 'var(--rv-red-line)' },
	'.rv-gutter-minor': { color: 'var(--rv-amber-line)' },
	'.rv-gutter-info': { color: 'var(--rv-green-line)' },
	'&[data-density="hidden"] .rv-gutter-info': { visibility: 'hidden' }
});
