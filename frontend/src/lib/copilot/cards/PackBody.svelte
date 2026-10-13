<script lang="ts">
	/**
	 * An opened pack card's body, read-only (Slice A): the state's copy, the reached outcome labelled "on these
	 * values", and the reference. No inputs, Calculate or Apply. `compact` (a sibling column) keeps the outcome
	 * line only: no caveats, citations or reference.
	 */
	import { outcomeOf } from '../state';
	import type { Citation, OpenResult } from '../types';
	import { citeText, missingLabels } from './format';
	import Reference from './Reference.svelte';

	let { result, compact = false }: { result: OpenResult; compact?: boolean } = $props();
	const p = $derived(result.preview);
	const out = $derived(outcomeOf(p));
</script>

{#snippet cites(list: Citation[])}
	{#if !compact && list.some((c) => citeText(c))}
		<ul class="cp-cites">
			{#each list.filter((c) => citeText(c)) as c, i (i)}<li>{citeText(c)}</li>{/each}
		</ul>
	{/if}
{/snippet}

<div class="cp-pack-body" class:cp-compact={compact}>
	{#if !p}
		{#if result.entry?.content.summary}<p class="cp-p">{result.entry.content.summary}</p>{/if}
	{:else if p.state === 'does_not_apply'}
		<div class="cp-label">Does not apply</div>
		{#if p.exclusion}
			<p class="cp-p" data-testid="cp-exclusion">{p.exclusion.classification}</p>
			{@render cites(p.exclusion.citations)}
		{/if}
	{:else if p.state === 'check_first'}
		<p class="cp-p">Some eligibility questions need an answer before this applies</p>
		{#if p.missing.length}
			<ul class="cp-list cp-asks">
				{#each missingLabels(p) as label, i (i)}<li>{label}</li>{/each}
			</ul>
		{/if}
	{:else if out}
		<div class="cp-label">On these values</div>
		<p class="cp-p cp-outcome">{out.classification}</p>
		{#if out.recommendation}<p class="cp-p">{out.recommendation}</p>{/if}
		{#if !compact && out.caveats.length}
			<ul class="cp-list cp-caveats">
				{#each out.caveats as c, i (i)}<li>{c}</li>{/each}
			</ul>
		{/if}
		{@render cites(out.citations)}
	{:else if p.possible.length}
		<div class="cp-label">Possible:</div>
		<ul class="cp-list">
			{#each p.possible as o, i (i)}<li>{o}</li>{/each}
		</ul>
	{/if}
	{#if p?.degraded}
		<p class="cp-p cp-muted cp-degraded">Some values could not be checked</p>
	{/if}
	{#if !compact && result.reference}
		<Reference reference={result.reference} />
	{/if}
</div>

<style>
	.cp-pack-body {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.cp-p {
		margin: 0;
	}
	.cp-outcome {
		font-weight: 600;
	}
	.cp-compact {
		font-size: 0.75rem;
	}
	.cp-degraded {
		font-size: 0.75rem;
		font-style: italic;
	}
</style>
