<script lang="ts">
	/**
	 * The inline edit for one value (Slice B2, §7.6): a menu of the input's own options (they already include
	 * "Not known" (sent as "Not stated"), which clears it) or, for a free value with no options (a size, a number), a text box. Choosing an
	 * option saves at once; the text box saves on Enter or Save. Escape cancels. Nothing is applied: the card
	 * re-previews and Calculate re-runs on the values shown.
	 */
	import { onMount } from 'svelte';
	import { optionLabel, shownValue } from './format';

	let {
		label,
		value = '',
		options = [],
		onSave,
		onCancel
	}: { label: string; value?: string; options?: string[]; onSave: (v: string) => void; onCancel: () => void } = $props();
	let draft = $state('');
	let el: HTMLSelectElement | HTMLInputElement | undefined = $state();
	onMount(() => {
		draft = value;
		el?.focus();
	});
	const key = (e: KeyboardEvent) => {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			onCancel();
		} else if (e.key === 'Enter' && !options.length) {
			e.preventDefault();
			if (draft.trim()) onSave(draft.trim());
		}
	};
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span class="cp-edit" onkeydown={key} onclick={(e) => e.stopPropagation()}>
	{#if options.length}
		<select bind:this={el} class="cp-edit-field" aria-label={`Answer for ${label}`} value={value} onchange={(e) => onSave(e.currentTarget.value)}>
			{#if !options.includes(value)}<option value={value} disabled>{shownValue(value) || 'Choose…'}</option>{/if}
			{#each options as o (o)}<option value={o}>{optionLabel(o)}</option>{/each}
		</select>
	{:else}
		<input bind:this={el} class="cp-edit-field" type="text" aria-label={`Answer for ${label}`} bind:value={draft} size="10" />
		<button type="button" class="rv-btn cp-edit-save" disabled={!draft.trim()} onclick={() => onSave(draft.trim())}>Save</button>
	{/if}
	<button type="button" class="cp-link cp-edit-cancel" onclick={onCancel}>Cancel</button>
</span>

<style>
	.cp-edit {
		display: inline-flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.cp-edit-field {
		font: inherit;
		font-size: 0.8125rem;
		padding: 2px 6px;
		border-radius: 5px;
		border: 1px solid var(--rv-border-strong);
		background: var(--rv-surface);
		color: var(--rv-text);
		max-width: 14rem;
	}
	.cp-edit-field:focus-visible {
		outline: 2px solid var(--rv-focus);
		outline-offset: 1px;
	}
	.cp-edit-save {
		padding: 1px 8px;
	}
	.cp-edit-cancel {
		font-size: 0.75rem;
		color: var(--rv-muted);
	}
</style>
