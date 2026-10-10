/**
 * The review layer's look (plan Task C2): `--rv-*` colour tokens for light and dark, density and legend emphasis.
 *
 * Tokens live on the editor element (`&light` / `&dark` follow the editor's own dark-theme flag, which
 * ReportEditor sets). Every highlight has ONE underline style: a soft dotted line in its colour, no fill, discreet
 * at rest. Meaning is never carried by colour alone: each mark has an accessible name, and widgets and gutter
 * markers carry an icon.
 *
 * The AI-generated layer is a very light background tint by category (`rv-form-*`, field.formOf): normals green,
 * negatives bearing on a finding amber, synthesis violet; no underline, no actions. It is ON by default (the legend's
 * "AI-generated" toggle, `data-rv-emph~="ai"`); off, it is plain text, except amber, which is always shown. Recommendations (teal), flagged issues (red),
 * minor items (amber) and pre-applied changes (blue) keep their dotted underline; hovering one (or its open inline
 * control, `rv-active`) lights it. Density (`data-density`, Quiet by default) is a dev-page capability.
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

/** The AI highlights mode as emphasis keys (Legend's three-way control): Key `['ai']` (amber, violet and the
 * recommendation underline), All `['ai', 'normals']` (plus green normals), Off `[]` (no AI tints at all). */
export const setEmphasis = StateEffect.define<readonly string[]>();

/** Key mode: the default (editor/decorations.ts DEFAULT_LEGEND). */
export const DEFAULT_EMPHASIS: readonly string[] = ['ai'];

