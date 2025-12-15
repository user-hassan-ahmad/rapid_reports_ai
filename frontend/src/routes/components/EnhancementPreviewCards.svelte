<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import pilotIcon from '$lib/assets/pilot.png';
	
	const dispatch = createEventDispatcher();
	
	export let guidelinesCount: number = 0;
	export let isLoading: boolean = false;
	export let hasError: boolean = false;
	export let reportId: string | null = null;
	
	function openSidebar(tab?: 'guidelines' | 'comparison' | 'chat') {
		dispatch('openSidebar', { tab });
	}
	
	// Show cards whenever there's a reportId - they should persist even after loading completes
	$: showCards = Boolean(reportId);
</script>

{#if showCards}
	<div class="mb-6 space-y-3">
		<!-- Header -->
		<!--
		<div class="flex items-center gap-2 mb-2">
			<img src={pilotIcon} alt="Copilot" class="w-5 h-5 brightness-0 invert" />
			<h3 class="text-sm font-semibold text-white">Copilot Assistance</h3>
		</div>
		-->
		
		<!-- Cards Grid -->
		<div class="grid grid-cols-1 md:grid-cols-3 gap-3">
			<!-- Guidelines Card -->
			<button
				type="button"
				onclick={() => openSidebar('guidelines')}
				disabled={isLoading}
				class="group relative bg-gradient-to-br from-purple-900/20 to-purple-800/10 backdrop-blur-xl border border-purple-500/30 hover:border-purple-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
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
					{#if guidelinesCount > 0}
						<span class="px-2 py-1 bg-purple-600 text-white text-xs font-bold rounded-full min-w-[28px] text-center">
							{guidelinesCount}
						</span>
					{:else if isLoading}
						<div class="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
					{/if}
				</div>
				{#if guidelinesCount > 0}
					<p class="text-xs text-gray-400 mt-2 text-left">View {guidelinesCount} guideline{guidelinesCount !== 1 ? 's' : ''} for this report</p>
				{:else if isLoading}
					<p class="text-xs text-gray-400 mt-2 text-left">Loading guidelines...</p>
				{:else}
					<p class="text-xs text-gray-400 mt-2 text-left">Click to load guidelines</p>
				{/if}
			</button>
			
			<!-- Comparison Card -->
			<button
				type="button"
				onclick={() => openSidebar('comparison')}
				disabled={isLoading}
				class="group relative bg-gradient-to-br from-orange-900/20 to-orange-800/10 backdrop-blur-xl border border-orange-500/30 hover:border-orange-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-orange-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
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
				class="group relative bg-gradient-to-br from-blue-900/20 to-blue-800/10 backdrop-blur-xl border border-blue-500/30 hover:border-blue-500/60 rounded-xl p-4 transition-all duration-300 hover:shadow-lg hover:shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
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

