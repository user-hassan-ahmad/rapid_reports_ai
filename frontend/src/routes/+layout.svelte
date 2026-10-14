<script>
	import '../app.css';
	import favicon from '$lib/assets/radflow-logo.png';
	import UpgradeBanner from '$lib/components/UpgradeBanner.svelte';
	import { isAuthenticated } from '$lib/stores/auth';
	import { browser, dev } from '$app/environment';
	import { get } from 'svelte/store';
	import { stackMode } from '$lib/hybrid-stack/mode';
	import { installAppLegacyGuard } from '$lib/hybrid-stack/legacyGuard';

	let { children } = $props();

	// The client tripwire (spec §9.5): once, for the whole app; it warns only while the stack is latched.
	if (browser) installAppLegacyGuard(() => get(stackMode), dev);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if $isAuthenticated}
	<UpgradeBanner />
{/if}
{@render children?.()}
