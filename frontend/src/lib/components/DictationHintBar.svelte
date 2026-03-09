<script lang="ts">
	let open = false;

	const tips = [
		{ icon: '🎙️', title: 'Type or dictate', body: 'Type findings directly or use the mic to dictate — the AI intelligently organises and groups them as you go.' },
		{ icon: '✏️', title: 'Correct by repeating', body: 'Made a mistake? Simply re-dictate or retype the correct finding — the AI updates or replaces it automatically.' },
		{ icon: '▶️', title: 'No need to stop', body: 'Keep dictating continuously across different findings. Pause or stop recording whenever you\'re ready.' },
		{ icon: '💡', title: 'CONSIDER prompts', body: 'The right panel surfaces imaging targets you may not have reviewed yet, based on what you\'ve documented.' },
		{ icon: '✅', title: 'Review guide', body: 'A reference checklist to ensure nothing is missed — systems light up as you cover them. Not a strict requirement.' },
		{ icon: '🗣️', title: 'Speak naturally', body: 'Hedge, self-correct, think aloud — the AI strips the filler and keeps only clean, precise findings.' },
	];

	function handleClickOutside(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (open && !target.closest('.hint-bar-root')) {
			open = false;
		}
	}
</script>

<svelte:window onclick={handleClickOutside} />

<div class="hint-bar-root relative">
	<button
		type="button"
		onclick={() => (open = !open)}
		class="flex items-center gap-1.5 px-2 py-1 rounded-md text-gray-600 hover:text-gray-400
			hover:bg-white/[0.05] transition-colors {open ? 'text-gray-400 bg-white/[0.05]' : ''}"
		title="How to use"
		aria-label="How to use"
	>
		<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 16 16">
			<circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
			<path d="M8 7v4M8 5.5v.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
		</svg>
		<span class="text-[11px] font-medium">How to use</span>
	</button>

	{#if open}
		<div
			class="absolute right-0 top-full mt-1.5 z-30 w-[480px] max-w-[90vw]
				rounded-xl border border-white/10 bg-[#0d1018] shadow-2xl shadow-black/60
				ring-1 ring-white/[0.04]"
		>
			<div class="px-4 py-3.5 grid grid-cols-2 gap-x-5 gap-y-3">
				{#each tips as tip}
					<div class="flex gap-2.5 items-start">
						<span class="text-base leading-none mt-0.5 shrink-0">{tip.icon}</span>
						<div>
							<p class="text-[11px] font-semibold text-gray-300 mb-0.5">{tip.title}</p>
							<p class="text-[11px] text-gray-500 leading-relaxed">{tip.body}</p>
						</div>
					</div>
				{/each}
			</div>
			<div class="px-4 pb-3 border-t border-white/[0.05] pt-2.5">
				<p class="text-[10px] text-gray-600">Click anywhere to dismiss</p>
			</div>
		</div>
	{/if}
</div>
