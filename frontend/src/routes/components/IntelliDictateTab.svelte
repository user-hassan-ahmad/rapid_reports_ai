<script lang="ts">
import { createEventDispatcher, tick } from 'svelte';
import { fly, fade } from 'svelte/transition';
import { token } from '$lib/stores/auth';
import { draftStore } from '$lib/stores/draft.js';
import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';
import DictationHintBar from '$lib/components/DictationHintBar.svelte';
import ReportResponseViewer from './ReportResponseViewer.svelte';
import Toast from '$lib/components/Toast.svelte';
import { API_URL } from '$lib/config';
import { readSSEStream } from '$lib/utils/sse';

	let toast: { show: (msg: string) => void } | undefined;

	const dispatch = createEventDispatcher();

	let clinicalHistory = '';
	let scanType = '';
	let prePoppedSections: string[] = [];
	let sectionsLoading = false;
	let sectionsError = '';
	let sectionsGeneratedFromScanType = '';
	let sectionsGeneratedFromHistory = '';
	let regenerating = false;

	// ── Quick-report ephemeral-skill-sheet pipeline ──
	// Speculative-parallel: backend fires FAST (GLM, ~9s) and BEST (Haiku, ~40s)
	// analysers concurrently and streams an `analyser_ready` event per variant.
	// /generate uses whichever sheet is available at click time — preferring
	// best. If both /analyse variants fail, /generate has a one-shot fallback
	// that runs the analyser inline from scan_type + clinical_history.
	let fastSheetId = '';
	let bestSheetId = '';
	// True while /analyse is streaming. The Generate button disables until at
	// least one sheet is ready (either variant enables it).
	let analyseLoading = false;
	// Monotonic token so stale /analyse responses (from superseded workspace
	// setups) can't overwrite fresh ones.
	let analyseVersion = 0;
	$: analyserReady = Boolean(fastSheetId || bestSheetId);
	$: bestSheetReady = Boolean(bestSheetId);

	// ── /generate SSE candidate ──
	// /generate streams a single GLM-4.7 candidate via SSE: one `candidate`
	// event carries the report content, then a `done` event carries the
	// persisted report_id.
	interface Candidate {
		model: string;
		content: string;
		latency_ms: number | null;
		run_id: string;
		generated_at: string;
		error: string | null;
		description?: string | null;
	}

	interface IntelliPrompt { question: string; source_text: string; rationale?: string; }

	// Reset confirmation (when scratchpad has content)
	let resetConfirmVisible = false;

	// Case details collapsed/expanded state
	let caseDetailsManuallyExpanded = false;

	$: workspaceOpen = prePoppedSections.length > 0 || sectionsLoading;
	$: sectionsDirty = prePoppedSections.length > 0
		&& (scanType.trim() !== sectionsGeneratedFromScanType
			|| clinicalHistory.trim() !== sectionsGeneratedFromHistory);
	// Show full form when: no workspace yet, user clicked edit, or there's a dirty state needing action
	$: caseDetailsExpanded = !workspaceOpen || caseDetailsManuallyExpanded || sectionsDirty;
	let scratchpadRef: {
		getContent: () => string;
		getFindingCount: () => number;
		reset: (doc: string) => void;
		highlightSource: (text: string) => void;
		clearHighlight: () => void;
	} | null = null;

	// Checklist: covered sections from Qwen API response
	let coveredSections: Set<string> = new Set();

	// IntelliPrompts from Qwen
	let activePrompts: IntelliPrompt[] = [];

	// Scratchpad content for parsing dynamic sections
	let scratchpadContent = '';

	// Recording state (from DictationScratchpad)
	let isRecording = false;

	// Review loading state (from DictationScratchpad)
	let isReviewing = false;

	// Generation (same shape as AutoReportTab)
	export let response: any = null;
	export let responseModel: any = null;
	export let loading = false;
	export let error: any = null;
	export let reportId: any = null;
	export let reportUpdateLoading = false;
	export let versionHistoryRefreshKey = 0;
	export let enhancementGuidelinesCount = 0;
	export let enhancementLoading = false;
	export let enhancementError = false;
	export let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		cerebras_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false
	};

	let applicableGuidelines: Array<{
		system: string;
		context: string;
		type: string;
		search_keywords?: string | null;
	}> = [];

	// ReportResponseViewer state
	let hasResponseEver = false;
	let responseVisible = false;

	$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);
	let findingsAtReportGeneration = '';
	$: findingsStale = hasResponseEver && !!response && scratchpadToFindings(scratchpadContent) !== findingsAtReportGeneration;

	// Review guide shows the pre-generated checklist sections only.
	// Coverage state comes entirely from covered_sections returned by Qwen — no text parsing.
	$: allChecklistSections = prePoppedSections;

	/**
	 * Fire the speculative-parallel quick-report analyser in the background.
	 * Backend streams `analyser_ready` events as each variant completes (FAST
	 * first, BEST second). Runs in parallel with the sections call so at least
	 * one skill sheet is ready by the time the radiologist finishes dictating.
	 * Silent on failure — the /generate endpoint has a fallback path that runs
	 * the analyser inline if neither sheet is available.
	 *
	 * Version-tokenised: if a subsequent triggerSheetAnalyse call fires while
	 * this one is still in flight (e.g. the user re-clicks "Set up workspace"
	 * after editing scan type), this call's events are discarded on return.
	 */
	async function triggerSheetAnalyse() {
		const thisVersion = ++analyseVersion;
		fastSheetId = '';
		bestSheetId = '';
		if (!scanType.trim() || !clinicalHistory.trim()) return;
		analyseLoading = true;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/quick-report/analyse`, {
				method: 'POST',
				headers: { ...headers, Accept: 'text/event-stream' },
				body: JSON.stringify({
					scan_type: scanType.trim(),
					clinical_history: clinicalHistory.trim()
				})
			});
			if (!res.ok) return;
			await readSSEStream(res, (eventName, data) => {
				// Discard stale events — a newer analyse has superseded this one
				if (thisVersion !== analyseVersion) return;
				if (eventName === 'analyser_ready') {
					if (data?.error || !data?.sheet_id) return;
					if (data.variant === 'fast') fastSheetId = data.sheet_id;
					else if (data.variant === 'best') bestSheetId = data.sheet_id;
				}
				// `done` and `error` events are logged implicitly via loading flag.
			});
		} catch {
			// Silent — /generate fallback handles this case
		} finally {
			if (thisVersion === analyseVersion) analyseLoading = false;
		}
	}

	async function handleSetUpWorkspace() {
		if (!clinicalHistory.trim()) {
			sectionsError = 'Please enter a clinical history';
			return;
		}
		if (!scanType.trim()) {
			sectionsError = 'Please enter a scan type';
			return;
		}
		sectionsLoading = true;
		sectionsError = '';

		// Fire the ephemeral skill sheet analyser in parallel — don't await
		// here because sections is the gating UX; the sheet is ready-when-ready.
		triggerSheetAnalyse();

		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/sections`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ scan_type: scanType.trim(), clinical_history: clinicalHistory.trim() })
			});
			const data = await res.json();
			if (data.sections && Array.isArray(data.sections)) {
				prePoppedSections = data.sections;
				coveredSections = new Set();
				sectionsGeneratedFromScanType = scanType.trim();
				sectionsGeneratedFromHistory = clinicalHistory.trim();
				caseDetailsManuallyExpanded = false;
			} else {
				sectionsError = 'Failed to generate sections. Please try again.';
			}
		} catch (e) {
			sectionsError = 'Failed to connect. Please try again.';
		} finally {
			sectionsLoading = false;
		}
	}

	async function handleRegenerateSections() {
		if (!clinicalHistory.trim() || !scanType.trim() || regenerating) return;
		regenerating = true;
		sectionsError = '';

		// Re-fire the ephemeral skill sheet analyser — scan context may have
		// changed, so the old sheet_id is no longer valid for this case.
		triggerSheetAnalyse();

		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/canvas/sections`, {
				method: 'POST',
				headers,
				body: JSON.stringify({ scan_type: scanType.trim(), clinical_history: clinicalHistory.trim() })
			});
			const data = await res.json();
			if (data.sections && Array.isArray(data.sections)) {
				scratchpadRef?.reset('');
				response = null;
				responseModel = null;
				reportId = null;
				applicableGuidelines = [];
			hasResponseEver = false;
			activePrompts = [];
				findingsAtReportGeneration = '';
				dispatch('clearResponse');

				prePoppedSections = data.sections;
				coveredSections = new Set();
				sectionsGeneratedFromScanType = scanType.trim();
				sectionsGeneratedFromHistory = clinicalHistory.trim();
				caseDetailsManuallyExpanded = false;
			} else {
				sectionsError = 'Failed to generate sections. Please try again.';
			}
		} catch (e) {
			sectionsError = 'Failed to connect. Please try again.';
		} finally {
			regenerating = false;
		}
	}

	function handleResetClick() {
		const content = scratchpadRef?.getContent()?.trim() ?? '';
		if (content.length > 0) {
			resetConfirmVisible = true;
		} else {
			doReset();
		}
	}

	function doReset() {
		scratchpadRef?.reset('');
		resetConfirmVisible = false;
		clinicalHistory = '';
		scanType = '';
		prePoppedSections = [];
		sectionsGeneratedFromScanType = '';
		sectionsGeneratedFromHistory = '';
		activePrompts = [];
		coveredSections = new Set();
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		applicableGuidelines = [];
		hasResponseEver = false;
		findingsAtReportGeneration = '';
		draftStore.clearIntelliTab();
		dispatch('resetForm');
		dispatch('clearResponse');
		dispatch('historyUpdate', { count: 0 });
	}

	function scratchpadToFindings(raw: string): string {
		return raw.replace(/\n{3,}/g, '\n\n').trim();
	}

	async function handleGenerateReport() {
		if (!scratchpadRef) return;

		const content = scratchpadToFindings(scratchpadRef.getContent());
		loading = true;
		error = null;
		response = null;
		responseModel = null;
		applicableGuidelines = [];

		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;

			// Quick-report ephemeral-skill-sheet pipeline.
			// Prefer the BEST sheet (Haiku); fall back to FAST (GLM) if BEST
			// hasn't landed yet. If neither is ready, /generate runs the
			// analyser inline from scan_type + clinical_history.
			const bestAvailable = bestSheetId || fastSheetId;
			const body: Record<string, unknown> = { findings: content };
			if (bestAvailable) {
				body.sheet_id = bestAvailable;
			} else {
				body.scan_type = scanType.trim();
				body.clinical_history = clinicalHistory.trim();
			}

			const res = await fetch(`${API_URL}/api/quick-report/generate`, {
				method: 'POST',
				headers: { ...headers, Accept: 'text/event-stream' },
				body: JSON.stringify(body)
			});

			if (!res.ok) {
				error = `Failed to generate report (HTTP ${res.status}). Please try again.`;
				loading = false;
				return;
			}

			// SSE stream — backend emits:
			//   event: candidate  (single GLM candidate)
			//   event: done       (after persist to DB)
			//   event: error      (upstream failure before the generator fires)
			let generatorErrored = false;
			await readSSEStream(res, (eventName, data) => {
				if (eventName === 'candidate') {
					const cand: Candidate = data;
					if (cand.error || !cand.content) {
						generatorErrored = true;
						error = cand.error || 'Generator failed to produce a report. Please try again.';
						return;
					}
					response = cand.content;
					responseModel = cand.model;
					hasResponseEver = true;
					findingsAtReportGeneration = content;
					loading = false;
				} else if (eventName === 'done') {
					reportId = data?.report_id ?? null;
					// If /generate ran the analyser inline (no sheet_id sent),
					// capture the sheet_id it created so subsequent regenerate
					// flows see a warm fast sheet.
					if (data?.sheet_id && !fastSheetId && !bestSheetId) fastSheetId = data.sheet_id;
					if (response === null && !generatorErrored) {
						error = 'Generator completed without content. Please try again.';
					}
					loading = false;
					draftStore.clearIntelliTab();
					dispatch('historyUpdate', { count: 1 });
				} else if (eventName === 'error') {
					error = data?.error || 'Failed to generate report. Please try again.';
					loading = false;
				}
			});

			applicableGuidelines = [];
		} catch (e) {
			error = 'Failed to connect. Please try again.';
			loading = false;
		}
	}

	function clearResponse() {
		response = null;
		responseModel = null;
		error = null;
		applicableGuidelines = [];
		hasResponseEver = false;
		responseVisible = false;
		findingsAtReportGeneration = '';
		dispatch('clearResponse');
	}


	function handleCoveredSectionsChange(covered: string[]) {
		coveredSections = new Set(covered);
	}

	function handlePromptsChange(prompts: IntelliPrompt[]) {
		activePrompts = prompts;
	}

	function copyToClipboard() {
		if (!response) return;
		navigator.clipboard.writeText(response).then(() => {
			if (toast) toast.show('Copied to clipboard!');
		});
	}

	function handleHistoryRestore(detail: { report?: { report_content: string; model_used?: string } }) {
		if (!detail?.report) return;
		response = detail.report.report_content;
		responseModel = detail.report.model_used ?? null;
		hasResponseEver = true;
		responseVisible = true;
		dispatch('historyRestored', detail);
	}

	async function handleReportSave(event: CustomEvent<{ content: string }>) {
		const newContent = event.detail.content;
		if (!reportId) return;

		try {
			reportUpdateLoading = true;
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/reports/${reportId}/update`, {
				method: 'PUT',
				headers,
				body: JSON.stringify({ content: newContent })
			});
			const data = await res.json();
			if (data.success) {
				response = data.report.report_content;
				versionHistoryRefreshKey += 1;
				dispatch('historyUpdate', { count: data.version?.version_number ?? 0 });
				if (toast) toast.show('Report updated successfully');

				// Also capture the quick-report-specific feedback signal:
				// final edited content + diff against the selected candidate.
				// Best-effort — server computes diff if not supplied. Failure
				// here doesn't break the save UX.
				try {
					await fetch(`${API_URL}/api/quick-report/reports/${reportId}/finalise`, {
						method: 'PATCH',
						headers,
						body: JSON.stringify({ final_report_content: newContent })
					});
				} catch {
					// silent — finalise is a data-capture convenience, not
					// part of the critical save path
				}
			} else {
				error = 'Failed to update report. Please try again.';
			}
		} catch (err) {
			error = 'Failed to update report. Please try again.';
		} finally {
			reportUpdateLoading = false;
		}
	}

	// Persist draft on every meaningful change (debounced inside store)
	$: {
		const hasContent =
			clinicalHistory.trim().length > 0 ||
			scanType.trim().length > 0 ||
			scratchpadContent.trim().length > 0;
		if (hasContent) {
			draftStore.saveIntelliTab(clinicalHistory, scanType, prePoppedSections, scratchpadContent);
		}
	}

	async function restoreIntelliDraft() {
		const draft = $draftStore;
		clinicalHistory = draft.intelliTab.clinicalHistory;
		scanType = draft.intelliTab.scanType;
		// Restore sections so the workspace re-opens
		prePoppedSections = [...(draft.intelliTab.prePoppedSections ?? [])];
		// Mark as not-dirty so workspace doesn't show the "regenerate" overlay
		sectionsGeneratedFromScanType = draft.intelliTab.scanType;
		sectionsGeneratedFromHistory = draft.intelliTab.clinicalHistory;
		// Wait for prePoppedSections to trigger the scratchpad render, then inject content
		if (draft.intelliTab.scratchpadContent && (draft.intelliTab.prePoppedSections?.length ?? 0) > 0) {
			await tick();
			scratchpadRef?.reset(draft.intelliTab.scratchpadContent);
		}
	}

	function dismissIntelliDraft() {
		draftStore.clearIntelliTab();
	}

	export async function restoreFromParent() {
		await restoreIntelliDraft();
	}

	export function dismissFromParent() {
		dismissIntelliDraft();
	}

	let reportViewerRef: any = null;

	export function handleExternalAuditAcknowledge(detail: { criterion: string; resolutionMethod: string }) {
		reportViewerRef?.acknowledgeFromExternal?.(detail);
	}
	export function handleExternalAuditRestore(detail: { criterion: string }) {
		reportViewerRef?.restoreFromExternal?.(detail);
	}
	export function handleExternalAuditSuggestFix(detail: unknown) {
		reportViewerRef?.suggestFixFromExternal?.(detail);
	}
	export function handleExternalAuditApplyFix(detail: unknown) {
		reportViewerRef?.applyFixFromExternal?.(detail);
	}
	export function handleExternalAuditInsertBanner(bannerText: string) {
		reportViewerRef?.insertBannerFromExternal?.(bannerText);
	}
	export function handleExternalAuditReaudit() {
		reportViewerRef?.reauditFromExternal?.();
	}

	const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
