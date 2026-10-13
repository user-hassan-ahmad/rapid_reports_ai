<script lang="ts">
	import { onMount } from 'svelte';

	const KEY = 'rr_banner_template_upgrade_2026_10';
	// Starts hidden so SSR and dismissed users never flash it; storage is read on mount.
	let visible = $state(false);

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

{#if visible}
	<div role="status" class="flex items-start gap-3 bg-sky-950/60 border-b border-sky-800 px-4 py-2 text-sm text-sky-100">
		<p class="flex-1">
			Your templates have been upgraded to the new workflow. If a template doesn't feel right, you can create a
			fresh one from a few example reports.
		</p>
		<button class="text-sky-300 hover:text-sky-100" onclick={dismiss} aria-label="Dismiss">Dismiss</button>
	</div>
{/if}
