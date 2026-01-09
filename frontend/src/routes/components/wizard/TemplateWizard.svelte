<script>
	import { createEventDispatcher } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';
	import Step1_ScanInfo from './Step1_ScanInfo.svelte';
	import Step2_ChooseMethod from './Step2_ChooseMethod.svelte';
	import Step3_SectionBuilder from './Step3_SectionBuilder.svelte';
	import Step4_FindingsSetup from './Step4_FindingsSetup.svelte';
	import Step5_ImpressionSetup from './Step5_ImpressionSetup.svelte';
	import Step6_Review from './Step6_Review.svelte';
	import Step7_Save from './Step7_Save.svelte';
	import Step3_ReportInput from './from-reports/Step3_ReportInput.svelte';
	import Step4_Analysis from './from-reports/Step4_Analysis.svelte';

	const dispatch = createEventDispatcher();

	export let onClose = () => {};
	export let editingTemplate = null; // Template being edited

	let currentStep = 1;
	let creationMethod = null; // 'wizard' or 'from_reports'
	let isEditMode = false;

	// Step 1: Scan Information
	let scanType = '';
	let contrast = '';
	let contrastOther = '';
	let contrastPhases = [];
	let protocolDetails = '';

	// Step 2: Method selection (handled by Step2 component)

	// Step 3: Section Builder (wizard) or Report Input (from_reports)
	let sections = {
		comparison: { included: false, has_input_field: true },
		technique: { included: false, has_input_field: false },
		limitations: { included: false, has_input_field: true },
		clinical_history: { include_in_output: false }
	};
	let sectionOrder = null; // Will be set from Step3

	// Step 3 (from_reports): Reports
	let reports = [];

	// Step 4: FINDINGS Setup (wizard) or Analysis (from_reports)
	let findingsConfig = {
		content_style: null,
		template_content: '',
		advanced: {
			instructions: '',
			writing_style: 'prose', // concise or prose
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
		}
	};

	// Step 4 (from_reports): Analysis results
	let analysisResult = null;

	// Step 5: IMPRESSION Setup
	let impressionConfig = {
		display_name: 'IMPRESSION',
		advanced: {
			instructions: '',
			verbosity_style: 'prose',
			format: 'prose',
			differential_approach: 'if_needed',
			recommendations: {
				specialist_referral: true,
				further_workup: true,
				imaging_followup: false,
				clinical_correlation: false
			}
		}
	};

	// Step 6: Review (shared)

	// Step 7: Save
	let templateName = '';
	let description = '';
	let tags = [];
	let isPinned = false;
	let globalCustomInstructions = '';
	let templateConfig = {}; // Initialize empty config

	function nextStep() {
		if (currentStep === 1 && (!scanType || !contrast)) {
			return; // Validation
		}
		if (currentStep === 2 && !creationMethod) {
			return; // Validation
		}
		if (currentStep === 3 && creationMethod === 'wizard') {
			// Section builder validation
			if (!sections.comparison.included && !sections.technique.included && !sections.limitations.included) {
				// At least one optional section should be included, or proceed anyway
			}
		}
		if (currentStep === 4 && creationMethod === 'wizard' && !findingsConfig.content_style) {
			return; // Must select content style
		}
		if (currentStep === 5 && creationMethod === 'wizard') {
			// Impression setup - no validation needed
		}
		if (currentStep === 6) {
			// Review - no validation needed
		}
		if (currentStep === 7) {
			// Save - handled by Step7 component
			return;
		}
		currentStep++;
	}

	function prevStep() {
		if (currentStep > 1) {
			currentStep--;
		}
	}

	function handleMethodSelected(event) {
		// Svelte passes event.detail as the first argument when using on:eventName
		const method = typeof event === 'string' ? event : (event?.detail || event);
		creationMethod = method;
		// Advance to next step - creationMethod is set, so validation will pass
		currentStep = 3;
	}

	function handleAnalysisComplete(result) {
		analysisResult = result;
		// Populate config from analysis result
		if (result.template_config) {
			const config = result.template_config;
			// Update scan info if needed
			if (config.scan_type) scanType = config.scan_type;
			if (config.protocol_details) protocolDetails = config.protocol_details;
			
			// Parse contrast (handle both old and new formats)
			const contrastValue = config.contrast || '';
			contrastPhases = config.contrast_phases || [];
			
			if (contrastValue === 'No contrast' || contrastValue === 'Non-contrast') {
				contrast = 'no_contrast';
				contrastPhases = [];
			} else if (contrastValue.startsWith('With contrast') || contrastValue === 'With IV contrast') {
				contrast = 'with_contrast';
				// If contrast_phases is not in config, try to parse from string
				if (!contrastPhases.length && contrastValue.includes('(') && contrastValue.includes(')')) {
					const phasesStr = contrastValue.match(/\((.*?)\)/)?.[1] || '';
					contrastPhases = [];
					if (phasesStr.includes('Pre-contrast')) contrastPhases.push('pre');
					if (phasesStr.includes('Arterial')) contrastPhases.push('arterial');
					if (phasesStr.includes('Portal venous')) contrastPhases.push('portal_venous');
					if (phasesStr.includes('Delayed')) contrastPhases.push('delayed');
					if (phasesStr.includes('Oral')) contrastPhases.push('oral');
				}
			} else if (contrastValue === 'Arterial phase') {
				contrast = 'with_contrast';
				contrastPhases = ['arterial'];
			} else if (contrastValue === 'Portal venous') {
				contrast = 'with_contrast';
				contrastPhases = ['portal_venous'];
			} else if (contrastValue && contrastValue !== 'Not specified') {
				contrast = 'with_contrast';
				contrastPhases = [];
			}
			
			// Extract sections
			if (config.sections) {
				config.sections.forEach(section => {
					if (section.name === 'COMPARISON') {
						sections.comparison.included = section.included || false;
						sections.comparison.has_input_field = section.has_input_field !== undefined ? section.has_input_field : true;
					} else if (section.name === 'TECHNIQUE') {
						sections.technique.included = section.included || false;
						sections.technique.has_input_field = section.has_input_field !== undefined ? section.has_input_field : false;
					} else if (section.name === 'LIMITATIONS') {
						sections.limitations.included = section.included || false;
						sections.limitations.has_input_field = section.has_input_field !== undefined ? section.has_input_field : true;
					} else if (section.name === 'FINDINGS') {
						findingsConfig.content_style = section.content_style || 'guided_template';
						findingsConfig.template_content = section.template_content || '';
						if (section.advanced) {
							findingsConfig.advanced = { ...findingsConfig.advanced, ...section.advanced };
						}
					} else if (section.name === 'IMPRESSION') {
						impressionConfig.display_name = section.display_name || 'IMPRESSION';
						if (section.advanced) {
							impressionConfig.advanced = { ...impressionConfig.advanced, ...section.advanced };
						}
					}
				});
			}
			
			// Update clinical history setting
			if (config.clinical_history) {
				sections.clinical_history.include_in_output = config.clinical_history.include_in_output || false;
			}
		}
		nextStep(); // Move to review step
	}

	function handleSaveComplete() {
		dispatch('templateCreated');
		onClose();
	}

	// Save function for edit mode - can be called from any step
	let saving = false;
	async function saveFromAnyStep() {
		if (!templateName.trim() || saving) {
			return;
		}

		saving = true;
		try {
			const config = buildTemplateConfig();
			const payload = {
				name: templateName,
				description: description || null,
				tags: tags,
				template_config: config,
				is_pinned: isPinned
			};

			const response = await fetch(`${API_URL}/api/templates/${editingTemplate.id}`, {
				method: 'PUT',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify(payload)
			});

			const data = await response.json();
			if (data.success) {
				dispatch('templateCreated');
				onClose();
			} else {
				alert(data.error || 'Failed to update template');
			}
		} catch (err) {
			console.error('Error saving template:', err);
			alert('Error updating template. Please try again.');
		} finally {
			saving = false;
		}
	}

	// Initialize from editingTemplate if provided (only once)
	let initializedFromTemplate = false;
	$: if (editingTemplate && editingTemplate.template_config && !initializedFromTemplate) {
		isEditMode = true;
		initializedFromTemplate = true;
		const config = editingTemplate.template_config;
		
		// Set scan info
		scanType = config.scan_type || '';
		protocolDetails = config.protocol_details || '';
		
		// Parse contrast (handle both old and new formats)
		const contrastValue = config.contrast || '';
		contrastPhases = config.contrast_phases || [];
		
		if (contrastValue === 'No contrast' || contrastValue === 'Non-contrast') {
			contrast = 'no_contrast';
			contrastPhases = [];
		} else if (contrastValue.startsWith('With contrast') || contrastValue === 'With IV contrast') {
			contrast = 'with_contrast';
			// If contrast_phases is not in config, try to parse from string
			if (!contrastPhases.length && contrastValue.includes('(') && contrastValue.includes(')')) {
				const phasesStr = contrastValue.match(/\((.*?)\)/)?.[1] || '';
				contrastPhases = [];
				if (phasesStr.includes('Pre-contrast')) contrastPhases.push('pre');
				if (phasesStr.includes('Arterial')) contrastPhases.push('arterial');
				if (phasesStr.includes('Portal venous')) contrastPhases.push('portal_venous');
				if (phasesStr.includes('Delayed')) contrastPhases.push('delayed');
				if (phasesStr.includes('Oral')) contrastPhases.push('oral');
			}
		} else if (contrastValue === 'Arterial phase') {
			// Legacy format - convert to new format
			contrast = 'with_contrast';
			contrastPhases = ['arterial'];
		} else if (contrastValue === 'Portal venous') {
			// Legacy format - convert to new format
			contrast = 'with_contrast';
			contrastPhases = ['portal_venous'];
		} else if (contrastValue && contrastValue !== 'Not specified') {
			// Old custom format - default to with_contrast
			contrast = 'with_contrast';
			contrastPhases = [];
			contrastOther = contrastValue;
		}

		// Set creation method from source
		creationMethod = config.source || 'wizard';
		
		// Skip to step 3 if editing (skip method selection)
		currentStep = 3;

		// Parse sections
		if (config.sections) {
			config.sections.forEach(section => {
				if (section.name === 'COMPARISON') {
					sections.comparison.included = section.included || false;
				} else if (section.name === 'TECHNIQUE') {
					sections.technique.included = section.included || false;
				} else if (section.name === 'LIMITATIONS') {
					sections.limitations.included = section.included || false;
				} else if (section.name === 'FINDINGS') {
					findingsConfig.content_style = section.content_style || null;
					findingsConfig.template_content = section.template_content || '';
					if (section.advanced) {
						findingsConfig.advanced = { ...findingsConfig.advanced, ...section.advanced };
					}
				} else if (section.name === 'IMPRESSION') {
					impressionConfig.display_name = section.display_name || 'IMPRESSION';
					if (section.advanced) {
						impressionConfig.advanced = { ...impressionConfig.advanced, ...section.advanced };
					}
				}
			});

			// Extract section order - preserve order and include required flags/descriptions
			const requiredSections = ['CLINICAL_HISTORY', 'FINDINGS', 'IMPRESSION'];
			const idMap = {
				'CLINICAL_HISTORY': 'clinical_history',
				'COMPARISON': 'comparison',
				'TECHNIQUE': 'technique',
				'LIMITATIONS': 'limitations',
				'FINDINGS': 'findings',
				'IMPRESSION': 'impression'
			};
			const descriptionMap = {
				'clinical_history': 'Input field',
				'comparison': 'Optional comparison',
				'technique': 'Auto-generated',
				'limitations': 'Optional limitations',
				'findings': 'Main findings',
				'impression': 'Auto-generated'
			};
			
			const ordered = config.sections
				.filter(s => s.order !== undefined)
				.sort((a, b) => a.order - b.order)
				.map(s => {
					const id = idMap[s.name] || s.name.toLowerCase();
					return { 
						id,
						name: s.name,
						required: requiredSections.includes(s.name),
						description: descriptionMap[id] || ''
					};
				});
			
			// Ensure all sections are present (add missing ones at the end)
			if (ordered.length > 0) {
				const existingIds = new Set(ordered.map(s => s.id));
				const allSectionIds = ['clinical_history', 'comparison', 'technique', 'limitations', 'findings', 'impression'];
				const missingIds = allSectionIds.filter(id => !existingIds.has(id));
				
				if (missingIds.length > 0) {
					const defaultOrder = [
						{ id: 'clinical_history', name: 'CLINICAL HISTORY', required: true, description: 'Manual input' },
						{ id: 'comparison', name: 'COMPARISON', required: false, description: 'Optional' },
						{ id: 'technique', name: 'TECHNIQUE', required: false, description: 'Optional' },
						{ id: 'limitations', name: 'LIMITATIONS', required: false, description: 'Optional' },
						{ id: 'findings', name: 'FINDINGS', required: true, description: 'Manual input' },
						{ id: 'impression', name: 'IMPRESSION', required: true, description: 'Auto-generated' }
					];
					const missing = missingIds.map(id => defaultOrder.find(d => d.id === id)).filter(Boolean);
					sectionOrder = [...ordered, ...missing];
				} else {
					// All sections present - use order exactly as parsed
					sectionOrder = ordered;
				}
			}
		}

		// Clinical history setting
		if (config.clinical_history) {
			sections.clinical_history.include_in_output = config.clinical_history.include_in_output || false;
		}

		// Set metadata
		templateName = editingTemplate.name || '';
		description = editingTemplate.description || '';
		tags = [...(editingTemplate.tags || [])];
		isPinned = editingTemplate.is_pinned || false;
		globalCustomInstructions = config.global_custom_instructions || '';
	}

	$: totalSteps = creationMethod === 'from_reports' ? 6 : 7;
	$: stepProgress = (currentStep / totalSteps) * 100;

	// Make templateConfig reactive so changes are captured when any dependency changes
	$: {
		templateConfig = buildTemplateConfig();
		// Debug: log when config changes (remove in production)
		if (currentStep === 7) {
			console.log('Template config updated:', templateConfig);
		}
	}

	function buildTemplateConfig() {
		// If we have analysis result with config, use it directly (from_reports pathway)
		if (analysisResult && analysisResult.template_config) {
			return analysisResult.template_config;
		}
		
		// Otherwise build from wizard inputs
		// Handle contrast value - convert to readable string with phases support
		let finalContrast = '';
		let finalContrastPhases = [];
		
		if (contrast === 'no_contrast') {
			finalContrast = 'Non-contrast';
			finalContrastPhases = [];
		} else if (contrast === 'with_contrast') {
			// Build readable string from phases
			const phaseLabels = {
				'pre': 'Pre-contrast',
				'arterial': 'Arterial',
				'portal_venous': 'Portal venous',
				'delayed': 'Delayed',
				'oral': 'Oral'
			};
			
			if (contrastPhases.length > 0) {
				const phases = contrastPhases.map(p => phaseLabels[p] || p).join(', ');
				finalContrast = `With contrast (${phases})`;
				finalContrastPhases = contrastPhases;
			} else {
				finalContrast = 'With contrast';
				finalContrastPhases = [];
			}
		} else if (contrast === 'other') {
			// Legacy support for "other" option
			finalContrast = contrastOther || 'Other';
			finalContrastPhases = [];
		} else if (!contrast) {
			finalContrast = '';
			finalContrastPhases = [];
		}
		
		const configSections = [];
		
		// Use sectionOrder if available, otherwise use default order
		const orderToUse = sectionOrder || [
			{ id: 'clinical_history', name: 'CLINICAL HISTORY' },
			{ id: 'comparison', name: 'COMPARISON' },
			{ id: 'technique', name: 'TECHNIQUE' },
			{ id: 'limitations', name: 'LIMITATIONS' },
			{ id: 'findings', name: 'FINDINGS' },
			{ id: 'impression', name: 'IMPRESSION' }
		];
		
		let order = 1;
		
		// Build sections in the specified order
		// CRITICAL: Save ALL sections with order, even if optional sections aren't included
		// This preserves the order even for non-included sections
		for (const sectionItem of orderToUse) {
			const sectionId = sectionItem.id;
			const sectionName = sectionItem.name;
			
			if (sectionId === 'clinical_history') {
				// Always included (required)
				configSections.push({
					order: order++,
					name: 'CLINICAL_HISTORY',
					included: true,
					has_input_field: true,
					is_required: true,
					generation_mode: 'passthrough'
				});
			} else if (sectionId === 'comparison') {
				// Save with order even if not included - preserves order
				if (sections.comparison.included) {
					configSections.push({
						order: order++,
						name: 'COMPARISON',
						included: true,
						has_input_field: sections.comparison.has_input_field,
						generation_mode: sections.comparison.has_input_field ? 'hybrid' : 'auto_generated'
					});
				} else {
					// Save as not included but preserve order position
					configSections.push({
						order: order++,
						name: 'COMPARISON',
						included: false
					});
				}
			} else if (sectionId === 'technique') {
				// Save with order even if not included - preserves order
				if (sections.technique.included) {
					configSections.push({
						order: order++,
						name: 'TECHNIQUE',
						included: true,
						has_input_field: sections.technique.has_input_field,
						generation_mode: sections.technique.has_input_field ? 'hybrid' : 'auto_generated'
					});
				} else {
					// Save as not included but preserve order position
					configSections.push({
						order: order++,
						name: 'TECHNIQUE',
						included: false
					});
				}
			} else if (sectionId === 'limitations') {
				// Save with order even if not included - preserves order
				if (sections.limitations.included) {
					configSections.push({
						order: order++,
						name: 'LIMITATIONS',
						included: true,
						has_input_field: sections.limitations.has_input_field,
						generation_mode: sections.limitations.has_input_field ? 'hybrid' : 'auto_generated'
					});
				} else {
					// Save as not included but preserve order position
					configSections.push({
						order: order++,
						name: 'LIMITATIONS',
						included: false
					});
				}
			} else if (sectionId === 'findings') {
				// Always included (required)
				configSections.push({
					order: order++,
					name: 'FINDINGS',
					included: true,
					has_input_field: true,
					is_required: true,
					generation_mode: 'template_based',
					content_style: findingsConfig.content_style,
					template_content: findingsConfig.template_content,
					advanced: findingsConfig.advanced
				});
			} else if (sectionId === 'impression') {
				// Always included (required)
				configSections.push({
					order: order++,
					name: 'IMPRESSION',
					display_name: impressionConfig.display_name,
					included: true,
					has_input_field: false,
					generation_mode: 'auto_generated',
					advanced: impressionConfig.advanced
				});
			}
		}

		return {
			scan_type: scanType,
			contrast: finalContrast,
			contrast_phases: finalContrastPhases,
			protocol_details: protocolDetails,
			language: 'british',
			clinical_history: {
				required_input: true,
				include_in_output: sections.clinical_history.include_in_output
			},
			sections: configSections,
			source: creationMethod || 'wizard',
			source_reports: creationMethod === 'from_reports' ? reports : [],
			global_custom_instructions: globalCustomInstructions || ''
		};
	}
