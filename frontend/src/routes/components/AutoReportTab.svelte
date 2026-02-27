<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import DictationButton from '$lib/components/DictationButton.svelte';
	import Toast from '$lib/components/Toast.svelte';
	import ReportResponseViewer from './ReportResponseViewer.svelte';
	import { API_URL } from '$lib/config';

	let toast;

	export let availableUseCases = [];
	// Form state - explicitly preserve these when component re-renders
	export let selectedUseCase = '';
	export let promptVariables = [];
	export let variableValues; // No default - prevents Svelte from resetting on re-render
	export let response = null;
	export let responseModel = null;
	export let loading = false;
	export let reportUpdateLoading = false;
	export let reportId = null;
	export let versionHistoryRefreshKey = 0;
	export let error = null;
	
	// Enhancement state props
	export let enhancementGuidelinesCount = 0;
	export let enhancementLoading = false;
	export let enhancementError = false;
	export let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		deepgram_configured: false,
		using_user_keys: {
			deepgram: false
		}
	};
	
	// Export selectedModel as a bindable prop - always uses Claude
	export let selectedModel = 'claude';

	const dispatch = createEventDispatcher();
	
	// Ensure props are never undefined to prevent errors
	if (typeof variableValues === 'undefined') {
		variableValues = {};
	}
	
	// Control collapsible state
	let formExpanded = true;
	let responseExpanded = false;
	let hasResponseEver = false;
	let responseVisible = false;
	
	// Track recording state for each variable (for glow effect)
	let dictationStates = {};
	
	// Store textarea element references for cursor-based insertion
	let textareaRefs = {};
	
	// Initialize dictation states for each variable
	$: if (promptVariables.length > 0) {
		promptVariables.forEach(variable => {
			if (!(variable in dictationStates)) {
				dictationStates[variable] = false;
			}
		});
	}
	
	// Check if Claude API key is configured (always uses Claude)
	$: hasModelKey = apiKeyStatus.anthropic_configured;
	
	// Auto-collapse form and expand response when response arrives
	$: if (response || error) {
		formExpanded = false;
		responseExpanded = true;
		if (response || error) {
			hasResponseEver = true;
		}
	}

$: responseVisible = hasResponseEver || Boolean(response) || Boolean(error);

	function onUseCaseChange() {
		variableValues = {};
		hasResponseEver = false;
		responseVisible = false;
		
		if (!selectedUseCase) {
			promptVariables = [];
			return;
		}

		// Dispatch event to parent to load prompt details
		dispatch('useCaseChange');
	}

	async function handleSubmit() {
		// Require a use case to be selected
		if (!selectedUseCase) {
			error = 'Please select a use case';
			return;
		}
		
		// Check if Claude API key is configured (always uses Claude)
		if (!apiKeyStatus.anthropic_configured) {
			error = 'Anthropic API key not configured. Please set ANTHROPIC_API_KEY environment variable.';
			return;
		}
		
		// For use cases with variables, check if they're filled
		if (promptVariables.length > 0) {
			const hasEmptyFields = promptVariables.some(v => !variableValues[v] || !variableValues[v].trim());
			if (hasEmptyFields) {
				error = 'Please fill in all required fields';
				return;
			}
		}
		
		loading = true;
		error = null;
		response = null;
		responseModel = null;
		
		// Dispatch submit event
		dispatch('submit');
	}

	function handleKeyPress(e) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}

	function handleFormKeyDown(e) {
		
		// Allow Enter to create new lines in textareas - don't interfere at all
		if (e.key === 'Enter' && e.target.tagName === 'TEXTAREA') {
			// Stop the event from bubbling to prevent form submission, but let textarea handle it
			e.stopPropagation();
			return;
		}
		// For other elements, prevent form submission on Enter
		if (e.key === 'Enter' && e.target.tagName !== 'BUTTON' && e.target.tagName !== 'TEXTAREA') {
			e.preventDefault();
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
		dispatch('clearResponse');
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
		// Dispatch to parent to handle the full reset
		dispatch('resetForm');
		dispatch('clearResponse');
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
		hasResponseEver = true;
		responseExpanded = true;
		responseVisible = true;
		dispatch('historyRestored', detail);
	}

	async function handleReportSave(event) {
		const newContent = event.detail.content;
		if (!reportId) return;

		try {
			reportUpdateLoading = true;
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};

			const res = await fetch(`${API_URL}/api/reports/${reportId}/update`, {
				method: 'PUT',
				headers,
				body: JSON.stringify({ content: newContent })
			});

			const data = await res.json();

			if (data.success) {
				response = data.report.report_content;
				versionHistoryRefreshKey += 1;
				// Dispatch event to notify parent (and sidebar) of the update
				dispatch('historyUpdate', { count: (data.version ? data.version.version_number : 0) });
				// We need to notify the sidebar to refresh its content/analysis
				// The sidebar listens to 'reportUpdated' on the parent, but here we are in a child.
				// We can dispatch a custom event that the parent listens to.
				// Actually, AutoReportTab dispatches 'historyRestored' which updates the sidebar.
				// Let's reuse that or dispatch a new one.
				// Looking at +page.svelte, it passes 'reportId' to Sidebar.
				// Sidebar has its own 'updateReportContent' but we are bypassing it here.
				// We should dispatch an event that +page.svelte can use to notify Sidebar or just rely on Sidebar's polling/reactivity if it has any (it doesn't seem to poll for content).
				
				// +page.svelte listens to 'historyRestored' from AutoReportTab.
				// Let's check how +page.svelte handles updates.
				// It seems +page.svelte doesn't have a direct 'reportUpdated' handler for AutoReportTab other than history restoration.
				// However, ReportEnhancementSidebar listens to 'reportUpdated' from ITSELF.
				
				// If we update the report here, the Sidebar needs to know.
				// The Sidebar takes 'reportContent' as a prop.
				// In +page.svelte: <ReportEnhancementSidebar reportContent={response || ''} ... />
				// 'response' in +page.svelte is bound to 'response' in AutoReportTab.
				// So updating 'response' here updates 'response' in +page.svelte, which updates 'reportContent' prop in Sidebar.
				// This should be sufficient for the Sidebar to see the new content!
				
				if (toast) toast.show('Report updated successfully');
			} else {
				error = data.error || 'Failed to update report';
			}
		} catch (err) {
			error = `Failed to update: ${err.message}`;
		} finally {
			reportUpdateLoading = false;
		}
	}
