<script lang="ts">
	/**
	 * A guideline that is not applied, collapsed to one row under its head ("{name} · Not applied"): the fact in plain
	 * words with where it came from (↗ shows the quote), one sentence on what the report will and won't contain, and two
	 * answers named by what they do: Correct (an answer: the value stands, onEdit) or the other value, applying the
	 * guideline. "Show details" opens today's full body.
	 */
	import Icon from './Icon.svelte';
	import type { CollapsedReason } from './questionnaire';
	import ValueEdit from './ValueEdit.svelte';

	let {
		reason,
		guideline = '',
		onConfirm = null,
		onToggle,
		controls = undefined
	}: {
		reason: CollapsedReason;
		guideline?: string;
		onConfirm?: ((input: string, value: string) => void) | null;
		onToggle: () => void;
		controls?: string;
	} = $props();
	let changing = $state(false);
	let showQuote = $state(false);
	const name = $derived(guideline || 'this guideline');
	const alt = $derived(reason.other && reason.other.kind !== 'choose' ? reason.other : null);
</script>

<div class="cp-collapsed" data-testid="cp-collapsed">
	<div class="cp-fact">
		<span class="cp-fact-text"><b>{reason.fact}</b></span>
		{#if reason.source}
			<span class="cp-fact-source cp-muted" data-testid="cp-fact-source">{reason.source}{#if reason.quote}<button type="button" class="rv-btn rv-btn-ghost cp-quote-btn" aria-label="Show the quote" aria-expanded={showQuote} onclick={() => (showQuote = !showQuote)}>↗</button>{/if}</span>
		{/if}
	</div>
	{#if showQuote && reason.quote}<p class="cp-p cp-muted cp-fact-quote" data-testid="cp-fact-quote">“{reason.quote}”</p>{/if}
	<p class="cp-p cp-collapsed-then">{name} doesn't cover this, so its recommendation won't be added.</p>
	{#if reason.kind === 'doubt' && changing && onConfirm}
		<ValueEdit label={reason.label} value={reason.value} options={reason.options} onSave={(v) => { changing = false; onConfirm?.(reason.input, v); }} onCancel={() => (changing = false)} />
	{/if}
	<span class="cp-collapsed-actions">
		{#if reason.kind === 'doubt' && onConfirm && !changing}
			{#if reason.value}<button type="button" class="rv-btn rv-btn-primary" onclick={() => onConfirm?.(reason.input, reason.value)}>Correct</button>{/if}
			{#if alt && alt.kind === 'boolean'}
				<button type="button" class="rv-btn" onclick={() => onConfirm?.(reason.input, alt.value)}>That's not right — apply {name}</button>
			{:else if alt}
				<button type="button" class="rv-btn" onclick={() => onConfirm?.(reason.input, alt.value)}>{alt.label} — apply {name}</button>
			{:else if reason.other}
				<button type="button" class="rv-btn" onclick={() => (changing = true)}>Choose another value — apply {name}</button>
			{/if}
		{/if}
		{#if reason.kind === 'doubt' && reason.more > 0}
			<button type="button" class="rv-btn rv-btn-ghost" aria-expanded="false" aria-controls={controls} onclick={onToggle}>+{reason.more} more</button>
		{/if}
		<button type="button" class="rv-btn rv-btn-ghost" aria-expanded="false" aria-controls={controls} onclick={onToggle}>Show details<span class="cp-caret"><Icon name="chev" size={11} /></span></button>
	</span>
</div>

<style>
	.cp-collapsed { display: flex; flex-direction: column; gap: 4px; font-size: 0.8125rem; }
	.cp-collapsed :global(.cp-p) { margin: 0; }
	.cp-fact { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 2px 8px; }
	.cp-fact-source { display: inline-flex; align-items: center; gap: 4px; font-size: 0.75rem; }
	.cp-quote-btn { padding: 0 6px; }
	.cp-fact-quote { font-style: italic; font-size: 0.75rem; }
	.cp-collapsed-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 4px; }
	.cp-caret { display: inline-block; margin-left: 2px; }
</style>
