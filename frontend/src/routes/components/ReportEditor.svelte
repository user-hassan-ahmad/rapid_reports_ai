<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher } from 'svelte';
	import { EditorView, ViewPlugin, Decoration, WidgetType, keymap } from '@codemirror/view';
	import type { DecorationSet, ViewUpdate } from '@codemirror/view';
	import { EditorState, StateField, StateEffect, Compartment } from '@codemirror/state';
	import type { Range } from '@codemirror/state';
	import { markdown } from '@codemirror/lang-markdown';
	import { history, defaultKeymap, historyKeymap } from '@codemirror/commands';
	import { syntaxHighlighting, HighlightStyle } from '@codemirror/language';
	import { tags } from '@lezer/highlight';
	import { detectUnfilledInRawText, findItemAtPos } from '$lib/utils/rawTextDetection';
	import type { UnfilledItems, UnfilledItem } from '$lib/utils/placeholderDetection';

	const fireEvent = createEventDispatcher();

	export let content: string = '';
	export let showHighlighting: boolean = true;
	export let generationLoading: boolean = false;

	let editorContainer: HTMLDivElement;
	let editor: EditorView | null = null;

	// Tracks the last value of the `content` prop that was pushed into CM6.
	// Only updated when we receive a new prop value — never when the user edits.
	// This prevents the reactive from firing on every user keystroke.
	let lastPropContent = '';
	let skipNextChange = false;

	// Current unfilled items — updated by the ViewPlugin each doc change
	let currentUnfilledItems: UnfilledItems = {
		measurements: [],
		variables: [],
		alternatives: [],
		instructions: [],
		blank_sections: [],
		total: 0
	};

	let hoverTimeout: ReturnType<typeof setTimeout> | null = null;
	let hideTimeout: ReturnType<typeof setTimeout> | null = null;

	// ─── StateEffect / StateField for toggling highlighting ─────────────────────

	const setHighlightingEffect = StateEffect.define<boolean>();

	const highlightingState = StateField.define<boolean>({
		create: () => true,
		update(value, tr) {
			for (const eff of tr.effects) {
				if (eff.is(setHighlightingEffect)) return eff.value;
			}
			return value;
		}
	});

	// ─── Compartment for editable toggle ────────────────────────────────────────

	const editableCompartment = new Compartment();

	// ─── ViewPlugin: build decorations from raw text detection ──────────────────

	// ─── Widget for //UNFILLED: SECTION_NAME lines ──────────────────────────────

	class UnfilledSectionWidget extends WidgetType {
		sectionName: string;
		constructor(sectionName: string) {
			super();
			this.sectionName = sectionName;
		}

		toDOM(): HTMLElement {
			const el = document.createElement('span');
			el.className = 'cm-unfilled-section-widget';
			el.setAttribute('data-section', this.sectionName);
			el.innerHTML = `
				<span class="cm-usw-accent"></span>
				<span class="cm-usw-icon">
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
					</svg>
				</span>
				<span class="cm-usw-body">
					<span class="cm-usw-tag">Missing section</span>
					<span class="cm-usw-name">${this.sectionName}</span>
				</span>
				<span class="cm-usw-cta">
					<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="9 18 15 12 9 6"/>
					</svg>
				</span>
			`;
			return el;
		}

		eq(other: UnfilledSectionWidget): boolean {
			return other.sectionName === this.sectionName;
		}

		get estimatedHeight(): number {
			return -1;
		}
	}

	// ─── Build CM6 decorations from raw text detection ───────────────────────────

	function buildDecorations(state: EditorState): DecorationSet {
		if (!state.field(highlightingState)) return Decoration.none;

		const text = state.doc.toString();
		const items = detectUnfilledInRawText(text);

		// Store for use by hover handler (set synchronously before updateListener fires)
		currentUnfilledItems = items;

		const marks: Range<Decoration>[] = [];

		for (const item of items.measurements) {
			const end = item.index + item.text.length;
			if (end <= text.length) {
				marks.push(
					Decoration.mark({ class: 'cm-unfilled-measurement' }).range(item.index, end)
				);
			}
		}
		for (const item of items.variables) {
			const end = item.index + item.text.length;
			if (end <= text.length) {
				marks.push(
					Decoration.mark({ class: 'cm-unfilled-variable' }).range(item.index, end)
				);
			}
		}
		for (const item of items.alternatives) {
			const end = item.index + item.text.length;
			if (end <= text.length) {
				marks.push(
					Decoration.mark({ class: 'cm-unfilled-alternative' }).range(item.index, end)
				);
			}
		}
		for (const item of items.blank_sections) {
			// Clamp to line.to (excludes newline) — ViewPlugins cannot replace line breaks
			const line = state.doc.lineAt(item.index);
			const end = line.to;
			if (item.index < end) {
				marks.push(
					Decoration.replace({
						widget: new UnfilledSectionWidget(item.text),
						inclusive: false
					}).range(item.index, end)
				);
			}
		}

		// Sort by from position (required by Decoration.set)
		marks.sort((a, b) => a.from - b.from);

		try {
			return Decoration.set(marks, true);
		} catch {
			// Overlap or ordering issue — return empty rather than crash
			return Decoration.none;
		}
	}

	const unfilledPlugin = ViewPlugin.fromClass(
		class {
			decorations: DecorationSet;

			constructor(view: EditorView) {
				this.decorations = buildDecorations(view.state);
			}

			update(update: ViewUpdate) {
				const highlightChanged =
					update.state.field(highlightingState) !==
					update.startState.field(highlightingState);

				if (update.docChanged || highlightChanged) {
					this.decorations = buildDecorations(update.state);
				}
			}
		},
		{ decorations: (v) => v.decorations }
	);

	// ─── Markdown syntax highlight style ────────────────────────────────────────

	const markdownHighlightStyle = HighlightStyle.define([
		{ tag: tags.heading1,   fontSize: '1.15em', fontWeight: '700', color: '#f9fafb' },
		{ tag: tags.heading2,   fontSize: '1.05em', fontWeight: '700', color: '#f3f4f6' },
		{ tag: tags.heading3,   fontWeight: '700',  color: '#e5e7eb' },
		{ tag: tags.heading4,   fontWeight: '600',  color: '#d1d5db' },
		{ tag: tags.strong,     fontWeight: '700',  color: '#f3f4f6' },
		{ tag: tags.emphasis,   fontStyle: 'italic', color: '#d1d5db' },
		{ tag: tags.strikethrough, textDecoration: 'line-through', color: '#6b7280' },
		{ tag: tags.link,       color: '#a78bfa', textDecoration: 'underline' },
		{ tag: tags.url,        color: '#818cf8' },
		{ tag: tags.monospace,  fontFamily: '"IBM Plex Mono", "Fira Code", ui-monospace, monospace', color: '#34d399', background: 'rgba(52,211,153,0.08)' },
		{ tag: tags.quote,      color: '#9ca3af', fontStyle: 'italic' },
	]);

	// ─── Dark theme matching existing card design ────────────────────────────────

	const darkTheme = EditorView.theme(
		{
			'&': {
				background: 'transparent',
				color: '#e5e7eb',
				fontSize: '0.9rem',
				fontFamily: '"IBM Plex Sans", "Source Sans Pro", system-ui, -apple-system, sans-serif'
			},
			'.cm-content': {
				padding: '0',
				lineHeight: '1.75',
				caretColor: '#a855f7',
				letterSpacing: '0.01em',
				fontFamily: '"IBM Plex Sans", "Source Sans Pro", system-ui, -apple-system, sans-serif',
				fontSize: '0.9rem'
			},
			'.cm-cursor, .cm-dropCursor': {
				borderLeftColor: '#a855f7',
				borderLeftWidth: '2px'
			},
			'&.cm-focused': {
				outline: 'none'
			},
			'.cm-scroller': {
				overflow: 'visible'
			},
			'.cm-line': {
				padding: '0 2px'
			},
			'.cm-selectionBackground': {
				background: 'rgba(168, 85, 247, 0.25) !important'
			},
			'&.cm-focused .cm-selectionBackground': {
				background: 'rgba(168, 85, 247, 0.3) !important'
			},
			'.cm-activeLine': {
				background: 'rgba(255, 255, 255, 0.03)'
			},
			'.cm-gutters': {
				display: 'none'
			},
			'.cm-tooltip': {
				display: 'none'
			}
		},
		{ dark: true }
	);

	// ─── Lifecycle ───────────────────────────────────────────────────────────────

	onMount(() => {
		lastPropContent = content;

		editor = new EditorView({
			state: EditorState.create({
				doc: content,
				extensions: [
					history(),
					keymap.of([
						{
							key: 'Mod-s',
							run: () => {
								fireEvent('save');
								return true;
							}
						},
						...defaultKeymap,
						...historyKeymap
					]),
					markdown(),
					syntaxHighlighting(markdownHighlightStyle),
					EditorView.lineWrapping,
					highlightingState,
					unfilledPlugin,
					editableCompartment.of(EditorView.editable.of(!generationLoading)),
					darkTheme,
					EditorView.updateListener.of((update) => {
						if (update.docChanged) {
							if (skipNextChange) {
								skipNextChange = false;
								// Still update currentUnfilledItems for the external update
								fireEvent('unfilledItems', { items: currentUnfilledItems });
								return;
							}
						const newContent = update.state.doc.toString();
						fireEvent('change', { content: newContent });
							fireEvent('unfilledItems', { items: currentUnfilledItems });
						}
					})
				]
			}),
			parent: editorContainer
		});

		// Fire initial unfilledItems so banner shows counts on mount
		const initialItems = detectUnfilledInRawText(content);
		currentUnfilledItems = initialItems;
		fireEvent('unfilledItems', { items: initialItems });

		editor.dom.addEventListener('mousemove', handleMouseMove);
		editor.dom.addEventListener('mouseleave', handleMouseLeave);
	});

	onDestroy(() => {
		if (editor) {
			editor.dom.removeEventListener('mousemove', handleMouseMove);
			editor.dom.removeEventListener('mouseleave', handleMouseLeave);
			editor.destroy();
			editor = null;
		}
		clearHoverTimeout();
		if (hideTimeout) {
			clearTimeout(hideTimeout);
			hideTimeout = null;
		}
	});

	// ─── Reactive: sync external content prop changes into CM6 ──────────────────
	// Compares against lastPropContent (not the live doc), so user edits never
	// trigger this and reset the editor mid-typing.

	$: if (editor && content !== lastPropContent) {
		lastPropContent = content;
		skipNextChange = true;
		editor.dispatch({
			changes: { from: 0, to: editor.state.doc.length, insert: content }
		});
	}

	// ─── Reactive: toggle highlighting ──────────────────────────────────────────

	$: if (editor) {
		editor.dispatch({ effects: setHighlightingEffect.of(showHighlighting) });
	}

	// ─── Reactive: toggle editable during loading ────────────────────────────────

	$: if (editor) {
		editor.dispatch({
			effects: editableCompartment.reconfigure(
				EditorView.editable.of(!generationLoading)
			)
		});
	}

	// ─── Hover popup ─────────────────────────────────────────────────────────────

	function handleMouseMove(e: MouseEvent) {
		if (!editor) return;

		const pos = editor.posAtCoords({ x: e.clientX, y: e.clientY });
		if (pos === null) {
			clearHoverTimeout();
			if (!hideTimeout) {
				hideTimeout = setTimeout(() => {
					hideTimeout = null;
					if (!document.querySelector('.unfilled-hover-popup:hover')) {
						fireEvent('hideHoverPopup');
					}
				}, 200);
			}
			return;
		}

		const item = findItemAtPos(pos, currentUnfilledItems);
		const isInteractive =
			item &&
			(item.type === 'measurement' ||
				item.type === 'variable' ||
				item.type === 'alternative' ||
				item.type === 'blank_section');

		if (isInteractive) {
			// Cancel any pending hide — mouse is back over an item
			if (hideTimeout) {
				clearTimeout(hideTimeout);
				hideTimeout = null;
			}
			// Only schedule if not already pending for the same item
			if (hoverTimeout) return;
			hoverTimeout = setTimeout(() => {
				hoverTimeout = null;
				if (!editor || !item) return;
				const coords = editor.coordsAtPos(item.index);
				if (!coords) return;
				fireEvent('showHoverPopup', {
					item,
					position: {
						x: coords.left + (coords.right - coords.left) / 2,
						y: coords.top
					},
					reportContent: editor.state.doc.toString()
				});
			}, 150);
		} else {
			clearHoverTimeout();
			// Delay hiding so the mouse can travel from the item into the popup
			// without it disappearing mid-way (same grace period as handleMouseLeave)
			if (!hideTimeout) {
				hideTimeout = setTimeout(() => {
					hideTimeout = null;
					if (!document.querySelector('.unfilled-hover-popup:hover')) {
						fireEvent('hideHoverPopup');
					}
				}, 200);
			}
		}
	}

	function handleMouseLeave() {
		clearHoverTimeout();
		if (hideTimeout) {
			clearTimeout(hideTimeout);
			hideTimeout = null;
		}
		setTimeout(() => {
			if (!document.querySelector('.unfilled-hover-popup:hover')) {
				fireEvent('hideHoverPopup');
			}
		}, 200);
	}

	function clearHoverTimeout() {
		if (hoverTimeout) {
			clearTimeout(hoverTimeout);
			hoverTimeout = null;
		}
	}

	// ─── Public: get current document content ───────────────────────────────────

	export function getCurrentContent(): string {
		return editor ? editor.state.doc.toString() : content;
	}

	// ─── Public: discard edits and restore to a given content string ─────────────

	export function resetContent(c: string): void {
		if (!editor) return;
		lastPropContent = c;
		skipNextChange = true;
		editor.dispatch({
			changes: { from: 0, to: editor.state.doc.length, insert: c }
		});
	}
