<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	
	const dispatch = createEventDispatcher();
	
	export let guidelinesCount: number = 0;
	/** Audit pipeline `guideline_references` count (Classification criteria in Copilot) */
	export let qaGuidelineCount: number = 0;
	/** True after a terminal audit state (complete / stale / error) */
	export let auditHasRun: boolean = false;
	/** True while POST /api/audit is in flight */
	export let auditLoading: boolean = false;
	export let isLoading: boolean = false;
	export let hasError: boolean = false;
	export let reportId: string | null = null;
	export let panelOpen: boolean = false;
	
	function openSidebar(tab?: 'guidelines' | 'comparison' | 'chat') {
		dispatch('openSidebar', { tab });
	}
	
	// Show cards whenever there's a reportId - they should persist even after loading completes
	$: showCards = Boolean(reportId);
	$: totalGuidelineRefs = guidelinesCount + qaGuidelineCount;
	$: showGuidelineBadge = totalGuidelineRefs > 0;
	$: showGuidelineSpinner = isLoading && guidelinesCount === 0 && qaGuidelineCount === 0;
</script>

{#if showCards}
	<div class="mb-6 space-y-3">
		<!-- Header -->
		
		<!-- Cards Grid — horizontal when container has room (~800px+), vertical when narrow (overflow) -->
		<div class="grid grid-cols-1 gap-3 @[800px]:grid-cols-3">
			<!-- Guidelines Card -->
			<button
				type="button"
				onclick={() => openSidebar('guidelines')}
				disabled={isLoading}
				class="group relative bg-gradient-to-br from-purple-900/40 to-purple-800/30 border border-purple-500/30 hover:border-purple-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
			>
				<div class="flex items-start justify-between mb-2">
					<div class="flex items-center gap-2">
						<div class="w-10 h-10 rounded-lg bg-purple-600/20 flex items-center justify-center">
							<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
							</svg>
						</div>
						<div class="text-left">
							<h4 class="text-sm font-semibold text-white group-hover:text-purple-300 transition-colors">Guidelines</h4>
							<p class="text-xs text-gray-400">Clinical references</p>
						</div>
					</div>
					{#if showGuidelineBadge}
						<span class="px-2 py-1 bg-purple-600 text-white text-xs font-bold rounded-full min-w-[28px] text-center">
							{totalGuidelineRefs}
						</span>
					{:else if showGuidelineSpinner || auditLoading}
						<div class="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
					{/if}
				</div>
				{#if guidelinesCount > 0 || qaGuidelineCount > 0 || auditHasRun || auditLoading}
					<div class="flex flex-wrap items-center gap-1.5 mt-2 text-left">
						{#if guidelinesCount > 0}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-purple-500/30 bg-purple-500/10 text-purple-200/90"
							>
								{guidelinesCount} supporting
							</span>
						{/if}
						{#if auditLoading}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-cyan-500/25 bg-cyan-500/10 text-cyan-200/80 inline-flex items-center gap-1"
							>
								<span class="inline-block w-2.5 h-2.5 border border-cyan-400/60 border-t-transparent rounded-full animate-spin"></span>
								QA: updating…
							</span>
						{:else if qaGuidelineCount > 0}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-cyan-500/30 bg-cyan-500/10 text-cyan-200/90"
							>
								{qaGuidelineCount} QA criteria
							</span>
						{:else if auditHasRun}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-white/[0.1] bg-white/[0.04] text-gray-400"
							>
								0 QA criteria
							</span>
						{:else}
							<span class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-dashed border-gray-600/60 bg-transparent text-gray-500">
								QA: run audit
							</span>
						{/if}
					</div>
				{:else if isLoading}
					<p class="text-[10px] text-gray-500 mt-2 text-left">Loading supporting references…</p>
					<div class="flex flex-wrap items-center gap-1.5 mt-1.5 text-left">
						{#if auditLoading}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-cyan-500/25 bg-cyan-500/10 text-cyan-200/80 inline-flex items-center gap-1"
							>
								<span class="inline-block w-2.5 h-2.5 border border-cyan-400/60 border-t-transparent rounded-full animate-spin"></span>
								QA: updating…
							</span>
						{:else if auditHasRun}
							<span
								class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-white/[0.1] bg-white/[0.04] text-gray-400"
							>
								{qaGuidelineCount} QA criteria
							</span>
						{:else}
							<span class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-dashed border-gray-600/60 bg-transparent text-gray-500">
								QA: run audit
							</span>
						{/if}
					</div>
				{:else}
					<div class="flex flex-wrap items-center gap-1.5 mt-2 text-left">
						<span class="text-[9px] font-semibold px-2 py-0.5 rounded-md border border-dashed border-gray-600/60 bg-transparent text-gray-500">
							QA: run audit
						</span>
					</div>
				{/if}
				<p class="text-xs text-gray-400 mt-2 text-left">View guidelines for this report →</p>
			</button>
			
			<!-- Comparison Card -->
			<button
				type="button"
				onclick={() => openSidebar('comparison')}
				disabled={isLoading}
				class="group relative bg-gradient-to-br from-orange-900/40 to-orange-800/30 border border-orange-500/30 hover:border-orange-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-orange-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
			>
				<div class="flex items-start justify-between mb-2">
					<div class="flex items-center gap-2">
						<div class="w-10 h-10 rounded-lg bg-orange-600/20 flex items-center justify-center">
							<svg class="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
							</svg>
						</div>
						<div class="text-left">
							<h4 class="text-sm font-semibold text-white group-hover:text-orange-300 transition-colors">Comparison</h4>
							<p class="text-xs text-gray-400">Interval analysis</p>
						</div>
					</div>
				</div>
				<p class="text-xs text-gray-400 mt-2 text-left">Compare with prior reports</p>
			</button>
			
			<!-- Chat Card -->
			<button
				type="button"
				onclick={() => openSidebar('chat')}
				disabled={isLoading}
				class="group relative bg-gradient-to-br from-blue-900/40 to-blue-800/30 border border-blue-500/30 hover:border-blue-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
			>
				<div class="flex items-start justify-between mb-2">
					<div class="flex items-center gap-2">
						<div class="w-10 h-10 rounded-lg bg-blue-600/20 flex items-center justify-center">
							<svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
							</svg>
						</div>
						<div class="text-left">
							<h4 class="text-sm font-semibold text-white group-hover:text-blue-300 transition-colors">Chat</h4>
							<p class="text-xs text-gray-400">Ask questions & apply edits</p>
						</div>
					</div>
				</div>
				<p class="text-xs text-gray-400 mt-2 text-left">Explore insights and modify your report</p>
			</button>
		</div>
		
		{#if hasError}
			<div class="mt-3 px-4 py-2 bg-red-500/10 border border-red-500/30 rounded-lg">
				<p class="text-xs text-red-400">Failed to load enhancements. Click any card to retry.</p>
			</div>
		{/if}
	</div>
{/if}

