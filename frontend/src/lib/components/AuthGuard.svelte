<script>
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAuthenticated } from '$lib/stores/auth';

	// Redirect if not authenticated
	onMount(() => {
		console.log('🛡️ AuthGuard mounted, isAuthenticated:', $isAuthenticated);
		if (!$isAuthenticated) {
			console.log('❌ Not authenticated, redirecting to /login');
			goto('/login');
		} else {
			console.log('✅ Authenticated, rendering content');
		}
	});

	// Don't render content if not authenticated
	$: shouldRender = $isAuthenticated;
	$: console.log('🛡️ AuthGuard shouldRender:', shouldRender, 'isAuthenticated:', $isAuthenticated);
</script>

{#if shouldRender}
	<slot />
{:else}
	<div class="p-6 text-center">
		<p class="text-slate-600">Redirecting to login...</p>
	</div>
{/if}

