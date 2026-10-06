/**
 * The review layer's look (plan Task C2): `--rv-*` colour tokens for light and dark, density and legend emphasis.
 *
 * Tokens live on the editor element (`&light` / `&dark` follow the editor's own dark-theme flag, which
 * ReportEditor sets). Every AI highlight has ONE underline style: a soft dotted line in its colour, no fill,
 * discreet at rest (amber and red a little stronger than green and blue). Meaning is never carried by colour alone:
 * each mark has an accessible name, and widgets and gutter markers carry an icon. The hovered highlight (or the one
 * whose inline control is open) brightens to full colour with a light tint.
 *
 * Density (`data-density`, Quiet by default, the app's fixed setting) only changes the assumed normals: `full` tints
 * them (dev page), `hidden` leaves plain text and drops their gutter markers. Emphasis (`data-rv-emph`, the legend's
 * filters, `setEmphasis`) brings the chosen classes forward (full colour + light tint) while the rest stay discreet;
 * "dictated" fades the AI highlights instead, so the radiologist's own text stands out.
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

/** The legend's filters: the classes brought forward (legend keys: dictated, excluded, normal, check, removed,
 * option). Empty: everything at rest. */
export const setEmphasis = StateEffect.define<readonly string[]>();

export const emphasisField = StateField.define<readonly string[]>({
	create: () => [],
	update(keys, tr) {
		for (const e of tr.effects) if (e.is(setEmphasis)) keys = [...e.value];
		return keys;
	},
	provide: (f) =>
		EditorView.editorAttributes.from(f, (keys) =>
			keys.length ? { 'data-rv-emph': keys.join(' ') } : ({} as Record<string, string>)
		)
});

