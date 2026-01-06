<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { fade } from 'svelte/transition';
	import { marked } from 'marked';
	import { token } from '$lib/stores/auth';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import EnhancementPreviewCards from './EnhancementPreviewCards.svelte';
	import EnhancementInlinePanel from './EnhancementInlinePanel.svelte';
	import { API_URL } from '$lib/config';
	import { detectUnfilledPlaceholders, highlightUnfilledContent, generateChatContext } from '$lib/utils/placeholderDetection';
	import { applyEditsToReport } from '$lib/utils/reportEditing';
	import type { UnfilledEdit } from '$lib/stores/unfilledEditor';
	import type { UnfilledItem } from '$lib/utils/placeholderDetection';
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
	
	// Unfilled placeholder detection state
	let highlightingEnabled = false;
	let showHighlighting = false;
	let manuallyDisabled = false; // Track if user manually disabled highlighting
	let showSummaryPanel = false;
	let unfilledItems = { measurements: [], variables: [], alternatives: [], instructions: [], total: 0 };
	
	// Hover popup state
	let hoverTimeout: ReturnType<typeof setTimeout> | null = null;

	$: if (!reportId && activeView === 'history') {
		activeView = 'report';
	}
	$: if (!visible && activeView !== 'report') {
		activeView = 'report';
	}
	
	// Detect unfilled placeholders when response changes
	$: if (response && activeView === 'report' && !isEditing && !generationLoading && !updateLoading) {
		unfilledItems = detectUnfilledPlaceholders(response);
		// Auto-enable highlighting if unfilled items found and not manually disabled
		if (unfilledItems.total > 0 && !highlightingEnabled && !manuallyDisabled) {
			highlightingEnabled = true;
			showHighlighting = true;
			showSummaryPanel = true;
			manuallyDisabled = false; // Reset manual disable flag when auto-enabling
		} else if (unfilledItems.total > 0 && highlightingEnabled && !updateLoading && !manuallyDisabled) {
			// Restore highlighting after update if it was enabled before and not manually disabled
			// This handles the case where updateLoading temporarily hid highlighting
			showHighlighting = true;
			showSummaryPanel = true;
		}
		// Reset if no unfilled items
		if (unfilledItems.total === 0) {
			showHighlighting = false;
			showSummaryPanel = false;
		}
	}
	
	// Reset highlighting when switching views, editing, or loading
	// But preserve highlightingEnabled flag so we can restore it after update
	$: if (activeView !== 'report' || isEditing || generationLoading || updateLoading) {
		// Only reset if actually loading, not just when updateLoading becomes false
		// But don't reset highlightingEnabled - preserve it so highlighting can be restored after update
		if (generationLoading || updateLoading) {
			showHighlighting = false;
			showSummaryPanel = false;
		}
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

	// Reset edit mode when report changes (only on NEW report, not updates)
	let lastReportId: string | null = null;
	$: if (reportId && reportId !== lastReportId) {
		isEditing = false;
		highlightingEnabled = false;
		showHighlighting = false;
		manuallyDisabled = false; // Reset manual disable flag for new report
		lastReportId = reportId;
	}
	
	// Handle click on highlighted items
	function handleHighlightMouseEnter(event: MouseEvent) {
		const target = event.target as HTMLElement;
		// Check for both unfilled-highlight and unfilled-section-marker classes
		const highlightElement = target.classList?.contains('unfilled-highlight') 
			? target 
			: target.classList?.contains('unfilled-section-marker')
			? target
			: (target.closest('.unfilled-highlight, .unfilled-section-marker') as HTMLElement);
			
		if (highlightElement) {
			const type = highlightElement.dataset.type as 'measurement' | 'variable' | 'alternative' | 'instruction' | 'blank_section';
			
			// #region agent log
			fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:handleHighlightMouseEnter',message:'hover detected',data:{targetTag:target?.tagName,targetClass:target?.className,hasHighlightClass:target?.classList?.contains('unfilled-highlight'),hasMarkerClass:target?.classList?.contains('unfilled-section-marker'),foundElement:!!highlightElement,type,sectionName:highlightElement.dataset.section,blankSectionsCount:unfilledItems.blank_sections.length},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
			// #endregion
			
			// Show popup for measurements, alternatives, variables, and blank sections
			if (type === 'measurement' || type === 'alternative' || type === 'variable' || type === 'blank_section') {
				// Clear any existing timeout
				if (hoverTimeout) {
					clearTimeout(hoverTimeout);
				}
				
				// Find the item
				const text = highlightElement.dataset.text || '';
				const sectionName = highlightElement.dataset.section || ''; // For blank sections
				const context = highlightElement.dataset.context || '';
				const index = parseInt(highlightElement.dataset.index || '0');
				
				// #region agent log
				fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:handleHighlightMouseEnter',message:'looking up item',data:{type,text,sectionName,index,blankSections:unfilledItems.blank_sections.map(bs => bs.text)},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
				// #endregion
				
				let item: UnfilledItem | null = null;
				if (type === 'measurement') {
					item = unfilledItems.measurements.find(i => i.text === text && i.index === index);
				} else if (type === 'alternative') {
					item = unfilledItems.alternatives.find(i => i.text === text && i.index === index);
				} else if (type === 'variable') {
					item = unfilledItems.variables.find(i => i.text === text && i.index === index);
				} else if (type === 'blank_section') {
					// Find blank section by name
					item = unfilledItems.blank_sections.find(i => i.text === sectionName);
					// #region agent log
					fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:handleHighlightMouseEnter',message:'blank section lookup',data:{sectionName,itemFound:!!item,itemText:item?.text},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
					// #endregion
				}
				
				if (item) {
					// Get position
					const rect = highlightElement.getBoundingClientRect();
					const popupPosition = {
						x: rect.left + rect.width / 2,
						y: rect.top
					};
					
					// #region agent log
					fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:handleHighlightMouseEnter',message:'dispatching popup',data:{itemType:item.type,popupPosition},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
					// #endregion
					
					// Reduced delay for faster response (150ms instead of 300ms)
					hoverTimeout = setTimeout(() => {
						// Dispatch event to show hover popup at root level
						dispatch('showHoverPopup', {
							item,
							position: popupPosition,
							reportContent: response || ''
						});
					}, 150);
				} else {
					// #region agent log
					fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:handleHighlightMouseEnter',message:'item not found',data:{type,text,sectionName,index},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
					// #endregion
				}
			}
		}
	}

	function handleHighlightMouseLeave(event: MouseEvent) {
		const target = event.target as HTMLElement;
		// Check for both unfilled-highlight and unfilled-section-marker classes
		const highlightElement = target.classList?.contains('unfilled-highlight') 
			? target 
			: target.classList?.contains('unfilled-section-marker')
			? target
			: (target.closest('.unfilled-highlight, .unfilled-section-marker') as HTMLElement);
			
		if (highlightElement) {
			// Check if we're moving to the popup
			const relatedTarget = event.relatedTarget as HTMLElement;
			if (relatedTarget && relatedTarget.closest('.unfilled-hover-popup')) {
				return; // Don't hide if moving to popup
			}
			
			if (hoverTimeout) {
				clearTimeout(hoverTimeout);
				hoverTimeout = null;
			}
			
			// Delay hiding to allow moving to popup
			setTimeout(() => {
				// Check if popup is still being hovered
				if (!document.querySelector('.unfilled-hover-popup:hover')) {
					// Dispatch event to hide hover popup
					dispatch('hideHoverPopup');
				}
			}, 200);
		}
	}

	function handlePopupApply(event: CustomEvent<{ item: UnfilledItem; value: string }>) {
		const { item, value } = event.detail;
		
		// Create edit
		const edit: UnfilledEdit = {
			itemId: `${item.type}-${item.index}`,
			originalText: item.text,
			newValue: value,
			type: item.type,
			context: item.surroundingContext,
			position: item.index
		};
		
		// Apply edit
		const edits = new Map<string, UnfilledEdit>();
		edits.set(edit.itemId, edit);
		const updatedReport = applyEditsToReport(response, edits);
		
		// Update response
		dispatch('save', { content: updatedReport });
		
		// Dispatch event to hide popup
		dispatch('hideHoverPopup');
		
		// Refresh detection
		setTimeout(() => {
			unfilledItems = detectUnfilledPlaceholders(updatedReport);
		}, 100);
	}

	function handlePopupAskAI(event: CustomEvent<{ message: string }>) {
		dispatch('openSidebar', { tab: 'chat', initialMessage: event.detail.message });
		// Dispatch event to hide popup
		dispatch('hideHoverPopup');
	}


	function handleHighlightClick(event: MouseEvent) {
		const target = event.target as HTMLElement;
		// Check if target itself has the class, or find closest parent with it
		const highlightElement = target.classList?.contains('unfilled-highlight') 
			? target 
			: (target.closest('.unfilled-highlight') as HTMLElement);
		if (highlightElement) {
			const type = highlightElement.dataset.type as 'measurement' | 'variable' | 'alternative' | 'instruction';
			
			
			// Only open chat for instructions (variables now use hover popup)
			// Measurements, alternatives, and variables should use the hover popup
			if (type === 'instruction') {
				const text = highlightElement.dataset.text || '';
				const context = highlightElement.dataset.context || '';
				
				if (text) {
					const chatPrompt = generateChatContext(type, text, context);
					dispatch('openSidebar', { tab: 'chat', initialMessage: chatPrompt });
				}
			}
		}
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
		// Cleanup hover timeout
		if (hoverTimeout) {
			clearTimeout(hoverTimeout);
			hoverTimeout = null;
		}
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
				onclick={(e) => {
					e.stopPropagation();
					dispatch('toggle');
				}}
				class="flex items-center gap-2 transition-colors"
				style="flex-shrink: 0;"
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
			<div class="flex items-center gap-2" style="flex-shrink: 0; position: relative; z-index: 15;">
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
				
				{#if activeView === 'report' && response && unfilledItems.total > 0 && !isEditing}
					<button
						type="button"
						onclick={(e) => {
							e.stopPropagation();
							e.preventDefault();
							// Toggle highlighting
							showHighlighting = !showHighlighting;
							// Track manual disable/enable
							if (!showHighlighting) {
								manuallyDisabled = true;
								highlightingEnabled = false;
							} else {
								manuallyDisabled = false;
								highlightingEnabled = true;
							}
						}}
						onmousedown={(e) => {
							e.stopPropagation();
						}}
						class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors {showHighlighting ? 'bg-yellow-600 text-white' : 'bg-gray-700 text-gray-300 hover:text-white'}"
						title="Toggle unfilled placeholder highlighting"
						style="position: relative; z-index: 25; pointer-events: auto; cursor: pointer; min-width: fit-content; flex-shrink: 0;"
					>
						<span class="flex items-center gap-1.5">
							🎨 Unfilled ({unfilledItems.total})
						</span>
					</button>
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

				{#if activeView === 'report'}
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
				{/if}
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
				<div class="relative p-4 pt-0 max-h-[calc(100vh-250px)] overflow-y-auto space-y-4">
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
							{#if showSummaryPanel && unfilledItems.total > 0 && !isEditing}
					<div class="relative mb-4" style="z-index: 10;">
						<div
							class="group relative w-full bg-gradient-to-br from-yellow-900/20 to-orange-800/10 backdrop-blur-xl border border-yellow-500/30 rounded-xl p-4"
						>
							<div class="flex items-start justify-between mb-3">
								<div class="flex items-center gap-3">
									<div class="w-10 h-10 rounded-lg bg-yellow-600/20 flex items-center justify-center">
										<svg class="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
										</svg>
									</div>
									<div class="text-left">
										<h4 class="text-sm font-semibold text-white group-hover:text-yellow-300 transition-colors">Unfilled Items</h4>
										<p class="text-xs text-gray-400">Complete your report</p>
									</div>
								</div>
								<div class="flex items-center gap-2 flex-wrap">
									{#if unfilledItems.measurements.length > 0}
										<span class="px-2.5 py-1 bg-yellow-600/20 text-yellow-400 text-xs font-semibold rounded border border-yellow-500/30 flex items-center gap-1.5">
											<span>🟡</span>
											<span>{unfilledItems.measurements.length}</span>
											<span class="text-[10px] text-yellow-300/70">Measurements</span>
										</span>
									{/if}
									{#if unfilledItems.alternatives.length > 0}
										<span class="px-2.5 py-1 bg-purple-600/20 text-purple-400 text-xs font-semibold rounded border border-purple-500/30 flex items-center gap-1.5">
											<span>🟣</span>
											<span>{unfilledItems.alternatives.length}</span>
											<span class="text-[10px] text-purple-300/70">Alternatives</span>
										</span>
									{/if}
									{#if unfilledItems.variables.length > 0}
										<span class="px-2.5 py-1 bg-green-600/20 text-green-400 text-xs font-semibold rounded border border-green-500/30 flex items-center gap-1.5">
											<span>🟢</span>
											<span>{unfilledItems.variables.length}</span>
											<span class="text-[10px] text-green-300/70">Variables</span>
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
							<div 
								class="report-content-wrapper"
								onclick={(e) => {
									handleHighlightClick(e);
								}}
								onmouseover={(e) => {
									// Use mouseover instead of mouseenter because mouseover bubbles
									// This allows us to detect when hovering over child SPAN elements or section markers
									const target = e.target as HTMLElement;
									const hasHighlight = target?.classList?.contains('unfilled-highlight') || target?.closest('.unfilled-highlight');
									const hasMarker = target?.classList?.contains('unfilled-section-marker') || target?.closest('.unfilled-section-marker');
									// #region agent log
									if (hasHighlight || hasMarker) {
										fetch('http://127.0.0.1:7242/ingest/a59119f0-db5c-49eb-9fef-3b4b91f1274b',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'ReportResponseViewer.svelte:onmouseover',message:'container mouseover',data:{targetTag:target?.tagName,targetClass:target?.className,hasHighlight,hasMarker},timestamp:Date.now(),sessionId:'debug-session',runId:'run1',hypothesisId:'BLANK_HOVER'})}).catch(()=>{});
									}
									// #endregion
									if (hasHighlight || hasMarker) {
										handleHighlightMouseEnter(e);
									}
								}}
								onmouseout={(e) => {
									// Use mouseout instead of mouseleave because mouseout bubbles
									const target = e.target as HTMLElement;
									const relatedTarget = e.relatedTarget as HTMLElement;
									// Only handle if leaving a highlight element or section marker and not moving to another highlight/marker or popup
									if (target?.classList?.contains('unfilled-highlight') || target?.closest('.unfilled-highlight') ||
										target?.classList?.contains('unfilled-section-marker') || target?.closest('.unfilled-section-marker')) {
										if (!relatedTarget?.closest('.unfilled-highlight') && 
											!relatedTarget?.closest('.unfilled-section-marker') && 
											!relatedTarget?.closest('.unfilled-hover-popup')) {
											handleHighlightMouseLeave(e);
										}
									}
								}}
							>
								{#if showHighlighting && unfilledItems.total > 0}
									<div class="prose prose-invert max-w-none unfilled-highlight-container">
										{@html (() => {
											const highlighted = highlightUnfilledContent(renderMarkdown(response), unfilledItems);
											return highlighted;
										})()}
									</div>
								{:else}
									<div class="prose prose-invert max-w-none">
										{@html renderMarkdown(response)}
									</div>
								{/if}
							</div>
						{/if}
					{:else}
						<p class="text-sm text-gray-400">Response will appear here once generated.</p>
					{/if}
					</div>
					{/if}
					</div>
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



<style>
	/* Unfilled placeholder highlighting */
	:global(.unfilled-highlight) {
		cursor: pointer;
		padding: 0 2px;
		border-radius: 2px;
		transition: all 0.2s;
		position: relative;
	}

	:global(.unfilled-highlight:hover) {
		transform: translateY(-1px);
		filter: brightness(1.2);
	}

	/* Type-specific colors (matching template preview) */
	:global(.unfilled-measurement) {
		background: rgba(251, 191, 36, 0.2);
		border-bottom: 2px solid #fbbf24;
		color: #fbbf24;
	}

	:global(.unfilled-variable) {
		background: rgba(52, 211, 153, 0.2);
		border-bottom: 2px solid #34d399;
		color: #34d399;
	}

	:global(.unfilled-section-marker) {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		margin: 0.5rem 0;
		background: rgba(251, 191, 36, 0.1);
		border-left: 4px solid rgb(251, 191, 36);
		border-radius: 0.375rem;
		cursor: pointer;
		transition: all 0.2s;
	}

	:global(.unfilled-section-marker:hover) {
		background: rgba(251, 191, 36, 0.2);
		transform: translateX(2px);
	}

	:global(.unfilled-section-icon) {
		font-size: 1.25rem;
	}

	:global(.unfilled-section-text) {
		color: rgb(251, 191, 36);
		font-weight: 500;
		font-size: 0.875rem;
	}

	:global(.unfilled-alternative) {
		background: rgba(192, 132, 252, 0.2);
		border-bottom: 2px solid #c084fc;
		color: #c084fc;
	}

	:global(.unfilled-instruction) {
		background: rgba(96, 165, 250, 0.2);
		border-bottom: 2px solid #60a5fa;
		color: #60a5fa;
	}

</style>

