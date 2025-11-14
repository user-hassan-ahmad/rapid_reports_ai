<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { marked } from 'marked';
	import { token } from '$lib/stores/auth';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import { API_URL } from '$lib/config';

	const dispatch = createEventDispatcher();

	export let visible = false;
	export let expanded = true;
	export let response = '';
	export let error = null;
	export let model = null;
	export let generationLoading = false;
	export let updateLoading = false;
	export let reportId = null;
	export let versionHistoryRefreshKey = 0;

	marked.setOptions({
		breaks: true,
		gfm: true
	});

	function renderMarkdown(md) {
		if (!md) return '';
		return marked.parse(md);
	}

	let activeView = 'report';
	$: if (!reportId && activeView === 'history') {
		activeView = 'report';
	}
$: if (!visible && activeView !== 'report') {
	activeView = 'report';
}

	$: hasContent = Boolean(response || error);
let historyCount = 0;
let historyAvailable = false;

$: if (!historyAvailable && activeView === 'history') {
	activeView = 'report';
}

function handleHistoryUpdate(event) {
	historyCount = event.detail?.count ?? 0;
	historyAvailable = historyCount > 1;
	if (!historyAvailable && activeView === 'history') {
		activeView = 'report';
	}
	dispatch('historyUpdate', { count: historyCount });
}

async function loadHistorySummary() {
	if (!reportId) {
		historyCount = 0;
		historyAvailable = false;
		dispatch('historyUpdate', { count: historyCount });
		return;
	}

	try {
		const headers = { 'Content-Type': 'application/json' };
		if ($token) {
			headers['Authorization'] = `Bearer ${$token}`;
		}
		const response = await fetch(`${API_URL}/api/reports/${reportId}/versions`, { headers });
		const data = await response.json();
		if (!response.ok || !data.success) {
			throw new Error(data.error || `Failed to load version history (${response.status})`);
		}
		historyCount = (data.versions || []).length;
		historyAvailable = historyCount > 1;
		dispatch('historyUpdate', { count: historyCount });
	} catch (err) {
		console.error('Failed to load history summary', err);
		historyCount = 0;
		historyAvailable = false;
		dispatch('historyUpdate', { count: historyCount });
	}
}

onMount(loadHistorySummary);

let lastSummaryReportId = undefined;
let lastSummaryRefreshKey = -1;
$: if (reportId !== lastSummaryReportId || versionHistoryRefreshKey !== lastSummaryRefreshKey) {
	lastSummaryReportId = reportId;
	lastSummaryRefreshKey = versionHistoryRefreshKey;
	loadHistorySummary();
}
</script>

{#if visible}
	<div class="card-dark">
		<div class="flex items-center justify-between px-4 py-3">
			<button
				type="button"
				onclick={() => dispatch('toggle')}
				class="flex items-center gap-2 transition-colors"
			>
				<h2 class="text-lg font-semibold text-white">Response</h2>
				<svg
					class="w-5 h-5 text-gray-400 transform transition-transform hover:text-purple-400 {expanded ? 'rotate-180' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
				</svg>
			</button>
			<div class="flex items-center gap-2">
{#if reportId}
	<div class="flex items-center bg-gray-800/60 rounded-lg p-1">
		<button
			type="button"
			class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {activeView === 'report' ? 'bg-purple-600 text-white' : 'text-gray-300 hover:text-white'}"
			onclick={() => activeView = 'report'}
		>
			Report
		</button>
		<button
			type="button"
			class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {activeView === 'history' ? 'bg-purple-600 text-white' : historyAvailable ? 'text-gray-300 hover:text-white' : 'text-gray-500'}"
			disabled={!historyAvailable}
			onclick={() => historyAvailable && (activeView = 'history')}
		>
			Version History
		</button>
	</div>
{/if}
				<button
					type="button"
					onclick={() => dispatch('openSidebar')}
					class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
					title="Get Guidelines & Enhancements"
					aria-label="Open enhancement sidebar"
					disabled={!response}
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
					</svg>
				</button>
				<button
					type="button"
					onclick={() => dispatch('copy')}
					class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
					title="Copy to clipboard"
					aria-label="Copy report"
					disabled={!response}
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
					</svg>
				</button>
				<button
					type="button"
					onclick={() => dispatch('clear')}
					class="p-2 text-gray-400 hover:text-red-400 transition-colors rounded-lg hover:bg-white/5"
					title="Clear response"
					aria-label="Clear report"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		</div>

		{#if expanded}
			<div class="relative">
				{#if generationLoading || updateLoading}
					<div class="absolute inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-10">
						<div class="flex items-center gap-3 text-gray-200 text-sm">
							<div class="w-6 h-6 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
							<span>{updateLoading ? 'Applying actions...' : 'Generating report...'}</span>
						</div>
					</div>
				{/if}
				<div class="p-4 pt-0 max-h-96 overflow-y-auto space-y-4">
					{#if activeView === 'history' && reportId}
						<ReportVersionInline
							reportId={reportId}
							refreshKey={versionHistoryRefreshKey}
							on:historyUpdate={handleHistoryUpdate}
							on:restored={(event) => dispatch('restore', event.detail)}
						/>
					{:else if error}
						<div class="border border-red-500/30 bg-red-500/10 rounded-lg p-4">
							<p class="text-red-400 font-medium mb-1">Error</p>
							<p class="text-red-300 text-sm">{error}</p>
						</div>
					{:else if response}
						<div>
							<div class="prose prose-invert max-w-none">
								{@html renderMarkdown(response)}
							</div>
						</div>
					{:else}
						<p class="text-sm text-gray-400">Response will appear here once generated.</p>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}

