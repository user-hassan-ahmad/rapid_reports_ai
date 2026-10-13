<script lang="ts">
	/**
	 * A finding with sibling packs (other bodies' guidelines on the same topic, §7.1): one GlCard whose body holds
	 * two (at most three) equal columns, the primary card's first, neither preselected. A column shows the outcome
	 * only; its title expands it to the full body at full width (plan Q5). Unless each column gets ~200 px (B0) they
	 * stack: every guideline at full width, one under the other, each with its own line (name, state chip) above its
	 * values and outcome; no switcher and nothing chosen (controller ruling 2026-10-13).
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef } from '../state';
	import type { Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import { assumptionsOf, columnRef, columnTitles, stateBadge } from './format';
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
		/** `auto` stacks unless each column gets MIN_COLUMN_PX of the card's width; tests and the gallery can pin it. */
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
	// Two readable columns need ~200 px each (B0, Hassan 2026-10-13); the 420 px rail's cards (~394 px, ~360 px of
	// body after the card's padding) are under that for two, so they stack there and sit side by side only when wider.
	const MIN_COLUMN_PX = 200;
	const CARD_CHROME_PX = 34; // the GlCard body's left and right padding
	const stacked = $derived(layout === 'stacked' || (layout === 'auto' && width > 0 && (width - CARD_CHROME_PX) / cols.length < MIN_COLUMN_PX));
	// stacked: every guideline at full width, one under the other, none chosen (§7.1); columns: a title expands one
	const shown = $derived(!stacked && chosen ? cols.filter((c) => c.key === chosen) : cols);
</script>

{#snippet column(c: { key: string; title: string }, full: boolean)}
	{@const cv = colView(c.key)}
	{@const err = errorOf(cv)}
	<div class="cp-col" class:cp-col--stacked={stacked} data-key={c.key}>
		{#if stacked}
			{@const p = cv.result?.preview ?? null}
			{@const badge = stateBadge(p)}
			{@const assumed = assumptionsOf(p)}
			<div class="cp-col-line">
				<span class="cp-col-name">{c.title}</span>
				{#if assumed.length}
					<span class="cp-chip cp-chip-warn" title={`Assumed eligible:\n${assumed.join('\n')}`}
						>⚠ {assumed.length} {assumed.length === 1 ? 'check' : 'checks'} assumed</span
					>
				{:else if badge}
					<span class="cp-chip">{badge.text}</span>
				{/if}
			</div>
		{:else}
			<button
				type="button"
				class="cp-col-head"
				aria-pressed={chosen === c.key}
				title={chosen === c.key ? 'Back to both' : 'Show this one in full'}
				onclick={() => (chosen = chosen === c.key ? null : c.key)}>{c.title}</button
			>
		{/if}
		<CardStatus loading={cv.loading && !cv.result} error={err} onRetry={() => onRetry(columnRef(card, c.key))} />
		{#if !err && cv.result}
			<PackBody result={cv.result} compact={!full && !stacked} />
		{/if}
	</div>
{/snippet}

{#snippet body()}
	<div class="cp-sib">
		<div class="cp-cols" class:cp-cols--stacked={stacked} style="--cp-cols: {stacked ? 1 : shown.length || 1}" data-testid="cp-columns">
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
		roomy
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
	.cp-cols--stacked {
		gap: 14px;
	}
	.cp-col--stacked + .cp-col--stacked {
		border-left: 0;
		padding-left: 0;
		padding-top: 12px;
		border-top: 1px solid var(--rv-border);
	}
	.cp-col-line {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 2px;
	}
	.cp-col-name {
		font-weight: 600;
		min-width: 0;
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
</style>
