<script lang="ts">
	import { marked } from 'marked';
	import { onDestroy } from 'svelte';
	import { fade, scale } from 'svelte/transition';

	interface GuidelineReference {
		system: string;
		context: string;
		type: string;
		source_url?: string | null;
		criteria_summary?: string | null;
		criteria_summary_truncated?: boolean;
		injected: boolean;
	}

	interface AuditCriterion {
		criterion: string;
		status: string;
		rationale: string;
		recommendation?: string | null;
	}

	const criterionLabels: Record<string, string> = {
		recommendations: 'Recommendations',
		anatomical_accuracy: 'Anatomical Accuracy',
		report_completeness: 'Report Completeness',
		clinical_relevance: 'Clinical Relevance',
		clinical_flagging: 'Clinical Flagging',
		diagnostic_fidelity: 'Diagnostic Fidelity',
	};

	export let references: GuidelineReference[] = [];
	// Pass the full criteria array from the audit result. getRelatedFlag filters to
	// non-pass only internally, so passing all criteria (including passes) is fine.
	export let auditCriteria: AuditCriterion[] = [];
	// When true, suppresses the outer wrapper (header label + top border/margin) so
	// the component can be embedded inside a parent that provides its own section header.
	export let compact: boolean = false;
	/** When set, shows an "Ask →" control to prefill Copilot chat */
	export let onAskAbout: ((text: string) => void) | undefined = undefined;

	let expanded = new Set<number>();
	let copiedIndex: number | null = null;
	let copyResetTimer: ReturnType<typeof setTimeout> | null = null;

	function clearCopyTimer() {
		if (copyResetTimer) {
			clearTimeout(copyResetTimer);
			copyResetTimer = null;
		}
	}

	onDestroy(() => clearCopyTimer());

	function toggle(i: number) {
		const n = new Set(expanded);
		if (n.has(i)) n.delete(i);
		else n.add(i);
		expanded = n;
	}

	// Returns the criterion key of the first non-pass criterion whose rationale or
	// recommendation mentions the guideline system name. Non-pass filter prevents
	// pass rationales like "Lung-RADS correctly applied" from producing false chips.
	function getRelatedFlag(system: string): string | null {
		if (!auditCriteria.length) return null;
		const systemLower = system.toLowerCase();
		const token = systemLower.split(/\s+/)[0];
		return auditCriteria
			.filter(c => c.status !== 'pass')
			.find(c => {
				const hay = `${c.rationale} ${c.recommendation ?? ''}`.toLowerCase();
				return hay.includes(systemLower) || (token.length >= 4 && hay.includes(token));
			})?.criterion ?? null;
	}

	function domainFromUrl(url: string): string {
		try {
			return new URL(url).hostname.replace(/^www\./, '');
		} catch {
			return url;
		}
	}

	async function copyExcerpt(ref: GuidelineReference, index: number) {
		const parts = [`[${ref.system}]`, ref.context];
		if (ref.criteria_summary) parts.push('', ref.criteria_summary);
		if (ref.criteria_summary_truncated) parts.push('', '(Excerpt — see source for full criteria.)');
		try {
			await navigator.clipboard.writeText(parts.join('\n'));
			clearCopyTimer();
			copiedIndex = index;
			copyResetTimer = setTimeout(() => {
				copiedIndex = null;
				copyResetTimer = null;
			}, 2000);
		} catch {
			/* ignore */
		}
	}
</script>

