<script>
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { settingsStore } from '$lib/stores/settings';
	import { tagsStore } from '$lib/stores/tags';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import { API_URL } from '$lib/config';
	
	// Tab components
	import QuickEditTab from './editor/QuickEditTab.svelte';
	import FindingsTab from './editor/FindingsTab.svelte';
	import ImpressionTab from './editor/ImpressionTab.svelte';

	export let editingTemplate = null;
	export let selectedModel = 'claude';
	export let cameFromTab = null;

	const dispatch = createEventDispatcher();

	let activeTab = 'quick';
	let hasUnsavedChanges = false;
	let autoSaveTimeout = null;
	let lastSaveTime = null;
	let autoSaving = false;

	// Template state
	let templateName = '';
	let description = '';
	let tags = [];
	let isPinned = false;
	let scanType = '';
	let contrast = '';
	let contrastOther = '';
	let contrastPhases = [];
	let protocolDetails = '';
	let globalCustomInstructions = '';
	let sections = {
		comparison: { included: false, has_input_field: true },
		technique: { included: false, has_input_field: false },
		limitations: { included: false, has_input_field: true },
		clinical_history: { include_in_output: false }
	};
	let sectionOrder = null;
	let findingsConfig = {
		content_style: null,
		template_content: '',
		// Store templates for each style
		style_templates: {
			normal_template: '',
			guided_template: '',
			checklist: '',
			headers: ''
		},
		advanced: {
			instructions: '',
			writing_style: 'prose', // concise or prose
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
			measurement_style: 'inline',
			negative_findings_style: 'grouped',
			descriptor_density: 'standard',
			paragraph_grouping: 'by_finding'
		}
	};
	let impressionConfig = {
		display_name: 'IMPRESSION',
		advanced: {
			instructions: '',
			verbosity_style: 'prose',
			impression_format: 'prose',
			differential_style: 'if_needed',
			comparison_terminology: 'measured',
			measurement_inclusion: 'key_only',
			incidental_handling: 'action_threshold',
		recommendations: {
			specialist_referral: true,
			further_workup: true,
			imaging_followup: false,
			clinical_correlation: false
		}
		}
	};

	// Tag management
	let tagInput = '';
	let tagInputElement = null; // Reference to input element
	let showTagSuggestions = false;
	let tagSuggestions = [];
	let selectedSuggestionIndex = -1;

	// Subscribe to tags store for autocomplete
	$: existingTags = $tagsStore.tags || [];
	
	// Subscribe to settings store for tag colors
	$: customTagColors = ($settingsStore.settings && $settingsStore.settings.tag_colors) || {};

	// Parse template_config into editor state
	function parseTemplateConfig(template) {
		if (!template || !template.template_config) {
			return;
		}

		const config = template.template_config;

		// Basic metadata
		templateName = template.name || '';
		description = template.description || '';
		tags = [...(template.tags || [])];
		isPinned = template.is_pinned || false;

		// Scan info
		scanType = config.scan_type || '';
		protocolDetails = config.protocol_details || '';
		globalCustomInstructions = config.global_custom_instructions || '';
		
		// Parse contrast (handle both old and new formats)
		const contrastValue = config.contrast || '';
		contrastPhases = config.contrast_phases || [];
		
		if (contrastValue === 'No contrast' || contrastValue === 'Non-contrast') {
			contrast = 'no_contrast';
			contrastPhases = [];
		} else if (contrastValue.startsWith('With contrast') || contrastValue === 'With IV contrast') {
			contrast = 'with_contrast';
			// Parse phases from string if present (backward compatibility)
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
			// Old format - convert to new
			contrast = 'with_contrast';
			contrastPhases = ['arterial'];
		} else if (contrastValue === 'Portal venous') {
			// Old format - convert to new
			contrast = 'with_contrast';
			contrastPhases = ['portal_venous'];
		} else if (contrastValue && contrastValue !== 'Not specified') {
			// Old custom format - default to with_contrast
			contrast = 'with_contrast';
			contrastPhases = [];
			// Store in protocol details instead
			if (!protocolDetails) {
				protocolDetails = `Contrast: ${contrastValue}`;
			}
		}

		// Parse sections
		if (config.sections) {
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
			
			// Get ordered sections from config - STRICTLY preserve order from config
			// Include ALL sections with order, even if included: false (to preserve order)
			const orderedFromConfig = config.sections
				.filter(s => s.order !== undefined)
				.sort((a, b) => a.order - b.order) // Sort by order property to get correct sequence
				.map(s => {
					const id = idMap[s.name] || s.name.toLowerCase();
					return { 
						id,
						name: s.name,
						required: requiredSections.includes(s.name),
						description: descriptionMap[id] || ''
					};
				});
			
			// Update sections state and configs from saved data
			// Process sections in order to ensure state matches saved config
			config.sections.forEach(section => {
				if (section.order === undefined) return; // Skip sections without order
				
				const id = idMap[section.name] || section.name.toLowerCase();
				
				if (id === 'comparison') {
					sections.comparison.included = section.included === true;
					sections.comparison.has_input_field = section.has_input_field !== undefined ? section.has_input_field : true;
				} else if (id === 'technique') {
					sections.technique.included = section.included === true;
					sections.technique.has_input_field = section.has_input_field !== undefined ? section.has_input_field : false;
				} else if (id === 'limitations') {
					sections.limitations.included = section.included === true;
					sections.limitations.has_input_field = section.has_input_field !== undefined ? section.has_input_field : true;
				} else if (id === 'findings') {
					findingsConfig.content_style = section.content_style || null;
					findingsConfig.template_content = section.template_content || '';
					// Load style templates if available
					if (section.style_templates) {
						findingsConfig.style_templates = { ...findingsConfig.style_templates, ...section.style_templates };
					}
					if (section.advanced) {
						findingsConfig.advanced = { ...findingsConfig.advanced, ...section.advanced };
					}
				} else if (id === 'impression') {
					impressionConfig.display_name = section.display_name || 'IMPRESSION';
					if (section.advanced) {
						impressionConfig.advanced = { ...impressionConfig.advanced, ...section.advanced };
						// Ensure recommendations object exists (for backward compatibility)
						if (!impressionConfig.advanced.recommendations || typeof impressionConfig.advanced.recommendations !== 'object') {
							impressionConfig.advanced.recommendations = {
								imaging_followup: true,
								clinical_correlation: true,
								further_workup: true,
								specialist_referral: true
							};
						}
						// Map old differential_style values to new ones (backward compatibility)
						if (impressionConfig.advanced.differential_style === 'when_uncertain') {
							impressionConfig.advanced.differential_style = 'if_needed';
						} else if (impressionConfig.advanced.differential_style === 'standard') {
							impressionConfig.advanced.differential_style = 'always_brief';
						}
					}
				}
			});
			
			// All sections should be present in a valid template config
			// If any are missing, add them at the end (shouldn't happen for valid templates)
			if (orderedFromConfig.length > 0) {
				const existingIds = new Set(orderedFromConfig.map(s => s.id));
				const allSectionIds = ['clinical_history', 'comparison', 'technique', 'limitations', 'findings', 'impression'];
				const missingIds = allSectionIds.filter(id => !existingIds.has(id));
				
				// Add missing sections at the end (preserve order of existing ones)
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
					sectionOrder = [...orderedFromConfig, ...missing];
				} else {
					// All sections present - use order exactly as parsed
					sectionOrder = orderedFromConfig;
				}
				
			} else {
				// Fallback to default order if no sections found (shouldn't happen)
				sectionOrder = [
					{ id: 'clinical_history', name: 'CLINICAL HISTORY', required: true, description: 'Manual input' },
					{ id: 'comparison', name: 'COMPARISON', required: false, description: 'Optional' },
					{ id: 'technique', name: 'TECHNIQUE', required: false, description: 'Optional' },
					{ id: 'limitations', name: 'LIMITATIONS', required: false, description: 'Optional' },
					{ id: 'findings', name: 'FINDINGS', required: true, description: 'Manual input' },
					{ id: 'impression', name: 'IMPRESSION', required: true, description: 'Auto-generated' }
				];
			}
		}

		// Clinical history setting
		if (config.clinical_history) {
			sections.clinical_history.include_in_output = config.clinical_history.include_in_output || false;
		}
	}

	// Build template_config from editor state
	function buildTemplateConfig() {
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
		} else if (!contrast) {
			finalContrast = '';
			finalContrastPhases = [];
		}

		const configSections = [];
		// CRITICAL: Use sectionOrder directly - it should always be set when editing
		// If it's null or empty, something went wrong - log warning but use default as fallback
		if (!sectionOrder || sectionOrder.length === 0) {
			console.warn('[buildTemplateConfig] sectionOrder is null or empty! This should not happen when editing a template.');
		}
		const orderToUse = sectionOrder && sectionOrder.length > 0 ? sectionOrder : [
			{ id: 'clinical_history', name: 'CLINICAL HISTORY' },
			{ id: 'comparison', name: 'COMPARISON' },
			{ id: 'technique', name: 'TECHNIQUE' },
			{ id: 'limitations', name: 'LIMITATIONS' },
			{ id: 'findings', name: 'FINDINGS' },
			{ id: 'impression', name: 'IMPRESSION' }
		];


		let order = 1;

		// CRITICAL: Iterate through ALL sections in orderToUse and save them ALL with their order
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
					style_templates: findingsConfig.style_templates,
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
			global_custom_instructions: globalCustomInstructions,
			language: 'british',
			clinical_history: {
				required_input: true,
				include_in_output: sections.clinical_history.include_in_output
			},
			sections: configSections,
			source: editingTemplate?.template_config?.source || 'wizard'
		};
	}

	// Initialize from template
	let lastTemplateId = null;
	$: if (editingTemplate) {
		if (editingTemplate.id !== lastTemplateId) {
			lastTemplateId = editingTemplate.id;
			parseTemplateConfig(editingTemplate);
			hasUnsavedChanges = false;
		}
	} else if (!editingTemplate && lastTemplateId !== null) {
		lastTemplateId = null;
		// Reset state
		templateName = '';
		description = '';
		tags = [];
		isPinned = false;
		scanType = '';
		contrast = '';
		contrastOther = '';
		contrastPhases = [];
		protocolDetails = '';
		sections = {
			comparison: { included: false, has_input_field: true },
			technique: { included: false, has_input_field: false },
			limitations: { included: false, has_input_field: true },
			clinical_history: { include_in_output: false }
		};
		sectionOrder = null;
		findingsConfig = {
			content_style: null,
			template_content: '',
			style_templates: {
				normal_template: '',
				guided_template: '',
				checklist: '',
				headers: ''
			},
			advanced: {
				instructions: '',
				verbosity: 1,
				format: 'prose',
				sentence_structure: 'standard'
			}
		};
		impressionConfig = {
			display_name: 'IMPRESSION',
			advanced: {
				instructions: '',
				verbosity_style: 'prose',
				impression_format: 'prose',
				differential_style: 'if_needed',
				comparison_terminology: 'measured',
				measurement_inclusion: 'key_only',
				incidental_handling: 'action_threshold',
		recommendations: {
			specialist_referral: true,
			further_workup: true,
			imaging_followup: false,
			clinical_correlation: false
		}
			}
		};
		hasUnsavedChanges = false;
	}

	// Tag management functions
	// Tags are now loaded via tagsStore - no need for separate loadExistingTags function

	function handleTagInput(event) {
		// Since tagInput is bound with bind:tagInput, it's already updated automatically
		// We just need to update suggestions based on the current tagInput value
		updateTagSuggestions();
	}
	
	let blurTimeout = null;
	
	function handleTagBlur() {
		// Hide suggestions when input loses focus
		// Use setTimeout to allow click events on suggestions to fire first
		// Clear any existing timeout to prevent race conditions
		if (blurTimeout) {
			clearTimeout(blurTimeout);
		}
		blurTimeout = setTimeout(() => {
			showTagSuggestions = false;
			blurTimeout = null;
		}, 200);
	}
	
	function cancelBlur() {
		// Cancel blur timeout when Enter is pressed or suggestion is selected
		if (blurTimeout) {
			clearTimeout(blurTimeout);
			blurTimeout = null;
		}
	}

	function updateTagSuggestions() {
		if (!tagInput || !tagInput.trim()) {
			tagSuggestions = [];
			showTagSuggestions = false;
			selectedSuggestionIndex = -1;
			return;
		}

		const inputLower = tagInput.toLowerCase();
		// Use existingTags from store (reactive)
		tagSuggestions = existingTags
			.filter(tag => tag.toLowerCase().includes(inputLower))
			.filter(tag => !tags.some(t => t.toLowerCase() === tag.toLowerCase()))
			.slice(0, 8);

		showTagSuggestions = tagSuggestions.length > 0;
		selectedSuggestionIndex = -1;
	}
	
	// Reactive statement to update suggestions when existingTags or tagInput changes
	$: if (tagInput && tagInput.trim() && existingTags.length > 0) {
		updateTagSuggestions();
	} else if (!tagInput || !tagInput.trim()) {
		// Hide suggestions when input is cleared
		tagSuggestions = [];
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
	}

	function handleTagKeydown(eventData) {
		// QuickEditTab now passes { event, value } object
		const data = eventData?.detail || eventData;
		const keyboardEvent = data?.event || data;
		const inputValue = data?.value;
		
		if (!keyboardEvent || !keyboardEvent.key) {
			return; // Invalid event
		}
		
		if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ',') {
			keyboardEvent.preventDefault();
			keyboardEvent.stopPropagation();
			// Cancel any pending blur timeout
			cancelBlur();
			// If a suggestion is selected, use it; otherwise use the input value
			// Use the passed value, or fall back to bound tagInput
			const valueToUse = inputValue ?? tagInput ?? '';
			if (showTagSuggestions && selectedSuggestionIndex >= 0 && tagSuggestions[selectedSuggestionIndex]) {
				addTag(tagSuggestions[selectedSuggestionIndex]);
			} else if (valueToUse && valueToUse.trim()) {
				addTag(valueToUse.trim());
			}
		} else if (keyboardEvent.key === 'ArrowDown') {
			keyboardEvent.preventDefault();
			if (showTagSuggestions && tagSuggestions.length > 0) {
				selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, tagSuggestions.length - 1);
			}
		} else if (keyboardEvent.key === 'ArrowUp') {
			keyboardEvent.preventDefault();
			selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1);
		} else if (keyboardEvent.key === 'Escape') {
			showTagSuggestions = false;
		}
	}

	function addTag(tagValue = null) {
		// Get the tag value - prefer passed value, then tagInput, then empty string
		const tagToAdd = tagValue || (tagInput && tagInput.trim()) || '';
		if (!tagToAdd || !tagToAdd.trim()) {
			return; // No tag to add
		}

		const trimmedTag = tagToAdd.trim();
		const existingTag = existingTags.find(
			t => t.toLowerCase() === trimmedTag.toLowerCase()
		);

		const finalTag = existingTag || trimmedTag;

		const isDuplicate = tags.some(t => t.toLowerCase() === finalTag.toLowerCase());
		if (isDuplicate) {
			return;
		}

		// Update tags array - this will automatically update QuickEditTab via binding
		tags = [...tags, finalTag];
		tagInput = '';
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
		hasUnsavedChanges = true;
		markChanged(); // Ensure change is marked
	}

	function removeTag(index) {
		tags = tags.filter((_, i) => i !== index);
		hasUnsavedChanges = true;
	}

	function selectSuggestion(suggestion) {
		cancelBlur();
		addTag(suggestion);
	}

	// Save template
	let saving = false;
	let error = null;

	// Auto-save functionality
	function scheduleAutoSave() {
		if (autoSaveTimeout) {
			clearTimeout(autoSaveTimeout);
		}
		
		// Auto-save after 2 seconds of inactivity
		autoSaveTimeout = setTimeout(() => {
			if (hasUnsavedChanges && !saving && !autoSaving) {
				autoSave();
			}
		}, 2000);
	}

	async function autoSave() {
		if (!templateName.trim() || !editingTemplate || autoSaving || saving) {
			return;
		}

		autoSaving = true;

		try {
			const templateConfig = buildTemplateConfig();
			const payload = {
				name: templateName,
				description: description || null,
				tags: tags,
				template_config: templateConfig,
				is_pinned: isPinned
			};

			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/templates/${editingTemplate.id}`, {
				method: 'PUT',
				headers,
				body: JSON.stringify(payload)
			});

			const data = await response.json();
			if (data.success) {
				if (data.template) {
					editingTemplate = data.template;
					// Don't call parseTemplateConfig to avoid overwriting user's current changes
				}
				hasUnsavedChanges = false;
				lastSaveTime = new Date();
			}
		} catch (err) {
			console.error('Auto-save error:', err);
			// Silent fail for auto-save
		} finally {
			autoSaving = false;
		}
	}

	// Cleanup on destroy
	onDestroy(() => {
		if (autoSaveTimeout) {
			clearTimeout(autoSaveTimeout);
		}
	});

	async function handleSave() {
		if (!templateName.trim()) {
			error = 'Template name is required';
			return;
		}

		if (!editingTemplate) {
			error = 'No template to save';
			return;
		}

		saving = true;
		error = null;

		try {
			const templateConfig = buildTemplateConfig();
			const payload = {
				name: templateName,
				description: description || null,
				tags: tags,
				template_config: templateConfig,
				is_pinned: isPinned
			};

			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/templates/${editingTemplate.id}`, {
				method: 'PUT',
				headers,
				body: JSON.stringify(payload)
			});

			const data = await response.json();
			if (data.success) {
				if (data.template) {
					editingTemplate = data.template;
					parseTemplateConfig(data.template);
				}
				hasUnsavedChanges = false;
				// Refresh tags after saving template (tags may have changed)
				await tagsStore.refreshTags();
				if (cameFromTab === 'templated') {
					dispatch('backToSource');
				} else {
					dispatch('saved');
				}
			} else {
				error = data.error || 'Failed to save template';
			}
		} catch (err) {
			console.error('Error saving template:', err);
			error = 'Error saving template. Please try again.';
		} finally {
			saving = false;
		}
	}

	function handleTabChange(newTab) {
		if (hasUnsavedChanges && activeTab !== newTab) {
			if (!confirm('You have unsaved changes. Do you want to continue?')) {
				return;
			}
		}
		activeTab = newTab;
	}

	// Mark changes when fields are modified
	function markChanged() {
		hasUnsavedChanges = true;
		scheduleAutoSave();
	}

	onMount(async () => {
		if (!$settingsStore.settings) {
			await settingsStore.loadSettings();
		}
		// Load tags from store
		if (!$tagsStore.tags || $tagsStore.tags.length === 0) {
			await tagsStore.loadTags();
		}
	});
