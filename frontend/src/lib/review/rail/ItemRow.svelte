<script module lang="ts">
	import type { CommandName } from '../commands';
	import type { ReviewItem } from '../types';

	/** The rail's single way out: (command, item id, args). The host runs it through lib/review/commands.ts. */
	export type RailCommand = (
		name: CommandName,
		itemId?: string,
		args?: Record<string, unknown>
	) => void;

	/** A removal the engine made (red): the text is out of the report; Restore puts it back. */
	export function isRemoval(it: ReviewItem): boolean {
		return it.kind === 'removed' || it.edit?.mode === 'remove';
	}

	export function removedText(it: ReviewItem): string {
		const ev = it.evidence ?? {};
		return (ev.removed_text as string) || ev.undo?.original_text || it.edit?.find || '';
	}

	/** A short non-colour status note for rows that are no longer simply open. */
	export function statusNote(it: ReviewItem): string | null {
		if (it.status === 'stale') return 'out of date';
		return null;
	}
</script>

<script lang="ts">
	import { ICONS, LABELS } from '../editor/decorations';
	import { checkReason } from '../editor/field';

	type Variant = 'row' | 'check' | 'option' | 'preapplied';

	let {
		item,
		onCommand,
		variant = 'row',
		updating = false
	}: { item: ReviewItem; onCommand: RailCommand; variant?: Variant; updating?: boolean } = $props();

	const label = $derived(item.label || item.kind);
	const open = $derived(item.status === 'open' || item.status === 'stale');
	const removal = $derived(isRemoval(item));
	const removalWhy = $derived(
		item.evidence?.removal_reason === 'number'
			? 'a measurement you did not dictate'
			: 'contradicts your dictation'
	);
	const icon = $derived(
		variant === 'check'
			? ICONS.check
			: variant === 'option'
				? ICONS.option
				: variant === 'preapplied'
					? removal
						? ICONS.removed
						: ICONS.preapplied
					: ICONS.minor
	);
	const iconName = $derived(
		variant === 'check'
			? LABELS.check
			: variant === 'option'
				? LABELS.option
				: variant === 'preapplied'
					? removal
						? LABELS.removed
						: LABELS.preapplied
					: LABELS.minor
	);
	const note = $derived(statusNote(item));
</script>

<div
	class="rv-row rv-row-{variant}"
	class:rv-done={!open && item.status !== 'pre_applied'}
	data-rv-item={item.id}
	data-rv-variant={variant}
	data-status={item.status}
>
	<button
		type="button"
		class="rv-row-main"
		aria-label={`Open: ${label}`}
		title={iconName}
		onclick={() => onCommand('open_item', item.id)}
	>
		<span class="rv-icon" aria-hidden="true" title={iconName}>{icon}</span>
		<span class="rv-row-text">
			<span class="rv-row-label">{label}</span>
			{#if variant === 'preapplied'}
				<span class="rv-row-sub">{removal ? removedText(item) : (item.edit?.replace ?? '')}</span>
			{:else if variant === 'check'}
				<span class="rv-row-sub">{checkReason(item.evidence).line}</span>
			{:else if variant === 'option' && item.reason}
				<span class="rv-row-sub">{item.reason}</span>
			{/if}
		</span>
	</button>

	<div class="rv-row-actions">
		{#if updating}<span class="rv-note" role="status">updating…</span>{/if}
		{#if note}<span class="rv-note">{note}</span>{/if}
		{#if item.syncError}<span class="rv-note" title={item.syncError}>⚠ not saved</span>{/if}

		{#if variant === 'preapplied' && item.status === 'pre_applied'}
			{#if removal}
				<span class="rv-pre">removed · {removalWhy}</span> ·
				<button
					type="button"
					class="rv-link"
					aria-label={`Restore: ${label}`}
					onclick={() => onCommand('restore', item.id)}>restore</button
				>
			{:else}
				<span class="rv-pre">added from your dictation</span> ·
				<button
					type="button"
					class="rv-link"
					aria-label={`Undo: ${label}`}
					onclick={() => onCommand('undo', item.id)}>undo</button
				>
			{/if}
		{:else if item.status === 'applied'}
			<span class="rv-pre">{variant === 'check' ? 'removed' : 'applied'}</span> ·
			<button
				type="button"
				class="rv-link"
				aria-label={`Undo: ${label}`}
				onclick={() => onCommand('undo', item.id)}>undo</button
			>
		{:else if open && variant === 'check'}
			<button
				type="button"
				class="rv-btn"
				aria-label={`Keep: ${label}`}
				onclick={() => onCommand('keep', item.id)}>Keep</button
			>
			<button
				type="button"
				class="rv-btn"
				aria-label={`Remove: ${label}`}
				onclick={() => onCommand('remove', item.id)}>Remove</button
			>
		{:else if open && variant === 'option'}
			<button
				type="button"
				class="rv-btn"
				aria-label={`Add: ${label}`}
				onclick={() => onCommand('apply', item.id)}>Add</button
			>
		{:else if open}
			{#if item.edit}
				<button
					type="button"
					class="rv-btn"
					aria-label={`Apply: ${label}`}
					onclick={() => onCommand('apply', item.id)}>Apply</button
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
</div>

<style>
	.rv-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 6px;
		border-radius: 0.375rem;
		font-size: 0.8125rem;
	}
	.rv-row:hover {
		background: var(--rv-surface-hover);
	}
	/* Gate G: the label column keeps at least half the row and wraps; the actions shrink and wrap beside it. */
	.rv-row-main {
		flex: 1 1 50%;
		min-width: 50%;
		display: flex;
		align-items: baseline;
		gap: 6px;
		text-align: left;
		background: none;
		border: 0;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.rv-row-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.rv-row-label {
		overflow-wrap: anywhere;
	}
	.rv-row-sub {
		color: var(--rv-muted);
		font-size: 0.75rem;
	}
	.rv-row-check .rv-icon {
		color: var(--rv-amber-line);
	}
	.rv-row-preapplied .rv-icon {
		color: var(--rv-green-line);
	}
	.rv-row-option .rv-icon {
		color: var(--rv-blue-line);
	}
	.rv-icon {
		width: 1em;
		flex: none;
		text-align: center;
		font-weight: 600;
	}
	.rv-row-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		align-items: center;
		gap: 4px;
		flex: 0 1 auto;
		min-width: 0;
		text-align: right;
		color: var(--rv-muted);
		font-size: 0.75rem;
	}
	.rv-done .rv-row-label {
		color: var(--rv-muted);
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