{#if references.length > 0}
	<div class="{compact ? '' : 'mt-4 pt-4 border-t border-cyan-500/15'}" aria-label="Reference guidelines">
		{#if !compact}
			<div class="flex items-center gap-2 mb-3">
				<svg class="w-3.5 h-3.5 text-cyan-400/90 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
				</svg>
				<span class="text-[9px] font-semibold uppercase tracking-widest text-cyan-400/80">Reference guidelines</span>
			</div>
			<p class="text-[9px] text-gray-600 leading-relaxed mb-3">
				Structural reference used as QA context — not automated classification.
			</p>
		{/if}
		<div class="space-y-2.5">
	{#each references as ref, i (ref.system + '-' + i)}
			{@const relatedFlag = getRelatedFlag(ref.system)}
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
							{#if relatedFlag}
								<span class="text-[8px] font-semibold px-1.5 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 text-amber-300/90">
									⚠ Related to {criterionLabels[relatedFlag] ?? relatedFlag}
								</span>
							{/if}
						</div>
						<p class="text-[10px] text-gray-500 mt-1 leading-relaxed">{ref.context}</p>
					</div>
				</div>
					{#if ref.injected && ref.criteria_summary}
						<div class="px-3 py-2 space-y-2">
						{#if expanded.has(i)}
							<div class="text-[10px] text-gray-400 leading-relaxed max-h-48 overflow-y-auto custom-scrollbar
								prose prose-invert max-w-none
								prose-p:my-1 prose-p:leading-relaxed prose-p:text-[10px]
								prose-strong:text-gray-300 prose-strong:font-semibold
								prose-ul:my-1 prose-ul:pl-3.5 prose-ul:space-y-0.5
								prose-ol:my-1 prose-ol:pl-3.5 prose-ol:space-y-0.5
								prose-li:text-gray-400 prose-li:leading-relaxed prose-li:pl-0 prose-li:text-[10px]
								prose-headings:text-gray-300 prose-headings:font-semibold prose-headings:text-[10px] prose-headings:mt-2 prose-headings:mb-1">
							{@html marked(ref.criteria_summary)}
						</div>
						{/if}
							<div class="flex flex-wrap items-center gap-2">
								<button
									type="button"
									class="text-[9px] font-semibold px-2 py-1 rounded-md bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/25 text-cyan-300/90 transition-colors"
									on:click={() => toggle(i)}
								>
									{expanded.has(i) ? 'Hide criteria' : 'Show criteria'}
								</button>
								{#if onAskAbout}
									<button
										type="button"
										class="text-[9px] font-semibold px-2 py-1 rounded-md border border-purple-500/25 text-purple-300/90 hover:bg-purple-500/15 transition-colors"
										on:click={() => onAskAbout?.(`[${ref.system}] ${ref.context}`.slice(0, 800))}
									>
										Ask →
									</button>
								{/if}
								<button
									type="button"
									class="text-[9px] font-semibold px-2 py-1 rounded-md border min-w-[92px] justify-center inline-flex items-center gap-1 transition-all duration-300 ease-out
										{copiedIndex === i
										? 'bg-emerald-500/[0.14] border-emerald-500/40 text-emerald-300 shadow-[0_0_14px_-4px_rgba(52,211,153,0.45)]'
										: 'bg-white/[0.04] hover:bg-white/[0.07] border-white/[0.08] text-gray-400'}"
									class:copy-excerpt-success={copiedIndex === i}
									on:click={() => copyExcerpt(ref, i)}
								>
									{#if copiedIndex === i}
										<span class="inline-flex items-center gap-1" in:scale={{ duration: 220, start: 0.88, opacity: 0 }}>
											<svg
												class="w-3 h-3 text-emerald-400 flex-shrink-0"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
												aria-hidden="true"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2.5"
													d="M5 13l4 4L19 7"
												/>
											</svg>
											<span in:fade={{ duration: 180 }}>Copied</span>
										</span>
									{:else}
										<span in:fade={{ duration: 120 }}>Copy excerpt</span>
									{/if}
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
	@keyframes copy-excerpt-ring {
		0% {
			box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.35);
		}
		100% {
			box-shadow: 0 0 0 7px rgba(52, 211, 153, 0);
		}
	}
	.copy-excerpt-success {
		animation: copy-excerpt-ring 0.65s ease-out 1;
	}

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
