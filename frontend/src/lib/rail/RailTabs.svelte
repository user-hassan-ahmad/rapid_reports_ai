<script lang="ts" generics="T extends string">
	/** The rail head's tabs: the Report Editor card's Report / History segmented control. */
	let {
		tabs,
		active = $bindable(),
		ariaLabel = 'Rail'
	}: {
		tabs: { id: T; label: string }[];
		active: T;
		ariaLabel?: string;
	} = $props();
</script>

<div class="rv-tabs" role="tablist" aria-label={ariaLabel}>
	{#each tabs as t (t.id)}
		<button type="button" role="tab" aria-selected={active === t.id} onclick={() => (active = t.id)}
			>{t.label}</button
		>
	{/each}
</div>

<style>
	.rv-tabs {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 2px;
		border-radius: 0.5rem;
		background: var(--rv-segment);
	}
	.rv-tabs [role='tab'] {
		font: inherit;
		font-size: 0.75rem;
		font-weight: 500;
		background: none;
		border: 0;
		border-radius: 0.375rem;
		padding: 4px 10px;
		color: #d1d5db;
		cursor: pointer;
		transition: background-color 0.15s, color 0.15s;
	}
	.rv-tabs [role='tab']:hover {
		color: #fff;
	}
	.rv-tabs [role='tab'][aria-selected='true'] {
		background: var(--rv-accent);
		color: #fff;
	}
	/* outranks hover and selected, as it did when this lived in the review rail */
	:global(.rv-rail[data-theme='light']) .rv-tabs [role='tab'] {
		color: var(--rv-muted);
	}
	button:focus-visible {
		outline: 2px solid var(--rv-focus);
		outline-offset: 1px;
	}
</style>
