<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import DictationButton from '$lib/components/DictationButton.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import ReportResponseViewer from './ReportResponseViewer.svelte';
	import { API_URL } from '$lib/config';

	const dispatch = createEventDispatcher();

	let toast;

	export let selectedTemplate; // No default - prevents Svelte from resetting on re-render
	export let variableValues; // No default - prevents Svelte from resetting on re-render
	export let response = null;
	export let responseModel = null;
	export let loading = false;
	export let reportUpdateLoading = false;
	export let error = null;
	export let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false,
		using_user_keys: {
			deepgram: false
		}
	};
	
	// Always use Claude for template reports
	export let selectedModel = 'claude';

export let reportId = null;
export let versionHistoryRefreshKey = 0;

	// Ensure props are never undefined to prevent errors
	if (typeof selectedTemplate === 'undefined') {
		selectedTemplate = null;
	}
	if (typeof variableValues === 'undefined') {
		variableValues = {};
	}
	
	// Track last template ID to detect when template actually changes (not just object reference)
	let lastTemplateId = null;
	let preservedVariableValues = {};
	
	// Reactive statement: Watch selectedTemplate to preserve values when template changes
	$: if (selectedTemplate && selectedTemplate.id) {
		const currentTemplateId = selectedTemplate.id;
		
		// Update lastTemplateId if template changed
		if (currentTemplateId !== lastTemplateId) {
			lastTemplateId = currentTemplateId;
			hasResponseEver = false;
			responseVisible = false;
		}
		
		// Always preserve current values if they exist
		if (Object.keys(variableValues || {}).length > 0) {
			preservedVariableValues[currentTemplateId] = { ...variableValues };
		}
	}
	
	// Separate reactive statement that watches variableValues directly
	// If variableValues becomes empty unexpectedly (when we have a template selected and preserved values),
	// restore them immediately
	$: if (selectedTemplate && selectedTemplate.id && preservedVariableValues[selectedTemplate.id]) {
		const currentTemplateId = selectedTemplate.id;
		const hasValues = variableValues && Object.keys(variableValues).length > 0;
		const hasPreserved = preservedVariableValues[currentTemplateId] && Object.keys(preservedVariableValues[currentTemplateId]).length > 0;
		
		// If variableValues is empty but we have preserved values, restore immediately
		if (!hasValues && hasPreserved) {
			variableValues = { ...preservedVariableValues[currentTemplateId] };
		}
	}
	
	// Check if selected model has API key configured (system environment variables)
	// Always uses Claude - check if Anthropic API key is configured
	$: hasModelKey = apiKeyStatus.anthropic_configured;

	// Control collapsible state
let formExpanded = true;
let responseExpanded = false;
let hasResponseEver = false;
let responseVisible = false;
	
	// Track recording state for each variable (for glow effect)
	let dictationStates = {};
	
	// Initialize dictation states for each variable
	$: if (Object.keys(variableValues).length > 0) {
		Object.keys(variableValues).forEach(variable => {
			if (!(variable in dictationStates)) {
				dictationStates[variable] = false;
			}
		});
	}
	
	// Auto-collapse form and expand response when response arrives
	$: if (response || error) {
		formExpanded = false;
		responseExpanded = true;
		if (response || error) {
			hasResponseEver = true;
		}
	}
	
	// Auto-expand form and collapse response when response is cleared and no response was ever shown
	$: if (!response && !error && !hasResponseEver) {
		formExpanded = true;
		responseExpanded = false;
	}