</script>

<div class="space-y-4">
	<div class="flex items-center gap-3 mb-6">
		<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
		</svg>
		<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Quick Reports</h1>
	</div>
	
	<!-- Form Collapsible Section -->
	<div class="card-dark">
		<!-- Header -->
		<div class="flex items-center justify-between p-4">
			<h2 class="text-lg font-semibold text-white">Generate Report</h2>
			
			<div class="flex items-center gap-3">
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
		<div class={formExpanded ? '' : 'hidden'}>
			<div class="p-4 pt-0">
				<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }} onkeydown={handleFormKeyDown} class="space-y-4">
					<!-- Use Case Selector -->
					<div>
						<label for="usecase-select" class="block text-sm font-medium text-gray-300 mb-2">
							Use Case
						</label>
						<select
							id="usecase-select"
							bind:value={selectedUseCase}
							onchange={onUseCaseChange}
							disabled={loading}
							class="select-dark"
						>
							{#each availableUseCases as useCase}
								<option value={useCase.name}>{useCase.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</option>
							{/each}
						</select>
					</div>
					
					{#if !apiKeyStatus.anthropic_configured && !apiKeyStatus.groq_configured}
						<p class="text-xs text-yellow-400">
							⚠️ No API keys configured. Please set ANTHROPIC_API_KEY or GROQ_API_KEY environment variables.
						</p>
					{/if}
					
					<!-- Variable Input Fields (when use case is selected) -->
					{#if promptVariables.length > 0}
						<div class="space-y-3">
							{#each promptVariables as variable}
								<div>
									<label for={variable} class="block text-sm font-medium text-gray-300 mb-1">
										{variable.replace(/_/g, ' ')}
									</label>
									<div class="flex gap-2 dictation-field-wrapper" class:dictating-active={dictationStates[variable]}>
										<textarea
											id={variable}
											bind:this={textareaRefs[variable]}
											bind:value={variableValues[variable]}
											placeholder={`Enter ${variable.replace(/_/g, ' ').toLowerCase()}...`}
											disabled={loading}
											class="input-dark flex-1 resize-none"
											rows="4"
											onkeydown={(e) => {
												
												if (e.key === 'Enter') {
												}
											}}
										></textarea>
										<div class="relative group">
											<DictationButton 
												bind:bindText={variableValues[variable]}
												textareaElement={textareaRefs[variable]}
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
					{/if}
					
					<!-- Send Button - Full Width -->
					<button
						type="submit"
						disabled={loading || !selectedUseCase || (promptVariables.length > 0 && promptVariables.some(v => !variableValues[v] || !variableValues[v].trim())) || !hasModelKey}
						class="w-full btn-primary px-6 py-3"
					>
						{loading ? 'Generating...' : 'Generate Report'}
					</button>
				</form>
			</div>
		</div>
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
			enhancementGuidelinesCount={enhancementGuidelinesCount}
			enhancementLoading={enhancementLoading}
			enhancementError={enhancementError}
			on:toggle={toggleResponse}
			on:openSidebar={(e) => dispatch('openSidebar', e.detail)}
			on:copy={copyToClipboard}
			on:clear={clearResponse}
			on:restore={(event) => handleHistoryRestore(event.detail)}
			on:historyUpdate={(event) => dispatch('historyUpdate', event.detail)}
			on:save={handleReportSave}
			on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
			on:hideHoverPopup={() => dispatch('hideHoverPopup')}
		/>
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
