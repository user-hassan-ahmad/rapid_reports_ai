<script lang="ts" module>
	export type { CardView, ColumnView } from './view';
</script>

<script lang="ts">
	/**
	 * The Copilot's card list, presentational: groups (exam first, then one per finding) of cards, each drawn by
	 * kind. It takes state and callbacks and never calls the API; the session store (A6) owns requests. Slice A is
	 * read-only throughout: no inputs, no Calculate, no Apply.
	 */
	import RailSkeleton from '$lib/rail/RailSkeleton.svelte';
	import { cardRef, kindOf, quiet, type Group } from '../state';
	import type { Card } from '../types';
	import './cards.css';
	import PackCard from './PackCard.svelte';
	import QuietLine from './QuietLine.svelte';
	import ReadOnlyCard from './ReadOnlyCard.svelte';
	import SiblingColumns from './SiblingColumns.svelte';
	import { closedView, type CardView } from './view';

	let {
		groups,
		views,
		matching,
		matchFailed,
		otherState,
		siblingLayout = 'auto',
		onOpen,
		onClose,
		onRetry,
		onRetryMatch,
		onOther,
		onEdit = undefined
	}: {
		groups: Group[];
		views: Record<string, CardView>;
		/** A /match is in flight. */
		matching: boolean;
		matchFailed: boolean;
		otherState: 'idle' | 'loading' | 'done' | 'failed';
		siblingLayout?: 'auto' | 'columns' | 'stacked';
		onOpen(ref: string): void;
		onClose(ref: string): void;
		/** A card ref, or `<cardRef>#<pack key>` for one sibling column. */
		onRetry(ref: string): void;
		onRetryMatch(): void;
		onOther(): void;
		/** Slice B2: inline edit on pack cards (session.edit). Absent: read-only. */
		onEdit?: (ref: string, input: string, value: string) => void;
	} = $props();

	const shown = $derived(groups.filter((g) => g.cards.length));
	const viewOf = (c: Card) => views[cardRef(c)] ?? closedView;
	const handlers = $derived({ onOpen, onClose, onRetry });
</script>

{#snippet one(c: Card)}
	{@const v = viewOf(c)}
	{@const other = !!v.fromOther}
	{@const kind = kindOf(c, other)}
	{#if kind === 'exam' && v.result && quiet(c, v.result.preview)}
		<QuietLine card={c} result={v.result} busy={v.loading} />
	{:else if kind === 'exam' || kind === 'finding'}
		{#if c.siblings.length}
			<SiblingColumns card={c} view={v} {other} layout={siblingLayout} {onEdit} {...handlers} />
		{:else}
			<PackCard card={c} view={v} {other} {onEdit} {...handlers} />
		{/if}
	{:else}
		<ReadOnlyCard card={c} {kind} view={v} {other} {...handlers} />
	{/if}
{/snippet}

<div class="cp-cards" data-testid="copilot-cards">
	{#if !shown.length}
		{#if matching}
			<RailSkeleton count={2} label="Checking guidelines" testid="cp-skeleton" />
		{:else if matchFailed}
			<p class="cp-muted cp-empty" role="status">
				Couldn't check guidelines · <button type="button" class="cp-link" onclick={onRetryMatch}>Retry</button>
			</p>
		{:else}
			<p class="cp-muted cp-empty" role="status">No guideline applies yet</p>
		{/if}
	{:else}
		{#each shown as g (g.finding?.id ?? 'exam')}
			<section class="cp-group" aria-label={g.finding ? g.finding.text : 'This exam'}>
				{#if g.finding}
					<div class="gl-inline-label cp-group-head" title={g.finding.text}>
						<span class="cp-group-text">{g.finding.text}</span>
					</div>
				{/if}
				{#each g.cards as c (cardRef(c))}
					{@render one(c)}
				{/each}
			</section>
		{/each}
	{/if}
	{#if shown.length || (!matching && !matchFailed)}
		<div class="cp-foot">
			{#if otherState === 'failed'}
				<span class="cp-muted">Couldn't fetch other guidelines ·</span>
				<button type="button" class="cp-link" onclick={onOther}>Retry</button>
			{:else if otherState === 'done'}
				<span class="cp-muted cp-other-done">Other guidelines checked</span>
			{:else}
				<button type="button" class="rv-btn" disabled={otherState === 'loading'} onclick={onOther}
					>{otherState === 'loading' ? 'Looking for other guidelines…' : 'Other guidelines'}</button
				>
			{/if}
		</div>
	{/if}
</div>

<style>
	.cp-group {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.cp-group + .cp-group {
		margin-top: 10px;
	}
	.cp-group-head {
		display: flex;
		min-width: 0;
		margin: 2px 0 0;
	}
	.cp-group-text {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--rv-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cp-empty {
		margin: 4px 0;
		font-size: 0.8125rem;
	}
	.cp-foot {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 10px;
		font-size: 0.8125rem;
	}
	.cp-other-done {
		font-size: 0.6875rem;
	}
</style>
