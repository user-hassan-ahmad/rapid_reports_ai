<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { writable } from 'svelte/store';
	import { token } from '$lib/stores/auth';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import EnhancementPreviewCards from './EnhancementPreviewCards.svelte';
	import EnhancementInlinePanel from './EnhancementInlinePanel.svelte';
	import ReportEditor from './ReportEditor.svelte';
	import AuditBanner from './AuditBanner.svelte';
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
	
	// Audit props
	export let scanType: string = '';
	export let clinicalHistory: string = '';
	
	// Track previous response to detect manual updates
	let previousResponse = '';

	let activeView = 'report';

	// Inline panel state
	let inlinePanelVisible = false;
	let inlinePanelTab: 'guidelines' | 'comparison' | 'chat' = 'guidelines';

	// Mobile detection for responsive QA panel
	let isMobile = false;
	let mediaQueryList: MediaQueryList | null = null;

	// Unfilled placeholder detection state — updated via on:unfilledItems from ReportEditor
	let showHighlighting = false;
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

	// ─── Audit integration ────────────────────────────────────────────────────
	// Per-component-instance store — avoids cross-contamination between the
	// AutoReportTab and TemplatedReportTab instances of ReportResponseViewer,
	// which previously shared a single module-level singleton.
	interface AuditCriterionItem {
		criterion: string;
		status: 'pass' | 'flag' | 'warning';
		rationale: string;
		highlighted_spans?: string[];
		recommendation?: string;
		acknowledged?: boolean;
	}

	interface AuditStoreState {
		status: 'idle' | 'loading' | 'complete' | 'stale' | 'error';
		result: any;
		auditId: string | null;
		error: string | null;
		activeCriterion: string | null;
	}

	const auditStore = writable<AuditStoreState>({
		status: 'idle', result: null, auditId: null, error: null, activeCriterion: null
	});

	// Store helpers — mirror the global store's API
	const auditActions = {
		setLoading: () => auditStore.update(s => ({ ...s, status: 'loading', error: null })),
		setResult: (result: any, auditId: string | null) =>
			auditStore.update(s => ({ ...s, status: 'complete', result, auditId, error: null })),
		setStale: () => auditStore.update(s => s.status === 'complete' ? { ...s, status: 'stale' } : s),
		setError: (error: string) => auditStore.update(s => ({ ...s, status: 'error', error })),
		setActiveCriterion: (criterion: string | null) =>
			auditStore.update(s => ({ ...s, activeCriterion: criterion })),
		acknowledgeLocal: (criterion: string, resolutionMethod?: string) => auditStore.update(s => {
			if (!s.result) return s;
			const criteria = s.result.criteria.map((c: AuditCriterionItem) =>
				c.criterion === criterion ? { ...c, acknowledged: true, resolution_method: resolutionMethod } : c
			);
			return { ...s, result: { ...s.result, criteria } };
		}),
		unacknowledgeLocal: (criterion: string) => auditStore.update(s => {
			if (!s.result) return s;
			const criteria = s.result.criteria.map((c: AuditCriterionItem) =>
				c.criterion === criterion ? { ...c, acknowledged: false, resolution_method: undefined } : c
			);
			return { ...s, result: { ...s.result, criteria } };
		}),
		reset: () => auditStore.set({ status: 'idle', result: null, auditId: null, error: null, activeCriterion: null }),
	};

	let auditPanelOpen = false;
	let auditPanelAutoOpened = false; // one-time flag so user can close panel without it snapping back

	// Content-based tracking: prevents re-auditing same content AND avoids stale triggers.
	// Set immediately (synchronously) inside triggerAudit so the reactive won't double-fire.
	let lastAuditedContent = '';

	// Track inserted banner texts — survives re-audits within the same report session.
	// Reset only when the report ID changes (new report loaded).
	let insertedBannerTexts: string[] = [];

	// Derive audit decorations — only for unacknowledged, non-passing criteria
	$: auditDecorations = ($auditStore.result?.criteria ?? [] as AuditCriterionItem[])
		.filter((c: AuditCriterionItem) => c.status !== 'pass')
		.filter((c: AuditCriterionItem) => !c.acknowledged)
		.flatMap((c: AuditCriterionItem) => (c.highlighted_spans || []).map((text: string) => ({
			text,
			criterion: c.criterion,
			status: c.status as 'flag' | 'warning',
			stale: $auditStore.status === 'stale'
		})));

	// Private tracking variable for audit resets — kept separate from `lastReportId` (used
	// for highlighting resets) to avoid Svelte's topological sort running the lastReportId
	// writer block before this reader block, which previously made this condition always false.
	let lastAuditReportId: string | null = null;
	$: if (reportId !== lastAuditReportId) {
		lastAuditReportId = reportId;
		lastAuditedContent = '';
		auditPanelOpen = false;
		auditPanelAutoOpened = false;
		auditActions.reset();
		insertedBannerTexts = [];
	}

	// Auto-trigger: only fires when response is new content we haven't audited yet.
	// Content-based check prevents firing with stale/old response text.
	$: if (response && !generationLoading && response !== lastAuditedContent && $auditStore.status === 'idle') {
		triggerAudit(response);
	}

	// Mark audit as stale when there are unsaved changes (user edits)
	$: if (hasUnsavedChanges && $auditStore.status === 'complete') {
		auditActions.setStale();
	}

	// Mark audit as stale when content changed (e.g. restore to previous version) and differs from last audited
	$: if (response && !generationLoading && response !== lastAuditedContent && $auditStore.status === 'complete') {
		auditActions.setStale();
	}

	// Auto-open audit panel once when audit first completes (one-time, so user can close it)
	$: if ($auditStore.status === 'complete' && !auditPanelAutoOpened) {
		auditPanelAutoOpened = true;
		auditPanelOpen = true;
	}

	// Audit panel toggle badge info
	$: auditFlagCount = ($auditStore.result?.criteria ?? [])
		.filter((c: AuditCriterionItem) => c.status === 'flag').length;
	$: auditWarningCount = ($auditStore.result?.criteria ?? [])
		.filter((c: AuditCriterionItem) => c.status === 'warning').length;

	async function triggerAudit(content: string) {
		if (!content.trim()) return;
		// Mark as audited immediately (synchronous) to prevent the reactive from re-firing
		lastAuditedContent = content;
		auditActions.setLoading();
		
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const res = await fetch(`${API_URL}/api/audit`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					report_content: content,
					scan_type: scanType,
					clinical_history: clinicalHistory,
					report_id: reportId
				})
			});
			
			const data = await res.json();
			
			if (!res.ok || !data.success) {
				throw new Error(data.detail || data.error || 'Audit failed');
			}
			
			auditActions.setResult(data, data.audit_id);
			// If a banner was previously inserted and is still in the report, auto-acknowledge
			// clinical_flagging so it doesn't re-surface decorations or the banner panel.
			if (insertedBannerTexts.length > 0) {
				const currentContent = (currentEditorContent || response || '').trim();
				const bannerStillPresent = insertedBannerTexts.some((txt: string) => currentContent.includes(txt));
				if (bannerStillPresent) {
					auditActions.acknowledgeLocal('clinical_flagging', 'manual');
				}
			}
		} catch (e) {
			auditActions.setError(e instanceof Error ? e.message : 'Audit failed');
		}
	}

	function handleAuditSpanHover(e: CustomEvent<{ criterion: string | null }>) {
		auditActions.setActiveCriterion(e.detail.criterion);
	}

	function handleAuditSpanClick(e: CustomEvent<{ criterion: string }>) {
		const { criterion } = e.detail;
		// Open the panel if closed, then navigate to the criterion card
		if (!auditPanelOpen && $auditStore.status !== 'idle') {
			auditPanelOpen = true;
			auditPanelAutoOpened = true;
		}
		auditActions.setActiveCriterion(criterion);
	}

	function handleRestore(e: CustomEvent<{ criterion: string }>) {
		auditActions.unacknowledgeLocal(e.detail.criterion);
	}

	async function handleAcknowledge(e: CustomEvent<{ criterion: string; resolutionMethod: string }>) {
		const { criterion, resolutionMethod } = e.detail;
		const auditId = $auditStore.auditId;
		
		if (!auditId) return;
		
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			await fetch(`${API_URL}/api/audit/${auditId}/criteria/${criterion}`, {
				method: 'PATCH',
				headers,
				body: JSON.stringify({ resolution_method: resolutionMethod })
			});
			
			auditActions.acknowledgeLocal(criterion, resolutionMethod);
		} catch (e) {
			console.error('Failed to acknowledge criterion:', e);
		}
	}

	async function handleSuggestFix(e: CustomEvent<{ criterion: string; rationale: string }>) {
		const { criterion, rationale } = e.detail;
		const msg = `The audit flagged an issue with "${criterion}": ${rationale}. Please go ahead and apply the appropriate correction to the report now.`;
		// Open chat sidebar
		dispatch('openSidebar', {
			tab: 'chat',
			initialMessage: msg,
			autoSend: true,
			labelInfo: { type: 'audit-fix', name: criterion }
		});
		// Also acknowledge the criterion so it moves to Reviewed and Completed sections
		auditActions.acknowledgeLocal(criterion, 'ai_assisted');
		const auditId = $auditStore.auditId;
		if (auditId) {
			try {
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) headers['Authorization'] = `Bearer ${$token}`;
				await fetch(`${API_URL}/api/audit/${auditId}/criteria/${criterion}`, {
					method: 'PATCH',
					headers,
					body: JSON.stringify({ resolution_method: 'ai_assisted' })
				});
			} catch (err) {
				console.error('Failed to acknowledge criterion on fix:', err);
			}
		}
	}

	async function handleInsertBanner(e: CustomEvent<{ bannerText: string }>) {
		const { bannerText } = e.detail;
		const base = (currentEditorContent || response || '').trimEnd();
		const newContent = base + '\n\n' + bannerText;
		// Track the banner so re-audits can auto-acknowledge clinical_flagging if it's still present
		insertedBannerTexts = [...insertedBannerTexts, bannerText];
		// Keep lastAuditedContent in sync so this save doesn't mark audit stale
		lastAuditedContent = newContent;
		dispatch('save', { content: newContent });
		auditActions.acknowledgeLocal('clinical_flagging');
		const auditId = $auditStore.auditId;
		if (auditId) {
			try {
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) headers['Authorization'] = `Bearer ${$token}`;
				await fetch(`${API_URL}/api/audit/${auditId}/criteria/clinical_flagging`, {
					method: 'PATCH',
					headers,
					body: JSON.stringify({ resolution_method: 'manual' })
				});
			} catch (err) {
				console.error('Failed to acknowledge clinical_flagging:', err);
			}
		}
	}

	function handleReaudit() {
		lastAuditedContent = '';
		auditActions.reset();
		triggerAudit(currentEditorContent || response);
	}

	$: if (!reportId && activeView === 'history') {
		activeView = 'report';
	}
	$: if (!visible && activeView !== 'report') {
		activeView = 'report';
	}
	
	// Auto-enable highlighting when unfilled items arrive from the editor
	function handleUnfilledItems(items: UnfilledItems) {
		unfilledItems = items;
		showHighlighting = items.total > 0;
		showSummaryPanel = items.total > 0;
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
	
	

	$: hasContent = Boolean(response || error);
	let historyCount = 0;
	let historyAvailable = false;

	$: if (!historyAvailable && activeView === 'history') {
		activeView = 'report';
	}

	// Reset state when a new report is loaded
	let lastReportId: string | null = null;
	$: if (reportId && reportId !== lastReportId) {
		showHighlighting = false;
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

	onMount(() => {
		loadHistorySummary();
		
		// Set up mobile detection via matchMedia
		mediaQueryList = window.matchMedia('(max-width: 767px)');
		isMobile = mediaQueryList.matches;
		const handleMediaChange = (e: MediaQueryListEvent) => { isMobile = e.matches; };
		mediaQueryList.addEventListener('change', handleMediaChange);
		
		return () => {
			mediaQueryList?.removeEventListener('change', handleMediaChange);
		};
	});

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
				

				<!-- QA toggle button -->
				{#if activeView === 'report' && $auditStore.status !== 'idle'}
					<button
						type="button"
						onclick={(e) => { e.stopPropagation(); auditPanelOpen = !auditPanelOpen; }}
						onmousedown={(e) => e.stopPropagation()}
						title="Toggle QA audit panel"
						class="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 sm:py-1.5 text-[10px] sm:text-xs font-medium rounded-lg transition-all
							{auditPanelOpen
								? 'bg-purple-600/30 text-purple-300 border border-purple-500/40'
								: 'bg-white/[0.05] text-gray-400 hover:text-gray-200 border border-white/[0.08] hover:border-white/[0.15]'}"
					>
						{#if $auditStore.status === 'loading'}
							<div class="w-2.5 h-2.5 border border-purple-400 border-t-transparent rounded-full animate-spin"></div>
							<span class="hidden sm:inline">QA</span>
						{:else}
							<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
							</svg>
							{#if auditFlagCount > 0}
								<span class="hidden sm:inline text-rose-300">{auditFlagCount}</span>
							{:else if auditWarningCount > 0}
								<span class="hidden sm:inline text-amber-300">{auditWarningCount}</span>
							{:else}
								<span class="hidden sm:inline">QA</span>
							{/if}
						{/if}
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
				<div class="relative px-3 sm:px-4 pt-0 pb-3 sm:pb-4 flex-1 min-h-0 overflow-y-auto">
					<!-- View container with absolute positioning for smooth crossfade transitions -->
					<div class="relative" style="min-height: calc(100vh - 330px);">
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
							class="absolute inset-0 overflow-hidden"
							transition:fade={{ duration: 200, easing: (t) => t * (2 - t) }}
						>
							<!-- Editor content (full-width, scrollable). @container for enhancement cards to switch layout based on available width -->
							<div class="@container h-full overflow-y-auto" style="padding-right: {!isMobile && auditPanelOpen && $auditStore.status !== 'idle' ? '288px' : '0'}; transition: padding-right 220ms cubic-bezier(0,0,0.2,1);"
							>
							<!-- Enhancement Preview Cards - Before report content -->
							{#if reportId}
					<EnhancementPreviewCards
						guidelinesCount={enhancementGuidelinesCount}
						isLoading={enhancementLoading}
						hasError={enhancementError}
						reportId={reportId}
						panelOpen={!isMobile && auditPanelOpen && $auditStore.status !== 'idle'}
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
						auditDecorations={auditDecorations}
						on:change={handleEditorChange}
						on:save={() => { if (hasUnsavedChanges) saveEditing(); }}
						on:unfilledItems={(e) => handleUnfilledItems(e.detail.items)}
						on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
						on:hideHoverPopup={() => dispatch('hideHoverPopup')}
						on:auditSpanHover={handleAuditSpanHover}
					on:auditSpanClick={handleAuditSpanClick}
					/>
					{:else}
						<p class="text-sm text-gray-400">Response will appear here once generated.</p>
					{/if}
							</div>

							<!-- Right: Audit side panel overlay (desktop only) -->
							{#if !isMobile && auditPanelOpen && $auditStore.status !== 'idle'}
								<div
									class="absolute top-0 right-0 bottom-0 w-[280px] border-l border-white/[0.06] overflow-hidden"
									transition:fly={{ x: 16, duration: 220, easing: (t) => 1 - Math.pow(1 - t, 3) }}
								>
									<AuditBanner
										auditState={$auditStore as any}
										canReaudit={$auditStore.status === 'stale' || $auditStore.status === 'complete'}
										showClose={true}
										on:acknowledge={handleAcknowledge}
										on:restore={handleRestore}
										on:suggestFix={handleSuggestFix}
										on:insertBanner={handleInsertBanner}
										on:reaudit={handleReaudit}
										on:close={() => auditPanelOpen = false}
									/>
								</div>
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

	<!-- Mobile QA Bottom Sheet -->
	{#if isMobile && auditPanelOpen && $auditStore.status !== 'idle'}
		<!-- Backdrop -->
		<button
			type="button"
			class="fixed inset-0 bg-black/60 z-40"
			transition:fade={{ duration: 200 }}
			onclick={() => auditPanelOpen = false}
			aria-label="Close QA panel"
		></button>
		
		<!-- Bottom Sheet -->
		<div
			class="fixed inset-x-0 bottom-0 z-50 bg-[#0a0a12] border-t border-white/10 rounded-t-2xl max-h-[70vh] flex flex-col shadow-2xl"
			transition:fly={{ y: 300, duration: 280, easing: (t) => 1 - Math.pow(1 - t, 3) }}
		>
			<!-- Drag handle indicator -->
			<div class="flex justify-center pt-3 pb-1">
				<div class="w-10 h-1 rounded-full bg-white/20"></div>
			</div>
			
			<!-- Close button row -->
			<div class="flex items-center justify-between px-4 pb-2">
				<span class="text-xs font-semibold text-white/60 uppercase tracking-wider">Report QA</span>
				<button
					type="button"
					class="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
					onclick={() => auditPanelOpen = false}
					aria-label="Close"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			
			<!-- AuditBanner content (scrollable) -->
			<div class="flex-1 min-h-0 overflow-hidden">
				<AuditBanner
					auditState={$auditStore as any}
					canReaudit={$auditStore.status === 'stale' || $auditStore.status === 'complete'}
					on:acknowledge={handleAcknowledge}
					on:restore={handleRestore}
					on:suggestFix={handleSuggestFix}
					on:insertBanner={handleInsertBanner}
					on:reaudit={handleReaudit}
				/>
			</div>
		</div>
	{/if}
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

