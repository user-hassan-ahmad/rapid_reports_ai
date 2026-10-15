<script lang="ts">
	/** A card's (or column's) request state in place of its body: a skeleton line while /open runs, a retry on
	 *  failure ("Still loading" when the server's settlement is still running), a plain note for a guideline
	 *  the library does not hold (web fetch is off: nothing to retry), nothing otherwise. */
	let { loading, error, onRetry }: { loading: boolean; error: string | null; onRetry: () => void } = $props();
</script>

{#if loading}
	<div class="cp-skel-line" data-testid="cp-card-loading" aria-label="Opening" aria-busy="true"></div>
{:else if error === 'unavailable'}
	<div class="cp-card-error cp-muted" role="status">Not in the guideline library yet</div>
{:else if error}
	<div class="cp-card-error cp-muted" role="status">
		{error === 'loading' ? 'Still loading' : "Couldn't open"} ·
		<button type="button" class="rv-btn rv-btn-ghost" onclick={(e) => (e.stopPropagation(), onRetry())}>Retry</button>
	</div>
{/if}

<style>
	.cp-card-error {
		font-size: 0.75rem;
	}
</style>
