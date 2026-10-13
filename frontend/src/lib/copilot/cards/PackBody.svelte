<script lang="ts">
	/**
	 * An opened pack card's body, read-only (Slice A), in reading order (B0, Hassan 2026-10-13):
	 * 1. the values (ValueRow: read plain, pre-filled amber-soft with its reasons, exam presets, answered, N/A; the
	 *    quote on hover or focus); from Task 3's draft, else (pre-Task 3) preview.settled;
	 * 2. the outcome and recommendation "on these values", then the remaining open questions that are not eligibility
	 *    checks, quieter; with no outcome, the open questions and then one collapsed line "N outcomes still possible"
	 *    (the full list was long and noisy, polish 2026-10-13; Task 3 will send one draft outcome instead);
	 * then the eligibility checks the card assumed (collapsed: never the lead), the degraded note and the reference.
	 * `does_not_apply` leads with its reason. `compact` (a sibling column) drops caveats, citations, the assumed list
	 * and the reference. No inputs, Calculate or Apply.
	 */
	import { outcomeOf } from '../state';
	import type { Citation, OpenResult } from '../types';
	import { assumptionsOf, citeText, openQuestions, valueRows } from './format';
	import Reference from './Reference.svelte';
	import ValueRow from './ValueRow.svelte';

	let {
		result,
		compact = false,
		assumptions = null
	}: {
		result: OpenResult;
		compact?: boolean;
		/** The assumed eligibility checks; null derives them (assumptionsOf). B1 feeds Task 3's list here. */
		assumptions?: string[] | null;
	} = $props();
	const p = $derived(result.preview);
	const out = $derived(outcomeOf(p));
	const rows = $derived(valueRows(result));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	const questions = $derived(p ? openQuestions(p) : []);
	let showAssumed = $state(false);
	let showPossible = $state(false);
	const uid = $props.id(); // ids for aria-controls / aria-describedby
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
	{:else}
		{#if p.state === 'does_not_apply'}
			<div class="cp-label">Does not apply</div>
			{#if p.exclusion}
				<p class="cp-p" data-testid="cp-exclusion">{p.exclusion.classification}</p>
				{@render cites(p.exclusion.citations)}
			{/if}
		{/if}
		{#if rows.length}
			<section class="cp-values" aria-label="Values">
				<div class="cp-label">Values</div>
				<ul class="cp-val-list">
					{#each rows as r (r.input)}
						<ValueRow row={r} {uid} />
					{/each}
				</ul>
			</section>
		{/if}
		{#if p.state !== 'does_not_apply'}
			{#if out}
				<section class="cp-outcome-block">
					<div class="cp-label">On these values</div>
					<p class="cp-p cp-outcome">{out.classification}</p>
					{#if out.recommendation}<p class="cp-p cp-rec">{out.recommendation}</p>{/if}
					{#if !compact && out.caveats.length}
						<ul class="cp-list cp-caveats">
							{#each out.caveats as c, i (i)}<li>{c}</li>{/each}
						</ul>
					{/if}
					{@render cites(out.citations)}
				</section>
			{/if}
			{#if questions.length}
				<section class="cp-open-q" aria-label="Still open">
					<div class="cp-label">Still open</div>
					<ul class="cp-list">
						{#each questions as q, i (i)}<li>{q}</li>{/each}
					</ul>
				</section>
			{/if}
			{#if !out && p.possible.length === 1}
				<section>
					<div class="cp-label">Possible:</div>
					<p class="cp-p">{p.possible[0]}</p>
				</section>
			{:else if !out && p.possible.length > 1}
				<section class="cp-possible">
					<button
						type="button"
						class="cp-link cp-possible-toggle"
						aria-expanded={showPossible}
						aria-controls="{uid}-possible"
						onclick={() => (showPossible = !showPossible)}
						>{p.possible.length} outcomes still possible — {showPossible ? 'hide' : 'show'}</button
					>
					<ul class="cp-list cp-possible-list" id="{uid}-possible" hidden={!showPossible}>
						{#each p.possible as o, i (i)}<li>{o}</li>{/each}
					</ul>
				</section>
			{/if}
		{/if}
		{#if assumed.length && !compact}
			<div class="cp-assumed">
				<button
					type="button"
					class="cp-link cp-assumed-toggle"
					aria-expanded={showAssumed}
					aria-controls="{uid}-assumed"
					onclick={() => (showAssumed = !showAssumed)}
					>⚠ Assumed eligible: {assumed.length} {assumed.length === 1 ? 'check' : 'checks'}</button
				>
				<ul class="cp-list cp-assumed-list" id="{uid}-assumed" hidden={!showAssumed}>
					{#each assumed as a, i (i)}<li>{a}</li>{/each}
				</ul>
			</div>
		{/if}
		{#if p.degraded}
			<p class="cp-p cp-muted cp-degraded">Some values could not be checked</p>
		{/if}
	{/if}
	{#if !compact && result.reference}
		<Reference reference={result.reference} />
	{/if}
</div>

<style>
	.cp-pack-body {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
	}
	.cp-pack-body section {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.cp-p {
		margin: 0;
	}
	.cp-val-list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.cp-outcome {
		font-size: 0.9375rem;
		font-weight: 650;
		line-height: 1.35;
	}
	.cp-open-q {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-possible-toggle,
	.cp-assumed-toggle {
		align-self: flex-start;
		text-align: left;
	}
	.cp-possible-toggle {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-possible-list {
		margin-top: 4px;
		font-size: 0.8125rem;
	}
	.cp-assumed-toggle {
		font-size: 0.8125rem;
		color: var(--rv-amber-line);
		text-decoration: none;
	}
	.cp-assumed-list {
		margin-top: 4px;
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-compact {
		font-size: 0.8125rem;
	}
	.cp-degraded {
		font-size: 0.8125rem;
		font-style: italic;
	}
</style>
