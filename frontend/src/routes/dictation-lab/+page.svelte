<script lang="ts">
	import { onMount } from 'svelte';
	import IntelliDictateTab from '../components/IntelliDictateTab.svelte';
	import DictationLabPanel from '$lib/components/DictationLabPanel.svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig, saveLabConfig } from '$lib/dictation-lab/labConfig';
	import type { CoverageTrace, ProcessTrace } from '$lib/dictation-lab/types';
	import type { DecisionRecord, OutcomeEvent } from '$lib/dictation-lab/decisionFirst';

	// Same bindings the home page gives the tab (src/routes/+page.svelte ~975-1000).
	let tabRef: {
		injectTranscript: (text: string, speechFinal?: boolean) => void;
		getCoverageState: () => { scratchpad: string; checklist: string[]; scanType: string };
	} | null = null;
	let coverageTrace: CoverageTrace | null = null;
	let coverageState: { scratchpad: string; checklist: string[]; scanType: string } | null = null;
	let response: any = null;
	let responseModel: any = null;
	let loading = false;
	let error: any = null;
	let reportId: any = null;
	let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		cerebras_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false
	};
	let statusError = '';

	// Decision-first (front door 'decision'): records upserted by id; display text stays in the page.
	let decisions: { rec: DecisionRecord; display: string }[] = [];
	let outcomes: OutcomeEvent[] = [];
	let sessionStartedAt = Date.now();
	function upsertDecision(rec: DecisionRecord, display: string): void {
		const i = decisions.findIndex((d) => d.rec.id === rec.id);
		decisions = i >= 0 ? decisions.map((d, j) => (j === i ? { rec, display } : d)) : [...decisions, { rec, display }];
	}

	let traces: ProcessTrace[] = [];
	function pushTrace(t: ProcessTrace): void {
		traces = [...traces, t];
	}

	$: saveLabConfig($labConfig);

	onMount(async () => {
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/settings/status`, { headers });
			if (!res.ok) {
				statusError = `service status ${res.status} — log in on the home page first`;
				return;
			}
			const data = await res.json();
			if (data.success) {
				apiKeyStatus = {
					anthropic_configured: data.anthropic_configured || false,
					groq_configured: data.groq_configured || false,
					cerebras_configured: data.cerebras_configured || false,
					deepgram_configured: data.deepgram_configured || false,
					has_at_least_one_model: Boolean(
						data.has_at_least_one_model ??
							(data.anthropic_configured || data.groq_configured || data.cerebras_configured)
					)
				};
			}
		} catch (e) {
			statusError = (e as Error).message;
		}
	});
</script>

<svelte:head><title>Dictation Lab</title></svelte:head>

<div class="min-h-screen p-4 space-y-3">
	<header class="flex items-baseline gap-3 flex-wrap">
		<h1 class="text-xl font-semibold">Dictation Lab</h1>
		<span class="text-sm text-gray-400">production dictation tab + triage instrumentation · dev only</span>
		{#if statusError}<span class="text-sm text-amber-400">{statusError}</span>{/if}
	</header>

	<div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_28rem] gap-4">
		<div class="min-w-0">
			<IntelliDictateTab
				bind:this={tabRef}
				bind:response
				bind:responseModel
				bind:loading
				bind:error
				bind:reportId
				{apiKeyStatus}
				labConfig={$labConfig}
				onProcessTrace={pushTrace}
				pillThresholds={$labConfig.pillThresholds}
				onCoverageTrace={(t) => {
					coverageTrace = t;
					coverageState = tabRef?.getCoverageState?.() ?? null;
				}}
				onDecision={upsertDecision}
				onOutcome={(e) => {
					outcomes = [...outcomes, e];
				}}
				on:resetForm={() => {
					traces = [];
				}}
				on:openSidebar={() => {}}
				on:auditStateChange={() => {}}
				on:showHoverPopup={() => {}}
				on:hideHoverPopup={() => {}}
			/>
		</div>
		<aside class="min-w-0">
			<DictationLabPanel
				inject={(text) => tabRef?.injectTranscript(text, true)}
				{traces}
				{coverageTrace}
				{coverageState}
				{decisions}
				{outcomes}
				{sessionStartedAt}
				onClear={() => {
					traces = [];
					decisions = [];
					outcomes = [];
					sessionStartedAt = Date.now();
				}}
			/>
		</aside>
	</div>
</div>
