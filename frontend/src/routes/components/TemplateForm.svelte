<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { token } from '$lib/stores/auth';
	import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import ReportResponseViewer from './ReportResponseViewer.svelte';
	import { API_URL } from '$lib/config';

	let toast: { show: (msg: string) => void } | undefined;

	const dispatch = createEventDispatcher();

	export let selectedTemplate: any = null;
	export let variableValues: Record<string, string> = {};
	export let response: any = null;
	export let responseModel: any = null;
	export let loading = false;
	export let reportUpdateLoading = false;
	export let error: any = null;
	export let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		deepgram_configured: false
	};
	export let selectedModel = 'claude';
	export let reportId: any = null;
	export let versionHistoryRefreshKey = 0;
	export let enhancementGuidelinesCount = 0;
	export let enhancementLoading = false;
	export let enhancementError = false;

	// Ensure props are never undefined
	if (typeof selectedTemplate === 'undefined') selectedTemplate = null;
	if (typeof variableValues === 'undefined') variableValues = {};

	// Step state (mirrors IntelliDictateTab)
	let step: 'context' | 'workspace' = 'context';
	let prePoppedSections: string[] = [];
	let sectionsLoading = false;
	let sectionsError = '';

	interface IntelliPrompt {
		question: string;
		source_text: string;
		rationale?: string;
	}

	let backConfirmVisible = false;
	let scratchpadRef: {
		getContent: () => string;
		getFindingCount: () => number;
		reset: (doc: string) => void;
		highlightSource: (text: string) => void;
		clearHighlight: () => void;
	} | null = null;

	let coveredSections: Set<string> = new Set();
	let activePrompts: IntelliPrompt[] = [];
	let checklistCollapsed = false;
	let considerScrollEl: HTMLDivElement | null = null;
	let considerScrolledToBottom = true;
	let expandedPrompts: Set<string> = new Set();

	let scratchpadContent = '';
	let isRecording = false;
	let scanType = '';
	let lastTemplateId: string | null = null;

	// ReportResponseViewer state
	let responseExpanded = false;
	let hasResponseEver = false;
	let responseVisible = false;

	$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);
	$: allChecklistSections = prePoppedSections;

	// Non-FINDINGS variables for step 1 (plain textareas, no dictation)
	$: nonFindingsVariables = (selectedTemplate?.variables || Object.keys(variableValues || {}))
		.filter((v: string) => v !== 'FINDINGS');

	// Extract FINDINGS template_content for section extraction
	$: findingsTemplateContent = (() => {
		const sections = selectedTemplate?.template_config?.sections;
		if (!sections || !Array.isArray(sections)) return '';
		const findingsSection = sections.find((s: any) => s?.name === 'FINDINGS');
		return findingsSection?.template_content || '';
	})();

	// Reset to step 1 when template changes
	$: if (selectedTemplate?.id && selectedTemplate.id !== lastTemplateId) {
		lastTemplateId = selectedTemplate.id;
		step = 'context';
		prePoppedSections = [];
		coveredSections = new Set();
		activePrompts = [];
		hasResponseEver = false;
		responseVisible = false;
	}

	// scanType from template config
	$: scanType = selectedTemplate?.template_config?.scan_type ?? '';

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

	$: if (activePrompts && considerScrollEl) {
		setTimeout(() => onConsiderScroll(), 50);
	}

	async function handleSetUpWorkspace() {
		// Validate required: CLINICAL_HISTORY (if it's a template variable)
		if (nonFindingsVariables.includes('CLINICAL_HISTORY') && !variableValues['CLINICAL_HISTORY']?.trim()) {
			sectionsError = 'Please enter Clinical History';
			return;
		}
		// Validate other required variables (sections with is_required)
		const sections = selectedTemplate?.template_config?.sections || [];
		for (const s of sections) {
			if (s.has_input_field && s.included && s.is_required && s.name !== 'FINDINGS') {
				if (!variableValues[s.name]?.trim()) {
					sectionsError = `Please fill in ${(s.display_name || s.name).replace(/_/g, ' ')}`;
					return;
				}
			}
		}

		sectionsLoading = true;
		sectionsError = '';

		try {
			// Fetch sections from FINDINGS template_content
			if (findingsTemplateContent?.trim()) {
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) headers['Authorization'] = `Bearer ${$token}`;
				const res = await fetch(`${API_URL}/api/canvas/sections-from-template`, {
					method: 'POST',
					headers,
					body: JSON.stringify({ template_content: findingsTemplateContent })
				});
				const data = await res.json();
				if (data.sections && Array.isArray(data.sections)) {
					prePoppedSections = data.sections;
				} else {
					prePoppedSections = [];
				}
			} else {
				prePoppedSections = [];
			}
			coveredSections = new Set();
			step = 'workspace';
		} catch (e) {
			sectionsError = 'Failed to connect to API';
			prePoppedSections = [];
			step = 'workspace';
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
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		hasResponseEver = false;
		responseExpanded = false;
		dispatch('reportCleared');
		dispatch('clearResponse');
	}

	function scratchpadToFindings(raw: string): string {
		return raw.replace(/\n{3,}/g, '\n\n').trim();
	}

	async function handleGenerateReport() {
		if (!scratchpadRef || !selectedTemplate) return;

		const findingsContent = scratchpadToFindings(scratchpadRef.getContent());
		// Merge FINDINGS from scratchpad into variableValues for the API call
		variableValues = { ...variableValues, FINDINGS: findingsContent };

		// Validate FINDINGS
		if (!findingsContent.trim()) {
			error = 'Please add findings in the scratchpad';
			return;
		}

		if (!apiKeyStatus.anthropic_configured) {
			error = 'Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable.';
			return;
		}

		loading = true;
		error = null;
		response = null;
		responseModel = null;

		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) headers['Authorization'] = `Bearer ${$token}`;
			const res = await fetch(`${API_URL}/api/templates/${selectedTemplate.id}/generate`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					user_inputs: variableValues,
					model: selectedModel
				})
			});
			const data = await res.json();

			if (data.success) {
				response = data.response;
				responseModel = data.model;
				reportId = data.report_id ?? null;
				hasResponseEver = true;
				responseExpanded = true;
				dispatch('reportGenerated', { reportId: data.report_id });
				dispatch('historyUpdate', { count: 1 });
			} else {
				error = data.error || 'Failed to generate report';
			}
		} catch (e) {
			error = 'Failed to connect to API. Make sure the backend is running.';
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
		dispatch('reportCleared');
		dispatch('historyUpdate', { count: 0 });
	}

	function resetForm() {
		step = 'context';
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
		dispatch('reportCleared');
		dispatch('historyUpdate', { count: 0 });
	}

	function handleCoveredSectionsChange(covered: string[]) {
		coveredSections = new Set(covered);
	}

	function handlePromptsChange(prompts: IntelliPrompt[]) {
		activePrompts = prompts;
		expandedPrompts = new Set([...expandedPrompts].filter((q) => prompts.some((p) => p.question === q)));
	}

	function handleScratchpadClear() {
		coveredSections = new Set();
		activePrompts = [];
		expandedPrompts = new Set();
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

{#if !selectedTemplate}
	<div class="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
		<p class="text-yellow-400">No template selected</p>
	</div>
{:else if Object.keys(variableValues || {}).length === 0}
	<div class="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
		<p class="text-yellow-400">This template has no variables to fill</p>
		<button onclick={() => dispatch('back')} class="btn-secondary mt-4">← Back to Templates</button>
	</div>
{:else}
	<div class="space-y-4">
		<div class="flex items-center gap-3 mb-6">
			<svg class="w-8 h-8 text-purple-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
			</svg>
			<div>
				<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">
					{selectedTemplate.name}
				</h1>
				{#if selectedTemplate.description}
					<p class="text-sm text-gray-400 mt-0.5">{selectedTemplate.description}</p>
				{/if}
			</div>
		</div>

		{#if step === 'context'}
			<!-- Step 1: Context Form (mirrors IntelliDictate) -->
			<div class="card-dark p-6" in:fly={{ x: -40, duration: 280, easing: easeOut }}>
				<div class="flex items-center justify-between mb-4">
					<div class="flex items-center gap-2">
						<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
						</svg>
						<h2 class="text-lg font-semibold text-white">Case Details</h2>
					</div>
					<div class="flex items-center gap-2">
						<button
							type="button"
							onclick={() => dispatch('editTemplate', { template: selectedTemplate })}
							class="px-3 py-1.5 btn-secondary text-sm flex items-center gap-2"
							title="Edit Template"
						>
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
							</svg>
							Edit Template
						</button>
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
				</div>
				<form onsubmit={(e) => { e.preventDefault(); handleSetUpWorkspace(); }} class="space-y-4">
					{#each nonFindingsVariables as variable}
						<div>
							<label for={variable} class="block text-sm font-medium text-gray-300 mb-2">
								{variable.replace(/_/g, ' ')}
							</label>
							<textarea
								id={variable}
								bind:value={variableValues[variable]}
								placeholder={`Enter ${variable.replace(/_/g, ' ').toLowerCase()}...`}
								disabled={sectionsLoading}
								class="input-dark w-full resize-none"
								rows="3"
							></textarea>
						</div>
					{/each}
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
			<!-- Step 2: Workspace (identical to IntelliDictate) -->
			<div class="flex flex-col gap-4 min-h-0 flex-1" in:fly={{ x: 40, duration: 280, easing: easeOut }}>
				<!-- Header bar -->
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
					<span class="text-xs text-gray-500 font-medium uppercase tracking-wider shrink-0">
						{scanType || selectedTemplate?.name || 'Template'}
					</span>
					{#if backConfirmVisible}
						<div
							class="flex items-center gap-2 ml-auto"
							in:fly={{ x: 24, duration: 200, easing: easeOut }}
							out:fly={{ x: 24, duration: 160, easing: easeOut }}
						>
							<p class="text-xs text-gray-400 whitespace-nowrap">Discard scratchpad content and go back?</p>
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

				<!-- Two-column workspace row -->
				<div class="flex gap-4 min-h-0 flex-1">
					<div class="flex flex-col flex-1 min-w-0 min-h-0">
						<DictationScratchpad
							bind:this={scratchpadRef}
							checklistSections={prePoppedSections}
							{activePrompts}
							{scanType}
							clinicalHistory={variableValues['CLINICAL_HISTORY'] ?? ''}
							{apiKeyStatus}
							onContentChange={(c) => { scratchpadContent = c; }}
							onRecordingChange={(recording) => { isRecording = recording; }}
						onCoveredSectionsChange={handleCoveredSectionsChange}
						onPromptsChange={handlePromptsChange}
						onScratchpadClear={handleScratchpadClear}
					/>
					</div>

					<!-- Side panel: Review Guide + Consider -->
					<aside
						class="flex flex-col shrink-0 transition-all duration-300 overflow-hidden {checklistCollapsed ? 'w-10' : 'w-[252px]'}"
					>
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
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
							</svg>
						</button>

						{#if !checklistCollapsed}
							<div class="mt-2 flex flex-col min-h-0 overflow-y-auto gap-0 flex-1">
								<div class="flex flex-col gap-0.5 pb-2">
									{#each allChecklistSections as section}
										{@const covered = coveredSections.has(section)}
										<div
											class="flex items-center gap-2.5 px-2 py-1.5 rounded-md transition-colors duration-300
								{covered ? 'text-emerald-400' : 'text-gray-600'}"
										>
											<span
												class="w-2 h-2 rounded-full shrink-0 transition-all duration-300
									{covered ? 'bg-emerald-400 border-transparent shadow-sm shadow-emerald-400/50 scale-100' : 'bg-transparent border border-gray-700 scale-90 opacity-60'}"
											></span>
											<span class="text-xs font-mono truncate leading-snug transition-colors duration-300">{section}</span>
										</div>
									{/each}
								</div>
								<p class="text-[10px] text-gray-700 px-2 pb-3 leading-relaxed border-b border-white/[0.05]">
									Unchecked systems are completed automatically in the final report.
								</p>

								{#if activePrompts.length > 0}
									<div class="pt-3 flex flex-col gap-2 min-h-0 flex-1" in:fade={{ duration: 200 }}>
										<div class="flex items-center gap-2 px-2 shrink-0">
											<span class="text-xs font-semibold text-gray-400 uppercase tracking-widest">Consider</span>
											<span class="consider-pulse w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
										</div>
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
															<p class="text-xs text-amber-300/80 leading-snug flex-1">{prompt.question}</p>
															{#if prompt.rationale}
																<svg
																	class="w-3 h-3 text-amber-400/50 shrink-0 mt-0.5 transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
																	fill="none"
																	stroke="currentColor"
																	viewBox="0 0 24 24"
																>
																	<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M19 9l-7 7-7-7" />
																</svg>
															{/if}
														</div>
														<p class="text-[10px] text-gray-600 mt-0.5 truncate">re: {prompt.source_text}</p>
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
											{#if !considerScrolledToBottom}
												<div
													class="absolute bottom-0 left-0 right-0 flex justify-center pb-1 pointer-events-none"
													in:fade={{ duration: 150 }}
													out:fade={{ duration: 150 }}
												>
													<span
														class="scroll-hint-arrow flex items-center justify-center w-5 h-5 rounded-full bg-amber-500 border border-amber-300/80 shadow-md shadow-black/40"
													>
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
				</div>

				<!-- Generate Report button -->
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
			</div>
		{/if}

		<!-- Report Response Viewer (always mounted when we have template) -->
		{#if selectedTemplate || response}
			<ReportResponseViewer
				visible={responseVisible && !!selectedTemplate}
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
				scanType={scanType}
				clinicalHistory={variableValues['CLINICAL_HISTORY'] ?? ''}
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
		{/if}
	</div>
{/if}

<Toast bind:this={toast} />

<style>
	@keyframes considerPulse {
		0%,
		100% {
			opacity: 1;
			transform: scale(1);
		}
		50% {
			opacity: 0.4;
			transform: scale(0.75);
		}
	}
	.consider-pulse {
		animation: considerPulse 1.8s ease-in-out infinite;
	}
	@keyframes scrollHintBounce {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.5;
		}
	}
	.scroll-hint-arrow {
		animation: scrollHintBounce 1.4s ease-in-out infinite;
	}
</style>
