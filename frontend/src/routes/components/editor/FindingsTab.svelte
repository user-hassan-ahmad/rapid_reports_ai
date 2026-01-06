<script>
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { fetchCustomPresets } from '$lib/stores/presets';
	import StylePresetCards from '../wizard/StylePresetCards.svelte';
	import StyleGranularControls from '../wizard/StyleGranularControls.svelte';
	import TemplateSyntaxPreview from '../shared/TemplateSyntaxPreview.svelte';

	const dispatch = createEventDispatcher();

	export let findingsConfig = {
		content_style: null,
		template_content: '',
		style_templates: {
			structured_template: '',
			normal_template: '',
			guided_template: '',
			checklist: ''
		},
		advanced: {
			instructions: '',
			writing_style: 'standard',
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
			measurement_style: 'inline',
			negative_findings_style: 'grouped',
			descriptor_density: 'standard',
			paragraph_grouping: 'by_finding'
		}
	};

	let selectedFindingsPreset = 'balanced_standard';

	function handlePresetChange(event) {
		selectedFindingsPreset = event.detail.presetId;
		handleChange();
	}

	function resetToDefaults() {
		selectedFindingsPreset = 'balanced_standard';
		findingsConfig.advanced = {
			instructions: '',
			writing_style: 'standard',
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
			measurement_style: 'inline',
			negative_findings_style: 'grouped',
			descriptor_density: 'standard',
			paragraph_grouping: 'by_finding'
		};
		handleChange();
	}

	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';

	let generating = false;
	let suggesting = false;
	let showInstructionsGuide = false;
	let showPreview = false;
	let showAdvanced = true; // Default to expanded

	// Track previous style to detect changes
	let previousStyle = null;

	// Initialize style_templates on first load
	$: if (findingsConfig.content_style && previousStyle === null) {
		// First load - store current template_content in style_templates if it exists
		if (findingsConfig.template_content && !findingsConfig.style_templates[findingsConfig.content_style]) {
			findingsConfig.style_templates[findingsConfig.content_style] = findingsConfig.template_content;
		}
		previousStyle = findingsConfig.content_style;
	}

	// Reactive: Clear conflicting style settings for structured templates
	$: if (findingsConfig.content_style === 'structured_template') {
		// Clear all style settings except instructions
		const currentInstructions = findingsConfig.advanced?.instructions || '';
		// Only update if advanced has properties other than instructions to avoid infinite loop
		const hasOtherProps = findingsConfig.advanced && Object.keys(findingsConfig.advanced).some(key => key !== 'instructions');
		if (hasOtherProps) {
			// @ts-ignore - We intentionally clear style settings for structured templates
			findingsConfig.advanced = {
				instructions: currentInstructions
			};
			handleChange();
		}
	}

	// Reactive: Restore defaults when switching away from structured template
	$: if (findingsConfig.content_style && 
		findingsConfig.content_style !== 'structured_template' && 
		!findingsConfig.advanced?.writing_style) {
		// Restore default style settings for other content styles
		findingsConfig.advanced = {
			instructions: findingsConfig.advanced?.instructions || '',
			writing_style: 'standard',
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
			measurement_style: 'inline',
			negative_findings_style: 'grouped',
			descriptor_density: 'standard',
			paragraph_grouping: 'by_finding'
		};
		handleChange();
	}

	// For UI display: hide full style controls for structured templates
	$: showFullStyleControls = findingsConfig.content_style !== 'structured_template';

	// Update range slider background based on value
	function updateRangeBackground(value, min, max, element) {
		const percentage = ((value - min) / (max - min)) * 100;
		element.style.background = `linear-gradient(to right, rgba(168, 85, 247, 0.8) 0%, rgba(168, 85, 247, 0.8) ${percentage}%, rgba(255, 255, 255, 0.1) ${percentage}%, rgba(255, 255, 255, 0.1) 100%)`;
	}

	function handleVerbosityChange(event) {
		updateRangeBackground(findingsConfig.advanced.verbosity, 0, 2, event.target);
		handleChange();
	}

	// Svelte action to initialize range slider
	function initRangeSlider(node, { value, min, max }) {
		updateRangeBackground(value, min, max, node);
		return {
			update({ value, min, max }) {
				updateRangeBackground(value, min, max, node);
			}
		};
	}

	const styleOptions = [
		{ 
			id: 'structured_template', 
			label: 'Structured Fill-In',
			description: 'AI intelligently fills variables and measurements',
			icon: '📐',
			example: '[keep titles!]\n\nLEFT VENTRICLE\nNormal/increased indexed LV end-diastolic volume (xxx ml/m2)'
		},
		{ 
			id: 'normal_template', 
			label: 'Normal Report',
			description: 'Pre-filled normal findings',
			icon: '📋',
			example: 'Complete normal text that AI adapts'
		},
		{ 
			id: 'guided_template', 
			label: 'Guided Template',
			description: 'Template with inline guidance',
			icon: '💡',
			example: 'Text with // comment hints'
		},
		{ 
			id: 'checklist', 
			label: 'Checklist',
			description: 'Systematic bullet points',
			icon: '✓',
			example: '- Item 1\n- Item 2'
		}
	];

	// Handle content style change - save current content and load new content
	function handleStyleChange(newStyle) {
		// Save current template content to the previous style in the persisted object
		if (previousStyle && findingsConfig.template_content) {
			findingsConfig.style_templates[previousStyle] = findingsConfig.template_content;
		}

		// Update to new style
		previousStyle = newStyle;
		findingsConfig.content_style = newStyle;

		// Load template content for the new style (from persisted storage or empty)
		const newContent = findingsConfig.style_templates[newStyle] || '';
		findingsConfig.template_content = newContent;

		// Force a re-render by creating a new object
		findingsConfig = { ...findingsConfig };

		// Trigger change event for auto-save
		handleChange();
	}

	// Handle template content change
	function handleTemplateContentChange(event) {
		// Save to the current style's storage in the persisted object
		if (findingsConfig.content_style) {
			findingsConfig.style_templates[findingsConfig.content_style] = findingsConfig.template_content;
		}
		handleChange();
	}

	function handleChange() {
		dispatch('change');
	}

	onMount(() => {
		fetchCustomPresets('findings');
	});

	// Note: contrastOther is not available in this component, but we don't need it for display

	async function generateWithAI() {
		if (!findingsConfig.content_style) {
			alert('Please select a content style first');
			return;
		}
		
		generating = true;
		try {
			// Convert contrast value to readable string
			let contrastValue = '';
			if (contrast === 'no_contrast') {
				contrastValue = 'No contrast';
			} else if (contrast === 'with_iv') {
				contrastValue = 'With IV contrast';
			} else if (contrast === 'arterial') {
				contrastValue = 'Arterial phase';
			} else if (contrast === 'portal_venous') {
				contrastValue = 'Portal venous';
			} else if (contrast === 'other') {
				contrastValue = 'Other'; // contrastOther not available here, but API should handle it
			}

			const response = await fetch(`${API_URL}/api/templates/generate-findings-content`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({
					scan_type: scanType,
					contrast: contrastValue,
					protocol_details: protocolDetails || '',
					content_style: findingsConfig.content_style,
					instructions: findingsConfig.advanced.instructions || ''
				})
			});

			const data = await response.json();
			if (data.success) {
				findingsConfig.template_content = data.content;
				// Save generated content to the current style in persisted storage
				if (findingsConfig.content_style) {
					findingsConfig.style_templates[findingsConfig.content_style] = data.content;
				}
				handleChange();
			} else {
				alert('Error generating template: ' + data.error);
			}
		} catch (error) {
			console.error('Error generating template:', error);
			alert('Error generating template. Please try again.');
		} finally {
			generating = false;
		}
	}

	async function suggestInstructions() {
		suggesting = true;
		try {
			const response = await fetch(`${API_URL}/api/templates/suggest-instructions`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({
					section: 'FINDINGS',
					scan_type: scanType,
					content_style: findingsConfig.content_style
				})
			});

			const data = await response.json();
			if (data.success && data.suggestions && data.suggestions.length > 0) {
				findingsConfig.advanced.instructions = data.suggestions[0];
				handleChange();
			}
		} catch (error) {
			console.error('Error suggesting instructions:', error);
		} finally {
			suggesting = false;
		}
	}

	async function extractPlaceholders(templateContent) {
		try {
			const response = await fetch(`${API_URL}/api/templates/extract-placeholders`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({ template_content: templateContent })
			});
			
			const data = await response.json();
			if (data.success) {
				return data.placeholders;
			}
			throw new Error(data.error || 'Failed to extract placeholders');
		} catch (err) {
			console.error('Error extracting placeholders:', err);
			throw err;
		}
	}

	async function validateTemplate(templateContent) {
		try {
			const response = await fetch(`${API_URL}/api/templates/validate-template`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({ template_content: templateContent })
			});
			const data = await response.json();
			if (data.success) {
				return data.validation;
			}
			throw new Error(data.error || 'Failed to validate template');
		} catch (err) {
			console.error('Error validating template:', err);
			throw err;
		}
	}