</script>

<div bind:this={editorContainer} class="cm-report-editor"></div>

<style>
	.cm-report-editor {
		width: 100%;
	}

	/* Unfilled placeholder highlight colours — match existing palette */
	:global(.cm-unfilled-measurement) {
		border-bottom: 2px solid #fbbf24;
		background: rgba(251, 191, 36, 0.15);
		color: #fbbf24;
		cursor: pointer;
		padding: 0 1px;
		border-radius: 2px;
	}

	:global(.cm-unfilled-variable) {
		border-bottom: 2px solid #34d399;
		background: rgba(52, 211, 153, 0.15);
		color: #34d399;
		cursor: pointer;
		padding: 0 1px;
		border-radius: 2px;
	}

	:global(.cm-unfilled-alternative) {
		border-bottom: 2px solid #c084fc;
		background: rgba(192, 132, 252, 0.15);
		color: #c084fc;
		cursor: pointer;
		padding: 0 1px;
		border-radius: 2px;
	}

	:global(.cm-unfilled-section-widget) {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 3px 6px 3px 0;
		background: linear-gradient(135deg, rgba(251,191,36,0.08) 0%, rgba(245,158,11,0.04) 100%);
		border: 1px solid rgba(251, 191, 36, 0.2);
		border-radius: 5px;
		cursor: pointer;
		transition: all 0.2s ease;
		vertical-align: middle;
		overflow: hidden;
		user-select: none;
		max-width: 100%;
	}

	@media (min-width: 640px) {
		:global(.cm-unfilled-section-widget) {
			gap: 8px;
			padding: 4px 10px 4px 0;
			border-radius: 6px;
		}
	}

	:global(.cm-unfilled-section-widget:hover) {
		background: linear-gradient(135deg, rgba(251,191,36,0.14) 0%, rgba(245,158,11,0.08) 100%);
		border-color: rgba(251, 191, 36, 0.4);
		transform: translateY(-1px);
		box-shadow: 0 2px 8px rgba(251, 191, 36, 0.12);
	}

	:global(.cm-usw-accent) {
		display: inline-block;
		width: 2px;
		height: 100%;
		min-height: 18px;
		background: linear-gradient(180deg, #fbbf24, #f59e0b);
		border-radius: 0 2px 2px 0;
		flex-shrink: 0;
		align-self: stretch;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-accent) {
			width: 3px;
			min-height: 22px;
		}
	}

	:global(.cm-usw-icon) {
		color: #f59e0b;
		display: flex;
		align-items: center;
		flex-shrink: 0;
		opacity: 0.9;
	}

	:global(.cm-usw-icon svg) {
		width: 10px;
		height: 10px;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-icon svg) {
			width: 12px;
			height: 12px;
		}
	}

	:global(.cm-usw-body) {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-body) {
			gap: 6px;
		}
	}

	:global(.cm-usw-tag) {
		font-size: 0.5em;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: #f59e0b;
		background: rgba(245, 158, 11, 0.15);
		padding: 1px 4px;
		border-radius: 2px;
		border: 1px solid rgba(245, 158, 11, 0.25);
		white-space: nowrap;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-tag) {
			font-size: 0.6em;
			letter-spacing: 0.08em;
			padding: 2px 6px;
			border-radius: 3px;
		}
	}

	:global(.cm-usw-name) {
		font-weight: 700;
		color: #fef3c7;
		font-size: 0.7em;
		letter-spacing: 0.03em;
		text-transform: uppercase;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-name) {
			font-size: 0.8em;
			letter-spacing: 0.04em;
		}
	}

	:global(.cm-usw-cta) {
		color: rgba(251, 191, 36, 0.4);
		display: none;
		align-items: center;
		transition: color 0.2s;
		flex-shrink: 0;
	}

	@media (min-width: 640px) {
		:global(.cm-usw-cta) {
			display: flex;
		}
	}

	:global(.cm-unfilled-section-widget:hover .cm-usw-cta) {
		color: rgba(251, 191, 36, 0.8);
	}

	/* Remove CM6's default focus ring — the card already provides context */
	:global(.cm-report-editor .cm-editor) {
		outline: none !important;
	}

	:global(.cm-report-editor .cm-editor.cm-focused) {
		outline: none !important;
	}
</style>
