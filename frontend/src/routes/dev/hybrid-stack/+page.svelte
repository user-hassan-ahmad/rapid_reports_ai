<script lang="ts">
	// Dev only (requireDevRoute): replay a pasted dictation sentence by sentence through the real
	// stack endpoints and show the grouped view, for the hand read (plan Task 20).
	import { token } from '$lib/stores/auth';
	import HybridStackView from '$lib/hybrid-stack/HybridStackView.svelte';
	import { fetchSchema, postClose, postGroup, postItems } from '$lib/hybrid-stack/api';
	import { abnormalAll } from '$lib/hybrid-stack/items';
	import { moveUnit } from '$lib/hybrid-stack/stackState';
	import type { StackItem, StackSchema, StackUnit } from '$lib/hybrid-stack/types';
	import { findingsText } from '$lib/hybrid-stack/regionState';
	import CopilotRail from '$lib/copilot/cards/CopilotRail.svelte';
	import { createCopilotSession, type CopilotSession, type CopilotState } from '$lib/copilot/session';

	let scanType = $state('CT abdomen and pelvis with contrast');
	let history = $state('');
	let templateId = $state('');
	let dictation = $state('');
	let schema: StackSchema | null = $state(null);
	let units: StackUnit[] = $state([]);
	let pills: string[] = $state([]);
	let status = $state('');
	let items: StackItem[] = $state([]);
	let tapped: string[] = $state([]);
	let removed: string[] = $state([]);

	// Copilot (Task A7): off until ticked, so the page sends no guideline request by default. Each replayed sentence
	// is one round; "recording" decides whether the last finding still counts as growing (unticking it is the stop).
	let copilotOn = $state(false);
	let recording = $state(true);
	let copilot: CopilotSession | null = $state.raw(null);
	let cs: CopilotState | null = $state.raw(null);
	$effect(() => {
		if (!copilotOn) return;
		const sess = createCopilotSession();
		copilot = sess;
		const unsub = sess.state.subscribe((v) => (cs = v));
		return () => {
			unsub();
			sess.destroy();
			copilot = null;
			cs = null;
		};
	});
	$effect(() => {
		copilot?.setContext({ scanType, history });
	});
	const copilotRound = (rec: boolean) => schema && copilot?.round(units, rec, findingsText(units, schema.groups));
	function setRecording(v: boolean) {
		recording = v;
		if (!v) copilotRound(false); // the stop: the last finding is stable now
	}

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
				copilotRound(recording);
			}
			const closed = await postClose($token, { units, regions: s.regions });
			units = closed.units;
			pills = closed.pills;
			copilotRound(recording);
			status = 'rows…';
			items = (await postItems($token, { scan_type: scanType, clinical_history: history, regions: s.pills, dictation: text,
				abnormal: abnormalAll(units), removed })).items;
			status = `done · ${s.source}${s.provisional ? ' (provisional)' : ''} · ${s.key}`;
		} catch (e) {
			status = `error: ${e instanceof Error ? e.message : String(e)}`;
		}
	}
</script>

<div class="mx-auto max-w-6xl p-6 space-y-4">
	<h1 class="text-lg font-semibold">Hybrid stack (dev)</h1>
	<div class="grid grid-cols-3 gap-2">
		<input class="border rounded px-2 py-1" bind:value={scanType} placeholder="Scan type" />
		<input class="border rounded px-2 py-1" bind:value={history} placeholder="Clinical history" />
		<input class="border rounded px-2 py-1" bind:value={templateId} placeholder="Template id (optional)" />
	</div>
	<textarea class="w-full h-40 border rounded p-2 text-sm" bind:value={dictation} placeholder="Paste dictation"></textarea>
	<div class="flex items-center gap-4 text-sm">
		<button type="button" class="rounded bg-slate-800 px-3 py-1 text-white" onclick={run}>Replay</button>
		<label><input type="checkbox" bind:checked={copilotOn} /> Copilot</label>
		<label><input type="checkbox" checked={recording} onchange={(e) => setRecording(e.currentTarget.checked)} disabled={!copilotOn} /> recording</label>
	</div>
	<p class="text-xs text-slate-500">{status}</p>
	{#if schema}
		<p class="text-xs">Pills: {pills.join(' · ') || '—'}</p>
		<div class="flex gap-3 h-[680px]">
		<div class="flex-1 min-w-0 overflow-y-auto rounded bg-slate-900 p-3">
			<HybridStackView {units} groups={schema.groups} pillRegions={schema.pills} onMove={(id, g) => (units = moveUnit(units, id, g))}
				onEditLine={() => {}} onConfirm={() => {}} {items} {tapped} {removed}
				onAnswer={(id) => (tapped = [...tapped, id])} onRemoveSentence={(t) => (removed = [...removed, t])} />
		</div>
		{#if copilot && cs?.on}
			<CopilotRail groups={cs.groups} views={cs.views} matching={cs.matching} matchFailed={cs.matchFailed} otherState={cs.otherState}
				onOpen={copilot.open} onClose={copilot.close} onRetry={copilot.retry} onRetryMatch={copilot.retryMatch} onOther={copilot.other}
				onEdit={copilot.edit} />
		{/if}
		</div>
	{/if}
</div>
