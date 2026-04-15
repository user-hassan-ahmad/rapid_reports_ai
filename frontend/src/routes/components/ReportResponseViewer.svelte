<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	import { writable } from 'svelte/store';
	import { token } from '$lib/stores/auth';
	import { getAuditState, auditActions as sharedAuditActions } from '$lib/stores/audit';
	import ReportVersionInline from './ReportVersionInline.svelte';
	import ReportEditor from './ReportEditor.svelte';
	import { API_URL } from '$lib/config';
	import { detectUnfilledPlaceholders, generateChatContext } from '$lib/utils/placeholderDetection';
	import { applyEditsToReport } from '$lib/utils/reportEditing';
	import type { UnfilledEdit } from '$lib/stores/unfilledEditor';
	import type { UnfilledItem, UnfilledItems } from '$lib/utils/placeholderDetection';
	import type { AuditFixContext } from '$lib/types/auditFixContext';
	const dispatch = createEventDispatcher();

	export let visible = false;
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
	export let applicableGuidelines: Array<{
		system: string;
		context: string;
		type: string;
		search_keywords?: string | null;
	}> = [];

	export let caseDetailsDirty = false;
	export let findingsStale = false;
	export let canRefineTemplate = false;
	
	// Track previous response to detect manual updates
	let previousResponse = '';

	let activeView = 'report';

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
		units_unconfirmed: [],
		total: 0
	};

	// Editor state
	let hasUnsavedChanges = false;
	let currentEditorContent = '';
	let lastSavedResponse = '';
	let reportEditorRef: { resetContent: (c: string) => void } | null = null;
	let saveInFlight = false;

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
		criterion_line?: string | null;
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
		auditActions.reset();
		insertedBannerTexts = [];
	}

	// Subscribe to shared store for Phase 2 merges from the sidebar
	$: sharedState = reportId ? getAuditState(reportId) : null;
	$: if (sharedState && $sharedState && $sharedState.result && $auditStore.result) {
		const sharedCount = $sharedState.result.criteria?.length ?? 0;
		const localCount = $auditStore.result?.criteria?.length ?? 0;
		if (sharedCount > localCount) {
			auditActions.setResult($sharedState.result, $sharedState.auditId);
			// Auto-acknowledge clinical_flagging if a banner was previously inserted and is still in the report
			if (insertedBannerTexts.length > 0) {
				const currentContent = (currentEditorContent || response || '').trim();
				const bannerStillPresent = insertedBannerTexts.some((txt: string) => currentContent.includes(txt));
				if (bannerStillPresent) {
					auditActions.acknowledgeLocal('clinical_flagging', 'manual');
				}
			}
		}
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

	async function triggerAudit(content: string) {
		if (!content.trim()) return;
		lastAuditedContent = content;
		auditActions.setLoading();
		dispatch('auditComplete', { guidelineReferences: [], auditCriteria: [] });
		
		const _auditT0 = typeof performance !== 'undefined' ? performance.now() : 0;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const auditBody = {
				report_content: content,
				scan_type: scanType,
				clinical_history: clinicalHistory,
				report_id: reportId,
				applicable_guidelines: applicableGuidelines
			};

			const res = await fetch(`${API_URL}/api/audit`, {
				method: 'POST',
				headers,
				body: JSON.stringify(auditBody)
			});
			
			const data = await res.json();
			const _auditT1 = typeof performance !== 'undefined' ? performance.now() : 0;
			console.debug(
				'[FLOW_TIMING] viewer POST /api/audit roundtrip_ms=',
				Math.round(_auditT1 - _auditT0),
				'report_id=',
				reportId
			);

			if (!res.ok || !data.success) {
				throw new Error('Audit failed. Please try again.');
			}
			
			auditActions.setResult(data, data.audit_id);
			if (reportId) {
				sharedAuditActions.setResult(reportId, data, data.audit_id);
			}
			dispatch('auditComplete', {
				guidelineReferences: data.guideline_references ?? [],
				auditCriteria: data.criteria ?? []
			});

			if (insertedBannerTexts.length > 0) {
				const currentContent = (currentEditorContent || response || '').trim();
				const bannerStillPresent = insertedBannerTexts.some((txt: string) => currentContent.includes(txt));
				if (bannerStillPresent) {
					auditActions.acknowledgeLocal('clinical_flagging', 'manual');
				}
			}
		} catch (e) {
			auditActions.setError('Audit failed. Please try again.');
			dispatch('auditComplete', { guidelineReferences: [], auditCriteria: [] });
		}
	}

	function handleAuditSpanHover(e: CustomEvent<{ criterion: string | null }>) {
		auditActions.setActiveCriterion(e.detail.criterion);
	}

	function handleAuditSpanClick(e: CustomEvent<{ criterion: string }>) {
		const { criterion } = e.detail;
		auditActions.setActiveCriterion(criterion);
		dispatch('openSidebar', { tab: 'qa' });
	}

	function handleRestore(e: CustomEvent<{ criterion: string }>) {
		auditActions.unacknowledgeLocal(e.detail.criterion);
	}

	async function handleAcknowledge(e: CustomEvent<{ criterion: string; resolutionMethod: string }>) {
		const { criterion, resolutionMethod } = e.detail;
		auditActions.acknowledgeLocal(criterion, resolutionMethod);
		await _tryPatchCriterion(criterion, resolutionMethod);
	}

	async function handleSuggestFix(
		e: CustomEvent<{
			criterion: string;
			rationale: string;
			auditFixContext?: AuditFixContext;
		}>
	) {
		const { criterion, rationale, auditFixContext } = e.detail;
		const msg =
			`The audit raised "${criterion}": ${rationale}\n\n` +
			`Address that concern first. Then re-read the full report (especially impression vs findings) and apply any **material** fixes needed for internal consistency and clinical completeness—` +
			`including important management implications supported by the documented findings even if the audit did not flag them. ` +
			`Go ahead and apply the edits to the report now.`;
		// Open chat sidebar
		dispatch('openSidebar', {
			tab: 'chat',
			initialMessage: msg,
			autoSend: true,
			labelInfo: { type: 'audit-fix', name: criterion },
			...(auditFixContext ? { auditFixContext } : {})
		});
		// Also acknowledge the criterion so it moves to Reviewed and Completed sections
		auditActions.acknowledgeLocal(criterion, 'ai_assisted');
		await _tryPatchCriterion(criterion, 'ai_assisted');
	}

	async function _tryPatchCriterion(criterion: string, resolutionMethod: string) {
		const auditId = $auditStore.auditId;
		if (!auditId) return;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/audit/${auditId}/criteria/${criterion}`, {
				method: 'PATCH',
				headers,
				body: JSON.stringify({ resolution_method: resolutionMethod })
			});
			if (!res.ok) {
				console.warn(`[Audit] PATCH ${criterion} returned ${res.status} — criterion may not exist in this audit row (Phase 2 cache)`);
			}
		} catch (err) {
			console.error('Failed to acknowledge criterion:', err);
		}
	}

	async function handleInsertBanner(e: CustomEvent<{ bannerText: string }>) {
		const { bannerText } = e.detail;
		const base = (currentEditorContent || response || '').trimEnd();
		const newContent = base + '\n\n' + bannerText;
		// Track the banner so re-audits can auto-acknowledge clinical_flagging if it's still present
		insertedBannerTexts = [...insertedBannerTexts, bannerText];
		currentEditorContent = newContent;
		reportEditorRef?.resetContent(newContent);
		lastAuditedContent = newContent;
		saveInFlight = true;
		dispatch('save', { content: newContent });
		auditActions.acknowledgeLocal('clinical_flagging');
		await _tryPatchCriterion('clinical_flagging', 'manual');
	}

	async function handleApplyFix(e: CustomEvent<{
		criterion: string;
		original: string | null;
		replacement: string | null;
		sentence: string | null;
		source: string;
	}>) {
		const { criterion, original, replacement, sentence, source } = e.detail;
		const base = currentEditorContent || response || '';

		let newContent: string;
		let originalSpan: string | null = null;
		let replacementSpan: string | null = null;

		if (original && replacement) {
			// Surgical span substitution — first occurrence only
			const index = base.indexOf(original);
			if (index === -1) {
				// Span not found (report edited after audit ran) — no-op; fall back to chat
				handleSuggestFix(new CustomEvent('suggestFix', { detail: { criterion, rationale: 'Span not found — please apply manually.' } }));
				return;
			}
			newContent = base.slice(0, index) + replacement + base.slice(index + original.length);
			originalSpan = original;
			replacementSpan = replacement;
		} else if (sentence) {
			// Structural insertion — append sentence after the last paragraph
			newContent = base.trimEnd() + '\n\n' + sentence;
			replacementSpan = sentence;
		} else {
			return;
		}

		currentEditorContent = newContent;
		reportEditorRef?.resetContent(newContent);
		lastAuditedContent = newContent;
		saveInFlight = true;
		dispatch('save', {
			content: newContent,
			editSource: source,
			originalSpan,
			replacementSpan,
			auditCriterion: criterion
		});
		auditActions.acknowledgeLocal(criterion, 'manual');
		await _tryPatchCriterion(criterion, 'manual');
	}

	function handleReaudit() {
		if (saveInFlight) return;
		lastAuditedContent = '';
		auditActions.reset();
		triggerAudit(currentEditorContent || response);
	}

	$: dispatch('auditStateChange', {
		status: $auditStore.status,
		result: $auditStore.result,
		auditId: $auditStore.auditId,
		error: $auditStore.error,
		activeCriterion: $auditStore.activeCriterion,
		saveInFlight
	});

	export function acknowledgeFromExternal(detail: { criterion: string; resolutionMethod: string }) {
		void handleAcknowledge(new CustomEvent('ack', { detail }));
	}
	export function restoreFromExternal(detail: { criterion: string }) {
		handleRestore(new CustomEvent('restore', { detail }));
	}
	export function suggestFixFromExternal(detail: {
		criterion: string;
		rationale: string;
		auditFixContext?: AuditFixContext;
	}) {
		void handleSuggestFix(new CustomEvent('sf', { detail }));
	}
	export function applyFixFromExternal(detail: unknown) {
		void handleApplyFix(new CustomEvent('applyFix', { detail }));
	}
	export function insertBannerFromExternal(bannerText: string) {
		void handleInsertBanner(new CustomEvent('insertBanner', { detail: { bannerText } }));
	}
	export function reauditFromExternal() {
		handleReaudit();
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
		saveInFlight = false;
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
			type: item.type as 'measurement' | 'variable' | 'alternative' | 'instruction' | 'units_unconfirmed',
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
				throw new Error('Failed to load version history. Please try again.');
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
			<div class="flex items-center gap-2 shrink-0">
				<h2 class="text-base sm:text-lg font-semibold text-white">Report Editor</h2>
			</div>
			
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

			{#if reportId}
				<!-- Interval Analysis / Compare: radiologist pastes in prior report text.
				     Icon matches the Copilot sidebar's Compare entry for cross-surface consistency. -->
				<button
					type="button"
					onclick={(e) => { e.stopPropagation(); dispatch('openCompare'); }}
					class="compare-rpt-btn"
					title="Paste a prior report to run AI interval analysis"
				>
					<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
					</svg>
					<div class="compare-rpt-inner">
						<span class="compare-rpt-label">Compare</span>
						<span class="compare-rpt-sub">vs prior study</span>
					</div>
				</button>
			{/if}

			{#if canRefineTemplate}
				<!-- Refine Template: opens the template-refinement drawer for the current skill-sheet template -->
				<button
					type="button"
					onclick={(e) => { e.stopPropagation(); dispatch('refineTemplate'); }}
					class="compare-rpt-btn refine-tpl-btn"
					title="Refine the template's instructions — applied to future reports"
				>
					<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
						<path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
					</svg>
					<div class="compare-rpt-inner">
						<span class="compare-rpt-label">Refine</span>
						<span class="compare-rpt-sub">template</span>
					</div>
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

	<div class="relative flex-1 min-h-0 flex flex-col transition-opacity duration-300 {caseDetailsDirty ? 'opacity-50 pointer-events-none' : ''}">
				{#if caseDetailsDirty}
					<div class="absolute inset-0 z-20 flex items-center justify-center bg-black/20 backdrop-blur-[1px]" in:fade={{ duration: 200 }}>
						<p class="text-sm text-gray-300 font-medium px-4 py-2 bg-black/60 rounded-lg shadow-lg">Case details changed — regenerate workspace to continue</p>
					</div>
				{/if}
				{#if findingsStale && !caseDetailsDirty}
					<div class="bg-amber-500/10 border-b border-amber-500/20 px-4 py-2 flex items-start gap-2 shrink-0" in:fade={{ duration: 200 }}>
						<svg class="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
						</svg>
						<p class="text-xs text-amber-200">
							Findings have been updated — report may not reflect current changes. <span class="font-medium text-amber-400">Regenerate to update.</span>
						</p>
					</div>
				{/if}

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
							<div class="@container h-full overflow-y-auto">
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

		</div>
	</div>

{/if}



<style>
	/* Highlight decoration styles are now in ReportEditor.svelte */

	/* ── Compare to prior report button ─────────────────────────────────────── */
	.compare-rpt-btn {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 5px 10px;
		border-radius: 8px;
		border: 1px solid rgba(139, 92, 246, 0.28);
		background: rgba(139, 92, 246, 0.08);
		color: #c4b5fd;
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s, color 0.15s, box-shadow 0.15s;
		font-family: inherit;
		flex-shrink: 0;
	}
	.compare-rpt-btn:hover {
		background: rgba(139, 92, 246, 0.16);
		border-color: rgba(139, 92, 246, 0.45);
		color: #e9d5ff;
		box-shadow: 0 0 12px rgba(139, 92, 246, 0.2);
	}
	.compare-rpt-inner {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 1px;
	}
	.compare-rpt-label {
		font-size: 10.5px;
		font-weight: 600;
		line-height: 1.2;
		letter-spacing: -0.01em;
	}
	.compare-rpt-sub {
		font-size: 8.5px;
		font-weight: 500;
		opacity: 0.6;
		line-height: 1.2;
		white-space: nowrap;
	}

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