$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);

	// No reactive statements that reset variableValues - parent handles that
	// State is managed in parent (TemplatedReportTab) like Quick Reports

	async function handleSubmit() {
		// Always uses Claude - check if Anthropic API key is configured
		if (!apiKeyStatus.anthropic_configured) {
			error = 'Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable.';
			return;
		}
		
		// Check if FINDINGS and CLINICAL_HISTORY are filled (required)
		if (!variableValues['FINDINGS'] || !variableValues['FINDINGS'].trim()) {
			error = 'Please fill in FINDINGS';
			return;
		}
		if (!variableValues['CLINICAL_HISTORY'] || !variableValues['CLINICAL_HISTORY'].trim()) {
			error = 'Please fill in CLINICAL_HISTORY';
			return;
		}
		
		// Check if other optional variables are filled
		const optionalEmptyFields = Object.keys(variableValues).filter(v => {
			if (v === 'FINDINGS' || v === 'CLINICAL_HISTORY') return false;
			return !variableValues[v] || !variableValues[v].trim();
		});
		
		if (optionalEmptyFields.length > 0) {
			error = `Please fill in all fields: ${optionalEmptyFields.join(', ')}`;
			return;
		}
		
		loading = true;
		error = null;
		response = null;
		responseModel = null;
		// Note: variableValues is NOT cleared - preserve form input like Quick Reports

		try {
			const payload = {
				variables: variableValues,
				model: selectedModel
			};

		const headers = { 'Content-Type': 'application/json' };
		if ($token) {
			headers['Authorization'] = `Bearer ${$token}`;
		}
		
		const res = await fetch(
			`${API_URL}/api/templates/${selectedTemplate.id}/generate`,
				{
					method: 'POST',
					headers,
					body: JSON.stringify(payload)
				}
			);

			const data = await res.json();

			if (data.success) {
				response = data.response;
				responseModel = data.model;
				// Dispatch reportId to parent
				dispatch('reportGenerated', { reportId: data.report_id });
			} else {
				error = data.error || 'Failed to generate report';
			}
		} catch (err) {
			error = 'Failed to connect to API. Make sure the backend is running.';
		} finally {
			loading = false;
		}
	}

	function toggleForm() {
		formExpanded = !formExpanded;
	}

	function toggleResponse() {
		responseExpanded = !responseExpanded;
	}

	function clearResponse() {
		response = null;
		responseModel = null;
		error = null;
		responseExpanded = false;
		formExpanded = true;
		hasResponseEver = false;
		responseVisible = false;
		dispatch('reportCleared');
		dispatch('historyUpdate', { count: 0 });
	}

	function resetForm() {
		// Expand form and collapse response
		formExpanded = true;
		responseExpanded = false;
		hasResponseEver = false;
		responseVisible = false;
		// Clear response state locally
		response = null;
		responseModel = null;
		error = null;
		// Clear preserved values to prevent reactive restoration
		preservedVariableValues = {};
		// Clear variableValues locally before dispatching to parent
		// This prevents reactive statements from restoring from preservedVariableValues
		variableValues = {};
		// Dispatch to parent to handle the full reset (including clearing variableValues)
		dispatch('resetForm');
		dispatch('reportCleared');
		dispatch('historyUpdate', { count: 0 });
	}

	function copyToClipboard() {
		if (!response) return;
		
		// Copy the plain text version (not markdown)
		navigator.clipboard.writeText(response)
			.then(() => {
				// Show toast notification
				if (toast) {
					toast.show('Copied to clipboard!');
				}
			})
			.catch(err => {
				// Failed to copy
			});
	}

	function handleHistoryRestore(detail) {
		if (!detail || !detail.report) return;
		response = detail.report.report_content;
		responseModel = detail.report.model_used;
		responseExpanded = true;
		hasResponseEver = true;
		responseVisible = true;
		dispatch('historyRestored', detail);
	}
</script>

