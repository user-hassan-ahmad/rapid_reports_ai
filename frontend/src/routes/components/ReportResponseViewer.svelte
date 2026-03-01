<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { token } from '$lib/stores/auth';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import EnhancementPreviewCards from './EnhancementPreviewCards.svelte';
	import EnhancementInlinePanel from './EnhancementInlinePanel.svelte';
	import ReportEditor from './ReportEditor.svelte';
	import { API_URL } from '$lib/config';
	import { detectUnfilledPlaceholders, generateChatContext } from '$lib/utils/placeholderDetection';
	import { applyEditsToReport } from '$lib/utils/reportEditing';
	import type { UnfilledEdit } from '$lib/stores/unfilledEditor';
	import type { UnfilledItem, UnfilledItems } from '$lib/utils/placeholderDetection';
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

	let activeView = 'report';

	// Inline panel state
	let inlinePanelVisible = false;
	let inlinePanelTab: 'guidelines' | 'comparison' | 'chat' = 'guidelines';

	// Unfilled placeholder detection state — updated via on:unfilledItems from ReportEditor
	let highlightingEnabled = false;
	let showHighlighting = false;
	let manuallyDisabled = false;
	let showSummaryPanel = false;
	let unfilledItems: UnfilledItems = {
		measurements: [],
		variables: [],
		alternatives: [],
		instructions: [],
		blank_sections: [],
		total: 0
	};

	// Editor state
	let hasUnsavedChanges = false;
	let currentEditorContent = '';
	let lastSavedResponse = '';
	let reportEditorRef: { resetContent: (c: string) => void } | null = null;

	$: if (!reportId && activeView === 'history') {
		activeView = 'report';
	}
	$: if (!visible && activeView !== 'report') {
		activeView = 'report';
	}
	
	// Auto-enable highlighting when unfilled items arrive from the editor
	function handleUnfilledItems(items: UnfilledItems) {
		unfilledItems = items;
		if (items.total > 0 && !highlightingEnabled && !manuallyDisabled) {
			highlightingEnabled = true;
			showHighlighting = true;
			showSummaryPanel = true;
		} else if (items.total > 0 && highlightingEnabled && !manuallyDisabled) {
			showHighlighting = true;
			showSummaryPanel = true;
		}
		if (items.total === 0) {
			showHighlighting = false;
			showSummaryPanel = false;
		}
	}

	// Reset highlighting during loading
	$: if (generationLoading || updateLoading) {
		showHighlighting = false;
		showSummaryPanel = false;
	}

	// Reset unsaved state whenever the parent updates the response (generate / restore / save)
	$: if (response !== lastSavedResponse) {
		hasUnsavedChanges = false;
		currentEditorContent = response;
		lastSavedResponse = response;
	}
	
	// Sync summary panel with highlighting toggle (only when not loading)
	$: if (showHighlighting && unfilledItems.total > 0 && !generationLoading && !updateLoading) {
		showSummaryPanel = true;
	} else if (!showHighlighting || generationLoading || updateLoading) {
		showSummaryPanel = false;
	}
	

	$: hasContent = Boolean(response || error);
	let historyCount = 0;
	let historyAvailable = false;

	$: if (!historyAvailable && activeView === 'history') {
		activeView = 'report';
	}

	// Reset state when a new report is loaded
	let lastReportId: string | null = null;
	$: if (reportId && reportId !== lastReportId) {
		highlightingEnabled = false;
		showHighlighting = false;
		manuallyDisabled = false;
		hasUnsavedChanges = false;
		lastReportId = reportId;
	}
	
	// Handle editor content changes (user typed something)
	function handleEditorChange(event: CustomEvent<{ content: string }>) {
		currentEditorContent = event.detail.content;
		hasUnsavedChanges = currentEditorContent !== response;
	}

	// Handle popup apply — apply a filled value to the current editor content
	function handlePopupApply(event: CustomEvent<{ item: UnfilledItem; value: string }>) {
		const { item, value } = event.detail;
		const edit: UnfilledEdit = {
			itemId: `${item.type}-${item.index}`,
			originalText: item.text,
			newValue: value,
			type: item.type as 'measurement' | 'variable' | 'alternative' | 'instruction',
			context: item.surroundingContext,
			position: item.index
		};
		const edits = new Map<string, UnfilledEdit>();
		edits.set(edit.itemId, edit);
		const base = currentEditorContent || response;
		const updatedReport = applyEditsToReport(base, edits);
		dispatch('save', { content: updatedReport });
		dispatch('hideHoverPopup');
	}

	function handlePopupAskAI(event: CustomEvent<{ message: string }>) {
		dispatch('openSidebar', { tab: 'chat', initialMessage: event.detail.message });
		dispatch('hideHoverPopup');
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

	function saveEditing() {
		dispatch('save', { content: currentEditorContent });
		hasUnsavedChanges = false;
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
	<div class="card-dark relative flex flex-col max-h-[calc(100vh-200px)]">
		<!-- Header: Mobile-first responsive layout -->
		<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 px-3 sm:px-4 py-2 sm:py-3">
			<!-- Title row -->
			<button
				type="button"
				onclick={(e) => {
					e.stopPropagation();
					dispatch('toggle');
				}}
				class="flex items-center gap-2 transition-colors shrink-0"
			>
				<h2 class="text-base sm:text-lg font-semibold text-white">Response</h2>
				<svg
					class="w-4 h-4 sm:w-5 sm:h-5 text-gray-400 transform transition-transform hover:text-purple-400 {expanded ? 'rotate-180' : ''}"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
				</svg>
			</button>
			
			<!-- Controls row: wraps on mobile -->
			<div class="flex flex-wrap items-center gap-1.5 sm:gap-2 relative z-15">
				{#if reportId}
					<div class="flex items-center bg-gray-800/60 rounded-lg p-0.5 sm:p-1">
						<button
							type="button"
							class="px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-medium rounded-md transition-colors {activeView === 'report' ? 'bg-purple-600 text-white' : 'text-gray-300 hover:text-white'}"
							onclick={() => activeView = 'report'}
						>
							Report
						</button>
						<button
							type="button"
							class="px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-medium rounded-md transition-colors {activeView === 'history' ? 'bg-purple-600 text-white' : historyAvailable ? 'text-gray-300 hover:text-white' : 'text-gray-500'}"
							disabled={!historyAvailable}
							onclick={() => historyAvailable && (activeView = 'history')}
							title="Version History"
						>
							<span class="hidden xs:inline">Version </span>History
						</button>
					</div>
				{/if}
				
				{#if activeView === 'report' && response && unfilledItems.total > 0}
					<button
						type="button"
						onclick={(e) => {
							e.stopPropagation();
							e.preventDefault();
							showHighlighting = !showHighlighting;
							if (!showHighlighting) {
								manuallyDisabled = true;
								highlightingEnabled = false;
							} else {
								manuallyDisabled = false;
								highlightingEnabled = true;
							}
						}}
						onmousedown={(e) => e.stopPropagation()}
						class="px-2 sm:px-3 py-1 sm:py-1.5 text-[10px] sm:text-xs font-medium rounded-lg transition-colors {showHighlighting ? 'bg-yellow-600 text-white' : 'bg-gray-700 text-gray-300 hover:text-white'}"
						title="Toggle unfilled placeholder highlighting"
					>
						<span class="flex items-center gap-1 sm:gap-1.5">
							<span class="hidden sm:inline">🎨</span>
							<span class="sm:hidden">⚠️</span>
							<span class="hidden sm:inline">Unfilled</span> ({unfilledItems.total})
						</span>
					</button>
				{/if}


				{#if activeView === 'report'}
					<button
						type="button"
						onclick={() => dispatch('copy')}
						class="p-1.5 sm:p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed"
						title="Copy to clipboard"
						aria-label="Copy report"
						disabled={!response}
					>
						<svg class="w-4 h-4 sm:w-5 sm:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
						</svg>
					</button>
				{/if}
				<button
					type="button"
					onclick={() => dispatch('clear')}
					class="p-1.5 sm:p-2 text-gray-400 hover:text-red-400 transition-colors rounded-lg hover:bg-white/5"
					title="Clear response"
					aria-label="Clear report"
				>
					<svg class="w-4 h-4 sm:w-5 sm:h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
		</div>

		{#if expanded}
			<div class="relative flex-1 min-h-0 flex flex-col">
				{#if generationLoading || updateLoading}
					<div class="absolute inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-10">
						<div class="flex items-center gap-3 text-gray-200 text-sm">
							<div class="w-6 h-6 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
							<span>{updateLoading ? 'Applying actions...' : 'Generating report...'}</span>
						</div>
					</div>
				{/if}
				<div class="relative px-3 sm:px-4 pt-0 pb-3 sm:pb-4 flex-1 min-h-0 overflow-y-auto space-y-3 sm:space-y-4">
					<!-- View container with absolute positioning for smooth crossfade transitions -->
					<div class="relative" style="min-height: calc(100vh - 300px);">
						<!-- History View -->
						{#if activeView === 'history' && reportId}
							<div 
								class="absolute inset-0 overflow-y-auto"
								transition:fade={{ duration: 200, easing: (t) => t * (2 - t) }}
								style="will-change: opacity;"
							>
								<ReportVersionInline
									reportId={reportId}
									refreshKey={versionHistoryRefreshKey}
									on:historyUpdate={handleHistoryUpdate}
									on:restored={(event) => dispatch('restore', event.detail)}
								/>
							</div>
						{/if}
						
						<!-- Report View -->
						{#if activeView === 'report'}
							<div 
								class="absolute inset-0 overflow-y-auto"
								transition:fade={{ duration: 200, easing: (t) => t * (2 - t) }}
								style="will-change: opacity; backface-visibility: hidden;"
							>
								<!-- Enhancement Preview Cards - Before report content -->
								{#if reportId}
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
							
						<!-- Summary Panel for Unfilled Items -->
						{#if showSummaryPanel && unfilledItems.total > 0}
					<div class="relative mb-3 sm:mb-4" style="z-index: 10;">
						<div
							class="group relative w-full bg-gradient-to-br from-yellow-900/20 to-orange-800/10 backdrop-blur-xl border border-yellow-500/30 rounded-lg sm:rounded-xl p-2.5 sm:p-4"
						>
							<div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 sm:gap-3">
								<div class="flex items-center gap-2 sm:gap-3">
									<div class="w-8 h-8 sm:w-10 sm:h-10 rounded-lg bg-yellow-600/20 flex items-center justify-center shrink-0">
										<svg class="w-4 h-4 sm:w-5 sm:h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
										</svg>
									</div>
									<div class="text-left">
										<h4 class="text-xs sm:text-sm font-semibold text-white group-hover:text-yellow-300 transition-colors">Unfilled Items</h4>
										<p class="text-[10px] sm:text-xs text-gray-400">Complete your report</p>
									</div>
								</div>
								<div class="flex items-center gap-1.5 sm:gap-2 flex-wrap">
									{#if unfilledItems.measurements.length > 0}
										<span class="px-1.5 sm:px-2.5 py-0.5 sm:py-1 bg-yellow-600/20 text-yellow-400 text-[10px] sm:text-xs font-semibold rounded border border-yellow-500/30 flex items-center gap-1">
											<span class="hidden sm:inline">🟡</span>
											<span>{unfilledItems.measurements.length}</span>
											<span class="text-[9px] sm:text-[10px] text-yellow-300/70">Meas</span>
										</span>
									{/if}
									{#if unfilledItems.alternatives.length > 0}
										<span class="px-1.5 sm:px-2.5 py-0.5 sm:py-1 bg-purple-600/20 text-purple-400 text-[10px] sm:text-xs font-semibold rounded border border-purple-500/30 flex items-center gap-1">
											<span class="hidden sm:inline">🟣</span>
											<span>{unfilledItems.alternatives.length}</span>
											<span class="text-[9px] sm:text-[10px] text-purple-300/70">Alt</span>
										</span>
									{/if}
									{#if unfilledItems.variables.length > 0}
										<span class="px-1.5 sm:px-2.5 py-0.5 sm:py-1 bg-green-600/20 text-green-400 text-[10px] sm:text-xs font-semibold rounded border border-green-500/30 flex items-center gap-1">
											<span class="hidden sm:inline">🟢</span>
											<span>{unfilledItems.variables.length}</span>
											<span class="text-[9px] sm:text-[10px] text-green-300/70">Var</span>
										</span>
									{/if}
								</div>
							</div>
						</div>
							</div>
							{/if}
							
							{#if validationStatus}
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
							
						{#if error}
							<div class="border border-red-500/30 bg-red-500/10 rounded-lg p-4">
								<p class="text-red-400 font-medium mb-1">Error</p>
								<p class="text-red-300 text-sm">{error}</p>
							</div>
						{:else if response}
						<ReportEditor
							bind:this={reportEditorRef}
							content={response}
							showHighlighting={showHighlighting}
							generationLoading={generationLoading || updateLoading}
							on:change={handleEditorChange}
							on:save={() => { if (hasUnsavedChanges) saveEditing(); }}
							on:unfilledItems={(e) => handleUnfilledItems(e.detail.items)}
							on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
							on:hideHoverPopup={() => dispatch('hideHoverPopup')}
						/>
						{:else}
							<p class="text-sm text-gray-400">Response will appear here once generated.</p>
						{/if}
					</div>
					{/if}
					</div>
				</div>
				
			<!-- Floating save bar -->
			{#if activeView === 'report' && hasUnsavedChanges}
				<div
					class="sticky-save-bar"
					transition:fly={{ y: 48, duration: 220, easing: (t) => 1 - Math.pow(1 - t, 3) }}
				>
					<div class="sticky-save-inner">
						<!-- Pulsing unsaved dot -->
						<div class="relative w-2.5 h-2.5 shrink-0">
							<span class="absolute inset-0 rounded-full bg-amber-400 animate-ping opacity-60"></span>
							<span class="absolute inset-0 rounded-full bg-amber-400"></span>
						</div>
						<span class="text-xs text-gray-300 font-medium">Unsaved changes</span>
						<kbd class="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-[10px] text-gray-400 font-mono">⌘S</kbd>
						<div class="flex items-center gap-2 ml-auto">
							<button
								type="button"
								onclick={() => {
									reportEditorRef?.resetContent(response);
									currentEditorContent = response;
									hasUnsavedChanges = false;
								}}
								class="px-3 py-1.5 text-xs font-medium rounded-lg text-gray-400 hover:text-white hover:bg-white/[0.08] transition-colors"
							>
								Discard
							</button>
							<button
								type="button"
								onclick={saveEditing}
								class="save-btn-glow flex items-center gap-1.5 px-3 sm:px-4 py-1.5 text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-500 text-white transition-colors"
							>
								<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
								</svg>
								Save Changes
							</button>
						</div>
					</div>
				</div>
			{/if}

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



<style>
	/* Highlight decoration styles are now in ReportEditor.svelte */

	/* ── Floating save bar ─────────────────────────────────────────────────── */

	.sticky-save-bar {
		padding: 0 0.75rem 0.75rem;
	}

	@media (min-width: 640px) {
		.sticky-save-bar {
			padding: 0 1rem 1rem;
		}
	}

	.sticky-save-inner {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.625rem 0.875rem;
		background: rgba(15, 12, 25, 0.82);
		backdrop-filter: blur(16px);
		-webkit-backdrop-filter: blur(16px);
		border: 1px solid rgba(168, 85, 247, 0.25);
		border-radius: 0.75rem;
		box-shadow:
			0 0 0 1px rgba(168, 85, 247, 0.08),
			0 8px 32px rgba(0, 0, 0, 0.5),
			0 0 20px rgba(168, 85, 247, 0.08);
	}

	@media (min-width: 640px) {
		.sticky-save-inner {
			padding: 0.75rem 1rem;
			gap: 0.75rem;
		}
	}

	/* ── Pulsing glow on save button ──────────────────────────────────────── */

	@keyframes save-glow-pulse {
		0%, 100% {
			box-shadow:
				0 0 0 0 rgba(168, 85, 247, 0.5),
				0 0 0 0 rgba(168, 85, 247, 0.2);
		}
		50% {
			box-shadow:
				0 0 10px 3px rgba(168, 85, 247, 0.55),
				0 0 22px 7px rgba(168, 85, 247, 0.18);
		}
	}

	.save-btn-glow {
		animation: save-glow-pulse 2s ease-in-out infinite;
	}

	.save-btn-glow:hover {
		animation: none;
		box-shadow: 0 0 14px 4px rgba(168, 85, 247, 0.6);
	}
</style>

