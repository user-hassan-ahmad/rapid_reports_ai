<script lang="ts">
	import { templatesStore } from '$lib/stores/templates';
	import { settingsStore } from '$lib/stores/settings';

	// Integration spec §10: shown only to users who own at least one converted template (the conversion script stamps
	// template_config.converted_at), naming those templates; dismissal is remembered on the server (User.settings), so it
	// never returns on another browser. Hidden until the templates and the settings have loaded.
	type Tpl = { id: string; name?: string; template_config?: { converted_at?: string } | null };
	const converted = $derived((($templatesStore?.templates ?? []) as Tpl[]).filter((t) => !!t?.template_config?.converted_at));
	const settings = $derived(($settingsStore as { settings: Record<string, unknown> | null; loading: boolean }) ?? null);
	let dismissedHere = $state(false);
	const visible = $derived(converted.length > 0 && !!settings?.settings && settings.settings.banner_template_upgrade_dismissed !== true && !dismissedHere);

	// The settings store is loaded by the pages that need it; the banner asks for it only when it has something to say.
	$effect(() => {
		if (converted.length > 0 && !settings?.settings && !settings?.loading) void settingsStore.loadSettings();
	});

	function dismiss() {
		dismissedHere = true;
		void settingsStore.updateSettings({ banner_template_upgrade_dismissed: true });
	}
</script>

{#if visible}
	<div role="status" class="flex items-start gap-3 bg-sky-950/60 border-b border-sky-800 px-4 py-2 text-sm text-sky-100">
		<p class="flex-1">
			{converted.length === 1 ? 'Your template' : 'Your templates'}
			{converted.map((t) => t.name || 'Untitled').join(', ')}
			{converted.length === 1 ? 'has' : 'have'} been upgraded to the new workflow. If one doesn't feel right, create a
			fresh one from a few example reports.
		</p>
		<button class="text-sky-300 hover:text-sky-100" onclick={dismiss} aria-label="Dismiss">Dismiss</button>
	</div>
{/if}
