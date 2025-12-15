<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { marked } from 'marked';
	import { token } from '$lib/stores/auth';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import EnhancementPreviewCards from './EnhancementPreviewCards.svelte';
	import EnhancementInlinePanel from './EnhancementInlinePanel.svelte';
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
	
	// Enhancement state for preview cards
	export let enhancementGuidelinesCount = 0;
	export let enhancementLoading = false;
	export let enhancementError = false;
	
	// Track previous response to detect manual updates
	let previousResponse = '';

	marked.setOptions({
		breaks: true,
		gfm: true
	});

	function renderMarkdown(md) {
		if (!md) return '';
		return marked.parse(md);
	}

	let activeView = 'report';
	let isEditing = false;
	let editContent = '';
	
	// Inline panel state
	let inlinePanelVisible = false;
	let inlinePanelTab: 'guidelines' | 'comparison' | 'chat' = 'guidelines';

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

	// Reset edit mode when report changes
	$: if (reportId) {
		isEditing = false;
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
			/** @type {Record<string, string>} */
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
			historyCount = 0;
			historyAvailable = false;
			dispatch('historyUpdate', { count: historyCount });
		}
	}

	function startEditing() {
		editContent = response;
		isEditing = true;
	}

	function cancelEditing() {
		isEditing = false;
		editContent = '';
	}

	function saveEditing() {
		dispatch('save', { content: editContent });
		isEditing = false;
	}

	onMount(loadHistorySummary);

	let lastSummaryReportId = undefined;
	let lastSummaryRefreshKey = -1;
	$: if (reportId !== lastSummaryReportId || versionHistoryRefreshKey !== lastSummaryRefreshKey) {
		lastSummaryReportId = reportId;
		lastSummaryRefreshKey = versionHistoryRefreshKey;
		loadHistorySummary();
	}

	// Validation status polling
	let validationStatus = null;
	let pollInterval = null;
	let pollTimeout = null;
	let hideNotificationTimeout = null;
	let wasGenerating = false; // Track if report was just generated (not updated)
	const POLL_INTERVAL = 2000; // 2 seconds
	const POLL_TIMEOUT = 30000; // 30 seconds max
	const NOTIFICATION_HIDE_DELAY = 5000; // 5 seconds to auto-hide notification

	async function checkValidationStatus() {
		if (!reportId) return;

		try {
			/** @type {Record<string, string>} */
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const res = await fetch(`${API_URL}/api/reports/${reportId}/validation-status`, { headers });
			const data = await res.json();
			
			if (data.success && data.validation_status) {
				const status = data.validation_status.status;
				validationStatus = data.validation_status;
				
				// Stop polling if validation is complete (not pending)
				if (status !== 'pending') {
					stopPolling();
					
					// If fixed, refresh version history and notify
					if (status === 'fixed') {
						loadHistorySummary();
						versionHistoryRefreshKey += 1;
						dispatch('validationComplete', { status, violations: data.validation_status.violations_count });
					} else if (status === 'passed') {
						dispatch('validationComplete', { status });
					}
					
					// Auto-hide notification after 5 seconds
					clearHideNotificationTimeout();
					hideNotificationTimeout = setTimeout(() => {
						validationStatus = null;
						hideNotificationTimeout = null;
					}, NOTIFICATION_HIDE_DELAY);
				}
			}
		} catch (err) {
			// Failed to check validation status
		}
	}

	function startPolling() {
		stopPolling(); // Clear any existing polling
		
		if (!reportId) return;
		
		// Initial check
		checkValidationStatus();
		
		// Set up polling interval
		pollInterval = setInterval(checkValidationStatus, POLL_INTERVAL);
		
		// Set timeout to stop polling after max time
		pollTimeout = setTimeout(() => {
			stopPolling();
			if (validationStatus?.status === 'pending') {
				validationStatus = { ...validationStatus, status: 'timeout' };
			}
		}, POLL_TIMEOUT);
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
		if (pollTimeout) {
			clearTimeout(pollTimeout);
			pollTimeout = null;
		}
	}

	function clearHideNotificationTimeout() {
		if (hideNotificationTimeout) {
			clearTimeout(hideNotificationTimeout);
			hideNotificationTimeout = null;
		}
	}

	// Reset validation status when reportId changes
	$: if (reportId !== lastSummaryReportId) {
		validationStatus = null;
		stopPolling();
		clearHideNotificationTimeout();
		wasGenerating = false; // Reset generation tracking
		previousResponse = ''; // Reset response tracking
	}

	// Track generation completion: only poll when generation transitions from true → false
	$: {
		if (generationLoading) {
			wasGenerating = true; // Mark that we're generating
		} else if (wasGenerating && !generationLoading && reportId && response && reportId === lastSummaryReportId) {
			// Generation just completed - start polling for validation status
			wasGenerating = false; // Reset flag
			startPolling();
		}
	}
	
	// Clear validation status when report is updated manually/via chat (response changes but not from generation)
	$: if (reportId && response && reportId === lastSummaryReportId && !generationLoading && !wasGenerating) {
		// If response changed but we weren't generating and had a previous response, it's a manual/chat update
		// This prevents clearing on initial load (when previousResponse is empty)
		if (previousResponse !== '' && previousResponse !== response) {
			validationStatus = null;
			stopPolling();
			clearHideNotificationTimeout();
		}
		// Update previousResponse after checking (but only if we have a response)
		if (response) {
			previousResponse = response;
		}
	}

	// Stop polling when component unmounts or reportId changes
	onDestroy(() => {
		stopPolling();
		clearHideNotificationTimeout();
	});

	// Reload report content when user wants to see fixed version
	async function reloadFixedVersion() {
		if (!reportId) return;
		
		try {
			/** @type {Record<string, string>} */
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const res = await fetch(`${API_URL}/api/reports/${reportId}`, { headers });
			const data = await res.json();
			
			if (data.success && data.report) {
				response = data.report.report_content;
				loadHistorySummary();
				versionHistoryRefreshKey += 1;
				dispatch('restore', { report: data.report });
			}
		} catch (err) {
			// Failed to reload fixed version
		}
	}