</script>

<div 
	class="fixed inset-0 bg-black/80 backdrop-blur-sm overflow-y-auto"
	style="z-index: 9999;"
	role="dialog"
	aria-modal="true"
>
	<div class="min-h-full flex items-center justify-center p-4 py-8">
		<div class="card-dark w-full max-w-4xl">
			<!-- Header -->
			<div class="flex items-center justify-between mb-6 pb-4 border-b border-white/10">
				<h2 class="text-2xl font-bold text-white">{isEditMode ? 'Edit Template' : 'Create Template'}</h2>
				<button
					onclick={onClose}
					class="btn-ghost text-gray-400 hover:text-white"
				>
					✕
				</button>
			</div>

			<!-- Progress Bar -->
			<div class="mb-6">
				<div class="flex items-center justify-between mb-2 text-sm text-gray-400">
					<span>Step {currentStep} of {totalSteps}</span>
					<span>{Math.round(stepProgress)}%</span>
				</div>
				<div class="w-full bg-white/10 rounded-full h-2">
					<div
						class="bg-purple-600 h-2 rounded-full transition-all duration-300"
						style="width: {stepProgress}%"
					></div>
				</div>
			</div>

			<!-- Step Content -->
			<div class="min-h-[400px]">
			{#if currentStep === 1}
				<Step1_ScanInfo
					bind:scanType
					bind:contrast
					bind:contrastOther
					bind:contrastPhases
					bind:protocolDetails
					on:next={nextStep}
				/>
			{:else if currentStep === 2 && !isEditMode}
				<Step2_ChooseMethod
					on:methodSelected={handleMethodSelected}
				/>
			{:else if currentStep === 2 && isEditMode}
				<!-- Skip method selection in edit mode -->
				<div class="text-center py-12 text-gray-400">
					<p>Loading...</p>
				</div>
			{:else if currentStep === 3}
				{#if creationMethod === 'wizard'}
					<Step3_SectionBuilder
						bind:sections
						initialSectionOrder={sectionOrder}
						on:next={(e) => {
							if (e.detail) {
								sectionOrder = e.detail;
							}
							nextStep();
						}}
					/>
				{:else if creationMethod === 'from_reports'}
					<Step3_ReportInput
						bind:reports
						scanType={scanType}
						contrast={contrast}
						protocolDetails={protocolDetails}
						on:next={nextStep}
					/>
				{:else}
					<div class="text-center py-12 text-gray-400">
						<p>Loading...</p>
					</div>
				{/if}
			{:else if currentStep === 4}
				{#if creationMethod === 'wizard'}
					<Step4_FindingsSetup
						bind:findingsConfig
						scanType={scanType}
						contrast={contrast}
						protocolDetails={protocolDetails}
						on:next={nextStep}
					/>
				{:else if creationMethod === 'from_reports'}
					<Step4_Analysis
						reports={reports}
						scanType={scanType}
						contrast={contrast}
						protocolDetails={protocolDetails}
						on:analysisComplete={handleAnalysisComplete}
					/>
				{/if}
			{:else if currentStep === 5 && creationMethod === 'wizard'}
				<Step5_ImpressionSetup
					bind:impressionConfig
					on:next={nextStep}
				/>
			{:else if currentStep === 6}
				<Step6_Review
					scanType={scanType}
					contrast={contrast}
					contrastPhases={contrastPhases}
					protocolDetails={protocolDetails}
					creationMethod={creationMethod}
					sections={sections}
					findingsConfig={findingsConfig}
					impressionConfig={impressionConfig}
					analysisResult={analysisResult}
					on:next={nextStep}
				/>
			{:else if currentStep === 7}
				<Step7_Save
					bind:templateName
					bind:description
					bind:tags
					bind:isPinned
					bind:globalCustomInstructions
					templateConfig={templateConfig}
					editingTemplate={editingTemplate}
					on:saveComplete={handleSaveComplete}
				/>
			{/if}
			</div>

			<!-- Navigation -->
			{#if currentStep < 7}
				<div class="flex items-center justify-between mt-6 pt-4 border-t border-white/10">
					<button
						onclick={prevStep}
						disabled={currentStep === 1}
						class="btn-secondary"
						class:opacity-50={currentStep === 1}
						class:cursor-not-allowed={currentStep === 1}
					>
						← Previous
					</button>
					<div class="flex gap-2">
						{#if editingTemplate}
							<!-- Show save button on all steps when editing -->
							<button
								onclick={saveFromAnyStep}
								disabled={saving || !templateName.trim()}
								class="btn-primary"
								class:opacity-50={saving || !templateName.trim()}
							>
								{saving ? 'Saving...' : '💾 Save Changes'}
							</button>
						{/if}
						<button
							onclick={onClose}
							class="btn-ghost"
						>
							Cancel
						</button>
					</div>
				</div>
			{:else if currentStep === 7}
				<!-- Navigation for Step 7 (Save) - show Previous and Cancel -->
				<div class="flex items-center justify-between mt-6 pt-4 border-t border-white/10">
					<button
						onclick={prevStep}
						class="btn-secondary"
					>
						← Previous
					</button>
					<div class="flex gap-2">
						<button
							onclick={onClose}
							class="btn-ghost"
						>
							Cancel
						</button>
					</div>
				</div>
			{/if}
</div>
</div>
</div>

