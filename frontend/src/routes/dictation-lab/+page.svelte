<script lang="ts">
	import { onMount } from 'svelte';
	import IntelliDictateTab from '../components/IntelliDictateTab.svelte';
	import DictationLabPanel from '$lib/components/DictationLabPanel.svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { labConfig, saveLabConfig } from '$lib/dictation-lab/labConfig';
	import type { ProcessTrace } from '$lib/dictation-lab/types';

	// Same bindings the home page gives the tab (src/routes/+page.svelte ~975-1000).
	let tabRef: { injectTranscript: (text: string, speechFinal?: boolean) => void } | null = null;
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
				onClear={() => {
					traces = [];
				}}
			/>
		</aside>
	</div>
</div>