export const emphasisField = StateField.define<readonly string[]>({
	create: () => DEFAULT_EMPHASIS,
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
export function emphasisExtension(keys: readonly string[] = DEFAULT_EMPHASIS): Extension {
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
	'--rv-violet-bg': '#ede7fb',
	'--rv-violet-line': '#7c5cd6',
	'--rv-teal-bg': '#d8f3f0',
	'--rv-teal-line': '#14857a',
	'--rv-tint-normal': 'rgba(63, 154, 93, 0.13)',
	'--rv-tint-negative': 'rgba(196, 128, 22, 0.15)',
	'--rv-tint-synthesis': 'rgba(124, 92, 214, 0.13)',
	'--rv-accent': '#9333ea',
	'--rv-accent-ring': 'rgba(168, 85, 247, 0.45)',
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
	'--rv-violet-bg': '#2e2648',
	'--rv-violet-line': '#b3a1f5',
	'--rv-teal-bg': '#163a37',
	'--rv-teal-line': '#5fd3c6',
	'--rv-tint-normal': 'rgba(92, 194, 133, 0.14)',
	'--rv-tint-negative': 'rgba(227, 169, 74, 0.15)',
	'--rv-tint-synthesis': 'rgba(179, 161, 245, 0.16)',
	'--rv-accent': '#9333ea',
	'--rv-accent-ring': 'rgba(168, 85, 247, 0.5)',
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

	// ---- marks: one soft dotted underline, discreet at rest ----
	'.rv-mark': {
		cursor: 'pointer',
		borderRadius: '2px',
		textDecorationLine: 'underline',
		textDecorationStyle: 'dotted',
		textDecorationThickness: '2px',
		textUnderlineOffset: '3px',
		transition: 'background-color 120ms ease, text-decoration-color 120ms ease, opacity 120ms ease'
	},
	'.rv-action': { textDecorationColor: 'color-mix(in srgb, var(--rv-red-line) 70%, transparent)' },
	'.rv-minor': { textDecorationColor: 'color-mix(in srgb, var(--rv-amber-line) 65%, transparent)' },
	'.rv-info': { textDecorationLine: 'none' }, // gutter only
	'.rv-preapplied': { textDecorationColor: 'color-mix(in srgb, var(--rv-blue-line) 50%, transparent)' },
	// the AI-generated layer, by the legend's three-way control (data-rv-emph): Key = "ai" (amber negatives, violet
	// synthesis and the teal recommendation underline), All = "ai normals" (plus green normals), Off = none (plain
	// editable text; rail cards, action marks and the recommendation checkboxes are unaffected). No underline on tints.
	'.rv-normal, .rv-check, .rv-synth': { cursor: 'text', textDecorationLine: 'none', borderRadius: '3px' },
	'&[data-rv-emph~="normals"] .rv-form-normal': { backgroundColor: 'var(--rv-tint-normal)' },
	'&[data-rv-emph~="ai"] .rv-form-negative': { backgroundColor: 'var(--rv-tint-negative)' },
	'&[data-rv-emph~="ai"] .rv-form-synthesis': { backgroundColor: 'var(--rv-tint-synthesis)' },
	// recommendations: their own dotted underline in Key and All (their control is the impression's checklist)
	'.rv-rec': {
		cursor: 'text',
		textDecorationLine: 'none',
		textDecorationColor: 'color-mix(in srgb, var(--rv-teal-line) 70%, transparent)'
	},
	'&[data-rv-emph~="ai"] .rv-rec': { textDecorationLine: 'underline' },
	// lit: hovered, or its inline control open (`rv-active`)
	'.rv-action:hover, .rv-active.rv-action, .rv-active .rv-action': {
		textDecorationColor: 'var(--rv-red-line)',
		backgroundColor: 'var(--rv-red-bg)'
	},
	'.rv-minor:hover, .rv-active.rv-minor, .rv-active .rv-minor': {
		textDecorationColor: 'var(--rv-amber-line)',
		backgroundColor: 'var(--rv-amber-bg)'
	},
	'.rv-preapplied:hover, .rv-active.rv-preapplied, .rv-active .rv-preapplied': {
		textDecorationColor: 'var(--rv-blue-line)',
		backgroundColor: 'var(--rv-blue-bg)'
	},

	// ---- suggestions: a checkbox subsection under a section's body (not document text) ----
	// a blank line's gap above each block (padding: CM measures block widgets by their box)
	'.rv-suggestions-block': { paddingTop: '1.15em', paddingBottom: '4px' },
	'.rv-suggestions': {
		margin: '0',
		padding: '3px 8px 4px',
		borderLeft: '2px solid color-mix(in srgb, var(--rv-blue-line) 45%, transparent)',
		fontFamily: "'DM Sans', 'IBM Plex Sans', system-ui, sans-serif",
		fontSize: '0.85em',
		lineHeight: '1.5',
		color: 'var(--rv-muted)',
		userSelect: 'none'
	},
	'.rv-suggestions-title': {
		fontSize: '0.8em',
		fontWeight: '600',
		letterSpacing: '0.06em',
		textTransform: 'uppercase',
		marginBottom: '1px'
	},
	'.rv-suggestion': {
		display: 'flex',
		alignItems: 'baseline',
		gap: '6px',
		cursor: 'pointer',
		color: 'var(--rv-text)'
	},
	// the app's checkbox: a rounded box in the border colour; purple-600 with a white tick when checked
	'.rv-suggestion input.rv-check-box': {
		appearance: 'none',
		WebkitAppearance: 'none',
		flex: '0 0 auto',
		boxSizing: 'border-box',
		width: '14px',
		height: '14px',
		margin: '0',
		border: '1.5px solid var(--rv-border)',
		borderRadius: '4px',
		backgroundColor: 'var(--rv-surface)',
		backgroundRepeat: 'no-repeat',
		backgroundPosition: 'center',
		backgroundSize: '10px 10px',
		cursor: 'pointer',
		transform: 'translateY(2px)',
		transition: 'background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease'
	},
	'.rv-suggestion input.rv-check-box:hover:not(:disabled)': { borderColor: '#a855f7' },
	'.rv-suggestion input.rv-check-box:checked': {
		backgroundColor: 'var(--rv-accent)',
		borderColor: 'var(--rv-accent)',
		backgroundImage:
			"url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2.5 6.2l2.3 2.3 4.7-5' fill='none' stroke='white' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")"
	},
	'.rv-suggestion input.rv-check-box:checked:hover:not(:disabled)': { backgroundColor: '#7e22ce', borderColor: '#7e22ce' },
	'.rv-suggestion input.rv-check-box:focus-visible': {
		outline: 'none',
		boxShadow: '0 0 0 2px var(--rv-accent-ring)'
	},
	'.rv-suggestion input.rv-check-box:disabled': { opacity: '0.5', cursor: 'default' },
	'.rv-suggestion:has(input:not(:checked)) .rv-suggestion-text': { color: 'var(--rv-muted)' },

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