</script>

<div class="space-y-4">
	<div class="flex items-center gap-3 mb-6">
		<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
		</svg>
		<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Quick Reports</h1>
	</div>

	<!-- Case Details -->
	<div class="rounded-xl border transition-all duration-300 ease-out overflow-hidden
		{caseDetailsExpanded
			? 'bg-black/50 border-white/10 p-5'
			: 'bg-white/[0.025] border-white/[0.06] px-4 py-3'}">

		{#if caseDetailsExpanded}
			<!-- Full form -->
			<div class="flex items-center justify-between mb-5" in:fade={{ duration: 150 }}>
				<div class="flex items-center gap-2">
					<div class="w-1.5 h-5 rounded-full bg-gradient-to-b from-purple-400 to-blue-500"></div>
					<h2 class="text-sm font-semibold text-white tracking-wide">Case Details</h2>
				</div>
				<div class="flex items-center gap-1">
					{#if resetConfirmVisible}
						<div
							class="flex items-center gap-2"
							in:fly={{ x: 16, duration: 200, easing: easeOut }}
							out:fly={{ x: 16, duration: 150, easing: easeOut }}
						>
							<p class="text-xs text-gray-400 whitespace-nowrap">Discard scratchpad content?</p>
							<button type="button" onclick={doReset}
								class="px-2.5 py-1 text-xs rounded-lg bg-red-600/80 hover:bg-red-500 text-white transition-colors whitespace-nowrap">
								Discard
							</button>
							<button type="button" onclick={() => (resetConfirmVisible = false)}
								class="px-2.5 py-1 text-xs rounded-lg text-gray-400 hover:bg-white/5 transition-colors">
								Cancel
							</button>
						</div>
					{:else}
						{#if workspaceOpen}
							<button type="button" onclick={() => (caseDetailsManuallyExpanded = false)}
								class="p-1.5 text-gray-500 hover:text-gray-300 transition-colors rounded-lg hover:bg-white/5"
								title="Collapse" aria-label="Collapse case details">
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
								</svg>
							</button>
						{/if}
						<button type="button" onclick={handleResetClick}
							class="p-1.5 text-gray-500 hover:text-orange-400 transition-colors rounded-lg hover:bg-white/5"
							title="Reset" aria-label="Reset form">
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
							</svg>
						</button>
					{/if}
				</div>
			</div>

			<form onsubmit={(e) => { e.preventDefault(); sectionsDirty ? handleRegenerateSections() : handleSetUpWorkspace(); }}
				class="space-y-3" in:fade={{ duration: 150 }}>
				<!-- Two-column layout for side-by-side fields -->
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
					<div class="space-y-1.5">
						<label for="clinical-history" class="block text-xs font-medium text-gray-400 uppercase tracking-wider">Clinical History</label>
						<textarea
							id="clinical-history"
							bind:value={clinicalHistory}
							placeholder="e.g. Jaundice, rule out biliary obstruction"
							disabled={sectionsLoading || regenerating}
							class="input-dark w-full resize-none text-sm"
							rows="3"
						></textarea>
					</div>
					<div class="space-y-1.5">
						<label for="scan-type" class="block text-xs font-medium text-gray-400 uppercase tracking-wider">Scan Type</label>
						<textarea
							id="scan-type"
							bind:value={scanType}
							placeholder="e.g. CT abdomen and pelvis with IV contrast"
							disabled={sectionsLoading || regenerating}
							class="input-dark w-full resize-none text-sm"
							rows="3"
						></textarea>
					</div>
				</div>

				{#if sectionsError}
					<p class="text-red-400 text-xs">{sectionsError}</p>
				{/if}

				<div class="flex items-center justify-between pt-1">
					<div class="flex items-center gap-2">
						{#if sectionsDirty && sectionsGeneratedFromScanType}
							<button type="button"
								onclick={() => { scanType = sectionsGeneratedFromScanType; clinicalHistory = sectionsGeneratedFromHistory; }}
								class="text-xs text-gray-500 hover:text-gray-300 transition-colors flex items-center gap-1"
								in:fade={{ duration: 200 }}>
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
								</svg>
								Revert changes
							</button>
						{/if}
					</div>
					<button type="submit" disabled={sectionsLoading || regenerating}
						class="px-5 py-2 rounded-lg text-sm font-medium transition-all duration-200
							{sectionsDirty
								? 'bg-amber-500/20 border border-amber-500/50 text-amber-300 hover:bg-amber-500/30 animate-pulse-once'
								: 'bg-gradient-to-r from-purple-600/80 to-blue-600/80 border border-purple-500/30 text-white hover:from-purple-600 hover:to-blue-600'}
							disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
						{#if sectionsLoading || regenerating}
							<div class="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
							<span>{sectionsDirty ? 'Regenerating...' : 'Setting up...'}</span>
						{:else}
							<span>{sectionsDirty ? 'Regenerate workspace' : 'Set up workspace'}</span>
						{/if}
					</button>
				</div>
			</form>

		{:else}
			<!-- Collapsed summary bar -->
			<div class="flex items-center gap-3 min-w-0 group cursor-pointer"
				onclick={() => (caseDetailsManuallyExpanded = true)}
				role="button" tabindex="0"
				onkeydown={(e) => e.key === 'Enter' && (caseDetailsManuallyExpanded = true)}
				title="Edit case details">
				<div class="flex items-center gap-2 flex-1 min-w-0">
					<span class="shrink-0 px-2.5 py-1 rounded-md bg-purple-500/15 border border-purple-500/25
						text-xs font-medium text-purple-300 truncate max-w-[220px] transition-colors
						group-hover:border-purple-500/40 group-hover:bg-purple-500/20">
						{scanType || '—'}
					</span>
					<span class="text-xs text-gray-500 truncate transition-colors group-hover:text-gray-400">
						{clinicalHistory || '—'}
					</span>
				</div>
				<div class="flex items-center gap-2 shrink-0">
					<span class="text-[10px] text-gray-600 group-hover:text-gray-400 transition-colors uppercase tracking-wider">Edit</span>
					<svg class="w-3.5 h-3.5 text-gray-600 group-hover:text-gray-400 transition-colors"
						fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
					</svg>
					<div class="w-px h-4 bg-white/10"></div>
					<button type="button" onclick={(e) => { e.stopPropagation(); handleResetClick(); }}
						class="p-1 text-gray-600 hover:text-orange-400 transition-colors rounded"
						title="Reset" aria-label="Reset">
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
						</svg>
					</button>
				</div>
			</div>

			{#if resetConfirmVisible}
				<div class="mt-2 flex items-center gap-2 pt-2 border-t border-white/[0.06]"
					in:fly={{ x: 16, duration: 200, easing: easeOut }}
					out:fly={{ x: 16, duration: 150, easing: easeOut }}>
					<p class="text-xs text-gray-400 flex-1">Discard scratchpad content?</p>
					<button type="button" onclick={doReset}
						class="px-2.5 py-1 text-xs rounded-lg bg-red-600/80 hover:bg-red-500 text-white transition-colors">
						Discard
					</button>
					<button type="button" onclick={() => (resetConfirmVisible = false)}
						class="px-2.5 py-1 text-xs rounded-lg text-gray-400 hover:bg-white/5 transition-colors">
						Cancel
					</button>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Skeleton loader while setting up workspace -->
	{#if sectionsLoading && prePoppedSections.length === 0}
		<div class="space-y-3" in:fade={{ duration: 250 }}>
			<div class="h-px bg-gradient-to-r from-transparent via-white/8 to-transparent"></div>
			<!-- Coverage chip strip skeleton -->
			<div class="flex flex-wrap gap-1.5 pb-1">
				{#each [72, 55, 88, 60, 76, 50, 82, 65] as w, i}
					<div class="h-6 bg-white/[0.04] rounded-full skeleton-shimmer" style="width:{w}px;animation-delay:{i*60}ms"></div>
				{/each}
			</div>
			<!-- Scratchpad skeleton -->
			<div class="bg-black/30 border border-white/[0.06] rounded-xl p-4 space-y-3 min-h-[180px]">
				<div class="space-y-2.5 pt-1">
					{#each [90, 75, 100, 60, 82, 68] as w, i}
						<div class="h-2.5 bg-white/[0.05] rounded-full skeleton-shimmer" style="width:{w}%;animation-delay:{i*80}ms"></div>
					{/each}
				</div>
			</div>
			<p class="text-[11px] text-gray-600 text-center tracking-wide">
				Generating review guide sections...
			</p>
		</div>
	{/if}

	{#if workspaceOpen && prePoppedSections.length > 0}
		<div
			class="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent"
			in:fade={{ duration: 400 }}
		></div>
	{/if}

	{#if prePoppedSections.length > 0}
		<!-- Workspace -->
		<div
			class="flex flex-col gap-4 min-h-0 flex-1"
			in:fly={{ y: 24, duration: 320, easing: easeOut }}
			out:fly={{ y: 12, duration: 180, easing: easeOut }}
		>
			<div class="flex items-start justify-between gap-3 border-b border-white/[0.06] pb-3 shrink-0 min-w-0">
				<span class="min-w-0 flex-1 text-xs font-medium uppercase tracking-wider break-words transition-colors duration-300
					{sectionsDirty ? 'text-gray-600' : 'text-gray-500'}">
					{sectionsGeneratedFromScanType || 'Scan'}
				</span>
				<div class="shrink-0">
					<DictationHintBar />
				</div>
			</div>

	<!-- Single-column workspace (greyed out when sectionsDirty) -->
	<div class="flex flex-col min-h-0 flex-1 gap-3 relative transition-opacity duration-300 {sectionsDirty ? 'opacity-50 pointer-events-none' : ''}">
		{#if sectionsDirty}
			<div
				class="absolute inset-0 z-10 flex items-center justify-center bg-black/20 rounded-lg"
				in:fade={{ duration: 200 }}
			>
				<p class="text-sm text-gray-400">Case details changed — regenerate workspace to continue</p>
			</div>
		{/if}

		<!-- Coverage chip strip -->
		<div class="flex flex-wrap gap-1.5 transition-opacity duration-300 {isReviewing ? 'opacity-50' : ''} {regenerating ? 'animate-pulse' : ''}">
			{#each allChecklistSections as section}
				{@const covered = coveredSections.has(section)}
				<span class="px-2.5 py-1 rounded-full text-[11px] font-medium transition-all duration-300
					{covered
						? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
						: 'bg-white/[0.04] text-gray-600 border border-white/[0.06]'}">
					{section.replace(/_/g, ' ')}
				</span>
			{/each}
		</div>

		<!-- Scratchpad (now full-width — IntelliPrompts margin is rendered inside) -->
		<DictationScratchpad
			bind:this={scratchpadRef}
			checklistSections={prePoppedSections}
			{activePrompts}
			{scanType}
			{clinicalHistory}
			{apiKeyStatus}
			onContentChange={(c) => { scratchpadContent = c; }}
			onRecordingChange={(recording) => { isRecording = recording; }}
			onReviewingChange={(reviewing) => { isReviewing = reviewing; }}
			onCoveredSectionsChange={handleCoveredSectionsChange}
			onPromptsChange={handlePromptsChange}
			onScratchpadClear={() => { coveredSections = new Set(); activePrompts = []; }}
		/>
	</div>

			<!-- Generate Report — full width spanning editor + side panel -->
			<!-- Speculative-parallel gate: the button enables as soon as the
			     first (FAST) sheet lands. While the BEST (Haiku) sheet is still
			     pending, a subtle indicator shows the higher-quality option is
			     still incoming — but the user can click through anytime. -->
			<button
				type="button"
				onclick={() => handleGenerateReport()}
				disabled={isRecording || loading || (analyseLoading && !analyserReady) || !scratchpadContent.trim() || sectionsDirty}
				class="btn-primary-subtle w-full px-6 py-3 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
				class:best-ready={bestSheetReady && !loading}
			>
				{#if loading}
					<div class="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
					<span>Generating...</span>
				{:else if analyseLoading && !analyserReady}
					<span>Start dictating findings</span>
				{:else}
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
					</svg>
					<span>Generate Report</span>
				{/if}
			</button>

		</div><!-- end workspace flex-col -->
	{/if}

	<!-- Report Response Viewer -->
	<ReportResponseViewer
		bind:this={reportViewerRef}
		visible={responseVisible}
		response={response ?? ''}
		{error}
		model={responseModel}
		generationLoading={loading}
		updateLoading={reportUpdateLoading}
		{reportId}
		{versionHistoryRefreshKey}
		{enhancementGuidelinesCount}
		{enhancementLoading}
		{enhancementError}
		{scanType}
		{clinicalHistory}
		{applicableGuidelines}
		caseDetailsDirty={sectionsDirty}
		{findingsStale}
		activeCandidateModel={null}
		on:openSidebar={(e) => dispatch('openSidebar', e.detail)}
	on:auditStateChange={(e) => dispatch('auditStateChange', e.detail)}
	on:openVersionHistory={() => dispatch('openVersionHistory')}
	on:openCompare={() => dispatch('openCompare')}
	on:copy={copyToClipboard}
	on:clear={clearResponse}
	on:restore={(e) => handleHistoryRestore(e.detail)}
	on:historyUpdate={(e) => dispatch('historyUpdate', e.detail)}
	on:auditComplete={(e) => dispatch('auditComplete', e.detail)}
	on:save={handleReportSave}
	on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
	on:hideHoverPopup={() => dispatch('hideHoverPopup')}
/>
</div>

<Toast bind:this={toast} />

<style>
	@keyframes pulse-once {
		0%   { box-shadow: 0 0 0 0 rgba(245,158,11,0.5); }
		60%  { box-shadow: 0 0 0 6px rgba(245,158,11,0); }
		100% { box-shadow: 0 0 0 0 rgba(245,158,11,0); }
	}
	.animate-pulse-once {
		animation: pulse-once 1s ease-out forwards;
	}
	@keyframes shimmer {
		0%   { opacity: 0.4; }
		50%  { opacity: 0.8; }
		100% { opacity: 0.4; }
	}
	.skeleton-shimmer {
		animation: shimmer 1.6s ease-in-out infinite;
	}
</style>
