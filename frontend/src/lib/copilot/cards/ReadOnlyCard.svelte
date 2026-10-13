<script lang="ts">
	/**
	 * Cards that never take inputs, Calculate or Apply:
	 * - needs_modality: one static line, "<name> needs <modality> to grade"; no chevron and never opened (/open is
	 *   not called: the server would refuse to settle it anyway);
	 * - reference (tier 2): opens to the Reference only;
	 * - tnm: opens to the entry summary and its branch criteria as text;
	 * - other (Other guidelines): opens to the entry; "Not in the guideline library yet" when it cannot.
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef, modalityLabel } from '../state';
	import type { Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import Reference from './Reference.svelte';
	import { errorOf, type CardView } from './view';

	let {
		card,
		kind,
		view,
		other = false,
		onOpen,
		onClose,
		onRetry
	}: {
		card: Card;
		kind: 'needs_modality' | 'reference' | 'tnm' | 'other';
		view: CardView;
		other?: boolean;
		onOpen: (ref: string) => void;
		onClose: (ref: string) => void;
		onRetry: (ref: string) => void;
	} = $props();

	const ref = $derived(cardRef(card));
	const err = $derived(errorOf(view));
	const entry = $derived(view.result?.entry ?? null);
	const hint = $derived(kind === 'reference' ? 'reference' : kind === 'tnm' ? 'staging criteria' : null);
</script>

{#snippet controls()}
	{#if other}<span class="cp-chip">other</span>{/if}
{/snippet}

{#snippet body()}
	<CardStatus loading={view.loading} error={err} onRetry={() => onRetry(ref)} />
	{#if !view.loading && !err && view.result}
		{#if kind === 'reference'}
			{#if view.result.reference}<Reference reference={view.result.reference} open />{/if}
		{:else}
			{#if entry?.content.summary}<p class="cp-p">{entry.content.summary}</p>{/if}
			{#if kind === 'tnm'}
				{#each entry?.content.branches ?? [] as b (b.name)}
					<div class="cp-label">{b.name}</div>
					<ul class="cp-list cp-criteria">
						{#each b.inputs as i (i.id)}
							<li>{i.question}{#if i.options.length}: <span class="cp-muted">{i.options.join(', ')}</span>{/if}</li>
						{/each}
					</ul>
				{/each}
			{:else}
				{#if entry?.sources.length}
					<ul class="cp-cites">
						{#each entry.sources as s (s.url)}<li>{s.title || s.url}</li>{/each}
					</ul>
				{/if}
				{#if view.result.reference}<Reference reference={view.result.reference} />{/if}
			{/if}
		{/if}
	{/if}
{/snippet}

{#if kind === 'needs_modality'}
	<div class="cp-card cp-needs" data-ref={ref} data-testid="cp-needs-modality">
		<span class="cp-needs-name">{card.name}</span>
		<span class="cp-muted">needs {modalityLabel(card.needs_modality)} to grade</span>
		{#if other}<span class="cp-chip">other</span>{/if}
	</div>
{:else}
	<div class="cp-card" data-ref={ref}>
		<GlCard
			title={card.name}
			{hint}
			roomy
			bind:open={() => view.open, (v) => (v ? onOpen(ref) : onClose(ref))}
			{controls}
			{body}
		/>
	</div>
{/if}

<style>
	.cp-needs {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 6px;
		padding: 10px 13px 10px 14px;
		border-left: 3px solid var(--rv-border-strong);
		border-radius: 6px;
		background: var(--rv-surface);
		font-size: 0.8125rem;
	}
	.cp-needs-name {
		font-weight: 600;
	}
	.cp-p {
		margin: 0;
	}
	.cp-criteria {
		font-size: 0.75rem;
	}
</style>
