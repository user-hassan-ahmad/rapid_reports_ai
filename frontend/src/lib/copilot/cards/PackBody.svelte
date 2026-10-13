<script lang="ts">
	/**
	 * An opened pack card's body, read-only (Slice A), in reading order (B0, Hassan 2026-10-13):
	 * 1. the values read from the dictation (label and value; the quote on hover or focus; "set by the exam");
	 * 2. the outcome and recommendation "on these values" (or the outcomes still possible);
	 * 3. the remaining open questions that are not eligibility checks, quieter;
	 * then the eligibility checks the card assumed (collapsed: never the lead), the degraded note and the reference.
	 * `does_not_apply` leads with its reason. `compact` (a sibling column) drops caveats, citations, the assumed list
	 * and the reference. No inputs, Calculate or Apply.
	 */
	import { outcomeOf } from '../state';
	import type { Citation, OpenResult } from '../types';
	import { assumptionsOf, citeText, openQuestions, valueRows } from './format';
	import Reference from './Reference.svelte';

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
			<section class="cp-values" aria-label="Read from the report">
				<div class="cp-label">Read from the report</div>
				<ul class="cp-val-list">
					{#each rows as r (r.input)}
						<!-- focusable so the quote shows for keyboard users too -->
						<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
						<li class="cp-val" tabindex={r.quote ? 0 : undefined} title={r.quote ? `“${r.quote}”` : undefined}>
							<span class="cp-val-label">{r.label}</span>
							<span class="cp-val-value"
								><b>{r.value}</b>{#if r.byExam}<span class="cp-chip cp-val-chip">set by the exam</span>{/if}</span
							>
							{#if r.quote}<span class="cp-quote">“{r.quote}”</span>{/if}
						</li>
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
			{:else if p.possible.length}
				<section>
					<div class="cp-label">Possible:</div>
					<ul class="cp-list">
						{#each p.possible as o, i (i)}<li>{o}</li>{/each}
					</ul>
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
		{/if}
		{#if assumed.length && !compact}
			<div class="cp-assumed">
				<button type="button" class="cp-link cp-assumed-toggle" aria-expanded={showAssumed} onclick={() => (showAssumed = !showAssumed)}
					>⚠ Assumed eligible: {assumed.length} {assumed.length === 1 ? 'check' : 'checks'}</button
				>
				{#if showAssumed}
					<ul class="cp-list cp-assumed-list">
						{#each assumed as a, i (i)}<li>{a}</li>{/each}
					</ul>
				{/if}
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
	.cp-val {
		position: relative;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 2px 8px;
		padding: 2px 6px;
		margin: 0 -6px;
		border-radius: 4px;
	}
	.cp-val[tabindex]:hover,
	.cp-val[tabindex]:focus {
		background: var(--rv-surface-hover);
		outline: none;
	}
	.cp-val[tabindex]:focus-visible {
		box-shadow: 0 0 0 2px var(--rv-focus);
	}
	.cp-val-label {
		flex: 0 0 44%; /* one column of labels, long ones wrap */
		color: var(--rv-muted);
	}
	.cp-val-value {
		flex: 1;
		min-width: 0;
		font-variant-numeric: tabular-nums;
	}
	.cp-val-value b {
		font-weight: 600;
	}
	.cp-val-chip {
		display: inline-block;
		margin-left: 6px;
		vertical-align: 1px;
	}
	/* a bubble under the row, out of the flow: revealing it never moves what is below (or under the pointer) */
	.cp-quote {
		display: none;
		position: absolute;
		left: 0;
		right: 0;
		top: 100%;
		z-index: 5;
		margin-top: 2px;
		padding: 5px 8px;
		border-radius: 6px;
		border: 1px solid var(--rv-border-strong);
		background: var(--rv-overlay);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
		font-size: 0.8125rem;
		font-style: italic;
		color: var(--rv-text);
		pointer-events: none;
	}
	.cp-val:hover .cp-quote,
	.cp-val:focus .cp-quote {
		display: block;
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
	.cp-compact .cp-val-label {
		flex-basis: 100%;
	}
	.cp-degraded {
		font-size: 0.8125rem;
		font-style: italic;
	}
</style>
