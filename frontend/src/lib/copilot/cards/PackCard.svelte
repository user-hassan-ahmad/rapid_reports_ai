<script lang="ts">
	/**
	 * A library pack card on the shared GlCard shell. Collapsed: name, version, the state badge once a preview
	 * exists, and the outcome as the hint ("on these values · …"). Opened: PackBody, read-only. Open state belongs
	 * to the session (view.open); the chevron asks for it through onOpen / onClose. A pack that does not apply dims.
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef } from '../state';
	import type { Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import { outcomeHint, setByExam, stateBadge } from './format';
	import PackBody from './PackBody.svelte';
	import { errorOf, type CardView } from './view';

	let {
		card,
		view,
		other = false,
		onOpen,
		onClose,
		onRetry
	}: {
		card: Card;
		view: CardView;
		/** Tag the card "other" (it came from Other guidelines). */
		other?: boolean;
		onOpen: (ref: string) => void;
		onClose: (ref: string) => void;
		onRetry: (ref: string) => void;
	} = $props();

	const ref = $derived(cardRef(card));
	const p = $derived(view.result?.preview ?? null);
	const err = $derived(errorOf(view));
	const showVersion = $derived(!!card.version && !card.name.includes(card.version));
	const hint = $derived(!view.open && err && err !== 'unavailable' ? "Couldn't open · open to retry" : outcomeHint(p));
</script>

{#snippet controls()}
	{#if showVersion}<span class="cp-muted cp-ver">{card.version}</span>{/if}
	{#if card.finding_id === 'exam' && setByExam(p)}<span class="cp-chip">set by the exam</span>{/if}
	{#if other}<span class="cp-chip">other</span>{/if}
{/snippet}

{#snippet body()}
	<!-- a re-open (exam card, debounced) keeps the last preview on screen instead of flickering to a skeleton -->
	<CardStatus loading={view.loading && !view.result} error={err} onRetry={() => onRetry(ref)} />
	{#if !err && view.result}
		<PackBody result={view.result} />
	{/if}
{/snippet}

<div class="cp-card" data-ref={ref}>
	<GlCard
		title={card.name}
		badge={stateBadge(p)}
		{hint}
		dim={p?.state === 'does_not_apply'}
		bind:open={() => view.open, (v) => (v ? onOpen(ref) : onClose(ref))}
		{controls}
		{body}
	/>
</div>

<style>
	.cp-ver {
		font-size: 0.6875rem;
	}
</style>
