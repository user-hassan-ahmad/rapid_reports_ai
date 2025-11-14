<script>
	import { createEventDispatcher } from 'svelte';
	import { fade, slide } from 'svelte/transition';
	import { user } from '../stores/auth';
	import logo from '../assets/radflow-logo.png';

	export let activeTab = 'auto';
	export let isCollapsed = false;
	
	const dispatch = createEventDispatcher();

	function handleTabChange(tab) {
		dispatch('tabChange', tab);
	}

	function handleLogout() {
		dispatch('logout');
	}

	function toggleCollapse() {
		isCollapsed = !isCollapsed;
	}
</script>

<!-- Mobile Overlay Backdrop -->
{#if !isCollapsed}
	<div 
		class="md:hidden fixed inset-0 bg-black/50 z-40"
		onclick={() => isCollapsed = true}
		transition:fade={{ duration: 200 }}
	></div>
{/if}

<!-- Sidebar -->
<aside 
	class="fixed left-0 top-0 h-screen bg-black/90 backdrop-blur-xl z-50 md:z-30 transition-all duration-300 overflow-hidden {isCollapsed ? 'md:w-16 w-0 pointer-events-none md:pointer-events-auto border-r-0 md:border-r border-white/10' : 'md:w-64 w-64 border-r border-white/10'} md:translate-x-0 {isCollapsed ? '-translate-x-full md:translate-x-0' : 'translate-x-0'}"
	transition:slide={{ duration: 300, axis: 'x' }}
>
	<div class="flex flex-col h-full overflow-hidden">
		<!-- Logo & Title -->
		<div class="flex items-center gap-3 border-b border-white/10 transition-all duration-300 {isCollapsed ? 'px-2 py-3 justify-center' : 'px-4 py-4'}">
			<div class="flex-shrink-0 {isCollapsed ? 'w-full flex justify-center' : ''}">
				<img src={logo} alt="RadFlow" class="transition-all duration-300 {isCollapsed ? 'h-10 w-10 object-contain max-w-full' : 'h-16 w-auto'}" />
			</div>
			{#if !isCollapsed}
				<h1 class="text-2xl font-bold text-white flex-1 min-w-0 leading-tight">
					RadFlow
				</h1>
			{/if}
		</div>

		<!-- Navigation -->
		<nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
			<button
				onclick={() => { handleTabChange('auto'); if (window.innerWidth < 768) isCollapsed = true; }}
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 {activeTab === 'auto' ? 'bg-purple-600/20 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
				title="Auto Report Generation"
			>
				<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
				</svg>
				{#if !isCollapsed}<span class="text-sm font-medium">Generate Quick Report</span>{/if}
			</button>

			<button
				onclick={() => { handleTabChange('templated'); if (window.innerWidth < 768) isCollapsed = true; }}
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 {activeTab === 'templated' ? 'bg-purple-600/20 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
				title="Templated Reports"
			>
				<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
				</svg>
				{#if !isCollapsed}<span class="text-sm font-medium">Generate Custom Report</span>{/if}
			</button>

			<button
				onclick={() => { handleTabChange('templates'); if (window.innerWidth < 768) isCollapsed = true; }}
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 {activeTab === 'templates' ? 'bg-purple-600/20 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
				title="Manage Templates"
			>
				<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
				</svg>
				{#if !isCollapsed}<span class="text-sm font-medium">Manage My Templates</span>{/if}
			</button>

			<button
				onclick={() => { handleTabChange('history'); if (window.innerWidth < 768) isCollapsed = true; }}
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 {activeTab === 'history' ? 'bg-purple-600/20 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
				title="History"
			>
				<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				{#if !isCollapsed}<span class="text-sm font-medium">History</span>{/if}
			</button>

			<button
				onclick={() => { handleTabChange('settings'); if (window.innerWidth < 768) isCollapsed = true; }}
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 {activeTab === 'settings' ? 'bg-purple-600/20 text-white' : 'text-gray-400 hover:bg-white/5 hover:text-white'}"
				title="Settings"
			>
				<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
				</svg>
				{#if !isCollapsed}<span class="text-sm font-medium">Settings</span>{/if}
			</button>
		</nav>

		<!-- User Section & Collapse Button -->
		<div class="px-3 py-4 border-t border-white/10 space-y-2">
			{#if !isCollapsed && $user}
				<div class="px-3 py-2 text-xs text-gray-500">
					<p class="font-medium text-white">{$user.full_name || 'User'}</p>
					<p class="truncate">{$user.email}</p>
				</div>
			{/if}
			
			<div class="flex items-center gap-2">
				<button
					onclick={handleLogout}
					class="flex-1 flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-red-400 hover:bg-red-500/10 hover:text-red-300"
					title="Logout"
				>
					<svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
					</svg>
					{#if !isCollapsed}<span class="text-sm font-medium">Logout</span>{/if}
				</button>
				
				<!-- Collapse Toggle (Desktop only) -->
				<button
					onclick={toggleCollapse}
					class="hidden md:flex items-center justify-center w-8 h-8 rounded-lg transition-all duration-200 text-gray-400 hover:bg-white/5 hover:text-white"
					title="{isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						{#if isCollapsed}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						{:else}
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
						{/if}
					</svg>
				</button>
			</div>
		</div>
	</div>
</aside>

<!-- Mobile Hamburger Button -->
<button
	onclick={() => isCollapsed = false}
	class="md:hidden fixed top-4 left-4 z-40 p-2 rounded-lg bg-black/90 backdrop-blur-xl border border-white/10 text-white"
	title="Menu"
>
	<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
		<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
	</svg>
</button>

<!-- Desktop Expand Button (when collapsed) -->
{#if isCollapsed}
	<button
		onclick={() => isCollapsed = false}
		class="hidden md:flex fixed left-16 bottom-4 z-50 p-2 rounded-lg bg-black/90 backdrop-blur-xl border border-white/10 text-white opacity-50 hover:opacity-100 hover:bg-white/5 transition-all shadow-lg"
		title="Expand sidebar"
	>
		<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
		</svg>
	</button>
{/if}

<style>
	:global(.translate-x-full) {
		transform: translateX(100%);
	}
</style>

