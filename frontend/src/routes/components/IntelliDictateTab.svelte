<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { token } from '$lib/stores/auth';
	import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';
	import DictationHintBar from '$lib/components/DictationHintBar.svelte';
	import ReportResponseViewer from './ReportResponseViewer.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import { API_URL } from '$lib/config';

	let toast: { show: (msg: string) => void } | undefined;

	const dispatch = createEventDispatcher();

	// Step state
	let step: 'context' | 'workspace' = 'context';
	let clinicalHistory = '';
	let scanType = '';
	let prePoppedSections: string[] = [];
	let sectionsLoading = false;
	let sectionsError = '';

	interface IntelliPrompt { question: string; source_text: string; rationale?: string; }

	// Back navigation
	let backConfirmVisible = false;
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
		deepgram_configured: false
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
				step = 'workspace';
			} else {
				sectionsError = data.error || 'Failed to generate sections';
			}
		} catch (e) {
			sectionsError = 'Failed to connect to API';
		} finally {
			sectionsLoading = false;
		}
	}

	function handleBackClick() {
		const content = scratchpadRef?.getContent()?.trim() ?? '';
		if (content.length > 0) {
			backConfirmVisible = true;
		} else {
			doBack();
		}
	}

	function doBack() {
		scratchpadRef?.reset('');
		backConfirmVisible = false;
		step = 'context';
		activePrompts = [];
		expandedPrompts = new Set();
		coveredSections = new Set();
		// Clear report so response viewer is hidden
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		hasResponseEver = false;
		responseExpanded = false;
		dispatch('clearResponse');
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
				dispatch('historyUpdate', { count: 1 });
			} else {
				error = data.error || 'Failed to generate report';
			}
		} catch (e) {
			error = 'Failed to connect to API';
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

	function resetForm() {
		step = 'context';
		clinicalHistory = '';
		scanType = '';
		prePoppedSections = [];
		coveredSections = new Set();
		activePrompts = [];
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		hasResponseEver = false;
		responseExpanded = false;
		responseVisible = false;
		backConfirmVisible = false;
		dispatch('resetForm');
		dispatch('clearResponse');
		dispatch('historyUpdate', { count: 0 });
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
				error = data.error || 'Failed to update report';
			}
		} catch (err) {
			error = `Failed to update: ${err instanceof Error ? err.message : 'Unknown error'}`;
		} finally {
			reportUpdateLoading = false;
		}
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

	<!-- Step 1: Context Form -->
	{#if step === 'context'}
		<div
			class="card-dark p-6"
			in:fly={{ x: -40, duration: 280, easing: easeOut }}
		>
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-2">
					<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
					</svg>
					<h2 class="text-lg font-semibold text-white">Case Details</h2>
				</div>
				<button
					type="button"
					onclick={resetForm}
					class="p-2 text-gray-400 hover:text-orange-400 transition-colors rounded-lg hover:bg-white/5"
					title="Reset form"
					aria-label="Reset form"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
					</svg>
				</button>
			</div>
			<form onsubmit={(e) => { e.preventDefault(); handleSetUpWorkspace(); }} class="space-y-4">
				<div>
					<label for="clinical-history" class="block text-sm font-medium text-gray-300 mb-2">Clinical History</label>
					<textarea
						id="clinical-history"
						bind:value={clinicalHistory}
						placeholder="e.g. Jaundice, rule out biliary obstruction"
						disabled={sectionsLoading}
						class="input-dark w-full resize-none"
						rows="3"
					></textarea>
				</div>
				<div>
					<label for="scan-type" class="block text-sm font-medium text-gray-300 mb-2">Scan Type</label>
					<input
						id="scan-type"
						type="text"
						bind:value={scanType}
						placeholder="e.g. CT abdomen and pelvis with IV contrast"
						disabled={sectionsLoading}
						class="input-dark w-full"
					/>
				</div>
				<button
					type="submit"
					disabled={sectionsLoading}
					class="btn-primary-subtle w-full px-6 py-3 flex items-center justify-center gap-2 bg-gradient-to-r from-purple-600 to-blue-600"
				>
					{#if sectionsLoading}
						<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
						<span>Setting up...</span>
					{:else}
						<span>Set up workspace</span>
					{/if}
				</button>
				{#if sectionsError}
					<p class="text-red-400 text-sm mt-2">{sectionsError}</p>
				{/if}
			</form>
		</div>
	{:else}
		<!-- Step 2: Workspace -->
		<div
			class="flex flex-col gap-4 min-h-0 flex-1"
			in:fly={{ x: 40, duration: 280, easing: easeOut }}
		>
			<!-- Header bar — back button + scan type + inline confirmation -->
			<div class="flex items-center gap-3 border-b border-white/[0.06] pb-3 shrink-0 min-w-0">
				<button
					type="button"
					onclick={handleBackClick}
					class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5 shrink-0"
					aria-label="Back"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
					</svg>
				</button>
				<span class="text-xs text-gray-500 font-medium uppercase tracking-wider shrink-0">{scanType || 'Scan'}</span>

				<!-- Inline back confirmation — slides in from right -->
				{#if backConfirmVisible}
					<div
						class="flex items-center gap-2 ml-auto"
						in:fly={{ x: 24, duration: 200, easing: easeOut }}
						out:fly={{ x: 24, duration: 160, easing: easeOut }}
					>
						<p class="text-xs text-gray-400 whitespace-nowrap">
							Discard scratchpad content and go back?
						</p>
						<button
							type="button"
							onclick={doBack}
							class="px-2.5 py-1 text-xs rounded-lg bg-red-600/80 hover:bg-red-500 text-white transition-colors whitespace-nowrap"
						>
							Discard
						</button>
						<button
							type="button"
							onclick={() => (backConfirmVisible = false)}
							class="px-2.5 py-1 text-xs rounded-lg text-gray-400 hover:bg-white/5 transition-colors"
						>
							Cancel
						</button>
					</div>
				{/if}
			</div>

		<DictationHintBar />

		<!-- Two-column workspace row -->
		<div class="flex gap-4 min-h-0 flex-1">
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
				: 'w-[252px]'}"
		>
			<!-- Panel header -->
			<button
				type="button"
				onclick={() => (checklistCollapsed = !checklistCollapsed)}
				class="flex items-center justify-between gap-2 px-3 py-2.5 bg-black/40 border border-white/10 rounded-lg text-left hover:bg-white/5 transition-colors shrink-0"
				title={checklistCollapsed ? 'Expand panel' : 'Collapse panel'}
			>
				{#if !checklistCollapsed}
					<span class="text-xs font-semibold text-gray-400 uppercase tracking-widest">Review Guide</span>
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
					<div class="flex flex-col gap-0.5 pb-2">
					{#each allChecklistSections as section}
						{@const covered = coveredSections.has(section)}
						<div class="flex items-center gap-2.5 px-2 py-1.5 rounded-md transition-colors duration-300
							{covered ? 'text-emerald-400' : 'text-gray-600'}">
							<span class="w-2 h-2 rounded-full shrink-0 transition-all duration-300
								{covered
									? 'bg-emerald-400 border-transparent shadow-sm shadow-emerald-400/50 scale-100'
									: 'bg-transparent border border-gray-700 scale-90 opacity-60'}">
							</span>
							<span class="text-xs font-mono truncate leading-snug transition-colors duration-300">{section}</span>
						</div>
					{/each}
					</div>

					<!-- Footer hint -->
					<p class="text-[10px] text-gray-700 px-2 pb-3 leading-relaxed border-b border-white/[0.05]">
						Unchecked systems are completed automatically in the final report.
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
				disabled={isRecording || loading || !scratchpadContent.trim()}
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
