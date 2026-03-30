<script lang="ts">
	interface GuidelineReference {
		system: string;
		context: string;
		type: string;
		source_url?: string | null;
		criteria_summary?: string | null;
		criteria_summary_truncated?: boolean;
		injected: boolean;
	}

	export let references: GuidelineReference[] = [];

	let expanded = new Set<number>();

	function toggle(i: number) {
		const n = new Set(expanded);
		if (n.has(i)) n.delete(i);
		else n.add(i);
		expanded = n;
	}

	function domainFromUrl(url: string): string {
		try {
			return new URL(url).hostname.replace(/^www\./, '');
		} catch {
			return url;
		}
	}

	async function copyExcerpt(ref: GuidelineReference) {
		const parts = [`[${ref.system}]`, ref.context];
		if (ref.criteria_summary) parts.push('', ref.criteria_summary);
		if (ref.criteria_summary_truncated) parts.push('', '(Excerpt — see source for full criteria.)');
		try {
			await navigator.clipboard.writeText(parts.join('\n'));
		} catch {
			/* ignore */
		}
	}
</script>

{#if references.length > 0}
	<div class="mt-4 pt-4 border-t border-cyan-500/15" aria-label="Reference guidelines">
		<div class="flex items-center gap-2 mb-3">
			<svg class="w-3.5 h-3.5 text-cyan-400/90 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
			</svg>
			<span class="text-[9px] font-semibold uppercase tracking-widest text-cyan-400/80">Reference guidelines</span>
		</div>
		<p class="text-[9px] text-gray-600 leading-relaxed mb-3">
			Structural reference used as QA context — not automated classification.
		</p>
		<div class="space-y-2.5">
			{#each references as ref, i (ref.system + '-' + i)}
				<div
					id="guideline-ref-{i}"
					class="rounded-lg border bg-cyan-950/20 overflow-hidden transition-colors
						{ref.injected ? 'border-cyan-500/20' : 'border-white/[0.06] opacity-90'}"
				>
					<div class="px-3 py-2.5 flex items-start justify-between gap-2 border-b border-white/[0.04]">
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2 flex-wrap">
								<span class="text-[11px] font-semibold text-cyan-200/95 truncate">{ref.system}</span>
								{#if !ref.injected}
									<span class="text-[8px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded border border-amber-500/30 text-amber-400/90 bg-amber-500/10">Not retrieved</span>
								{/if}
							</div>
							<p class="text-[10px] text-gray-500 mt-1 leading-relaxed">{ref.context}</p>
						</div>
					</div>
					{#if ref.injected && ref.criteria_summary}
						<div class="px-3 py-2 space-y-2">
							{#if expanded.has(i)}
								<pre class="text-[9px] text-gray-400 leading-relaxed whitespace-pre-wrap font-sans max-h-48 overflow-y-auto custom-scrollbar">{ref.criteria_summary}{#if ref.criteria_summary_truncated}<span class="text-gray-600"> …</span>{/if}</pre>
								{#if ref.criteria_summary_truncated}
									<p class="text-[8px] text-gray-600">Excerpt only — full text is cached server-side.</p>
								{/if}
							{/if}
							<div class="flex flex-wrap items-center gap-2">
								<button
									type="button"
									class="text-[9px] font-semibold px-2 py-1 rounded-md bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/25 text-cyan-300/90 transition-colors"
									on:click={() => toggle(i)}
								>
									{expanded.has(i) ? 'Hide criteria' : 'Show criteria'}
								</button>
								<button
									type="button"
									class="text-[9px] font-semibold px-2 py-1 rounded-md bg-white/[0.04] hover:bg-white/[0.07] border border-white/[0.08] text-gray-400 transition-colors"
									on:click={() => copyExcerpt(ref)}
								>
									Copy excerpt
								</button>
								{#if ref.source_url}
									<a
										href={ref.source_url}
										target="_blank"
										rel="noopener noreferrer"
										class="text-[9px] font-medium text-cyan-500/80 hover:text-cyan-400 truncate max-w-[140px]"
									>{domainFromUrl(ref.source_url)}</a>
								{/if}
							</div>
						</div>
					{:else if !ref.injected}
						<div class="px-3 py-2 text-[9px] text-gray-600">No criteria text was added to this audit (fetch miss, timeout, or filter).</div>
					{/if}
				</div>
			{/each}
		</div>
	</div>
{/if}

<style>
	.custom-scrollbar {
		scrollbar-width: thin;
		scrollbar-color: rgba(34, 211, 238, 0.15) transparent;
	}
	.custom-scrollbar::-webkit-scrollbar {
		width: 3px;
	}
	.custom-scrollbar::-webkit-scrollbar-thumb {
		background: rgba(34, 211, 238, 0.15);
		border-radius: 2px;
	}
</style>
