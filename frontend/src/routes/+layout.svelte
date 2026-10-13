<script>
	import '../app.css';
	import favicon from '$lib/assets/radflow-logo.png';
	import UpgradeBanner from '$lib/components/UpgradeBanner.svelte';
	import { isAuthenticated } from '$lib/stores/auth';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if $isAuthenticated}
	<UpgradeBanner />
{/if}
{@render children?.()}
