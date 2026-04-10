<script>
	/** @type {{ name: string, paragraphs: string[] }[]} */
	export let sections = [];

	const romans = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];
</script>

<div class="font-mono text-sm space-y-4">
	{#each sections as section}
		<div>
			<div class="text-purple-400/90 tracking-[0.15em] text-xs font-semibold mb-2">
				{section.name}
			</div>
			{#if section.paragraphs && section.paragraphs.length > 0}
				<div class="pl-4 space-y-1.5 border-l border-white/[0.08]">
					{#each section.paragraphs as para, i}
						<div class="flex items-baseline gap-3 pl-3">
							<span class="text-gray-600 text-xs w-6 shrink-0 text-right">{romans[i] || (i + 1)}.</span>
							<span class="text-gray-300 italic font-sans leading-relaxed">{para}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
