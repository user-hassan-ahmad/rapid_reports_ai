<script lang="ts">
	/**
	 * Check (spec 2026-10-14 §4.2, §6; named by the card's "What this rests on" section): only the values the
	 * radiologist must affirm before Apply, grouped by where they came from (not dictated, probably from the
	 * dictation, worked out, set by the exam), each group one bordered block. A row is two lines: the question (muted)
	 * and the answer (bold; its basis muted after it; ↗ shows the quote). ✓ records the tick on the card (nothing is
	 * sent) and becomes "Confirmed" once ticked. A scope doubt sits first in its own amber style: Confirm sends the
	 * value as the radiologist's answer (it may then exclude). ✎ opens the input's own options. Read-only without
	 * handlers.
	 */
	import { displayValue, shownValue } from './format';
	import Icon from './Icon.svelte';
	import type { CheckItem } from './questionnaire';
	import ValueEdit from './ValueEdit.svelte';

	let {
		items,
		guideline = '',
		onTick = null,
		onEdit = null
	}: {
		items: CheckItem[];
		guideline?: string;
		onTick?: ((input: string, value: string) => void) | null;
		onEdit?: ((input: string, value: string) => void) | null;
	} = $props();
	let editing = $state<string | null>(null);
	let quoted = $state<Record<string, boolean>>({});
	const doubts = $derived(items.filter((c) => c.kind === 'doubt'));
	const GROUPS = [
		{ key: 'assumed', head: 'NOT DICTATED', has: (c: CheckItem) => c.kind === 'assumed' },
		{ key: 'dictation', head: 'PROBABLY FROM YOUR DICTATION', has: (c: CheckItem) => c.kind === 'prefilled' && !c.basis && !c.byExam },
		{ key: 'worked', head: 'WORKED OUT', has: (c: CheckItem) => c.kind === 'prefilled' && !!c.basis },
		{ key: 'exam', head: 'SET BY THE EXAM', has: (c: CheckItem) => c.kind === 'prefilled' && !c.basis && c.byExam }
	];
	const groups = $derived(GROUPS.map((g) => ({ ...g, rows: items.filter(g.has) })).filter((g) => g.rows.length));
</script>

{#snippet row(c: CheckItem)}
	<li class="cp-check-item" class:cp-check-doubt={c.kind === 'doubt'} data-testid={c.kind === 'doubt' ? 'cp-scope-doubt' : 'cp-check-item'}>
		<span class="cp-check-q">{c.label}</span>
		{#if onEdit && editing !== c.input}
			<span class="cp-check-actions">
				{#if c.kind === 'doubt'}
					{#if c.value}<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onEdit?.(c.input, c.value)}>Confirm</button>{/if}
				{:else if c.affirmed}
					<span class="cp-confirmed" data-testid="cp-confirmed">✓ Confirmed</span>
				{:else if onTick}
					<button type="button" class="rv-btn" aria-label={`Confirm ${c.label} ${shownValue(c.value)}`} onclick={() => onTick?.(c.input, c.value)}>✓</button>
				{/if}
				<button type="button" class="rv-btn cp-check-change" aria-label={`Change ${c.label}`} title={`Change ${c.label}`} onclick={() => (editing = c.input)}><Icon name="edit" size={13} /></button>
			</span>
		{/if}
		<span class="cp-check-a">
			<b class="cp-check-answer">{displayValue(c.value, c.basis)}</b>
			{#if c.basis}<span class="cp-muted"> {c.basis}</span>{/if}
			{#if c.quote}<button type="button" class="rv-btn rv-btn-ghost cp-quote-btn" aria-label={`Show the quote for ${c.label}`} aria-expanded={!!quoted[c.input]} onclick={() => (quoted[c.input] = !quoted[c.input])}>↗</button>{/if}
		</span>
		{#if c.kind === 'doubt'}<span class="cp-muted cp-check-why">would make {guideline || 'this guideline'} not apply</span>{/if}
		{#if quoted[c.input] && c.quote}<span class="cp-muted cp-check-quote" data-testid="cp-check-quote">“{c.quote}”</span>{/if}
		{#if editing === c.input && onEdit}
			<ValueEdit label={c.label} value={c.value} options={c.options} onSave={(v) => { editing = null; onEdit?.(c.input, v); }} onCancel={() => (editing = null)} />
		{/if}
	</li>
{/snippet}

{#if items.length}
	<section class="cp-check" aria-label="Check" data-testid="cp-check">
		{#if doubts.length}
			<ul class="cp-check-block cp-check-block--doubt">{#each doubts as c (c.input)}{@render row(c)}{/each}</ul>
		{/if}
		{#each groups.filter((g) => g.rows.some((c) => c.kind !== 'doubt')) as g (g.key)}
			{@const rows = g.rows.filter((c) => c.kind !== 'doubt')}
			<div class="cp-check-group" data-testid="cp-check-group">
				<div class="cp-check-sub" data-testid="cp-check-group-label">{g.head} · {rows.length}</div>
				<ul class="cp-check-block">{#each rows as c (c.input)}{@render row(c)}{/each}</ul>
			</div>
		{/each}
	</section>
{/if}

<style>
	.cp-check { display: flex; flex-direction: column; gap: 8px; font-size: 0.8125rem; }
	.cp-check-group { display: flex; flex-direction: column; gap: 3px; }
	.cp-check-sub { font-size: 0.6875rem; font-weight: 600; letter-spacing: 0.05em; color: var(--rv-muted); }
	.cp-check-block { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; border: 1px solid var(--rv-border); border-radius: 8px; overflow: hidden; }
	.cp-check-block--doubt { border-color: color-mix(in srgb, var(--rv-amber-line) 55%, transparent); background: var(--rv-amber-bg); }
	.cp-check-item { display: grid; grid-template-columns: 1fr auto; align-items: start; gap: 2px 6px; padding: 6px 8px; }
	.cp-check-item + .cp-check-item { border-top: 1px solid var(--rv-border); }
	.cp-check-q { grid-column: 1; grid-row: 1; color: var(--rv-muted); font-weight: 400; min-width: 0; overflow-wrap: anywhere; }
	.cp-check-actions { grid-column: 2; grid-row: 1 / span 2; display: flex; align-items: center; gap: 6px; }
	.cp-check-a { grid-column: 1; grid-row: 2; min-width: 0; overflow-wrap: anywhere; }
	.cp-check-answer { color: var(--rv-text); font-weight: 650; }
	.cp-check-why, .cp-check-quote { grid-column: 1 / -1; font-size: 0.75rem; }
	.cp-check-quote { font-style: italic; }
	.cp-check-item > :global(:not(.cp-check-q):not(.cp-check-actions):not(.cp-check-a):not(.cp-check-why):not(.cp-check-quote)) { grid-column: 1 / -1; }
	.cp-confirmed { font-size: 0.75rem; color: var(--rv-muted); white-space: nowrap; }
	.cp-quote-btn { padding: 0 6px; }
</style>
