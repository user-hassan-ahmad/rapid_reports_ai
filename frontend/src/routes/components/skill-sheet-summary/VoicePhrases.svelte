<script>
	/** @type {string} */
	export let description = '';
	/** @type {string[]} */
	export let phrases = [];
</script>

<div class="space-y-4">
	<p class="text-sm text-gray-300 leading-relaxed">{description}</p>

	<div class="border-l-2 border-purple-500/40 pl-4 space-y-2">
		{#each phrases as phrase}
			<p class="text-sm text-gray-200 italic font-serif leading-snug">
				<span class="text-purple-400/60 mr-1">"</span>{phrase}<span class="text-purple-400/60 ml-1">"</span>
			</p>
		{/each}
		<p class="text-[10px] text-gray-600 uppercase tracking-[0.2em] font-mono pt-1">
			— signature voice
		</p>
	</div>
</div>
