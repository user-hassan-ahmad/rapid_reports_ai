<script>
	/** @type {string[]} */
	export let flow = [];
	/** @type {string} */
	export let detail = '';
</script>

<div class="space-y-3">
	<div class="flex flex-wrap items-center gap-x-2 gap-y-2 font-mono text-sm">
		{#each flow as step, i}
			<span class="text-gray-200 font-semibold tracking-tight">{step}</span>
			{#if i < flow.length - 1}
				<span class="text-purple-400/70 text-base leading-none">→</span>
			{/if}
		{/each}
	</div>
	<p class="text-sm text-gray-400 leading-relaxed">{detail}</p>
</div>
