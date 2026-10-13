<script lang="ts">
	/**
	 * A library pack card on the shared GlCard shell, judgement first (B-design, Hassan after checkpoint 3).
	 * Head, always visible: the guideline's name and the verdict pill (coloured by the outcome's action category,
	 * with an icon); below, the key values as chips and the assumed-checks cue. The card's left strip takes the
	 * category colour, so a column of cards scans by colour. Opened: PackBody (verdict, notes, source, values).
	 * Open state belongs to the session (view.open); the chevron asks for it through onOpen / onClose. A pack that
	 * does not apply dims. `headline` / `action` / `category` override the derived verdict (the planned backend
	 * fields drop in here or on the outcome itself).
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef } from '../state';
	import type { ActionCategory, Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import HeadChips from './HeadChips.svelte';
	import { assumptionsOf, categoryColor, verdictOf } from './format';
	import PackBody from './PackBody.svelte';
	import VerdictPill from './VerdictPill.svelte';
	import { errorOf, type CardView } from './view';

	let {
		card,
		view,
		other = false,
		assumptions = null,
		headline = null,
		action = null,
		category = null,
		onEdit = null,
		onCalculate = null,
		onOpen,
		onClose,
		onRetry
	}: {
		card: Card;
		view: CardView;
		/** Tag the card "other" (it came from Other guidelines). */
		other?: boolean;
		/** Eligibility checks assumed rather than asked; null derives them from the preview. */
		assumptions?: string[] | null;
		headline?: string | null;
		action?: string | null;
		category?: ActionCategory | null;
		/** Slice B2: answer or change a value; absent keeps the card read-only. */
		onEdit?: ((ref: string, input: string, value: string) => void) | null;
		/** Slice B2: Calculate over the values shown; absent hides the button. Apply is never offered. */
		onCalculate?: ((ref: string) => void) | null;
		onOpen: (ref: string) => void;
		onClose: (ref: string) => void;
		onRetry: (ref: string) => void;
	} = $props();

	const ref = $derived(cardRef(card));
	const p = $derived(view.result?.preview ?? null);
	const err = $derived(errorOf(view));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	const verdict = $derived(verdictOf(p, { headline, action, category }));
	const hint = $derived(!view.open && err && err !== 'unavailable' ? "Couldn't open · open to retry" : null);
</script>

{#snippet aside()}
	{#if verdict}<VerdictPill {verdict} />{/if}
{/snippet}

{#snippet controls()}
	{#if other}<span class="cp-chip">other</span>{/if}
{/snippet}

{#snippet meta()}
	{#if view.result}
		<HeadChips result={view.result} {assumed} checkFirst={p?.state === 'check_first'} />
	{/if}
{/snippet}

{#snippet body()}
	<!-- a re-open (exam card, debounced) keeps the last preview on screen instead of flickering to a skeleton -->
	<CardStatus loading={view.loading && !view.result} error={err} onRetry={() => onRetry(ref)} />
	{#if !err && view.result}
		<PackBody
			result={view.result}
			assumptions={assumed}
			{verdict}
			onEdit={onEdit ? (input, value) => onEdit(ref, input, value) : null}
			onCalculate={onCalculate ? () => onCalculate(ref) : null}
			calc={view.calc ?? null}
		/>
	{/if}
{/snippet}

<div class="cp-card" data-ref={ref}>
	<GlCard
		title={card.name}
		{hint}
		accent={verdict ? categoryColor(verdict.category) : null}
		dim={p?.state === 'does_not_apply'}
		roomy
		bind:open={() => view.open, (v) => (v ? onOpen(ref) : onClose(ref))}
		{aside}
		{controls}
		{meta}
		{body}
	/>
</div>
