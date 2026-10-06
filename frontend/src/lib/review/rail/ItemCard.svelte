<script lang="ts">
	// An `action` item: a card with its lane badge, label, reason, what was dictated, and the fix.
	import { ICONS, LABELS } from '../editor/decorations';
	import type { ReviewItem } from '../types';
	import { statusNote, type RailCommand } from './ItemRow.svelte';

	let {
		item,
		onCommand,
		updating = false
	}: { item: ReviewItem; onCommand: RailCommand; updating?: boolean } = $props();

	const label = $derived(item.label || item.kind);
	const open = $derived(item.status === 'open' || item.status === 'stale');
	const note = $derived(statusNote(item));
</script>

<article
	class="rv-card"
	class:rv-done={!open}
	data-rv-item={item.id}
	data-rv-variant="card"
	data-status={item.status}
>
	<button
		type="button"
		class="rv-card-main"
		aria-label={`Open: ${label}`}
		title={LABELS.action}
		onclick={() => onCommand('open_item', item.id)}
	>
		<span class="rv-card-head">
			<span class="rv-icon" aria-hidden="true">{ICONS.action}</span>
			<span class="rv-card-label">{label}</span>
			<span class="rv-badge">{item.lane}</span>
		</span>
		{#if item.reason}<span class="rv-card-reason">{item.reason}</span>{/if}
		{#if item.source_line}<span class="rv-card-source">You dictated: “{item.source_line}”</span
			>{/if}
		{#if item.edit?.replace && open}
			<span class="rv-card-fix">
				{#if item.edit.find}<del>{item.edit.find}</del> →
				{/if}<ins>{item.edit.replace}</ins>
			</span>
		{/if}
	</button>

	<div class="rv-card-actions">
		{#if updating}<span class="rv-note" role="status">updating…</span>{/if}
		{#if note}<span class="rv-note">{note}</span>{/if}
		{#if item.syncError}<span class="rv-note" title={item.syncError}>⚠ not saved</span>{/if}
		{#if item.status === 'applied'}
			<span class="rv-note">applied</span> ·
			<button
				type="button"
				class="rv-link"
				aria-label={`Undo: ${label}`}
				onclick={() => onCommand('undo', item.id)}>undo</button
			>
		{:else if open}
			{#if item.edit}
				<button
					type="button"
					class="rv-btn rv-primary"
					aria-label={`Apply: ${label}`}
					onclick={() => onCommand('apply', item.id)}>Apply</button
				>
			{:else}
				<button
					type="button"
					class="rv-btn"
					aria-label={`Ask in chat: ${label}`}
					onclick={() => onCommand('ask_chat', item.id)}>Ask in chat</button
				>
			{/if}
			<button
				type="button"
				class="rv-btn rv-quiet"
				aria-label={`Dismiss: ${label}`}
				onclick={() => onCommand('dismiss', item.id)}>Dismiss</button
			>
		{/if}
	</div>
</article>

<style>
	.rv-card {
		border: 1px solid var(--rv-border);
		border-left: 3px solid var(--rv-red-line);
		border-radius: 0.5rem;
		padding: 10px 12px;
		margin: 6px 0 8px;
		background: var(--rv-surface);
		font-size: 0.8125rem;
	}
	.rv-card.rv-done {
		border-left-style: dotted;
		opacity: 0.75;
	}
	.rv-card-main {
		display: flex;
		flex-direction: column;
		gap: 3px;
		width: 100%;
		text-align: left;
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.rv-card-head {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}
	.rv-icon {
		font-weight: 700;
		color: var(--rv-red-line);
	}
	.rv-card-label {
		font-weight: 600;
		flex: 1;
	}
	.rv-badge {
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--rv-muted);
		border: 1px solid var(--rv-border);
		border-radius: 9999px;
		padding: 0 6px;
	}
	.rv-card-reason,
	.rv-card-source {
		color: var(--rv-muted);
		font-size: 0.78rem;
	}
	.rv-card-fix {
		font-size: 0.8rem;
	}
	.rv-card-fix del {
		color: var(--rv-del);
	}
	.rv-card-fix ins {
		color: var(--rv-ins);
		text-decoration: none;
		font-weight: 600;
	}
	.rv-card-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 6px;
		margin-top: 6px;
		color: var(--rv-muted);
		font-size: 0.75rem;
	}
	.rv-note {
		font-style: italic;
	}
	.rv-btn {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 500;
		padding: 2px 9px;
		line-height: 1.45;
		border-radius: 0.375rem;
		border: 1px solid var(--rv-border);
		background: var(--rv-surface);
		color: var(--rv-text);
		cursor: pointer;
		transition: background-color 0.15s, border-color 0.15s;
	}
	.rv-btn:hover:not(:disabled) {
		background: var(--rv-surface-hover);
		border-color: var(--rv-border-strong);
	}
	.rv-primary {
		background: var(--rv-accent);
		border-color: var(--rv-accent);
		color: #fff;
		font-weight: 600;
	}
	.rv-primary:hover:not(:disabled) {
		background: var(--rv-accent-hover);
		border-color: var(--rv-accent-hover);
	}
	.rv-quiet {
		color: var(--rv-muted);
	}
	.rv-link {
		font: inherit;
		background: none;
		border: 0;
		padding: 0;
		color: var(--rv-text);
		text-decoration: underline;
		cursor: pointer;
	}
	button:focus-visible {
		outline: 2px solid var(--rv-focus, #a855f7);
		outline-offset: 1px;
	}
</style>
