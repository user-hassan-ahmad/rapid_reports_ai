<script lang="ts">
	/**
	 * A library pack card on the shared GlCard shell, judgement first (B-design, Hassan after checkpoint 3).
	 * Head, always visible (simplified card): guideline · result pill (coloured by the outcome's action category, with
	 * an icon) · assumptions chip (one assumption named, several counted). The card's left strip takes the
	 * category colour, so a column of cards scans by colour. Opened: PackBody (verdict, notes, source, values).
	 * Open state belongs to the session (view.open); the chevron asks for it through onOpen / onClose. A pack that
	 * does not apply dims. `headline` / `action` / `category` override the derived verdict (the planned backend
	 * fields drop in here or on the outcome itself).
	 */
	import GlCard from '$lib/rail/GlCard.svelte';
	import { cardRef } from '../state';
	import type { ActionCategory, Card } from '../types';
	import CardStatus from './CardStatus.svelte';
	import AssumedChip from './AssumedChip.svelte';
	import { assumptionsOf, categoryColor, scopeDoubts, verdictOf } from './format';
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
	<span class="cp-head-marks">
		{#if verdict}<VerdictPill {verdict} busy={view.loading && !!view.result} />{/if}
		{#if scopeDoubts(p).length}<span class="cp-chip cp-chip-warn" data-testid="cp-scope-doubt-chip">⚠ check applicability</span>{/if}
		<!-- the applicability chip already says why the card is check_first: no second "check first" -->
		<AssumedChip {assumed} checkFirst={p?.state === 'check_first' && !scopeDoubts(p).length} />
	</span>
{/snippet}

{#snippet controls()}
	{#if other}<span class="cp-chip">other</span>{/if}
{/snippet}

{#snippet body()}
	<!-- a re-open (exam card, debounced) keeps the last preview on screen instead of flickering to a skeleton -->
	<CardStatus loading={view.loading && !view.result} error={err} onRetry={() => onRetry(ref)} />
	{#if !err && view.result}
		<PackBody
			result={view.result}
			assumptions={assumed}
			{verdict}
			guideline={card.name}
			onEdit={onEdit ? (input, value) => onEdit(ref, input, value) : null}
			busy={view.loading}
			editError={view.editError ?? null}
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
		{body}
	/>
</div>

<style>
	.cp-head-marks {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-start;
		align-items: center;
		gap: 4px 6px;
		max-width: 100%;
		min-width: 0;
	}
	/* a long chip shrinks and ends in an ellipsis rather than running past the card's edge */
	.cp-head-marks > :global(.cp-chip) {
		flex-shrink: 1;
		min-width: 0;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
	}
</style>
