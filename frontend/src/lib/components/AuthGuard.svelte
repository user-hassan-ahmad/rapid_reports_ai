<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAuthenticated } from '$lib/stores/auth';
	import { browser } from '$app/environment';

	let checkingAuth = browser; // Start as true on client to prevent flash
	
	// Redirect if not authenticated
	onMount(() => {
		console.log('🛡️ AuthGuard mounted, isAuthenticated:', $isAuthenticated);
		// Give a small delay to allow auth store to initialize
		setTimeout(() => {
			if (!$isAuthenticated) {
				console.log('❌ Not authenticated, redirecting to /login');
				checkingAuth = false;
				goto('/login');
			} else {
				console.log('✅ Authenticated, rendering content');
				checkingAuth = false;
			}
		}, 50); // Small delay to allow auth store to sync
	});

	// Don't render content if not authenticated
	$: shouldRender = $isAuthenticated && !checkingAuth;
	$: console.log('🛡️ AuthGuard shouldRender:', shouldRender, 'isAuthenticated:', $isAuthenticated, 'checkingAuth:', checkingAuth);
</script>

{#if checkingAuth}
	<!-- Skeleton loader while checking auth -->
	<div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950">
		<div class="flex flex-col items-center gap-3">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
			<p class="text-sm text-gray-400">Loading...</p>
		</div>
	</div>
{:else if shouldRender}
	<slot />
{:else}
	<div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950">
		<div class="flex flex-col items-center gap-3">
			<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
			<p class="text-sm text-gray-400">Redirecting to login...</p>
		</div>
	</div>
{/if}

