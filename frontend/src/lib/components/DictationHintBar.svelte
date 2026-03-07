<div class="group relative mb-3 cursor-default select-none">
	<!-- Collapsed strip -->
	<div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-gray-500 transition-colors group-hover:border-white/10 group-hover:bg-white/[0.05]">
		<svg class="w-3 h-3 shrink-0 text-purple-400/60 group-hover:text-purple-400/90 transition-colors" fill="none" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M8 7v4M8 5.5v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
		<span class="text-[11px] font-medium text-gray-500 group-hover:text-gray-400 transition-colors">How to use</span>
		<span class="text-[11px] text-gray-600 group-hover:text-gray-500 transition-colors truncate">— type or dictate, correct by repeating, stop anytime</span>
		<svg class="w-3 h-3 ml-auto shrink-0 text-gray-600 group-hover:text-gray-500 transition-all duration-200 group-hover:rotate-180" fill="none" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
	</div>
	<!-- Expanded panel -->
	<div class="absolute left-0 right-0 top-full mt-1 z-20 overflow-hidden rounded-lg border border-white/10 bg-[#0f1117] shadow-xl
		opacity-0 -translate-y-1 pointer-events-none
		group-hover:opacity-100 group-hover:translate-y-0 group-hover:pointer-events-auto
		transition-all duration-200 ease-out">
		<div class="px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5">
			{#each tips as tip}
			<div class="flex gap-2.5 items-start">
				<span class="text-base leading-none mt-0.5">{tip.icon}</span>
				<div>
					<p class="text-[11px] font-semibold text-gray-300 mb-0.5">{tip.title}</p>
					<p class="text-[11px] text-gray-500 leading-relaxed">{tip.body}</p>
				</div>
			</div>
			{/each}
		</div>
	</div>
</div>

<script lang="ts">
	const tips = [
		{ icon: '🎙️', title: 'Type or dictate', body: 'Type findings directly or use the mic to dictate — the AI intelligently organises and groups them as you go.' },
		{ icon: '✏️', title: 'Correct by repeating', body: 'Made a mistake? Simply re-dictate or retype the correct finding — the AI updates or replaces it automatically.' },
		{ icon: '▶️', title: 'No need to stop', body: 'Keep dictating continuously across different findings. Pause or stop recording whenever you\'re ready.' },
		{ icon: '💡', title: 'CONSIDER prompts', body: 'The right panel surfaces imaging targets you may not have reviewed yet, based on what you\'ve documented.' },
		{ icon: '✅', title: 'Review guide', body: 'A reference checklist to ensure nothing is missed — systems light up as you cover them. Not a strict requirement.' },
		{ icon: '🗣️', title: 'Speak naturally', body: 'Hedge, self-correct, think aloud — the AI strips the filler and keeps only clean, precise findings.' },
	];
</script>
