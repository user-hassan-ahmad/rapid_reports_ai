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
	import { assumptionsOf, categoryColor, pillWord, scopeDoubts, verdictOf } from './format';
	import { assumedUnticked, collapsible } from './questionnaire';
	import type { AppliedRec } from '$lib/hybrid-stack/types';
	import PackBody from './PackBody.svelte';
	import type { Unresolved } from '../gate';
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
		applyOn = false,
		applied = null,
		onTick = null,
		onPick = null,
		onApply = null,
		unresolved = null,
		onSeen = null,
		onOpen,
		onClose,
		onRetry,
		onExpand = null
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
		/** The Apply flag; with it, the card offers ✓, the outcome pick and Apply. */
		applyOn?: boolean;
		applied?: AppliedRec | null;
		onTick?: ((ref: string, input: string, value: string) => void) | null;
		onPick?: ((ref: string, outcome: string | null) => void) | null;
		onApply?: ((ref: string) => void) | null;
		/** The card blocks Confirm (§7.12 item 5): its note and "Seen, leave as is" sit above the result. */
		unresolved?: Unresolved | null;
		onSeen?: ((key: string) => void) | null;
		onOpen: (ref: string) => void;
		onClose: (ref: string) => void;
		onRetry: (ref: string) => void;
		/** A card that may not apply is collapsed to one row; this opens or collapses it (view.expanded). */
		onExpand?: ((ref: string, open: boolean) => void) | null;
	} = $props();

	const ref = $derived(cardRef(card));
	const p = $derived(view.result?.preview ?? null);
	const err = $derived(errorOf(view));
	const assumed = $derived(assumptions ?? assumptionsOf(p));
	const verdict = $derived(verdictOf(p, { headline, action, category }));
	// the head's assumptions chip leaves while the open body shows them in Check (a collapsed row does not)
	const assumedHead = $derived(assumptions ?? assumedUnticked(p, view.ticks ?? {}));
	// (only a preview with a draft has a Check zone to duplicate)
	const bodyShown = $derived(view.open && !!p?.draft?.length && !(collapsible(p) && !view.expanded));
	const hint = $derived(!view.open && err && err !== 'unavailable' ? "Couldn't open · open to retry" : null);
</script>

{#snippet aside()}
	<span class="cp-head-marks">
		{#if verdict}<VerdictPill {verdict} busy={view.loading && !!view.result} text={view.open ? pillWord(verdict) : null} title={view.open ? null : verdict.pill} />{/if}
		{#if scopeDoubts(p).length}<span class="cp-chip cp-chip-warn" data-testid="cp-scope-doubt-chip">⚠ check applicability</span>{/if}
		<!-- the applicability chip already says why the card is check_first: no second "check first" -->
		{#if !bodyShown}<AssumedChip assumed={assumedHead} checkFirst={p?.state === 'check_first' && !scopeDoubts(p).length} />{/if}
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
			edits={view.edits ?? {}}
			ticks={view.ticks ?? {}}
			pick={view.pick ?? null}
			applying={!!view.applying}
			applyError={view.applyError ?? null}
			{applied}
			{applyOn}
			onTick={onTick ? (input, value) => onTick(ref, input, value) : null}
			onPick={onPick ? (outcome) => onPick(ref, outcome) : null}
			onApply={onApply ? () => onApply(ref) : null}
			expanded={!!view.expanded}
			onExpand={onExpand ? (open) => onExpand(ref, open) : null}
			{unresolved}
			{onSeen}
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