<div class="p-6">
	{#if !selectedTemplate}
		<div class="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
			<p class="text-yellow-400">No template selected</p>
		</div>
	{:else if Object.keys(variableValues).length === 0}
		<div class="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
			<p class="text-yellow-400">This template has no variables to fill</p>
			<button
				onclick={() => dispatch('back')}
				class="btn-secondary mt-4"
			>
				← Back to Templates
			</button>
		</div>
	{:else}
		<div class="space-y-4">
			<!-- Form Collapsible Section -->
			<div class="card-dark">
				<!-- Header -->
				<div class="flex items-center justify-between p-4">
					<div class="flex items-center gap-3">
						<h2 class="text-lg font-semibold text-white">{selectedTemplate.name}</h2>
						{#if selectedTemplate.description}
							<span class="text-xs text-gray-400">- {selectedTemplate.description}</span>
						{/if}
					</div>
					
					<div class="flex items-center gap-3">
						<!-- Edit Template Button -->
						<button
							type="button"
							onclick={() => dispatch('editTemplate', { template: selectedTemplate })}
							class="px-4 py-2 btn-secondary text-sm whitespace-nowrap flex items-center gap-2 hover:bg-gray-700 transition-colors"
							title="Edit Template"
						>
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
							</svg>
							Edit Template
						</button>
						
						<!-- Reset Button -->
						<button
							onclick={resetForm}
							class="p-2 text-gray-400 hover:text-orange-400 transition-colors rounded-lg hover:bg-white/5"
							title="Reset form"
							aria-label="Reset form"
						>
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
							</svg>
						</button>
						
						<!-- Collapse Toggle -->
						<button
							onclick={toggleForm}
							class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5"
							title="Toggle form"
							aria-label="Toggle form"
						>
							<svg
								class="w-5 h-5 transform transition-transform {formExpanded ? 'rotate-180' : ''}"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</button>
					</div>
				</div>

				<!-- Collapsible Content -->
				{#if formExpanded}
					<div class="p-4 pt-0">
						<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
							
							{#if !apiKeyStatus.anthropic_configured}
								<p class="text-xs text-yellow-400 mb-6">
									⚠️ Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable.
								</p>
							{/if}

							<!-- Variable Inputs -->
							<div class="space-y-4 mb-6">
								{#each Object.keys(variableValues) as variable}
								<div>
									<label for={variable} class="block text-sm font-medium text-gray-300 mb-1">
										{variable.replace(/_/g, ' ')}
									</label>
									<div class="flex gap-2 dictation-field-wrapper" class:dictating-active={dictationStates[variable]}>
										<textarea
											id={variable}
											bind:value={variableValues[variable]}
											placeholder={`Enter ${variable.replace(/_/g, ' ').toLowerCase()}...`}
											disabled={loading}
											required
											rows="4"
											class="input-dark flex-1 resize-none"
										></textarea>
										<div class="relative group">
											<DictationButton 
												bind:bindText={variableValues[variable]} 
												bind:isRecording={dictationStates[variable]} 
												disabled={loading || !apiKeyStatus.using_user_keys?.deepgram}
												disabledReason={!apiKeyStatus.using_user_keys?.deepgram ? 'Add Deepgram API key in Settings to enable dictation' : ''}
											/>
											{#if !apiKeyStatus.using_user_keys?.deepgram}
												<div class="absolute right-full mr-2 top-1/2 -translate-y-1/2 px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-sm text-gray-100 whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none z-50 shadow-xl">
													<div class="flex items-center gap-2">
														<svg class="w-4 h-4 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
															<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
														</svg>
														<span>Add Deepgram API key in Settings to enable dictation</span>
													</div>
													<!-- Arrow pointing right -->
													<div class="absolute left-full top-1/2 -translate-y-1/2 border-4 border-transparent border-l-gray-900"></div>
												</div>
											{/if}
										</div>
									</div>
								</div>
								{/each}
							</div>

							<!-- Submit Button -->
							<button
								type="submit"
								disabled={loading || !hasModelKey}
								class="btn-primary w-full px-6 py-3"
							>
								{loading ? 'Generating...' : 'Generate Report'}
							</button>
						</form>
					</div>
				{/if}
			</div>

			<ReportResponseViewer
				visible={responseVisible}
				expanded={responseExpanded}
				response={response}
				error={error}
				model={responseModel}
				generationLoading={loading}
				updateLoading={reportUpdateLoading}
				reportId={reportId}
				versionHistoryRefreshKey={versionHistoryRefreshKey}
				on:toggle={toggleResponse}
				on:openSidebar={() => dispatch('openSidebar')}
				on:copy={copyToClipboard}
				on:clear={clearResponse}
				on:restore={(event) => handleHistoryRestore(event.detail)}
			on:historyUpdate={(event) => dispatch('historyUpdate', event.detail)}
			/>
		</div>
	{/if}
</div>

<Toast bind:this={toast} />

<style>
	textarea {
		font-family: inherit;
	}

	/* Glow animation for dictation */
	.dictation-field-wrapper {
		position: relative;
	}

	.dictation-field-wrapper.dictating-active textarea {
		animation: dictationGlow 2s ease-in-out infinite;
		border-color: rgba(139, 92, 246, 0.5); /* purple-500 */
		box-shadow: 0 0 20px rgba(139, 92, 246, 0.3), 0 0 40px rgba(139, 92, 246, 0.2);
	}

	@keyframes dictationGlow {
		0%, 100% {
			box-shadow: 0 0 20px rgba(139, 92, 246, 0.3), 0 0 40px rgba(139, 92, 246, 0.2);
		}
		50% {
			box-shadow: 0 0 30px rgba(139, 92, 246, 0.5), 0 0 60px rgba(139, 92, 246, 0.3);
		}
	}
</style>
