<script lang="ts">
	/** /dev/copilot (Task A5): every Copilot card state from SYNTHETIC fixtures, no backend; and the whole case in
	 *  CopilotRail at wide and narrow widths. Guarded by +page.ts (dev routes only). */
	import '$lib/rail/rail.css';
	import { sections, wholeCase } from './gallery';
	import GallerySection from './GallerySection.svelte';

	let mode = $state<'gallery' | 'wide' | 'narrow'>('gallery');
	let theme = $state<'dark' | 'light'>('dark');
	const modes = [
		{ id: 'gallery', label: 'Gallery' },
		{ id: 'wide', label: 'Rail, wide' },
		{ id: 'narrow', label: 'Rail, narrow' }
	] as const;
</script>

<svelte:head><title>Copilot cards (dev)</title></svelte:head>

<main class="dv" class:dv--light={theme === 'light'}>
	<header class="dv-head">
		<h1>Copilot cards</h1>
		<div class="dv-modes" role="radiogroup" aria-label="View">
			{#each modes as m (m.id)}
				<label><input type="radio" name="mode" value={m.id} bind:group={mode} /> {m.label}</label>
			{/each}
		</div>
		<div class="dv-modes" role="radiogroup" aria-label="Theme">
			<label><input type="radio" name="theme" value="dark" bind:group={theme} /> Dark</label>
			<label><input type="radio" name="theme" value="light" bind:group={theme} /> Light</label>
		</div>
	</header>
	{#if mode === 'gallery'}
		<div class="dv-grid">
			{#each sections as s (s.id)}
				<GallerySection section={s} {theme} />
			{/each}
		</div>
	{:else}
		{#key mode}
			<GallerySection section={{ id: 'case', title: 'Whole case', ...wholeCase }} rail={mode} {theme} />
		{/key}
	{/if}
</main>

<style>
	.dv {
		min-height: 100vh;
		min-width: 100%;
		width: max-content;
		box-sizing: border-box;
		padding: 16px;
		background: #06060a;
		color: #e5e7eb;
		font-family: 'DM Sans', 'IBM Plex Sans', system-ui, sans-serif;
	}
	.dv--light {
		background: #f3f4f6;
		color: #1f2937;
	}
	.dv-head {
		display: flex;
		align-items: center;
		gap: 16px;
		margin-bottom: 16px;
	}
	.dv-head h1 {
		font-size: 1rem;
		margin: 0;
	}
	.dv-modes {
		display: flex;
		gap: 12px;
		font-size: 0.8125rem;
	}
	.dv-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(420px, 100%), 420px));
		gap: 20px;
		align-items: start;
	}
</style>
