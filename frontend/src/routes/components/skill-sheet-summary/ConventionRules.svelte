<script>
	/** @type {{ title: string, detail: string }[]} */
	export let rules = [];
</script>

<ol class="space-y-3 list-none p-0 m-0">
	{#each rules as rule, i}
		<li class="flex items-baseline gap-3">
			<span class="font-mono text-xs text-purple-400/60 w-6 shrink-0 text-right tabular-nums">
				{String(i + 1).padStart(2, '0')}
			</span>
			<div class="flex-1 min-w-0">
				<div class="text-sm text-white font-semibold leading-snug">{rule.title}</div>
				<div class="text-xs text-gray-400 leading-relaxed mt-0.5">{rule.detail}</div>
			</div>
		</li>
	{/each}
</ol>
