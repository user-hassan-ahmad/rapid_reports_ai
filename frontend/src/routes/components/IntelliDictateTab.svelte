<script lang="ts">
import { createEventDispatcher, onMount, tick } from 'svelte';
import { fly, fade } from 'svelte/transition';
import { token } from '$lib/stores/auth';
import { draftStore, hasIntelliDraft } from '$lib/stores/draft.js';
import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';
import DictationHintBar from '$lib/components/DictationHintBar.svelte';
import ReportResponseViewer from './ReportResponseViewer.svelte';
import Toast from '$lib/components/Toast.svelte';
import { API_URL } from '$lib/config';

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

	interface IntelliPrompt { question: string; source_text: string; rationale?: string; }

	// Reset confirmation (when scratchpad has content)
	let resetConfirmVisible = false;

	// Case details collapsed/expanded state
	let caseDetailsManuallyExpanded = false;

	$: workspaceOpen = prePoppedSections.length > 0 || sectionsLoading;
	$: sectionsDirty = workspaceOpen
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

	// Side panel collapse
	let checklistCollapsed = false;

	// Draft restore banner
	let showRestoreBanner = false;

	onMount(() => {
		showRestoreBanner = $hasIntelliDraft;
	});

	// CONSIDER scroll overflow indicator + expand state
	let considerScrollEl: HTMLDivElement | null = null;
	let considerScrolledToBottom = true;
	let expandedPrompts: Set<string> = new Set();

	function togglePromptExpand(question: string) {
		expandedPrompts = expandedPrompts.has(question)
			? new Set([...expandedPrompts].filter((q) => q !== question))
			: new Set([...expandedPrompts, question]);
	}
	function onConsiderScroll() {
		if (!considerScrollEl) return;
		const { scrollTop, scrollHeight, clientHeight } = considerScrollEl;
		considerScrolledToBottom = scrollTop + clientHeight >= scrollHeight - 4;
	}
	// Re-evaluate overflow whenever prompts change (new prompt may push content below fold)
	$: if (activePrompts && considerScrollEl) {
		setTimeout(() => onConsiderScroll(), 50);
	}

	// Scratchpad content for parsing dynamic sections
	let scratchpadContent = '';

	// Recording state (from DictationScratchpad)
	let isRecording = false;

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

	// ReportResponseViewer state
	let responseExpanded = false;
	let hasResponseEver = false;
	let responseVisible = false;

	$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);

	// Review guide shows the pre-generated checklist sections only.
	// Coverage state comes entirely from covered_sections returned by Qwen — no text parsing.
	$: allChecklistSections = prePoppedSections;

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
		expandedPrompts = new Set();
		coveredSections = new Set();
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		hasResponseEver = false;
		responseExpanded = false;
		draftStore.clearIntelliTab();
		showRestoreBanner = false;
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

		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/chat`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					message: '',
					model: 'claude',
					use_case: 'radiology_report',
					variables: {
						CLINICAL_HISTORY: clinicalHistory,
						SCAN_TYPE: scanType,
						FINDINGS: content
					}
				})
			});
			const data = await res.json();
			if (data.success) {
				response = data.response;
				responseModel = data.model_used ?? data.model ?? 'claude';
				reportId = data.report_id ?? null;
				hasResponseEver = true;
				responseExpanded = true;
				draftStore.clearIntelliTab();
				dispatch('historyUpdate', { count: 1 });
			} else {
				error = 'Failed to generate report. Please try again.';
			}
		} catch (e) {
			error = 'Failed to connect. Please try again.';
		} finally {
			loading = false;
		}
	}

	function toggleResponse() {
		responseExpanded = !responseExpanded;
	}

	function clearResponse() {
		response = null;
		responseModel = null;
		error = null;
		responseExpanded = false;
		hasResponseEver = false;
		responseVisible = false;
		dispatch('clearResponse');
	}


	function handleCoveredSectionsChange(covered: string[]) {
		coveredSections = new Set(covered);
	}

	function handlePromptsChange(prompts: IntelliPrompt[]) {
		activePrompts = prompts;
		expandedPrompts = new Set([...expandedPrompts].filter((q) => prompts.some((p) => p.question === q)));
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
		responseExpanded = true;
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
		showRestoreBanner = false;
		// Wait for prePoppedSections to trigger the scratchpad render, then inject content
		if (draft.intelliTab.scratchpadContent && (draft.intelliTab.prePoppedSections?.length ?? 0) > 0) {
			await tick();
			scratchpadRef?.reset(draft.intelliTab.scratchpadContent);
		}
	}

	function dismissIntelliDraft() {
		draftStore.clearIntelliTab();
		showRestoreBanner = false;
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

	<!-- Draft Restore Banner -->
	{#if showRestoreBanner}
		<div
			class="flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-amber-950/40 border border-amber-500/25 text-sm"
			in:fade={{ duration: 200 }}
			out:fade={{ duration: 150 }}
		>
			<div class="flex items-center gap-2.5 min-w-0">
				<svg class="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
				</svg>
				<span class="text-amber-200/80 truncate">
					Unsaved draft from {new Date($draftStore.savedAt ?? 0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} — restore your previous work?
				</span>
			</div>
			<div class="flex items-center gap-2 shrink-0">
				<button
					type="button"
					onclick={restoreIntelliDraft}
					class="px-3 py-1 text-xs font-medium rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors border border-amber-500/30"
				>
					Restore
				</button>
				<button
					type="button"
					onclick={dismissIntelliDraft}
					class="px-3 py-1 text-xs rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
				>
					Dismiss
				</button>
			</div>
		</div>
	{/if}

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
			<div class="flex gap-4">
				<!-- Scratchpad skeleton -->
				<div class="flex-1 bg-black/30 border border-white/[0.06] rounded-xl p-4 space-y-3 min-h-[180px]">
					<div class="flex items-center justify-between pb-3 border-b border-white/[0.05]">
						<div class="h-2.5 w-20 bg-white/8 rounded-full skeleton-shimmer"></div>
						<div class="h-2.5 w-12 bg-white/5 rounded-full skeleton-shimmer"></div>
					</div>
					<div class="space-y-2.5 pt-1">
						{#each [90, 75, 100, 60, 82, 68] as w, i}
							<div class="h-2.5 bg-white/[0.05] rounded-full skeleton-shimmer" style="width:{w}%;animation-delay:{i*80}ms"></div>
						{/each}
					</div>
				</div>
				<!-- Review guide skeleton -->
				<div class="w-52 shrink-0 bg-black/30 border border-white/[0.06] rounded-xl p-4 space-y-2">
					<div class="h-2.5 w-24 bg-white/8 rounded-full skeleton-shimmer mb-3"></div>
					<div class="grid grid-cols-2 gap-1.5">
						{#each [85, 60, 75, 90, 65, 80, 55, 70] as w, i}
							<div class="h-2 bg-white/[0.04] rounded-full skeleton-shimmer" style="width:{w}%;animation-delay:{i*60}ms"></div>
						{/each}
					</div>
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
			<div class="flex items-center justify-between border-b border-white/[0.06] pb-3 shrink-0 min-w-0">
				<span class="text-xs font-medium uppercase tracking-wider shrink-0 transition-colors duration-300
					{sectionsDirty ? 'text-gray-600' : 'text-gray-500'}">
					{sectionsGeneratedFromScanType || 'Scan'}
				</span>
				<DictationHintBar />
			</div>

		<!-- Two-column workspace row (greyed out when sectionsDirty) -->
		<div class="flex gap-4 min-h-0 flex-1 relative transition-opacity duration-300 {sectionsDirty ? 'opacity-50 pointer-events-none' : ''}">
			{#if sectionsDirty}
				<div
					class="absolute inset-0 z-10 flex items-center justify-center bg-black/20 rounded-lg"
					in:fade={{ duration: 200 }}
				>
					<p class="text-sm text-gray-400">Case details changed — regenerate workspace to continue</p>
				</div>
			{/if}
			<!-- Scratchpad column -->
			<div class="flex flex-col flex-1 min-w-0 min-h-0">
			<DictationScratchpad
					bind:this={scratchpadRef}
					checklistSections={prePoppedSections}
					{activePrompts}
					{scanType}
					{clinicalHistory}
					{apiKeyStatus}
					onContentChange={(c) => { scratchpadContent = c; }}
					onRecordingChange={(recording) => { isRecording = recording; }}
				onCoveredSectionsChange={handleCoveredSectionsChange}
				onPromptsChange={handlePromptsChange}
				onScratchpadClear={() => { coveredSections = new Set(); activePrompts = []; expandedPrompts = new Set(); }}
				/>
				</div>

		<!-- Side panel: Review Guide + Consider -->
		<aside
			class="flex flex-col shrink-0 transition-all duration-300 overflow-hidden {checklistCollapsed
				? 'w-10'
				: 'w-[320px]'}"
		>
			<!-- Panel header -->
			<button
				type="button"
				onclick={() => (checklistCollapsed = !checklistCollapsed)}
				class="flex items-center justify-between gap-2 px-3 py-2.5 bg-black/40 border border-white/10 rounded-lg text-left hover:bg-white/5 transition-colors shrink-0"
				title={checklistCollapsed ? 'Expand panel' : 'Collapse panel'}
			>
				{#if !checklistCollapsed}
					{#if regenerating}
						<div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
					{:else}
						<span class="text-xs font-semibold text-gray-400 uppercase tracking-widest">Review Guide</span>
					{/if}
				{/if}
				<svg
					class="w-4 h-4 text-gray-500 shrink-0 transition-transform duration-300 {checklistCollapsed ? 'rotate-180' : ''}"
					fill="none" stroke="currentColor" viewBox="0 0 24 24"
				>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
				</svg>
			</button>

			{#if !checklistCollapsed}
				<div class="mt-2 flex flex-col min-h-0 overflow-y-auto gap-0 flex-1">

				<!-- Systems list -->
				<div class="grid grid-cols-2 gap-0.5 pb-2 {regenerating ? 'animate-pulse' : ''}">
				{#each allChecklistSections as section}
					{@const covered = coveredSections.has(section)}
					<div class="flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors duration-300
						{covered ? 'text-emerald-400' : 'text-gray-600'}">
						<span class="w-2 h-2 rounded-full shrink-0 transition-all duration-300
							{covered
								? 'bg-emerald-400 border-transparent shadow-sm shadow-emerald-400/50 scale-100'
								: 'bg-transparent border border-gray-700 scale-90 opacity-60'}">
						</span>
						<span class="text-[11px] font-mono leading-snug transition-colors duration-300">{section.replace(/_/g, ' ')}</span>
					</div>
				{/each}
				</div>

					<!-- Footer hint -->
				<p class="text-[11px] text-gray-500 px-2 py-2 pb-3 leading-relaxed border-b border-white/[0.05] italic">
					Reference guide only — unchecked systems are completed automatically in the final report.
				</p>

				<!-- CONSIDER section -->
				{#if activePrompts.length > 0}
					<div class="pt-3 flex flex-col gap-2 min-h-0 flex-1" in:fade={{ duration: 200 }}>
						<div class="flex items-center gap-2 px-2 shrink-0">
							<span class="text-xs font-semibold text-gray-400 uppercase tracking-widest">Consider</span>
							<span class="consider-pulse w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
						</div>
						<!-- Scrollable prompt list -->
						<div class="relative flex-1 min-h-0">
						<div
							bind:this={considerScrollEl}
							onscroll={onConsiderScroll}
							class="flex flex-col gap-1.5 overflow-y-auto max-h-48 pr-0.5 pb-2 scrollbar-hide"
						>
							{#each activePrompts as prompt (prompt.question)}
								{@const isExpanded = expandedPrompts.has(prompt.question)}
								<button
									type="button"
									onclick={() => prompt.rationale && togglePromptExpand(prompt.question)}
									class="w-full text-left border-l-2 border-amber-400/60 pl-2.5 pr-2 py-2 rounded-r-md
										bg-amber-400/5 shrink-0 transition-colors duration-150
										{prompt.rationale ? 'cursor-pointer hover:bg-amber-400/10' : 'cursor-default'}"
									in:fly={{ y: 8, duration: 220 }}
									out:fade={{ duration: 150 }}
								>
									<div class="flex items-start justify-between gap-1.5">
										<p class="text-xs text-amber-300/80 leading-snug flex-1">
											{prompt.question}
										</p>
										{#if prompt.rationale}
											<svg
												class="w-3 h-3 text-amber-400/50 shrink-0 mt-0.5 transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
												fill="none" stroke="currentColor" viewBox="0 0 24 24"
											>
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7" />
											</svg>
										{/if}
									</div>
									<p class="text-[10px] text-gray-600 mt-0.5 truncate">
										re: {prompt.source_text}
									</p>
									{#if isExpanded && prompt.rationale}
										<p
											class="text-[11px] text-gray-400 leading-relaxed mt-2 pt-2 border-t border-amber-400/10"
											in:fly={{ y: -4, duration: 180 }}
											out:fade={{ duration: 100 }}
										>
											{prompt.rationale}
										</p>
									{/if}
								</button>
							{/each}
							</div>
							<!-- Pulsating scroll-down arrow — visible when more content is below -->
							{#if !considerScrolledToBottom}
								<div
									class="absolute bottom-0 left-0 right-0 flex justify-center pb-1 pointer-events-none"
									in:fade={{ duration: 150 }}
									out:fade={{ duration: 150 }}
								>
									<span class="scroll-hint-arrow flex items-center justify-center w-5 h-5 rounded-full bg-amber-500 border border-amber-300/80 shadow-md shadow-black/40">
										<svg class="w-3 h-3 text-black" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
										</svg>
									</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				</div>
			{/if}
			</aside>
			</div><!-- end two-column row -->

			<!-- Generate Report — full width spanning editor + side panel -->
			<button
				type="button"
				onclick={() => handleGenerateReport()}
				disabled={isRecording || loading || !scratchpadContent.trim() || sectionsDirty}
				class="btn-primary-subtle w-full px-6 py-3 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
			>
				{#if loading}
					<div class="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
					<span>Generating...</span>
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
		visible={responseVisible}
		expanded={responseExpanded}
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
		on:toggle={toggleResponse}
		on:openSidebar={(e) => dispatch('openSidebar', e.detail)}
		on:copy={copyToClipboard}
		on:clear={clearResponse}
		on:restore={(e) => handleHistoryRestore(e.detail)}
		on:historyUpdate={(e) => dispatch('historyUpdate', e.detail)}
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
	@keyframes considerPulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.4; transform: scale(0.75); }
	}
	.consider-pulse {
		animation: considerPulse 1.8s ease-in-out infinite;
	}
	@keyframes scrollHintBounce {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
	.scroll-hint-arrow {
		animation: scrollHintBounce 1.4s ease-in-out infinite;
	}
</style>
