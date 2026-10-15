<script lang="ts">
	/**
	 * A guideline that may not apply, collapsed to one row under its head (name · pill): the reason (a scope doubt, or
	 * why it does not apply), the doubt's Confirm (an answer, sent through onEdit), an "unresolved" marker when the
	 * gate lists it, and "Show details" for today's full body.
	 */
	import Icon from './Icon.svelte';
	import { shownValue } from './format';

	let {
		reason,
		more = 0,
		confirm = null,
		unresolvedKey = null,
		onConfirm = null,
		onSeen = null,
		onToggle,
		controls = undefined
	}: {
		reason: string;
		more?: number;
		confirm?: { input: string; label: string; value: string } | null;
		/** The gate lists this guideline as unresolved (its key): marker, and "Seen" keeps the gate one tap. */
		unresolvedKey?: string | null;
		onConfirm?: ((input: string, value: string) => void) | null;
		onSeen?: ((key: string) => void) | null;
		onToggle: () => void;
		controls?: string;
	} = $props();
</script>

<div class="cp-collapsed" data-testid="cp-collapsed">
	<p class="cp-p cp-collapsed-reason">
		{reason}{#if more > 0}<span class="cp-muted"> · +{more} more</span>{/if}
		{#if unresolvedKey}<span class="cp-chip cp-chip-warn" data-testid="cp-collapsed-unresolved">unresolved</span>{#if onSeen} <button type="button" class="cp-link" onclick={() => onSeen?.(unresolvedKey)}>Seen, leave as is</button>{/if}{/if}
	</p>
	<span class="cp-collapsed-actions">
		{#if confirm && onConfirm}<button type="button" class="rv-btn" aria-label={`Confirm ${confirm.label} ${shownValue(confirm.value)}`} onclick={() => onConfirm?.(confirm.input, confirm.value)}>Confirm</button>{/if}
		<button type="button" class="cp-link cp-aux-toggle" aria-expanded="false" aria-controls={controls} onclick={onToggle}>Show details <span class="cp-caret"><Icon name="chev" size={11} /></span></button>
	</span>
</div>

<style>
	.cp-collapsed { display: flex; flex-direction: column; gap: 6px; font-size: 0.8125rem; }
	.cp-collapsed-reason { margin: 0; color: var(--rv-text); }
	.cp-collapsed-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
	.cp-caret { display: inline-block; margin-left: 2px; }
</style>
