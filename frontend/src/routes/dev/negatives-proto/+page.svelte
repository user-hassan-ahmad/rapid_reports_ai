<script lang="ts">
	// Dev-only prototype: how generated normal/negative statements look and behave in the report
	// editor. Logic lives in $lib/review/negatives-proto; this page only wires it up.
	// Production text never enters the repo: bundles are loaded from a local file.
	import { onDestroy, onMount } from 'svelte';
	import { EditorView, keymap } from '@codemirror/view';
	import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
	import type { NegativesBundle } from '$lib/review/negatives-proto/bundle';
	import { createNegState, negCounts, negItems, parseBundle, type NegCounts } from '$lib/review/negatives-proto/state';
	import { ICONS, LABELS, negativesDisplay } from '$lib/review/negatives-proto/decorations';

	let host: HTMLDivElement;
	let view: EditorView | null = null;
	let bundle = $state<NegativesBundle | null>(null);
	let counts = $state<NegCounts | null>(null);
	let error = $state('');
	let warnings = $state<string[]>([]);
	let copied = $state(false);
	let dragging = $state(false);

	// Legend wording candidates (prototype only): pick one to see it in place.
	const LABEL_SETS: Record<string, Record<string, string>> = {
		'E · meaning': { dictated: 'your dictation', default: 'assumed normal', implicated: 'check',
			removed: 'removed · contradicts your dictation', excluded: 'removed by you', option: 'suggested · not included' },
		'A · current': { dictated: 'dictated', default: 'added (likely stays)', implicated: 'added (check)',
			removed: 'removed (contradicted by dictation · restore)', excluded: 'excluded by you', option: 'option (not in report)' },
		'B · source': { dictated: 'your dictation', default: 'standard normal', implicated: 'normal · may conflict',
			removed: 'removed · conflicts with dictation', excluded: 'removed by you', option: 'suggestion' },
		'C · action': { dictated: 'dictated', default: 'added · keep', implicated: 'added · review',
			removed: 'auto-removed · restore?', excluded: 'you removed · restore?', option: 'optional · add?' },
		'D · short': { dictated: 'dictated', default: 'inferred normal', implicated: 'needs review',
			removed: 'conflict removed', excluded: 'excluded', option: 'optional' }
	};
	let labelSet = $state('E · meaning');
	let density = $state<'full' | 'quiet' | 'hidden'>('quiet');
	const KEYS = ['dictated', 'default', 'implicated', 'removed', 'excluded', 'option'] as const;
	let legend = $derived(KEYS.map((key) => ({ key, icon: ICONS[key], label: LABEL_SETS[labelSet][key], title: LABELS[key] })));
	$effect(() => {
		const d = density; // read first so the effect tracks it even before the editor exists
		if (view) view.dom.dataset.density = d;
	});

	function extensions() {
		return [
			history(),
			keymap.of([...defaultKeymap, ...historyKeymap]),
			EditorView.lineWrapping,
			negativesDisplay(),
			EditorView.updateListener.of((u) => {
				if (u.docChanged || u.transactions.length) counts = negCounts(negItems(u.state));
			})
		];
	}

	function load(raw: unknown) {
		try {
			const parsed = parseBundle(raw);
			bundle = parsed.bundle;
			warnings = parsed.warnings;
			error = '';
			const state = createNegState(parsed.bundle, extensions());
			view?.setState(state);
			counts = negCounts(negItems(state));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function loadFile(file: File | undefined) {
		if (!file) return;
		try {
			load(JSON.parse(await file.text()));
		} catch (e) {
			error = `Could not read ${file.name}: ${e instanceof Error ? e.message : String(e)}`;
		}
	}

	async function loadSample() {
		const mod = await import('$lib/review/negatives-proto/sample-synthetic.json');
		load(structuredClone(mod.default));
	}

	async function copyReport() {
		if (!view) return;
		await navigator.clipboard.writeText(view.state.doc.toString());
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}

	function onDrop(e: DragEvent) {
		e.preventDefault();
		dragging = false;
		loadFile(e.dataTransfer?.files?.[0]);
	}

	onMount(() => {
		view = new EditorView({ parent: host, state: createNegState(emptyBundle(), extensions()) });
	});
	onDestroy(() => view?.destroy());

	function emptyBundle(): NegativesBundle {
		return { version: 1, id8: '', scan: '', history: '', dictation: '', report: '', marked: [], removed: [], options: [] };
	}
</script>

<svelte:head><title>Negatives prototype</title></svelte:head>

<div
	class="neg-proto"
	class:dragging
	role="region"
	aria-label="Negatives prototype"
	ondragover={(e) => {
		e.preventDefault();
		dragging = true;
	}}
	ondragleave={() => (dragging = false)}
	ondrop={onDrop}
>
	<header class="top">
		<h1>Negatives prototype <span class="dev">dev</span></h1>
		<div class="loaders">
			<label class="btn">
				Load bundle…
				<input type="file" accept="application/json,.json" onchange={(e) => loadFile(e.currentTarget.files?.[0])} />
			</label>
			<button class="btn" type="button" onclick={loadSample}>Load sample</button>
			<span class="hint">or drop a bundle JSON anywhere</span>
		</div>
	</header>

	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#each warnings as w}<p class="warn">{w}</p>{/each}

	<div class="layout">
		<section class="editor-card">
			<div class="editor-head">
				<div class="title">
					{#if bundle}<strong>{bundle.scan}</strong> <span class="muted">{bundle.id8}</span>{:else}<span class="muted"
							>No bundle loaded</span
						>{/if}
				</div>
				<div class="controls">
					<span class="muted">Added normals:</span>
					{#each [['full', 'Highlighted'], ['quiet', 'Quiet'], ['hidden', 'Hidden']] as [v, t]}
						<button type="button" class="seg" class:on={density === v} onclick={() => (density = v as typeof density)}>{t}</button>
					{/each}
					<span class="muted" style="margin-left:12px">Legend wording:</span>
					<select bind:value={labelSet}>
						{#each Object.keys(LABEL_SETS) as k}<option value={k}>{k}</option>{/each}
					</select>
				</div>
				<ul class="legend" aria-label="Legend">
					{#each legend as l}
						<li title={l.title}>
							<span class="sw sw-{l.key}" aria-hidden="true">{l.icon}</span>{l.label}
						</li>
					{/each}
				</ul>
			</div>
			<div class="editor" bind:this={host}></div>
		</section>

		<aside class="side">
			{#if counts}
				<p class="counts">
					{counts.added} added normals · {counts.check} to check · {counts.removed} removed · {counts.options}
					options{#if counts.excluded} · {counts.excluded} excluded{/if}
				</p>
			{/if}
			<button class="btn primary" type="button" onclick={copyReport} disabled={!bundle}>
				{copied ? 'Copied' : 'Copy report'}
			</button>
			{#if bundle}
				<h2>Clinical history</h2>
				<p class="pre">{bundle.history || '—'}</p>
				<h2>Dictation</h2>
				<p class="pre">{bundle.dictation || '—'}</p>
			{/if}
		</aside>
	</div>
</div>

<style>
	.neg-proto {
		--neg-bg: #f7f7f5;
		--neg-surface: #ffffff;
		--neg-surface-hover: #f0f0ec;
		--neg-text: #1f2328;
		--neg-muted: #5f6670;
		--neg-border: #d6d8db;
		--neg-green-bg: #dcf3e2;
		--neg-green-line: #3f9a5d;
		--neg-amber-bg: #fcebc7;
		--neg-amber-line: #b7791f;
		--neg-red-line: #cf3b3b;
		--neg-grey-line: #8a9099;
		--neg-ghost: #7b828c;
		--neg-error: #b42318;
	}
	@media (prefers-color-scheme: dark) {
		:global(:root:not([data-theme='light'])) .neg-proto {
			--neg-bg: #15171a;
			--neg-surface: #1e2125;
			--neg-surface-hover: #292d32;
			--neg-text: #e6e8eb;
			--neg-muted: #a0a7b1;
			--neg-border: #3a3f46;
			--neg-green-bg: #1d3a28;
			--neg-green-line: #5cc285;
			--neg-amber-bg: #43341a;
			--neg-amber-line: #e3a94a;
			--neg-red-line: #ff7a7a;
			--neg-grey-line: #8f969f;
			--neg-ghost: #8d949e;
			--neg-error: #ff8c80;
		}
	}
	:global(:root[data-theme='dark']) .neg-proto {
		--neg-bg: #15171a;
		--neg-surface: #1e2125;
		--neg-surface-hover: #292d32;
		--neg-text: #e6e8eb;
		--neg-muted: #a0a7b1;
		--neg-border: #3a3f46;
		--neg-green-bg: #1d3a28;
		--neg-green-line: #5cc285;
		--neg-amber-bg: #43341a;
		--neg-amber-line: #e3a94a;
		--neg-red-line: #ff7a7a;
		--neg-grey-line: #8f969f;
		--neg-ghost: #8d949e;
		--neg-error: #ff8c80;
	}

	.neg-proto {
		min-height: 100vh;
		background: var(--neg-bg);
		color: var(--neg-text);
		padding: 16px;
		box-sizing: border-box;
		font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
	}
	.neg-proto.dragging {
		outline: 3px dashed var(--neg-green-line);
		outline-offset: -8px;
	}
	.top {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 12px;
	}
	h1 {
		font-size: 1.15rem;
		font-weight: 600;
		margin: 0;
	}
	.dev {
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 8px;
		border: 1px solid var(--neg-border);
		color: var(--neg-muted);
		vertical-align: 2px;
	}
	.loaders {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}
	.hint,
	.muted {
		color: var(--neg-muted);
		font-size: 0.85rem;
	}
	.btn {
		display: inline-block;
		font: inherit;
		font-size: 0.875rem;
		padding: 5px 12px;
		border-radius: 6px;
		border: 1px solid var(--neg-border);
		background: var(--neg-surface);
		color: var(--neg-text);
		cursor: pointer;
	}
	.btn:hover:not(:disabled) {
		background: var(--neg-surface-hover);
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.btn.primary {
		border-color: var(--neg-green-line);
	}
	.btn input[type='file'] {
		display: none;
	}
	.error {
		color: var(--neg-error);
		margin: 0 0 8px;
	}
	.warn {
		color: var(--neg-amber-line);
		margin: 0 0 4px;
		font-size: 0.85rem;
	}

	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 320px;
		gap: 16px;
		align-items: start;
	}
	@media (max-width: 860px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.editor-card,
	.side {
		background: var(--neg-surface);
		border: 1px solid var(--neg-border);
		border-radius: 8px;
	}
	.editor-head {
		padding: 10px 14px;
		border-bottom: 1px solid var(--neg-border);
	}
	.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0; font-size: 0.85em; }
	.seg { padding: 2px 8px; border-radius: 6px; border: 1px solid var(--neg-border); background: var(--neg-surface); color: var(--neg-text); cursor: pointer; }
	.seg.on { background: var(--neg-surface-hover); font-weight: 600; }
	.controls select { background: var(--neg-surface); color: var(--neg-text); border: 1px solid var(--neg-border); border-radius: 6px; padding: 2px 6px; }
	.legend {
		list-style: none;
		margin: 8px 0 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 14px;
		font-size: 0.8rem;
		color: var(--neg-muted);
	}
	.legend li {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		cursor: help;
	}
	.sw {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 22px;
		height: 18px;
		padding: 0 3px;
		border-radius: 3px;
		font-size: 0.75rem;
		color: var(--neg-text);
		border: 1px solid var(--neg-border);
	}
	.sw-default {
		background: var(--neg-green-bg);
		border-bottom: 2px solid var(--neg-green-line);
	}
	.sw-implicated {
		background: var(--neg-amber-bg);
		border-bottom: 2px dashed var(--neg-amber-line);
	}
	.sw-removed {
		color: var(--neg-red-line);
		text-decoration: line-through;
		text-decoration-color: var(--neg-red-line);
	}
	.sw-excluded {
		color: var(--neg-grey-line);
		text-decoration: line-through;
	}
	.sw-option {
		color: var(--neg-ghost);
		font-style: italic;
		border-style: dashed;
	}
	.editor {
		min-height: 360px;
	}
	.editor :global(.cm-editor) {
		background: var(--neg-surface);
		color: var(--neg-text);
		font-size: 15px;
		line-height: 1.65;
	}
	.editor :global(.cm-editor.cm-focused) {
		outline: none;
	}
	.editor :global(.cm-content) {
		padding: 14px 4px;
		caret-color: var(--neg-text);
	}
	.editor :global(.cm-line) {
		padding: 0 14px;
	}
	.editor :global(.cm-selectionBackground),
	.editor :global(.cm-focused .cm-selectionBackground) {
		background: color-mix(in srgb, var(--neg-text) 18%, transparent) !important;
	}
	.side {
		padding: 12px 14px;
	}
	.counts {
		margin: 0 0 10px;
		font-size: 0.9rem;
	}
	h2 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--neg-muted);
		margin: 16px 0 4px;
	}
	.pre {
		white-space: pre-wrap;
		margin: 0;
		font-size: 0.9rem;
		line-height: 1.5;
	}
</style>
