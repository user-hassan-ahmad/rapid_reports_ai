/**
 * The review layer's look (plan Task C2): `--rv-*` colour tokens for light and dark, and density.
 *
 * Tokens live on the editor element (`&light` / `&dark` follow the editor's own dark-theme flag, which
 * ReportEditor sets). Meaning is never carried by colour alone: every mark has a distinct line style (normal
 * dotted, check dashed, action solid, minor dotted, pre-applied double) plus an accessible name, and widgets and
 * gutter markers carry an icon.
 *
 * Quiet at rest: every mark is a soft thin underline in its colour with no fill; the hovered mark (or the one whose
 * chip is open) brightens to full colour with a light tint. Density (`view.dom.dataset.density`, Quiet by default,
 * the app's fixed setting) only changes the assumed normals: `full` tints them (dev page), `hidden` leaves plain
 * text and drops their gutter markers. Checks, actions, removals and options are always shown.
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

	// ---- marks: quiet at rest ----
	// Every mark is a soft thin underline in its colour, no fill: green normal, amber check, red action, a soft blue
	// double line for pre-applied. Hovering (or the open chip, `rv-active`) brightens that one mark to full colour
	// with a light tint. Density only varies the assumed normals (the dev page's Full tints them; Hidden drops them).
	'.rv-mark': {
		cursor: 'pointer',
		borderRadius: '2px',
		textDecorationLine: 'underline',
		textDecorationThickness: '1px',
		textUnderlineOffset: '3px',
		transition: 'background-color 120ms ease, text-decoration-color 120ms ease'
	},
	'.rv-normal': {
		textDecorationStyle: 'dotted',
		textDecorationColor: 'color-mix(in srgb, var(--rv-green-line) 55%, transparent)'
	},
	'&[data-density="full"] .rv-normal': { backgroundColor: 'var(--rv-green-bg)' },
	'&[data-density="hidden"] .rv-normal': { textDecorationLine: 'none' },
	'.rv-check': {
		textDecorationStyle: 'dashed',
		textDecorationColor: 'color-mix(in srgb, var(--rv-amber-line) 65%, transparent)'
	},
	'.rv-action': {
		textDecorationStyle: 'solid',
		textDecorationColor: 'color-mix(in srgb, var(--rv-red-line) 70%, transparent)'
	},
	'.rv-minor': {
		textDecorationStyle: 'dotted',
		textDecorationColor: 'color-mix(in srgb, var(--rv-amber-line) 60%, transparent)'
	},
	'.rv-info': { textDecorationLine: 'none' }, // gutter only
	'.rv-preapplied': {
		textDecorationStyle: 'double',
		textDecorationColor: 'color-mix(in srgb, var(--rv-blue-line) 60%, transparent)'
	},
	'.rv-mark:hover, .rv-mark.rv-active, .rv-active .rv-mark': {
		textDecorationThickness: '2px'
	},
	'.rv-normal:hover, .rv-active.rv-normal, .rv-active .rv-normal': {
		textDecorationColor: 'var(--rv-green-line)',
		backgroundColor: 'var(--rv-green-bg)'
	},
	'.rv-check:hover, .rv-active.rv-check, .rv-active .rv-check': {
		textDecorationColor: 'var(--rv-amber-line)',
		backgroundColor: 'var(--rv-amber-bg)'
	},
	'.rv-action:hover, .rv-active.rv-action, .rv-active .rv-action': {
		textDecorationColor: 'var(--rv-red-line)',
		backgroundColor: 'var(--rv-red-bg)'
	},
	'.rv-minor:hover, .rv-active.rv-minor, .rv-active .rv-minor': {
		textDecorationColor: 'var(--rv-amber-line)',
		backgroundColor: 'var(--rv-amber-bg)'
	},
	'.rv-info:hover, .rv-active.rv-info, .rv-active .rv-info': { backgroundColor: 'var(--rv-blue-bg)' },
	'.rv-preapplied:hover, .rv-active.rv-preapplied, .rv-active .rv-preapplied': {
		textDecorationColor: 'var(--rv-blue-line)',
		backgroundColor: 'var(--rv-blue-bg)'
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

	// ---- hover chip (one line; the app's dark glass + purple border) ----
	'@keyframes rv-chip-in': {
		'0%': { opacity: '0', transform: 'translateY(3px)' },
		'100%': { opacity: '1', transform: 'translateY(0)' }
	},
	// The chip dom IS the tooltip element, and the report editor's theme hides `.cm-tooltip`; this selector
	// outranks that rule so the chip shows.
	'.cm-tooltip.rv-chip': {
		display: 'flex',
		alignItems: 'center',
		gap: '6px',
		padding: '2px 3px 2px 8px',
		marginBottom: '4px',
		whiteSpace: 'nowrap',
		maxWidth: 'min(520px, 90vw)',
		fontFamily: "'DM Sans', 'IBM Plex Sans', system-ui, sans-serif",
		fontSize: '12px',
		lineHeight: '1.5',
		color: 'var(--rv-chip-text)',
		background: 'var(--rv-chip-bg)',
		border: '1px solid var(--rv-chip-border)',
		borderRadius: '8px',
		boxShadow: '0 6px 20px rgba(0,0,0,0.35)',
		animation: 'rv-chip-in 120ms ease-out'
	},
	'.rv-chip-icon': {
		fontWeight: '700',
		width: '14px',
		textAlign: 'center',
		flex: 'none'
	},
	'.rv-chip-check .rv-chip-icon': { color: 'var(--rv-amber-line)' },
	'.rv-chip-action .rv-chip-icon, .rv-chip-removed .rv-chip-icon': { color: 'var(--rv-red-line)' },
	'.rv-chip-normal .rv-chip-icon': { color: 'var(--rv-green-line)' },
	'.rv-chip-option .rv-chip-icon, .rv-chip-preapplied .rv-chip-icon, .rv-chip-info .rv-chip-icon': {
		color: 'var(--rv-blue-line)'
	},
	'.rv-chip-text': { overflow: 'hidden', textOverflow: 'ellipsis', minWidth: '0', color: 'var(--rv-chip-muted)' },
	'.rv-chip-actions': {
		display: 'inline-flex',
		alignItems: 'center',
		gap: '1px',
		paddingLeft: '4px',
		borderLeft: '1px solid var(--rv-chip-border)',
		flex: 'none'
	},
	'.rv-chip-btn': {
		font: 'inherit',
		fontSize: '13px',
		lineHeight: '1',
		width: '24px',
		height: '22px',
		display: 'inline-flex',
		alignItems: 'center',
		justifyContent: 'center',
		border: '0',
		borderRadius: '6px',
		background: 'transparent',
		color: 'var(--rv-chip-text)',
		cursor: 'pointer'
	},
	'.rv-chip-btn:hover, .rv-chip-btn:focus-visible': {
		background: 'var(--rv-chip-hover)',
		color: '#fff'
	},
	'&light .rv-chip-btn:hover, &light .rv-chip-btn:focus-visible': { color: 'var(--rv-text)' },
	'.rv-chip-btn[data-rv-chip-action="apply"]:hover, .rv-chip-btn[data-rv-chip-action="apply"]:focus-visible': {
		background: '#9333ea',
		color: '#fff'
	},
	'.rv-chip-btn:focus-visible': { outline: '2px solid #a855f7', outlineOffset: '0' },
	'.rv-chip-reveal': { fontSize: '16px', color: 'var(--rv-chip-muted)' },

	// ---- gutter ----
	'.rv-gutter': { minWidth: '14px' },
	'.rv-gutter-marker': { fontSize: '0.75em', textAlign: 'center', cursor: 'pointer' },
	'.rv-gutter-action': { color: 'var(--rv-red-line)' },
	'.rv-gutter-minor': { color: 'var(--rv-amber-line)' },
	'.rv-gutter-info': { color: 'var(--rv-green-line)' },
	'&[data-density="hidden"] .rv-gutter-info': { visibility: 'hidden' }
});