/** Emphasis state, initialised to `keys`, written to the editor element's `data-rv-emph`. */
export function emphasisExtension(keys: readonly string[] = []): Extension {
	return emphasisField.init(() => [...keys]);
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
	'--rv-ins': '#1f7a3f',
	'--rv-chip-bg': '#ffffff',
	'--rv-chip-text': '#1f2937',
	'--rv-chip-muted': '#4b5563',
	'--rv-chip-border': 'rgba(147, 51, 234, 0.3)',
	'--rv-chip-hover': '#f3e8ff'
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
	'--rv-ins': '#6fd394',
	'--rv-chip-bg': 'rgba(15, 12, 25, 0.96)',
	'--rv-chip-text': '#e5e7eb',
	'--rv-chip-muted': '#c4c7cc',
	'--rv-chip-border': 'rgba(168, 85, 247, 0.35)',
	'--rv-chip-hover': 'rgba(255, 255, 255, 0.1)'
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

	// ---- marks: one soft dotted underline for every AI highlight, discreet at rest ----
	'.rv-mark': {
		cursor: 'pointer',
		borderRadius: '2px',
		textDecorationLine: 'underline',
		textDecorationStyle: 'dotted',
		textDecorationThickness: '2px',
		textUnderlineOffset: '3px',
		transition: 'background-color 120ms ease, text-decoration-color 120ms ease, opacity 120ms ease'
	},
	'.rv-normal': { textDecorationColor: 'color-mix(in srgb, var(--rv-green-line) 45%, transparent)' },
	'&[data-density="full"] .rv-normal': { backgroundColor: 'var(--rv-green-bg)' },
	'&[data-density="hidden"] .rv-normal': { textDecorationLine: 'none' },
	'.rv-check, .rv-minor': { textDecorationColor: 'color-mix(in srgb, var(--rv-amber-line) 65%, transparent)' },
	'.rv-action': { textDecorationColor: 'color-mix(in srgb, var(--rv-red-line) 70%, transparent)' },
	'.rv-info': { textDecorationLine: 'none' }, // gutter only
	'.rv-preapplied': { textDecorationColor: 'color-mix(in srgb, var(--rv-blue-line) 50%, transparent)' },
	// lit: hovered, or its inline control open (`rv-active`)
	'.rv-normal:hover, .rv-active.rv-normal, .rv-active .rv-normal': {
		textDecorationColor: 'var(--rv-green-line)',
		backgroundColor: 'var(--rv-green-bg)'
	},
	'.rv-check:hover, .rv-active.rv-check, .rv-active .rv-check, .rv-minor:hover, .rv-active.rv-minor, .rv-active .rv-minor':
		{ textDecorationColor: 'var(--rv-amber-line)', backgroundColor: 'var(--rv-amber-bg)' },
	'.rv-action:hover, .rv-active.rv-action, .rv-active .rv-action': {
		textDecorationColor: 'var(--rv-red-line)',
		backgroundColor: 'var(--rv-red-bg)'
	},
	'.rv-info:hover, .rv-active.rv-info, .rv-active .rv-info': { backgroundColor: 'var(--rv-blue-bg)' },
	'.rv-preapplied:hover, .rv-active.rv-preapplied, .rv-active .rv-preapplied': {
		textDecorationColor: 'var(--rv-blue-line)',
		backgroundColor: 'var(--rv-blue-bg)'
	},

	// ---- legend filters (`data-rv-emph`): the chosen classes forward, the rest discreet ----
	// "dictated" first, so an emphasised class (later, same specificity) stays at full opacity
	'&[data-rv-emph~="dictated"] .rv-mark, &[data-rv-emph~="dictated"] .rv-widget': { opacity: '0.4' },
	'&[data-rv-emph~="normal"] .rv-normal': {
		opacity: '1',
		textDecorationLine: 'underline',
		textDecorationColor: 'var(--rv-green-line)',
		backgroundColor: 'color-mix(in srgb, var(--rv-green-bg) 70%, transparent)'
	},
	'&[data-rv-emph~="check"] .rv-check': {
		opacity: '1',
		textDecorationColor: 'var(--rv-amber-line)',
		backgroundColor: 'color-mix(in srgb, var(--rv-amber-bg) 70%, transparent)'
	},
	'&[data-rv-emph~="removed"] .rv-removed': {
		opacity: '1',
		borderRadius: '2px',
		backgroundColor: 'color-mix(in srgb, var(--rv-red-bg) 70%, transparent)'
	},
	'&[data-rv-emph~="excluded"] .rv-excluded': {
		opacity: '1',
		borderRadius: '2px',
		backgroundColor: 'var(--rv-surface-hover)'
	},
	'&[data-rv-emph~="option"] .rv-option': {
		opacity: '1',
		borderRadius: '2px',
		backgroundColor: 'color-mix(in srgb, var(--rv-blue-bg) 70%, transparent)'
	},

	// ---- apply preview (hovering ⏎): old struck, new as ghost text ----
	'.rv-preview-del': {
		textDecorationLine: 'line-through',
		textDecorationColor: 'var(--rv-red-line)',
		textDecorationThickness: '2px',
		color: 'var(--rv-muted)'
	},
	'.rv-preview-ins': {
		color: 'var(--rv-ins)',
		opacity: '0.75',
		fontStyle: 'italic',
		marginLeft: '2px',
		pointerEvents: 'none'
	},

	// ---- after an action: the range ticks and fades into its new state ----
	'@keyframes rv-flash-fade': {
		'0%': { backgroundColor: 'color-mix(in srgb, var(--rv-green-line) 35%, transparent)' },
		'100%': { backgroundColor: 'transparent' }
	},
	'@keyframes rv-tick': {
		'0%': { opacity: '0', transform: 'translateY(2px) scale(0.8)' },
		'25%': { opacity: '1', transform: 'translateY(0) scale(1)' },
		'100%': { opacity: '0' }
	},
	'.rv-flash': { animation: 'rv-flash-fade 650ms ease-out forwards', borderRadius: '2px' },
	'.rv-flash-tick': {
		display: 'inline-block',
		marginLeft: '2px',
		fontSize: '0.8em',
		color: 'var(--rv-green-line)',
		animation: 'rv-tick 650ms ease-out forwards',
		pointerEvents: 'none'
	},

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

	// ---- inline control: expands at the END of the highlight, inside the text flow ----
	'@keyframes rv-inline-in': {
		'0%': { maxWidth: '0', opacity: '0' },
		'100%': { maxWidth: '6em', opacity: '1' }
	},
	'.rv-inline': {
		display: 'inline-flex',
		alignItems: 'center',
		gap: '1px',
		boxSizing: 'border-box',
		height: '1.2em',
		margin: '0 1px 0 3px',
		padding: '0 2px',
		verticalAlign: '-0.2em',
		overflow: 'hidden',
		whiteSpace: 'nowrap',
		fontFamily: "'DM Sans', 'IBM Plex Sans', system-ui, sans-serif",
		fontSize: '0.8em',
		lineHeight: '1',
		color: 'var(--rv-chip-text)',
		background: 'var(--rv-chip-bg)',
		border: '1px solid var(--rv-chip-border)',
		borderRadius: '6px',
		userSelect: 'none',
		animation: 'rv-inline-in 120ms ease-out'
	},
	'.rv-inline-btn': {
		font: 'inherit',
		fontSize: '1em',
		lineHeight: '1',
		width: '1.45em',
		height: '100%',
		padding: '0',
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		border: '0',
		borderRadius: '4px',
		background: 'transparent',
		color: 'var(--rv-chip-muted)',
		cursor: 'pointer'
	},
	'.rv-inline-btn[data-rv-action="keep"], .rv-inline-btn[data-rv-action="apply"]': {
		color: 'var(--rv-green-line)'
	},
	'.rv-inline-btn[data-rv-action="remove"], .rv-inline-btn[data-rv-action="dismiss"]': {
		color: 'var(--rv-red-line)'
	},
	'.rv-inline-btn[data-rv-action="restore"], .rv-inline-btn[data-rv-action="undo"]': {
		color: 'var(--rv-blue-line)'
	},
	'.rv-inline-btn:hover, .rv-inline-btn:focus-visible': { background: 'var(--rv-chip-hover)' },
	'.rv-inline-btn:focus-visible': { outline: '2px solid #a855f7', outlineOffset: '-2px' },
	'.rv-inline-reveal': { color: 'var(--rv-chip-muted)', fontSize: '1.15em' },

	// ---- gutter ----
	'.rv-gutter': { minWidth: '14px' },
	'.rv-gutter-marker': { fontSize: '0.75em', textAlign: 'center', cursor: 'pointer' },
	'.rv-gutter-action': { color: 'var(--rv-red-line)' },
	'.rv-gutter-minor': { color: 'var(--rv-amber-line)' },
	'.rv-gutter-info': { color: 'var(--rv-green-line)' },
	'&[data-density="hidden"] .rv-gutter-info': { visibility: 'hidden' }
});
