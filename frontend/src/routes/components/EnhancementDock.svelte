<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import pilotIcon from '$lib/assets/pilot.png';
	
	const dispatch = createEventDispatcher();
	
	export let guidelinesCount: number = 0;
	export let isLoading: boolean = false;
	export let hasError: boolean = false;
	export let reportId: string | null = null;
	
	let isExpanded = false;
	let showTooltip: string | null = null;
	
	function openSidebar(tab?: 'guidelines' | 'comparison' | 'chat') {
		dispatch('openSidebar', { tab });
	}
	
	function toggleExpanded() {
		isExpanded = !isExpanded;
	}
</script>

<!-- Floating Enhancement Dock -->
<div 
	class="fixed bottom-6 right-6 z-[9998] flex flex-col items-end gap-3 transition-all duration-300"
	onmouseenter={() => isExpanded = true}
	onmouseleave={() => isExpanded = false}
>
	<!-- Expanded View -->
	{#if isExpanded}
		<div class="bg-gray-900/95 backdrop-blur-xl border border-gray-700/50 rounded-2xl shadow-2xl p-3 flex flex-col gap-2 min-w-[200px]">
			<!-- Header -->
			<div class="flex items-center gap-2 px-2 pb-2 border-b border-gray-700/50">
				<img src={pilotIcon} alt="Copilot" class="w-6 h-6 brightness-0 invert" />
				<span class="text-sm font-semibold text-white">Copilot</span>
			</div>
			
			<!-- Guidelines Button -->
			<button
				type="button"
				onclick={() => openSidebar('guidelines')}
				disabled={!reportId || isLoading}
				class="flex items-center justify-between px-4 py-2.5 rounded-lg bg-gray-800/50 hover:bg-purple-600/20 border border-gray-700/50 hover:border-purple-500/50 transition-all duration-200 group disabled:opacity-50 disabled:cursor-not-allowed"
				onmouseenter={() => showTooltip = 'guidelines'}
				onmouseleave={() => showTooltip = null}
			>
				<div class="flex items-center gap-3">
					<svg class="w-5 h-5 text-purple-400 group-hover:text-purple-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
					</svg>
					<span class="text-sm font-medium text-gray-200 group-hover:text-white">Guidelines</span>
				</div>
				{#if guidelinesCount > 0}
					<span class="px-2 py-0.5 bg-purple-600 text-white text-xs font-semibold rounded-full min-w-[24px] text-center">
						{guidelinesCount}
					</span>
				{:else if isLoading}
					<div class="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
				{/if}
			</button>
			
			<!-- Comparison Button -->
			<button
				type="button"
				onclick={() => openSidebar('comparison')}
				disabled={!reportId || isLoading}
				class="flex items-center justify-between px-4 py-2.5 rounded-lg bg-gray-800/50 hover:bg-orange-600/20 border border-gray-700/50 hover:border-orange-500/50 transition-all duration-200 group disabled:opacity-50 disabled:cursor-not-allowed"
			>
				<div class="flex items-center gap-3">
					<svg class="w-5 h-5 text-orange-400 group-hover:text-orange-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
					</svg>
					<span class="text-sm font-medium text-gray-200 group-hover:text-white">Comparison</span>
				</div>
			</button>
			
			<!-- Chat Button -->
			<button
				type="button"
				onclick={() => openSidebar('chat')}
				disabled={!reportId || isLoading}
				class="flex items-center justify-between px-4 py-2.5 rounded-lg bg-gray-800/50 hover:bg-blue-600/20 border border-gray-700/50 hover:border-blue-500/50 transition-all duration-200 group disabled:opacity-50 disabled:cursor-not-allowed"
			>
				<div class="flex items-center gap-3">
					<svg class="w-5 h-5 text-blue-400 group-hover:text-blue-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
					</svg>
					<span class="text-sm font-medium text-gray-200 group-hover:text-white">Chat</span>
				</div>
			</button>
			
			{#if hasError}
				<div class="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded-lg">
					<p class="text-xs text-red-400">Failed to load enhancements</p>
				</div>
			{/if}
		</div>
	{:else}
		<!-- Collapsed View - Floating Button -->
		<button
			type="button"
			onclick={toggleExpanded}
			class="w-14 h-14 rounded-full bg-gradient-to-br from-purple-600 to-blue-600 shadow-lg shadow-purple-500/50 hover:shadow-xl hover:shadow-purple-500/60 transition-all duration-300 flex items-center justify-center group relative"
			aria-label="Open Copilot enhancements"
		>
			<img src={pilotIcon} alt="Copilot" class="w-8 h-8 brightness-0 invert" />
			{#if guidelinesCount > 0}
				<span class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 rounded-full border-2 border-gray-900 flex items-center justify-center">
					<span class="text-[10px] font-bold text-white">{guidelinesCount > 9 ? '9+' : guidelinesCount}</span>
				</span>
			{/if}
			{#if isLoading}
				<div class="absolute inset-0 rounded-full border-2 border-white/30 border-t-white animate-spin"></div>
			{/if}
		</button>
	{/if}
</div>

<style>
	/* Smooth animations */
	button {
		transition: all 0.2s ease;
	}
</style>

