<script lang="ts">
	/**
	 * The review rail's Guidelines tab: today's guidelines panel (GuidelinesPanel) fed by POST /enhance through
	 * lib/guidelines/enhance.ts (cached per report, one request shared with the Copilot sidebar). It never touches the
	 * report itself: "Ask" goes out through the rail's command path (`ask_chat` with the text), so the question lands
	 * in the rail chat and any edit from it is applied and tracked like every other item.
	 */
	import { loadEnhancement, peekEnhancement, type EnhancementData } from '$lib/guidelines/enhance';
	import GuidelinesPanel from './GuidelinesPanel.svelte';
	import type { RailCommand } from './ItemRow.svelte';

	let {
		reportId,
		onCommand
	}: {
		reportId: string;
		onCommand: RailCommand;
	} = $props();

	let data = $state<EnhancementData | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function load(id: string, force = false): Promise<void> {
		const hit = force ? undefined : peekEnhancement(id);
		if (hit) {
			data = hit;
			error = null;
			return;
		}
		loading = true;
		error = null;
		try {
			const d = await loadEnhancement(id, { force });
			if (id === reportId) data = d;
		} catch (e) {
			if (id === reportId) error = e instanceof Error ? e.message : String(e);
		} finally {
			if (id === reportId) loading = false;
		}
	}

	$effect(() => {
		const id = reportId;
		data = null;
		void load(id);
	});

	function ask(text: string): void {
		onCommand('ask_chat', undefined, { text: `Re: ${text} — `, source: 'guidelines' });
	}
</script>

<div class="rv-guidelines">
	<GuidelinesPanel
		guidelines={data?.guidelines ?? []}
		urgencySignals={data?.urgencySignals ?? []}
		{loading}
		loaded={!!data}
		{error}
		lookupFailed={data?.lookupFailed ?? false}
		onRetry={() => load(reportId, true)}
		onAsk={ask}
	/>
</div>

<style>
	.rv-guidelines {
		padding: 4px 0 8px;
	}
</style>
