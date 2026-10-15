<script lang="ts">
	/** The entry's reference fields (summary, definitions, tables, pitfalls), each with its citation, collapsed
	 *  under "Reference". `open` starts it expanded (a tier 2 card has nothing else to show). */
	import { untrack } from 'svelte';
	import type { ReferenceView } from '../types';
	import { citeText } from './format';

	let { reference, open = false }: { reference: ReferenceView; open?: boolean } = $props();
	let shown = $state(untrack(() => open));
	const texts = $derived([
		{ label: 'Summary', items: reference.summary },
		{ label: 'Definitions', items: reference.definitions },
		{ label: 'Pitfalls', items: reference.pitfalls }
	]);
	const empty = $derived(!texts.some((t) => t.items.length) && !reference.tables.length);
</script>

{#if !empty}
	<div class="cp-ref">
		<button type="button" class="rv-btn rv-btn-ghost cp-ref-toggle" aria-expanded={shown} onclick={() => (shown = !shown)}
			>Reference</button
		>
		{#if shown}
			<div class="cp-ref-body">
				{#each texts.slice(0, 2) as t (t.label)}
					{#if t.items.length}
						<div class="cp-label">{t.label}</div>
						<ul class="cp-list">
							{#each t.items as it (it.id)}
								<li>{it.text} {#if citeText(it.citation)}<span class="cp-muted cp-ref-cite">({citeText(it.citation)})</span>{/if}</li>
							{/each}
						</ul>
					{/if}
				{/each}
				{#each reference.tables as tb (tb.id)}
					<div class="cp-label">{tb.title}</div>
					<div class="cp-ref-table-wrap">
						<table class="cp-ref-table">
							<thead><tr>{#each tb.columns as c, i (i)}<th>{c}</th>{/each}</tr></thead>
							<tbody>
								{#each tb.rows as r, ri (ri)}
									<tr>{#each r as cell, ci (ci)}<td>{cell}</td>{/each}</tr>
								{/each}
							</tbody>
						</table>
					</div>
					{#if citeText(tb.citation)}<div class="cp-muted cp-ref-cite">{citeText(tb.citation)}</div>{/if}
				{/each}
				{#if texts[2].items.length}
					<div class="cp-label">{texts[2].label}</div>
					<ul class="cp-list">
						{#each texts[2].items as it (it.id)}
							<li>{it.text} {#if citeText(it.citation)}<span class="cp-muted cp-ref-cite">({citeText(it.citation)})</span>{/if}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.cp-ref-toggle {
		font-size: 0.75rem;
	}
	.cp-ref-body {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-top: 6px;
		font-size: 0.75rem;
		max-height: 16rem;
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.cp-ref-cite {
		font-size: 0.6875rem;
	}
	.cp-ref-table-wrap {
		overflow-x: auto;
	}
	.cp-ref-table {
		border-collapse: collapse;
		font-size: 0.6875rem;
		width: 100%;
	}
	.cp-ref-table th,
	.cp-ref-table td {
		border: 1px solid var(--rv-border);
		padding: 2px 5px;
		text-align: left;
		vertical-align: top;
	}
</style>
