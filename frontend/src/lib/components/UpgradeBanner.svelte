<script lang="ts">
	import { onMount } from 'svelte';
	import { templatesStore } from '$lib/stores/templates';

	const KEY = 'rr_banner_template_upgrade_2026_10';
	// Starts hidden so SSR and dismissed users never flash it; storage is read on mount.
	let visible = $state(false);
	// Only template owners see it, from the app-wide templates store (no fetch of its own): hidden until the
	// templates have loaded, on a load error, and on pages that never load them.
	const ownsTemplate = $derived(($templatesStore?.templates?.length ?? 0) > 0);

	onMount(() => {
		try {
			visible = localStorage.getItem(KEY) !== '1';
		} catch {
			visible = true;
		}
	});

	function dismiss() {
		visible = false;
		try {
			localStorage.setItem(KEY, '1');
		} catch {
			/* storage blocked */
		}
	}
</script>

{#if visible && ownsTemplate}
	<div role="status" class="flex items-start gap-3 bg-sky-950/60 border-b border-sky-800 px-4 py-2 text-sm text-sky-100">
		<p class="flex-1">
			Your templates have been upgraded to the new workflow. If a template doesn't feel right, you can create a
			fresh one from a few example reports.
		</p>
		<button class="text-sky-300 hover:text-sky-100" onclick={dismiss} aria-label="Dismiss">Dismiss</button>
	</div>
{/if}
