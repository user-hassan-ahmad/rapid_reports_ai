<script lang="ts">
	/** Placeholder cards while a rail's first answer is pending: fixed height, so nothing jumps when items land. */
	let {
		count = 3,
		label = 'Loading review',
		testid = 'rv-skeleton'
	}: { count?: number; label?: string; testid?: string } = $props();
</script>

<div data-testid={testid} aria-label={label} aria-busy="true">
	{#each Array.from({ length: count }, (_, i) => i) as n (n)}
		<div class="rv-skel-card">
			<div class="rv-skel rv-skel-title"></div>
			<div class="rv-skel"></div>
			<div class="rv-skel rv-skel-short"></div>
		</div>
	{/each}
</div>

<style>
	.rv-skel-card {
		border: 1px solid var(--rv-border);
		border-radius: 0.5rem;
		padding: 10px 12px;
		margin: 6px 0 8px;
		background: var(--rv-surface);
	}
	.rv-skel {
		height: 10px;
		margin: 6px 0;
		border-radius: 4px;
		background: var(--rv-surface-hover);
		animation: rv-pulse 1.6s ease-in-out infinite;
	}
	.rv-skel-title {
		width: 60%;
		height: 12px;
	}
	.rv-skel-short {
		width: 40%;
	}
	@keyframes rv-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}
</style>