</script>

<!-- Preview Modal -->
<TemplateSyntaxPreview 
	bind:show={showPreview}
	templateContent={findingsConfig.template_content}
	on:close={() => showPreview = false}
/>

<style>
	.range-slider {
		-webkit-appearance: none;
		appearance: none;
		background: linear-gradient(to right, rgba(168, 85, 247, 0.8) 0%, rgba(168, 85, 247, 0.8) 50%, rgba(255, 255, 255, 0.1) 50%, rgba(255, 255, 255, 0.1) 100%);
		outline: none;
		border-radius: 8px;
		height: 8px;
	}

	.range-slider::-webkit-slider-thumb {
		-webkit-appearance: none;
		appearance: none;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: linear-gradient(135deg, #a855f7, #8b5cf6);
		cursor: pointer;
		border: 2px solid rgba(255, 255, 255, 0.2);
		box-shadow: 0 2px 8px rgba(168, 85, 247, 0.4);
		transition: all 0.2s ease;
	}

	.range-slider::-webkit-slider-thumb:hover {
		transform: scale(1.1);
		box-shadow: 0 4px 12px rgba(168, 85, 247, 0.6);
	}

	.range-slider::-moz-range-thumb {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: linear-gradient(135deg, #a855f7, #8b5cf6);
		cursor: pointer;
		border: 2px solid rgba(255, 255, 255, 0.2);
		box-shadow: 0 2px 8px rgba(168, 85, 247, 0.4);
		transition: all 0.2s ease;
	}

	.range-slider::-moz-range-thumb:hover {
		transform: scale(1.1);
		box-shadow: 0 4px 12px rgba(168, 85, 247, 0.6);
	}

	.range-slider::-moz-range-track {
		background: rgba(255, 255, 255, 0.1);
		border-radius: 8px;
		height: 8px;
	}

	.range-slider::-moz-range-progress {
		background: rgba(168, 85, 247, 0.8);
		border-radius: 8px;
		height: 8px;
	}
</style>

<div class="max-w-6xl mx-auto space-y-6 py-2">
	<!-- Header with gradient -->
	<div class="flex items-center justify-between mb-6">
		<div>
			<h2 class="text-3xl font-bold bg-gradient-to-r from-emerald-400 to-teal-400 bg-clip-text text-transparent">FINDINGS Configuration</h2>
			<p class="text-sm text-gray-400 mt-2 flex items-center gap-2">
				<svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
				</svg>
				Configure the FINDINGS section template content and generation settings
			</p>
		</div>
	</div>

	<div class="space-y-6">
		<!-- Template Content with Style Cards -->
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-teal-500/30 transition-all duration-300">
			<div class="flex items-center justify-between mb-6">
				<div class="flex items-center gap-3">
					<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-teal-600 shadow-lg shadow-teal-500/30">
						<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
						</svg>
					</div>
					<h3 class="text-lg font-bold text-white uppercase tracking-wider">Template Content</h3>
				</div>
				{#if findingsConfig.content_style}
					<button
						type="button"
						onclick={generateWithAI}
						disabled={generating}
						class="px-4 py-2 bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 disabled:from-gray-600 disabled:to-gray-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg shadow-lg hover:shadow-purple-500/30 transition-all duration-200 flex items-center gap-2 text-sm"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
						</svg>
						{generating ? 'Generating...' : 'AI Regenerate'}
					</button>
				{/if}
			</div>

			<!-- Content Style Cards -->
			<div class="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-6">
				{#each styleOptions as style}
					<button
						type="button"
						onclick={() => handleStyleChange(style.id)}
						class="relative p-2.5 rounded-lg border-2 transition-all duration-300 text-left group {
							findingsConfig.content_style === style.id 
								? 'bg-gradient-to-br from-purple-500/20 to-purple-600/10 border-purple-500 shadow-lg shadow-purple-500/30 scale-[1.02]' 
								: 'bg-black/20 border-white/10 hover:border-purple-400/50 hover:bg-black/30 hover:scale-[1.02]'
						}"
					>
						<!-- Selection Indicator -->
						{#if findingsConfig.content_style === style.id}
							<div class="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gradient-to-br from-purple-500 to-purple-600 rounded-full flex items-center justify-center shadow-lg">
								<svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
								</svg>
							</div>
						{/if}
						
						<div class="flex flex-col items-center text-center gap-1">
							<div class="text-2xl mb-0.5 transition-transform duration-300 {
								findingsConfig.content_style === style.id ? 'scale-110' : 'group-hover:scale-110'
							}">{style.icon}</div>
							<div class="font-bold text-xs {
								findingsConfig.content_style === style.id ? 'text-purple-200' : 'text-white group-hover:text-purple-300'
							}">{style.label}</div>
							<div class="text-[10px] leading-tight {
								findingsConfig.content_style === style.id ? 'text-purple-300/80' : 'text-gray-400 group-hover:text-gray-300'
							}">{style.description}</div>
						</div>
					</button>
				{/each}
			</div>

			{#if findingsConfig.content_style}
				<!-- Template Content Editor -->
				<div class="space-y-3">
					<textarea
						bind:value={findingsConfig.template_content}
						oninput={findingsConfig.content_style === 'structured_template' ? handleTemplateContentChange : handleChange}
						rows="12"
						placeholder="Enter your findings template content here..."
						class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all resize-y font-mono hover:border-white/20 min-h-[200px]"
						key={findingsConfig.content_style}
					></textarea>
					
					{#if findingsConfig.content_style === 'structured_template' && findingsConfig.template_content}
						<button
							onclick={() => showPreview = true}
							class="mt-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded-lg transition-colors flex items-center gap-2"
						>
							<span>👁️</span> Preview Template Syntax
						</button>
					{/if}

					<!-- Validation Panel for Structured Templates -->
					{#if findingsConfig.content_style === 'structured_template' && findingsConfig.template_content}
						{#await validateTemplate(findingsConfig.template_content) then validation}
							{@const hasErrors = validation.errors?.length > 0}
							{@const hasWarnings = validation.warnings?.length > 0}
							{@const isValid = !hasErrors && !hasWarnings}
							{@const hasOnlyWarnings = hasWarnings && !hasErrors}
							{@const validationClass = hasErrors ? 'bg-red-900/20 border-red-500/30' : (isValid ? 'bg-green-900/20 border-green-500/30' : 'bg-yellow-900/20 border-yellow-500/30')}
							<div class="mt-4 p-4 rounded-lg border {validationClass}">
								{#if hasErrors}
									<div class="space-y-2">
										<h4 class="text-sm font-semibold text-red-300 flex items-center gap-2">
											❌ Template Errors ({validation.errors.length})
										</h4>
										{#each validation.errors as error}
											<p class="text-xs text-red-400">• {error.message}</p>
										{/each}
									</div>
								{/if}
								
								{#if hasWarnings}
									<div class="mt-3 space-y-2">
										<h4 class="text-sm font-semibold text-yellow-300 flex items-center gap-2">
											⚠️ Suggestions ({validation.warnings.length})
										</h4>
										{#each validation.warnings as warning}
											<p class="text-xs text-yellow-400">• {warning.message}</p>
										{/each}
									</div>
								{/if}
								
							{#if validation.valid && !hasErrors}
								<div class="space-y-2">
									<div class="flex items-center gap-2 text-green-300">
										<span class="text-lg">✅</span>
										<strong class="text-sm">Template Valid</strong>
									</div>
									
									{#if validation.placeholders?.variables?.length > 0}
										<div class="mt-2">
											<p class="text-xs text-gray-400 font-semibold mb-1">Variables ({validation.stats.variables}):</p>
											<div class="flex flex-wrap gap-1">
												{#each validation.placeholders.variables as variable}
													<span class="text-xs px-2 py-0.5 bg-green-900/30 text-green-300 rounded border border-green-500/30">
														~{variable}~
													</span>
												{/each}
											</div>
										</div>
									{/if}
									
									{#if validation.stats.measurements > 0}
										<p class="text-xs text-gray-400">
											<strong>Measurements:</strong> {validation.stats.measurements} (xxx)
										</p>
									{/if}
								</div>
							{/if}
							</div>
						{:catch error}
							<div class="mt-4 p-4 bg-red-900/20 border border-red-500/30 rounded-lg">
								<p class="text-xs text-red-400">Validation error</p>
							</div>
						{/await}
					{/if}
					
					<!-- Context-aware help tip -->
					<div class="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
						<p class="text-xs text-blue-200 flex items-start gap-2">
							<svg class="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							<span>
							{#if findingsConfig.content_style === 'structured_template'}
								Pre-written template with placeholders. Use xxx for measurements, {'{VAR}'} for dynamic values, // for actionable AI instructions, and [option1/option2] for alternatives.
							{:else if findingsConfig.content_style === 'guided_template'}
								Use // comments for guidance. Example: "The lungs are clear.\n// Assess: consolidation, masses, nodules"
							{:else if findingsConfig.content_style === 'checklist'}
								Use bullet points. Example: "- Lungs (parenchyma, nodules)\n- Pleural spaces (effusions)"
							{:else}
								Write complete normal findings. AI will replace relevant sections when abnormalities are found.
							{/if}
							</span>
						</p>
					</div>
				</div>
			{:else}
				<!-- Prompt to select a style -->
				<div class="py-12 text-center">
					<div class="text-4xl mb-3">👆</div>
					<p class="text-gray-400 text-sm">Select a content style above to begin</p>
				</div>
			{/if}
		</section>

		<!-- Writing Style Section (always visible) -->
		{#if findingsConfig.content_style}
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-purple-500/30 transition-all duration-300">
			<div class="flex items-center justify-between mb-6">
				<div class="flex items-center gap-3">
					<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-purple-600 shadow-lg shadow-purple-500/30">
						<span class="text-xl">✨</span>
					</div>
					<h3 class="text-lg font-bold text-white uppercase tracking-wider">Writing Style</h3>
				</div>
				{#if findingsConfig.content_style !== 'structured_template'}
					<button 
						type="button"
						onclick={resetToDefaults}
						class="px-3 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-all"
					>
						Reset to Defaults
					</button>
				{/if}
			</div>
			
			<!-- Preset Cards (hidden for structured templates) -->
			{#if showFullStyleControls}
				<StylePresetCards 
					section="findings"
					bind:selectedPresetId={selectedFindingsPreset}
					bind:advanced={findingsConfig.advanced}
					on:presetChange={handlePresetChange}
				/>
			{/if}
			
			<!-- Granular Controls -->
			<div class="mt-6">
				{#if showFullStyleControls}
					<!-- Show full StyleGranularControls component for normal styles -->
					<StyleGranularControls 
						section="findings"
						bind:advanced={findingsConfig.advanced}
						findingsContentStyle={findingsConfig.content_style}
						on:fieldChange={() => { selectedFindingsPreset = 'custom'; handleChange(); }}
					/>
				{:else}
					<!-- Warning banner for structured templates -->
					<div class="flex items-start gap-3 rounded-lg border border-blue-500/30 bg-blue-900/20 p-4">
						<div class="text-xl">ℹ️</div>
						<div class="text-sm text-blue-300">
							<strong>Writing Style Options Disabled</strong>
							<p class="mt-1 text-xs text-gray-400">
								Writing style options are disabled because your template structure is pre-defined. 
								The template text will be preserved exactly as written. Fine-tuning instructions 
								are not available for structured templates—use inline // instructions in your 
								template content instead.
							</p>
						</div>
					</div>
				{/if}
			</div>
		</section>
		{/if}
	</div>
</div>

