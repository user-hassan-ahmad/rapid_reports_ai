<script lang="ts">
	// An `info` item: a subtle tag. No actions beyond opening it in the editor.
	import { ICONS, LABELS } from '../editor/decorations';
	import type { ReviewItem } from '../types';
	import type { RailCommand } from './ItemRow.svelte';

	let {
		item,
		onCommand,
		updating = false
	}: { item: ReviewItem; onCommand: RailCommand; updating?: boolean } = $props();

	const label = $derived(item.label || item.kind);
</script>

<div class="rv-tag" data-rv-item={item.id} data-rv-variant="tag" data-status={item.status}>
	<button
		type="button"
		class="rv-tag-main"
		aria-label={`Open: ${label}`}
		title={item.reason || LABELS.info}
		onclick={() => onCommand('open_item', item.id)}
	>
		<span class="rv-icon" aria-hidden="true">{ICONS.info}</span>
		<span>{label}</span>
	</button>
	{#if updating}<span class="rv-note" role="status">updating…</span>{/if}
	{#if item.status === 'stale'}<span class="rv-note">out of date</span>{/if}
</div>

<style>
	.rv-tag {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin: 2px 4px 2px 0;
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
	.rv-tag-main {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border: 1px dashed var(--rv-border);
		border-radius: 10px;
		padding: 0 7px;
		background: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.rv-tag-main:hover {
		background: var(--rv-surface-hover);
	}
	.rv-icon {
		font-style: italic;
		font-weight: 600;
		color: var(--rv-blue-line);
	}
	.rv-note {
		font-style: italic;
	}
	button:focus-visible {
		outline: 2px solid var(--rv-blue-line);
		outline-offset: 1px;
	}
</style>
