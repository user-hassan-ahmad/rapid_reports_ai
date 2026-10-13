<script lang="ts">
	/**
	 * A finding with sibling packs (other bodies' guidelines on the same topic, §7.1): one GlCard whose body holds
	 * two (at most three) equal columns, the primary card's first, neither preselected. A column shows the outcome
	 * only; its title expands it to the full body at full width (plan Q5). Narrower than 300 px the columns stack
	 * behind a switcher, again with nothing chosen until the radiologist picks.
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef } from '../state';
	import type { Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import { columnRef, columnTitles } from './format';
	import PackBody from './PackBody.svelte';
	import { closedView, errorOf, type CardView, type ColumnView } from './view';

	let {
		card,
		view,
		other = false,
		layout = 'auto',
		onOpen,
		onClose,
		onRetry
	}: {
		card: Card;
		view: CardView;
		other?: boolean;
		/** `auto` stacks when the card (the list's width) is under 300 px; tests and the gallery can pin it. */
		layout?: 'auto' | 'columns' | 'stacked';
		onOpen: (ref: string) => void;
		onClose: (ref: string) => void;
		/** Called with columnRef(card, key) (`<cardRef>#<pack key>`), so one failed column is retried. */
		onRetry: (ref: string) => void;
	} = $props();

	const ref = $derived(cardRef(card));
	const colView = (key: string): ColumnView =>
		view.columns?.[key] ?? (key === card.key ? view : { ...closedView, loading: view.loading });
	const cols = $derived(
		columnTitles(card, Object.fromEntries(Object.entries(view.columns ?? {}).map(([k, c]) => [k, c.result])))
	);
	let width = $state(0);
	let chosen = $state<string | null>(null);
	const stacked = $derived(layout === 'stacked' || (layout === 'auto' && width > 0 && width < 300));
	const shown = $derived(chosen ? cols.filter((c) => c.key === chosen) : stacked ? [] : cols);
</script>

{#snippet column(c: { key: string; title: string }, full: boolean)}
	{@const cv = colView(c.key)}
	{@const err = errorOf(cv)}
	<div class="cp-col" data-key={c.key}>
		{#if !stacked}
			<button
				type="button"
				class="cp-col-head"
				aria-pressed={chosen === c.key}
				title={chosen === c.key ? 'Back to both' : 'Show this one in full'}
				onclick={() => (chosen = chosen === c.key ? null : c.key)}>{c.title}</button
			>
		{/if}
		<CardStatus loading={cv.loading} error={err} onRetry={() => onRetry(columnRef(card, c.key))} />
		{#if !cv.loading && !err && cv.result}
			<PackBody result={cv.result} compact={!full} />
		{/if}
	</div>
{/snippet}

{#snippet body()}
	<div class="cp-sib">
		{#if stacked}
			<div class="cp-switch" role="tablist" aria-label="Guidelines on this finding">
				{#each cols as c (c.key)}
					<button type="button" role="tab" aria-selected={chosen === c.key} onclick={() => (chosen = c.key)}
						>{c.title}</button
					>
				{/each}
			</div>
			{#if !chosen}<p class="cp-muted cp-pick">Choose a guideline to read</p>{/if}
		{/if}
		<div class="cp-cols" style="--cp-cols: {shown.length || 1}" data-testid="cp-columns">
			{#each shown as c (c.key)}
				{@render column(c, !!chosen)}
			{/each}
		</div>
	</div>
{/snippet}

{#snippet controls()}
	{#if other}<span class="cp-chip">other</span>{/if}
{/snippet}

<div class="cp-card" data-ref={ref} bind:clientWidth={width}>
	<GlCard
		title={cols.map((c) => c.title).join(' · ')}
		hint={`${cols.length} guidelines on this finding`}
		bind:open={() => view.open, (v) => (v ? onOpen(ref) : onClose(ref))}
		{controls}
		{body}
	/>
</div>

<style>
	.cp-cols {
		display: grid;
		grid-template-columns: repeat(var(--cp-cols), minmax(0, 1fr));
		gap: 8px;
	}
	.cp-col {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.cp-col + .cp-col {
		border-left: 1px solid var(--rv-border);
		padding-left: 8px;
	}
	.cp-col-head {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 600;
		text-align: left;
		padding: 0;
		background: none;
		border: 0;
		color: var(--rv-text);
		cursor: pointer;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-col-head:hover {
		color: var(--rv-accent-hover);
	}
	.cp-switch {
		display: flex;
		gap: 2px;
		padding: 2px;
		border-radius: 0.5rem;
		background: var(--rv-segment);
		margin-bottom: 6px;
	}
	.cp-switch [role='tab'] {
		flex: 1;
		font: inherit;
		font-size: 0.75rem;
		background: none;
		border: 0;
		border-radius: 0.375rem;
		padding: 3px 6px;
		color: var(--rv-muted);
		cursor: pointer;
	}
	.cp-switch [role='tab'][aria-selected='true'] {
		background: var(--rv-accent);
		color: #fff;
	}
	.cp-pick {
		margin: 0;
		font-size: 0.75rem;
	}
</style>