</script>

{#if visible}
	<div class="card-dark relative">
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
				
				{#if activeView === 'report' && response && !isEditing}
					<button
						type="button"
						onclick={startEditing}
						class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5"
						title="Edit report"
						aria-label="Edit report"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
						</svg>
					</button>
				{/if}

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
				<div class="relative p-4 pt-0 max-h-96 overflow-y-auto space-y-4">
					<!-- Enhancement Preview Cards - Before report content -->
					{#if activeView === 'report' && reportId}
						<EnhancementPreviewCards
							guidelinesCount={enhancementGuidelinesCount}
							isLoading={enhancementLoading}
							hasError={enhancementError}
							reportId={reportId}
							on:openSidebar={(e) => {
								dispatch('openSidebar', e.detail);
							}}
						/>
					{/if}
					
					{#if validationStatus && activeView === 'report'}
						<div class="mb-3">
							{#if validationStatus.status === 'pending'}
								<div class="flex items-center gap-2 text-yellow-400 text-sm bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-2">
									<div class="w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin"></div>
									<span>Validating report...</span>
								</div>
							{:else if validationStatus.status === 'passed'}
								<div class="flex items-center gap-2 text-green-400 text-sm bg-green-500/10 border border-green-500/30 rounded-lg p-2">
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
									</svg>
									<span>Report validated - No issues found</span>
								</div>
							{:else if validationStatus.status === 'fixed'}
								<div class="flex items-center justify-between gap-2 text-green-400 text-sm bg-green-500/10 border border-green-500/30 rounded-lg p-2">
									<div class="flex items-center gap-2">
										<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
										</svg>
										<span>Report validated: {validationStatus.violations_count} issue(s) fixed automatically</span>
									</div>
									<button
										type="button"
										onclick={reloadFixedVersion}
										class="px-2 py-1 text-xs font-medium bg-green-600 hover:bg-green-500 text-white rounded transition-colors"
									>
										View Fixed Version
									</button>
								</div>
							{:else if validationStatus.status === 'error'}
								<div class="flex items-center gap-2 text-yellow-400 text-sm bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-2">
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
									</svg>
									<span>Validation failed: {validationStatus.error || 'Unknown error'}</span>
								</div>
							{/if}
						</div>
					{/if}
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
						{#if isEditing}
							<div class="space-y-3">
								<textarea
									bind:value={editContent}
									class="w-full h-80 bg-gray-800/50 border border-gray-700 rounded-lg p-4 text-gray-200 font-mono text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none resize-none"
									placeholder="Edit report content..."
								></textarea>
								<div class="flex justify-end gap-2">
									<button
										type="button"
										onclick={cancelEditing}
										class="px-3 py-1.5 text-sm font-medium text-gray-400 hover:text-white transition-colors"
									>
										Cancel
									</button>
									<button
										type="button"
										onclick={saveEditing}
										class="px-3 py-1.5 text-sm font-medium bg-purple-600 hover:bg-purple-500 text-white rounded-lg transition-colors shadow-lg shadow-purple-900/20"
									>
										Save Changes
									</button>
								</div>
							</div>
						{:else}
							<div>
								<div class="prose prose-invert max-w-none">
									{@html renderMarkdown(response)}
								</div>
							</div>
						{/if}
					{:else}
						<p class="text-sm text-gray-400">Response will appear here once generated.</p>
					{/if}
				</div>
				
				<!-- Inline Enhancement Panel - Hidden for now -->
				<!--
				{#if inlinePanelVisible && reportId}
					<EnhancementInlinePanel
						reportId={reportId}
						reportContent={response || ''}
						visible={inlinePanelVisible}
						bind:activeTab={inlinePanelTab}
						on:close={() => inlinePanelVisible = false}
						on:enhancementState={(e) => {
							// Forward enhancement state to parent
							dispatch('enhancementState', e.detail);
						}}
					/>
				{/if}
				-->
			</div>
		{/if}
	</div>
{/if}

