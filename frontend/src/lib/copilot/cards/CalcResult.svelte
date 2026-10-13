<script lang="ts">
	/**
	 * A Calculate result (Slice B2, §7.7), read-only: nothing is applied (Apply stays off). It reads as the engine's
	 * answer over exactly the values sent:
	 * - an outcome: its classification, recommendation, notes and source, then each value used with its state;
	 * - an exclusion: "Does not apply" with the reason;
	 * - no outcome: the outcomes still possible and what is still needed.
	 * Values sent back at their assumed value stay assumptions (confirmed at Apply, not by Calculate): they are
	 * marked, and counted in a warning line.
	 */
	import type { DraftValue } from '../types';
	import Icon from './Icon.svelte';
	import { actionOf, headlineOf, sourcesOf } from './format';
	import type { CalcView } from './view';

	let { calc, labels = {} }: { calc: CalcView; labels?: Record<string, string> } = $props();
	const c = $derived(calc.result);
	const out = $derived(c?.result ?? null);
	const src = $derived(sourcesOf(out?.citations ?? c?.exclusion?.citations ?? []));
	const assumed = $derived(new Set(c?.assumptions ?? []));
	const label = (id: string) => labels[id] || c?.values.find((v) => v.input === id)?.label || id;
	const used = $derived((c?.values ?? []).filter((v) => v.value && v.state !== 'not_applicable'));
	const stateWord = (v: DraftValue) =>
		assumed.has(v.input) || v.state === 'assumed' ? 'assumed' : ({ read: 'read', prefilled: 'pre-filled', answered: 'answered', edited: 'changed' } as Record<string, string>)[v.state] ?? '';
</script>

<section class="cp-calc" aria-label="Calculated" aria-live="polite" aria-busy={calc.loading}>
	{#if calc.loading}
		<div class="cp-skel-line" data-testid="cp-calc-loading" aria-label="Calculating"></div>
	{:else if calc.error}
		<p class="cp-p cp-muted cp-calc-error" role="status">
			{calc.error === 'not a pack' || calc.error === 'needs modality' ? 'This guideline cannot be calculated here' : "Couldn't calculate"} · press Calculate to try again
		</p>
	{:else if c}
		<p class="cp-p cp-calc-caption">Calculated on these values</p>
		{#if out}
			<p class="cp-p cp-calc-headline">{out.headline ?? headlineOf(out.classification)}</p>
			{#if out.action ?? actionOf(out.recommendation)}
				<p class="cp-p cp-calc-action"><Icon name="check" size={13} /> {out.action ?? actionOf(out.recommendation)}</p>
			{/if}
			<p class="cp-p cp-calc-cls">{out.classification}</p>
			{#if out.caveats.length}<p class="cp-p cp-muted cp-calc-meta">{out.caveats.length} {out.caveats.length === 1 ? 'note' : 'notes'} on the card above</p>{/if}
		{:else if c.exclusion}
			<p class="cp-p cp-calc-headline"><Icon name="slash" size={13} /> Does not apply</p>
			<p class="cp-p cp-calc-cls">{c.exclusion.classification}</p>
		{:else}
			<p class="cp-p cp-calc-headline">Not enough to decide</p>
			{#if c.needed.length}
				<p class="cp-p cp-calc-cls">Still needed: {c.needed.map(label).join(', ')}</p>
			{/if}
			{#if c.possible.length}
				<p class="cp-p cp-muted cp-calc-meta">{c.possible.length} {c.possible.length === 1 ? 'outcome' : 'outcomes'} possible: {c.possible.join('; ')}</p>
			{/if}
		{/if}
		{#if src.short}<p class="cp-p cp-muted cp-calc-meta">{src.short}{#if src.more}{` +${src.more}`}{/if}</p>{/if}
		{#if assumed.size}
			<p class="cp-p cp-calc-assumed">
				<Icon name="warn" size={12} /> {assumed.size} {assumed.size === 1 ? 'value is' : 'values are'} still assumed ({[...assumed].map(label).join(', ')}): confirmed only at Apply
			</p>
		{/if}
		{#if used.length}
			<ul class="cp-calc-values" aria-label="Values used">
				{#each used as v (v.input)}
					<li class:cp-calc-assumed-row={stateWord(v) === 'assumed'}>
						<span class="cp-muted">{v.label}</span>
						<b>{v.value}</b>
						{#if stateWord(v)}<span class="cp-chip">{stateWord(v)}</span>{/if}
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</section>

<style>
	.cp-calc {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 10px 12px;
		border-radius: 8px;
		border: 1px solid var(--rv-border);
		background: var(--rv-surface-hover);
	}
	.cp-p {
		margin: 0;
	}
	.cp-calc-caption {
		font-size: 0.6875rem;
		color: var(--rv-muted);
	}
	.cp-calc-headline {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 0.9375rem;
		font-weight: 650;
	}
	.cp-calc-action {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 600;
		font-size: 0.875rem;
	}
	.cp-calc-cls {
		font-size: 0.8125rem;
		color: var(--rv-muted);
	}
	.cp-calc-meta,
	.cp-calc-error {
		font-size: 0.75rem;
	}
	.cp-calc-assumed {
		display: flex;
		align-items: flex-start;
		gap: 5px;
		font-size: 0.8125rem;
		color: var(--rv-amber-text);
	}
	.cp-calc-values {
		margin: 4px 0 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 0.8125rem;
	}
	.cp-calc-values li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 8px;
	}
	.cp-calc-values b {
		font-weight: 600;
	}
	.cp-calc-assumed-row .cp-chip {
		color: var(--rv-amber-text);
		border-style: dashed;
	}
</style>
