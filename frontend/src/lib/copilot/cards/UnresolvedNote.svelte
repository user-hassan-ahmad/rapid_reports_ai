<script lang="ts">
	/** A card that blocks Confirm (spec §7.12 item 5): why (the conclusion check's reason, when it ran) and the one
	 *  tap that always clears it, "Seen, leave as is" (held until the card's verdict changes). */
	import type { Unresolved } from '../gate';

	let { item, onSeen = null }: { item: Unresolved; onSeen?: ((key: string) => void) | null } = $props();
</script>

<div class="cp-unresolved" role="note" data-testid="cp-unresolved">
	<p class="cp-unresolved-text">
		{item.reason ?? (item.checked === 'failed' ? "Couldn't check the conclusion against this: tap Seen to continue" : 'Blocks Confirm until the conclusion covers it')}
	</p>
	{#if onSeen}
		<button type="button" class="rv-btn" onclick={(e) => (e.stopPropagation(), onSeen?.(item.key))}>Seen, leave as is</button>
	{/if}
</div>

<style>
	.cp-unresolved {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 8px;
		min-width: 0;
		margin-bottom: 8px;
		padding: 6px 8px;
		border-radius: 6px;
		border-left: 3px solid var(--rv-amber-line);
		background: var(--rv-surface-hover);
		font-size: 0.8125rem;
	}
	.cp-unresolved-text {
		flex: 1 1 12rem;
		min-width: 0;
		margin: 0;
		color: var(--rv-text);
		overflow-wrap: anywhere;
	}
</style>
