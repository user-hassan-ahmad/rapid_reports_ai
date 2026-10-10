<script lang="ts">
	// An `action` item: a card with its lane badge, label, reason, what was dictated, and the fix. Edit (write your
	// own replacement) and Ask in chat live here only; the editor's hover chip carries the quick actions.
	import { ICONS, LABELS } from '../editor/decorations';
	import type { ReviewItem } from '../types';
	import { isRemoval, statusNote, type RailCommand } from './ItemRow.svelte';

	let {
		item,
		onCommand,
		updating = false
	}: { item: ReviewItem; onCommand: RailCommand; updating?: boolean } = $props();

	const label = $derived(item.label || item.kind);
	const open = $derived(item.status === 'open' || item.status === 'stale');
	const note = $derived(statusNote(item));
	const verb = $derived(isRemoval(item) ? 'Remove' : 'Apply');

	let editing = $state(false);
	let draft = $state('');
	function startEdit() {
		draft = item.edit?.replace ?? item.anchor?.text ?? '';
		editing = true;
	}
	function saveEdit() {
		editing = false;
		onCommand('edit', item.id, { replacement: draft });
	}
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

	{#if editing}
		<form
			class="rv-card-edit"
			onsubmit={(e) => {
				e.preventDefault();
				saveEdit();
			}}
		>
			<!-- svelte-ignore a11y_autofocus -->
			<input
				type="text"
				bind:value={draft}
				aria-label={`Replacement for: ${label}`}
				autofocus
				onkeydown={(e) => {
					if (e.key === 'Escape') {
						e.preventDefault();
						editing = false;
					}
				}}
			/>
			<button type="submit" class="rv-btn rv-primary">Save</button>
			<button type="button" class="rv-btn rv-quiet" onclick={() => (editing = false)}>Cancel</button>
		</form>
	{/if}

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
					aria-label={`${verb}: ${label}`}
					onclick={() => onCommand('apply', item.id)}>{verb}</button
				>
				{#if item.anchor && !editing}
					<button
						type="button"
						class="rv-btn"
						aria-label={`Edit: ${label}`}
						onclick={startEdit}>Edit</button
					>
				{/if}
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
	.rv-card-edit {
		display: flex;
		gap: 6px;
		margin-top: 8px;
	}
	.rv-card-edit input {
		flex: 1;
		min-width: 0;
		font: inherit;
		font-size: 0.8125rem;
		padding: 3px 8px;
		border-radius: 0.375rem;
		border: 1px solid var(--rv-border);
		background: rgba(0, 0, 0, 0.4);
		color: var(--rv-text);
	}
	.rv-card-edit input:focus {
		outline: none;
		border-color: var(--rv-focus, #a855f7);
		box-shadow: 0 0 0 2px rgba(168, 85, 247, 0.3);
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
