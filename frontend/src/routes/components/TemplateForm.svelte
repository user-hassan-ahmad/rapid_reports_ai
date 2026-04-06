<script lang="ts">
	import { createEventDispatcher, tick } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { token } from '$lib/stores/auth';
	import DictationScratchpad from '$lib/components/DictationScratchpad.svelte';
	import DictationHintBar from '$lib/components/DictationHintBar.svelte';
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
		cerebras_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false
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

	export let prePoppedSections: string[] = [];
	let sectionsLoading = false;
	let sectionsError = '';

	interface IntelliPrompt {
		question: string;
		source_text: string;
		rationale?: string;
	}

	let resetConfirmVisible = false;
	let caseDetailsManuallyExpanded = false;

	$: workspaceOpen = prePoppedSections.length > 0 || sectionsLoading;

	// Non-FINDINGS variables for step 1 (plain textareas, no dictation)
	$: nonFindingsVariables = (selectedTemplate?.variables || Object.keys(variableValues || {}))
		.filter((v: string) => v !== 'FINDINGS');

	let variableValuesGeneratedFrom: Record<string, string> = {};
	$: sectionsDirty = prePoppedSections.length > 0 && nonFindingsVariables.some(
		(v) => (variableValues[v] ?? '').trim() !== (variableValuesGeneratedFrom[v] ?? '').trim()
	);

	$: caseDetailsExpanded = !workspaceOpen || caseDetailsManuallyExpanded || sectionsDirty;
	let scratchpadRef: {
		getContent: () => string;
		getFindingCount: () => number;
		reset: (doc: string) => void;
		highlightSource: (text: string) => void;
		clearHighlight: () => void;
	} | null = null;

	let coveredSections: Set<string> = new Set();
	let activePrompts: IntelliPrompt[] = [];
	let isReviewing = false;

	export let scratchpadContent = '';
	let isRecording = false;
	let scanType = '';
	let lastTemplateId: string | null = null;

	// ReportResponseViewer state
	let responseExpanded = false;
	let hasResponseEver = false;
	let responseVisible = false;
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

	$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);
	let findingsAtReportGeneration = '';
	$: findingsStale = hasResponseEver && !!response && scratchpadToFindings(scratchpadContent) !== findingsAtReportGeneration;

	$: allChecklistSections = prePoppedSections;

	// Extract FINDINGS template_content and content_style for section extraction
	$: findingsTemplateContent = (() => {
		const sections = selectedTemplate?.template_config?.sections;
		if (!sections || !Array.isArray(sections)) return '';
		const findingsSection = sections.find((s: any) => s?.name === 'FINDINGS');
		return findingsSection?.template_content || '';
	})();
	$: findingsContentStyle = (() => {
		const sections = selectedTemplate?.template_config?.sections;
		if (!sections || !Array.isArray(sections)) return '';
		const findingsSection = sections.find((s: any) => s?.name === 'FINDINGS');
		return findingsSection?.content_style || '';
	})();

	// Reset when template changes
	$: if (selectedTemplate?.id && selectedTemplate.id !== lastTemplateId) {
		lastTemplateId = selectedTemplate.id;
		prePoppedSections = [];
		coveredSections = new Set();
		activePrompts = [];
		hasResponseEver = false;
		responseVisible = false;
	}

	// scanType from template config
	$: scanType = selectedTemplate?.template_config?.scan_type ?? '';

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
			const templateId = selectedTemplate?.id ?? 'unknown';
			const templateName = selectedTemplate?.name ?? 'unknown';
			console.log('[SetUpWorkspace] template:', templateId, templateName, 'findingsTemplateContent len:', findingsTemplateContent?.length ?? 0, 'content_style:', findingsContentStyle);

			if (findingsTemplateContent?.trim()) {
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) headers['Authorization'] = `Bearer ${$token}`;
				const res = await fetch(`${API_URL}/api/canvas/sections-from-template`, {
					method: 'POST',
					headers,
					body: JSON.stringify({
						template_content: findingsTemplateContent,
						content_style: findingsContentStyle
					})
				});
				const data = await res.json();
				console.log('[SetUpWorkspace] sections-from-template res.status:', res.status, 'data:', data, 'data.sections:', data?.sections);

				if (data.sections && Array.isArray(data.sections)) {
					// Snapshot variables for dirty tracking
					variableValuesGeneratedFrom = {};
					for (const v of nonFindingsVariables) {
						variableValuesGeneratedFrom[v] = variableValues[v] || '';
					}

					// If workspace is already open, this is a regeneration, so clear previous state
					if (workspaceOpen) {
						scratchpadRef?.reset('');
						response = null;
						responseModel = null;
						reportId = null;
						hasResponseEver = false;
						responseExpanded = false;
						activePrompts = [];
						findingsAtReportGeneration = '';
						dispatch('clearResponse');
					}

					prePoppedSections = data.sections;
					console.log('[SetUpWorkspace] prePoppedSections set:', prePoppedSections.length, prePoppedSections);
				} else {
					prePoppedSections = [];
					console.log('[SetUpWorkspace] prePoppedSections empty (no valid data.sections)');
				}
			} else {
				prePoppedSections = [];
				console.log('[SetUpWorkspace] prePoppedSections empty (findingsTemplateContent empty or whitespace)');
			}
			coveredSections = new Set();
		caseDetailsManuallyExpanded = false;
		} catch (e) {
			console.error('[SetUpWorkspace] fetch error:', e);
			sectionsError = 'Failed to connect to API';
			prePoppedSections = [];
		} finally {
			sectionsLoading = false;
			console.log('[SetUpWorkspace] done. prePoppedSections.length:', prePoppedSections.length, 'workspaceOpen will be:', prePoppedSections.length > 0);
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
		prePoppedSections = [];
		activePrompts = [];
		coveredSections = new Set();
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		hasResponseEver = false;
		responseExpanded = false;
		findingsAtReportGeneration = '';
		dispatch('resetForm');
		dispatch('reportCleared');
		dispatch('clearResponse');
		dispatch('historyUpdate', { count: 0 });
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

		loading = true;
		error = null;
		response = null;
		responseModel = null;

		const _flowT0 = typeof performance !== 'undefined' ? performance.now() : 0;
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
			const _flowT1 = typeof performance !== 'undefined' ? performance.now() : 0;
			console.debug(
				'[FLOW_TIMING] template POST /generate roundtrip_ms=',
				Math.round(_flowT1 - _flowT0),
				'report_id=',
				data.report_id
			);

			if (data.success) {
				response = data.response;
				responseModel = data.model;
				reportId = data.report_id ?? null;
				hasResponseEver = true;
				responseExpanded = true;
				findingsAtReportGeneration = findingsContent;
				dispatch('reportGenerated', { reportId: data.report_id });
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
		findingsAtReportGeneration = '';
		dispatch('reportCleared');
		dispatch('historyUpdate', { count: 0 });
	}


	function handleCoveredSectionsChange(covered: string[]) {
		coveredSections = new Set(covered);
	}

	function handlePromptsChange(prompts: IntelliPrompt[]) {
		activePrompts = prompts;
	}

	function handleScratchpadClear() {
		coveredSections = new Set();
		activePrompts = [];
	}

	export async function restoreWorkspace(sections: string[], content: string) {
		prePoppedSections = [...sections];
		if (content && sections.length > 0) {
			await tick();
			scratchpadRef?.reset(content);
		}
		// Treat restored state as ground truth so sectionsDirty stays false
		variableValuesGeneratedFrom = {};
		for (const v of nonFindingsVariables) {
			variableValuesGeneratedFrom[v] = variableValues[v] ?? '';
		}
	}

	function copyToClipboard() {
		if (!response) return;
		navigator.clipboard.writeText(response).then(() => {
			if (toast) toast.show('Copied to clipboard!');
		});
	}

	function handleHistoryRestore(detail: {
		report?: {
			report_content: string;
			model_used?: string;
			input_data?: { variables?: Record<string, string> };
		};
	}) {
		if (!detail?.report) return;
		response = detail.report.report_content;
		responseModel = detail.report.model_used ?? null;
		hasResponseEver = true;
		responseExpanded = true;
		responseVisible = true;

		const savedVars = detail.report.input_data?.variables;
		if (savedVars && typeof savedVars === 'object') {
			const nonFindings = Object.fromEntries(
				Object.entries(savedVars).filter(([k]) => k !== 'FINDINGS')
			);
			variableValues = { ...variableValues, ...nonFindings };
		}

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

	const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

	function toTitleCase(s: string): string {
		return s.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
	}

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
							<div class="flex items-center gap-2"
								in:fly={{ x: 16, duration: 200, easing: easeOut }}
								out:fly={{ x: 16, duration: 150, easing: easeOut }}>
								<p class="text-xs text-gray-400 whitespace-nowrap">Discard scratchpad content?</p>
								<button type="button" onclick={doReset}
									class="px-2.5 py-1 text-xs rounded-lg bg-red-600/80 hover:bg-red-500 text-white transition-colors whitespace-nowrap">Discard</button>
								<button type="button" onclick={() => (resetConfirmVisible = false)}
									class="px-2.5 py-1 text-xs rounded-lg text-gray-400 hover:bg-white/5 transition-colors">Cancel</button>
							</div>
						{:else}
							{#if workspaceOpen}
								<button type="button" onclick={() => (caseDetailsManuallyExpanded = false)}
									class="p-1.5 text-gray-500 hover:text-gray-300 transition-colors rounded-lg hover:bg-white/5"
									title="Collapse" aria-label="Collapse">
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
									</svg>
								</button>
							{/if}
							<button type="button"
								onclick={() => dispatch('editTemplate', { template: selectedTemplate })}
								class="px-2.5 py-1.5 text-xs btn-secondary flex items-center gap-1.5">
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
								</svg>
								Edit Template
							</button>
							<button type="button" onclick={handleResetClick}
								class="p-1.5 text-gray-500 hover:text-orange-400 transition-colors rounded-lg hover:bg-white/5"
								title="Reset" aria-label="Reset">
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
								</svg>
							</button>
						{/if}
					</div>
				</div>

				<form onsubmit={(e) => { e.preventDefault(); handleSetUpWorkspace(); }} class="space-y-3"
					in:fade={{ duration: 150 }}>
					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
						{#each nonFindingsVariables as variable}
							<div class="space-y-1.5">
								<label for={variable} class="block text-xs font-medium text-gray-400 uppercase tracking-wider">
									{toTitleCase(variable)}
								</label>
								<textarea
									id={variable}
									bind:value={variableValues[variable]}
									placeholder={`Enter ${variable.replace(/_/g, ' ').toLowerCase()}...`}
									disabled={sectionsLoading}
									class="input-dark w-full resize-none text-sm"
									rows="3"
								></textarea>
							</div>
						{/each}
					</div>
					{#if sectionsError}
						<p class="text-red-400 text-xs">{sectionsError}</p>
					{/if}
					<div class="flex items-center justify-between pt-1">
						<div class="flex items-center gap-2">
							{#if sectionsDirty}
								<button type="button"
									onclick={() => { 
										for (const v of nonFindingsVariables) {
											variableValues[v] = variableValuesGeneratedFrom[v] ?? '';
										}
									}}
									class="text-xs text-gray-500 hover:text-gray-300 transition-colors flex items-center gap-1"
									in:fade={{ duration: 200 }}>
									<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
									</svg>
									Revert changes
								</button>
							{/if}
						</div>
						<button type="submit" disabled={sectionsLoading}
							class="px-5 py-2 rounded-lg text-sm font-medium transition-all duration-200
								{sectionsDirty
									? 'bg-amber-500/20 border border-amber-500/50 text-amber-300 hover:bg-amber-500/30 animate-pulse-once'
									: 'bg-gradient-to-r from-purple-600/80 to-blue-600/80 border border-purple-500/30 text-white hover:from-purple-600 hover:to-blue-600'}
								disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
							{#if sectionsLoading}
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
							text-xs font-medium text-purple-300 truncate max-w-[200px] transition-colors
							group-hover:border-purple-500/40 group-hover:bg-purple-500/20">
							{selectedTemplate?.name ?? '—'}
						</span>
						{#each nonFindingsVariables.slice(0, 2) as v}
							{#if variableValues[v]}
								<span class="text-xs text-gray-500 truncate transition-colors group-hover:text-gray-400">
									{variableValues[v]}
								</span>
							{/if}
						{/each}
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
							class="px-2.5 py-1 text-xs rounded-lg bg-red-600/80 hover:bg-red-500 text-white transition-colors">Discard</button>
						<button type="button" onclick={() => (resetConfirmVisible = false)}
							class="px-2.5 py-1 text-xs rounded-lg text-gray-400 hover:bg-white/5 transition-colors">Cancel</button>
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
				<p class="text-[11px] text-gray-600 text-center tracking-wide">Generating review guide sections...</p>
			</div>
		{/if}

		{#if workspaceOpen && prePoppedSections.length > 0}
			<div class="h-px bg-gradient-to-r from-transparent via-white/10 to-transparent"
				in:fade={{ duration: 400 }}></div>
		{/if}

		{#if prePoppedSections.length > 0}
			<!-- Workspace -->
			<div
				class="flex flex-col gap-4 min-h-0 flex-1"
				in:fly={{ y: 24, duration: 320, easing: easeOut }}
				out:fly={{ y: 12, duration: 180, easing: easeOut }}
			>
				<div class="flex items-start justify-between gap-3 border-b border-white/[0.06] pb-3 shrink-0 min-w-0">
					<span class="min-w-0 flex-1 text-xs text-gray-500 font-medium uppercase tracking-wider break-words">
						{scanType || selectedTemplate?.name || 'Template'}
					</span>
					<div class="shrink-0">
						<DictationHintBar />
					</div>
				</div>

		<!-- Single-column workspace (aligned with Quick Reports) -->
		<div class="flex flex-col min-h-0 flex-1 gap-3 relative transition-opacity duration-300 {sectionsDirty ? 'opacity-50 pointer-events-none' : ''}">
			{#if sectionsDirty}
				<div class="absolute inset-0 z-10 flex items-center justify-center bg-black/20 rounded-lg" in:fade={{ duration: 200 }}>
					<p class="text-sm text-gray-400">Case details changed — regenerate workspace to continue</p>
				</div>
			{/if}
			<!-- Coverage chip strip -->
			<div class="flex flex-wrap gap-1.5 transition-opacity duration-300 {isReviewing ? 'opacity-50' : ''}">
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

				<!-- Scratchpad (prompts rendered in IntelliPromptsMargin) -->
				<DictationScratchpad
					bind:this={scratchpadRef}
					checklistSections={prePoppedSections}
					{activePrompts}
					{scanType}
					clinicalHistory={variableValues['CLINICAL_HISTORY'] ?? ''}
					{apiKeyStatus}
					onContentChange={(c) => { scratchpadContent = c; }}
					onRecordingChange={(recording) => { isRecording = recording; }}
					onReviewingChange={(reviewing) => { isReviewing = reviewing; }}
					onCoveredSectionsChange={handleCoveredSectionsChange}
					onPromptsChange={handlePromptsChange}
					onScratchpadClear={handleScratchpadClear}
				/>
			</div>

				<!-- Generate Report button -->
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
			</div>
		{/if}

		<!-- Report Response Viewer (always mounted when we have template) -->
		{#if selectedTemplate || response}
			<ReportResponseViewer
				bind:this={reportViewerRef}
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
				caseDetailsDirty={sectionsDirty}
				{findingsStale}
				on:toggle={toggleResponse}
			on:openSidebar={(e) => dispatch('openSidebar', e.detail)}
			on:auditStateChange={(e) => dispatch('auditStateChange', e.detail)}
			on:openVersionHistory={() => dispatch('openVersionHistory')}
			on:copy={copyToClipboard}
			on:clear={clearResponse}
			on:restore={(e) => handleHistoryRestore(e.detail)}
			on:historyUpdate={(e) => dispatch('historyUpdate', e.detail)}
			on:auditComplete={(e) => dispatch('auditComplete', e.detail)}
			on:save={handleReportSave}
			on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
			on:hideHoverPopup={() => dispatch('hideHoverPopup')}
		/>
		{/if}
	</div>
{/if}

<Toast bind:this={toast} />

<style>
	@keyframes shimmer {
		0%   { opacity: 0.4; }
		50%  { opacity: 0.8; }
		100% { opacity: 0.4; }
	}
	.skeleton-shimmer {
		animation: shimmer 1.6s ease-in-out infinite;
	}
</style>
