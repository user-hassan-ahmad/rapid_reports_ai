<script lang="ts">
	// Dev only (requireDevRoute): replay a pasted dictation sentence by sentence through the real
	// stack endpoints and show the grouped view, for the hand read (plan Task 20).
	import { token } from '$lib/stores/auth';
	import HybridStackView from '$lib/hybrid-stack/HybridStackView.svelte';
	import { fetchSchema, postClose, postGroup } from '$lib/hybrid-stack/api';
	import { moveUnit } from '$lib/hybrid-stack/stackState';
	import type { StackSchema, StackUnit } from '$lib/hybrid-stack/types';

	let scanType = $state('CT abdomen and pelvis with contrast');
	let history = $state('');
	let templateId = $state('');
	let dictation = $state('');
	let schema: StackSchema | null = $state(null);
	let units: StackUnit[] = $state([]);
	let pills: string[] = $state([]);
	let status = $state('');

	async function run() {
		try {
			status = 'schema…';
			const s = await fetchSchema($token, { scan_type: scanType, clinical_history: history, template_id: templateId || null });
			schema = s;
			units = [];
			const sentences = dictation.split(/(?<=[.?!])\s+/).filter((x) => x.trim());
			let text = '';
			for (const sentence of sentences) {
				text = text ? `${text} ${sentence}` : sentence;
				status = `grouping ${text.length} chars…`;
				const res = await postGroup($token, { scan_type: scanType, text, regions: s.regions, previous: units });
				units = res.units;
				pills = res.pills;
			}
			const closed = await postClose($token, { units, regions: s.regions });
			units = closed.units;
			pills = closed.pills;
			status = `done · ${s.source}${s.provisional ? ' (provisional)' : ''} · ${s.key}`;
		} catch (e) {
			status = `error: ${e instanceof Error ? e.message : String(e)}`;
		}
	}
</script>

<div class="mx-auto max-w-5xl p-6 space-y-4">
	<h1 class="text-lg font-semibold">Hybrid stack (dev)</h1>
	<div class="grid grid-cols-3 gap-2">
		<input class="border rounded px-2 py-1" bind:value={scanType} placeholder="Scan type" />
		<input class="border rounded px-2 py-1" bind:value={history} placeholder="Clinical history" />
		<input class="border rounded px-2 py-1" bind:value={templateId} placeholder="Template id (optional)" />
	</div>
	<textarea class="w-full h-40 border rounded p-2 text-sm" bind:value={dictation} placeholder="Paste dictation"></textarea>
	<button type="button" class="rounded bg-slate-800 px-3 py-1 text-white text-sm" onclick={run}>Replay</button>
	<p class="text-xs text-slate-500">{status}</p>
	{#if schema}
		<p class="text-xs">Pills: {pills.join(' · ') || '—'}</p>
		<HybridStackView {units} groups={schema.groups} onSelect={() => {}} onMove={(id, g) => (units = moveUnit(units, id, g))} />
	{/if}
</div>