</script>

<div class="p-6">
		<!-- Navigation and Header -->
		<div class="mb-8">
			<!-- Back Button - Separate line with more spacing -->
			<div class="mb-4">
				<button
					type="button"
					onclick={() => {
						if (cameFromTab === 'templated') {
							dispatch('backToSource');
						} else {
							dispatch('close');
						}
					}}
					class="text-gray-400 hover:text-white flex items-center gap-2 transition-colors group"
					title={cameFromTab === 'templated' ? 'Back to Personalised Reports' : 'Back to Templates'}
				>
					<svg class="w-5 h-5 group-hover:-translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
					</svg>
					<span class="text-sm font-medium">{cameFromTab === 'templated' ? 'Back to Reports' : 'Back to Templates'}</span>
				</button>
			</div>
			
			<!-- Title and Status Row -->
			<div class="flex items-start justify-between gap-4">
				<div class="flex-1 min-w-0">
					<h1 class="text-3xl font-bold text-white mb-2 break-words">
						Edit Template: <span class="bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">{templateName || 'Untitled'}</span>
					</h1>
					<!-- Auto-save indicator - Below title -->
					<div class="flex items-center gap-3">
						{#if autoSaving}
							<span class="flex items-center gap-1.5 text-sm text-blue-400">
								<svg class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
									<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
									<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
								</svg>
								<span>Saving...</span>
							</span>
						{:else if lastSaveTime}
							<span class="flex items-center gap-1.5 text-sm text-emerald-400">
								<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
									<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
								</svg>
								<span>Saved</span>
							</span>
						{:else if hasUnsavedChanges}
							<span class="flex items-center gap-1.5 text-sm text-gray-400">
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
								</svg>
								<span>Unsaved changes</span>
							</span>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<!-- Tabs -->
		<div class="mb-8 border-b border-white/10">
			<div class="flex items-center gap-1">
				<button
					type="button"
					onclick={() => handleTabChange('quick')}
					class="px-5 py-3 text-base font-medium transition-all relative {activeTab === 'quick' ? 'text-white' : 'text-gray-400 hover:text-gray-300'}"
				>
					<span class="relative z-10">Quick Edit</span>
					{#if activeTab === 'quick'}
						<div class="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-blue-500"></div>
					{/if}
				</button>
				<button
					type="button"
					onclick={() => handleTabChange('findings')}
					class="px-5 py-3 text-base font-medium transition-all relative {activeTab === 'findings' ? 'text-white' : 'text-gray-400 hover:text-gray-300'}"
				>
					<span class="relative z-10">Findings</span>
					{#if activeTab === 'findings'}
						<div class="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-blue-500"></div>
					{/if}
				</button>
				<button
					type="button"
					onclick={() => handleTabChange('impression')}
					class="px-5 py-3 text-base font-medium transition-all relative {activeTab === 'impression' ? 'text-white' : 'text-gray-400 hover:text-gray-300'}"
				>
					<span class="relative z-10">Impression</span>
					{#if activeTab === 'impression'}
						<div class="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-purple-500 to-blue-500"></div>
					{/if}
				</button>
			</div>
		</div>

		<!-- Tab Content -->
		<div class="min-h-[400px]">
			{#if activeTab === 'quick'}
				<QuickEditTab
					bind:templateName
					bind:description
					bind:tags
					bind:isPinned
					bind:scanType
					bind:contrast
					bind:contrastOther
					bind:contrastPhases
					bind:protocolDetails
					bind:sections
					bind:sectionOrder
					bind:tagInput
					bind:showTagSuggestions
					bind:tagSuggestions
					bind:selectedSuggestionIndex
					bind:globalCustomInstructions
					{customTagColors}
					on:tagInput={handleTagInput}
					on:tagKeydown={handleTagKeydown}
					on:tagBlur={(e) => handleTagBlur(e.detail || e)}
					on:selectSuggestion={(e) => selectSuggestion(e.detail)}
					on:removeTag={(e) => removeTag(e.detail)}
					on:switchTab={(e) => handleTabChange(e.detail)}
					on:change={markChanged}
				/>
			{:else if activeTab === 'findings'}
				<FindingsTab
					bind:findingsConfig
					{scanType}
					{contrast}
					{protocolDetails}
					onChange={markChanged}
				/>
			{:else if activeTab === 'impression'}
				<ImpressionTab
					bind:impressionConfig
					onChange={markChanged}
				/>
			{/if}
		</div>

		<!-- Error Message -->
		{#if error}
			<div class="mt-4 p-3 bg-red-600/20 border border-red-600/50 rounded text-red-300 text-sm">
				{error}
			</div>
		{/if}

		<!-- Actions -->
		<div class="flex gap-3 mt-6 pt-4 border-t border-white/10">
			<button
				type="button"
				onclick={() => {
					if (cameFromTab === 'templated') {
						dispatch('backToSource');
					} else {
						dispatch('close');
					}
				}}
				class="btn-secondary flex-1"
			>
				Cancel
			</button>
			<button
				type="button"
				onclick={handleSave}
				disabled={saving || !templateName.trim()}
				class="btn-primary flex-1"
				class:opacity-50={saving || !templateName.trim()}
			>
				{saving ? 'Saving...' : '💾 Save Changes'}
			</button>
		</div>
	</div>

