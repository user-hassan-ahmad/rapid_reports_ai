<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { fetchCustomPresets } from '$lib/stores/presets';
	import StylePresetCards from './StylePresetCards.svelte';
	import StyleGranularControls from './StyleGranularControls.svelte';
	import TemplateSyntaxPreview from '../shared/TemplateSyntaxPreview.svelte';
	import { highlightSyntax } from '$lib/utils/templateSyntaxHighlighting';

	const dispatch = createEventDispatcher();

	export let findingsConfig = {
		content_style: null,
		template_content: '',
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

	let selectedFindingsPreset: string | null = 'balanced_standard';

	function handlePresetChange(event: any) {
		selectedFindingsPreset = event.detail.presetId;
	}

	function handleChange() {
		dispatch('change');
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
	}

	onMount(() => {
		fetchCustomPresets('findings' as any);
	});

	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';

	let generating = false;
	let suggesting = false;
	let showAdvanced = false;
	let currentCardIndex = 0;
	let showAnimation: string | null = null;
	let showFullCarousel = true;
	let showInstructionsGuide = false;
	let showPreview = false;
	let hasInteractedWithWorkflow = false;

	// Reactive: Initialize showFullCarousel based on whether a style is already selected
	$: if (findingsConfig.content_style) {
		showFullCarousel = false;
		// Set currentCardIndex to match the selected style
		const selectedIndex = styleOptions.findIndex((s) => s.id === findingsConfig.content_style);
		if (selectedIndex !== -1) {
			currentCardIndex = selectedIndex;
		}
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
		}
	}

	// Reactive: Restore defaults when switching away from structured template
	$: if (
		findingsConfig.content_style &&
		findingsConfig.content_style !== 'structured_template' &&
		!findingsConfig.advanced?.writing_style
	) {
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
	}

	// For UI display: hide full style controls for structured templates
	$: showFullStyleControls = findingsConfig.content_style !== 'structured_template';

	const styleOptions = [
		{
			id: 'structured_template',
			icon: '📐',
			title: 'Structured Fill-In Template',
			shortTitle: 'Structured',
			tagline: 'Strict fill-in-the-blanks. No structural deviations.',
			description:
				'Your template is preserved EXACTLY as written. AI acts as a smart form-filler, inserting measurements into placeholders and selecting options based on your findings.',
			features: [
				'High fidelity to your template structure with intelligent flexibility',
				'{VAR} : Named variables (e.g. {LVEF})',
				'xxx : Measurement placeholders',
				'[opt1/opt2] : Alternatives (brackets wrap options only, not sentences)',
				'// instruction : Actionable AI guidance, not labels (stripped from output)'
			],
			workflow: {
				step1: {
					label: 'Template',
					content:
						'// Keep headers uppercase\n\nLEFT VENTRICLE\nEnd-diastolic volume is [normal/dilated] at xxx ml/m².\nSystolic function is [preserved/reduced] (LVEF={LVEF}%).\n\n// Describe only if assessed\nRIGHT VENTRICLE\nRV size is [normal/dilated] at xxx ml/m².'
				},
				step2: {
					label: 'You Provide',
					content: 'LV dilated (145 ml/m2), EF 35%. RV normal (88 ml/m2).'
				},
				step3: {
					label: 'AI Generates',
					content:
						'LEFT VENTRICLE\nEnd-diastolic volume is dilated at 145 ml/m².\nSystolic function is reduced (LVEF=35%).\n\nRIGHT VENTRICLE\nRV size is normal at 88 ml/m².'
				}
			}
		},
		{
			id: 'normal_template',
			icon: '📋',
			title: 'Normal Template',
			shortTitle: 'Normal Template',
			tagline: 'Flexible generation based on your style',
			description:
				'The standard approach. AI uses your normal template as a base language model, adapting it to describe specific pathology while maintaining your preferred phrasing and voice.',
			features: [
				'Flexible, natural language generation',
				'Adapts your normal text to findings',
				'Maintains your voice and style',
				'Great for general reporting (CT Chest, Abdo)'
			],
			workflow: {
				step1: {
					label: 'Template',
					content:
						'The lungs are clear. The pleural spaces are clear with no effusion. The mediastinum is unremarkable.'
				},
				step2: {
					label: 'You Dictate',
					content: '4cm spiculated mass RUL, small left effusion'
				},
				step3: {
					label: 'AI Generates',
					content:
						'There is a 4cm spiculated mass in the right upper lobe. A small left pleural effusion is present. The mediastinum is unremarkable.'
				}
			}
		},
		{
			id: 'guided_template',
			icon: '📝',
			title: 'Guided Template',
			shortTitle: 'Guided',
			tagline: 'Template with embedded AI instructions',
			description:
				"Use // comments to guide the AI's attention and structure without forcing rigid text. Perfect for ensuring specific features are mentioned in a specific order.",
			features: [
				'Template content + // guidance comments',
				'AI follows instructions in // lines',
				'Best of both worlds: structure + flexibility',
				'Good for complex logic or staging'
			],
			workflow: {
				step1: {
					label: 'Template',
					content:
						'The lungs are well aerated.\n// Describe nodules (size, loc, diff)\n\nThe pleural spaces are clear.\n// Exclude pneumothorax explicitly'
				},
				step2: {
					label: 'You Dictate',
					content: '4cm spiculated mass RUL, no ptx'
				},
				step3: {
					label: 'AI Generates',
					content:
						'There is a 4cm spiculated mass in the right upper lobe. No pneumothorax is identified. The pleural spaces are otherwise clear.'
				}
			}
		},
		{
			id: 'checklist',
			icon: '✓',
			title: 'Systematic Checklist',
			shortTitle: 'Checklist',
			tagline: 'Simple list, AI expands each item',
			description:
				'Your template is a bullet-point list of anatomical structures. AI generates complete findings covering each item systematically.',
			features: [
				'Template is just a bullet list',
				'You dictate all findings at once',
				'AI generates findings for each structure',
				'Ensures nothing is missed'
			],
			workflow: {
				step1: {
					label: 'Template',
					content:
						'- Lungs (parenchyma, nodules, consolidation)\n- Pleural spaces\n- Mediastinum (lymph nodes, vessels, airways)\n- Heart and pericardium\n- Chest wall and bones'
				},
				step2: {
					label: 'You Dictate',
					content:
						'RUL mass 4cm spiculated with ground glass, small left effusion, paratracheal nodes 2cm, heart normal, no bone lesions'
				},
				step3: {
					label: 'AI Generates',
					content:
						'Lungs: There is a 4cm spiculated mass in the right upper lobe with associated ground glass opacification.\n\nPleural spaces: A small left pleural effusion is present.\n\nMediastinum: Enlarged right paratracheal lymph nodes are noted, measuring up to 2cm in short axis diameter. The airways and major vessels are unremarkable.\n\nHeart and pericardium: The heart is normal in size with no pericardial effusion.\n\nChest wall and bones: No osseous lesions are identified.'
				}
			}
		}
	];

	function nextCard() {
		currentCardIndex = (currentCardIndex + 1) % styleOptions.length;
		hasInteractedWithWorkflow = false;
		showAnimation = null;
	}

	function prevCard() {
		currentCardIndex = (currentCardIndex - 1 + styleOptions.length) % styleOptions.length;
		hasInteractedWithWorkflow = false;
		showAnimation = null;
	}

	function goToCard(index: number) {
		currentCardIndex = index;
		hasInteractedWithWorkflow = false;
		showAnimation = null;
	}

	function toggleAnimation(styleId: string) {
		showAnimation = showAnimation === styleId ? null : styleId;
		hasInteractedWithWorkflow = true;
	}

	$: currentStyle = styleOptions[currentCardIndex];

	function selectStyle(styleId: any) {
		findingsConfig.content_style = styleId;
		showAnimation = null; // Close animation when selecting
		showFullCarousel = false; // Collapse carousel after selection
	}

	function getStyleLabel(styleId: any) {
		const style = styleOptions.find((s) => s.id === styleId);
		return style ? style.shortTitle : '';
	}

	function expandCarousel() {
		// Only warn if there's actual template content that would be lost
		// Don't warn if just switching tabs or if content is empty
		if (findingsConfig.template_content && findingsConfig.template_content.trim().length > 50) {
			const confirmed = confirm(
				'Changing the template style will clear your current template content.\n\n' +
					'Are you sure you want to proceed?'
			);
			if (!confirmed) {
				return; // User cancelled, don't change style
			}
		}

		// Clear everything and show carousel
		showFullCarousel = true;
		findingsConfig.content_style = null;
		findingsConfig.template_content = '';
		currentCardIndex = 0;
	}

	async function generateWithAI() {
		if (!findingsConfig.content_style) return;

		generating = true;
		try {
			const response = await fetch(`${API_URL}/api/templates/generate-findings-content`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${$token}`
				},
				body: JSON.stringify({
					scan_type: scanType,
					contrast: contrast,
					protocol_details: protocolDetails || '',
					content_style: findingsConfig.content_style,
					instructions: findingsConfig.advanced.instructions || ''
				})
			});

			const data = await response.json();
			if (data.success) {
				findingsConfig.template_content = data.content;
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
					Authorization: `Bearer ${$token}`
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
			}
		} catch (error) {
			console.error('Error suggesting instructions:', error);
		} finally {
			suggesting = false;
		}
	}

	async function extractPlaceholders(templateContent: string) {
		try {
			const response = await fetch(`${API_URL}/api/templates/extract-placeholders`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${$token}`
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

	async function validateTemplate(templateContent: any) {
		try {
			const response = await fetch(`${API_URL}/api/templates/validate-template`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${$token}`
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

	function handleNext() {
		if (!findingsConfig.content_style || !findingsConfig.template_content.trim()) {
			alert('Please select a content style and provide template content.');
			return;
		}
		dispatch('next');
	}

	$: canProceed = findingsConfig.content_style && findingsConfig.template_content.trim() !== '';
</script>

<div class="space-y-6">
	<div class="mb-8 text-center">
		<h3 class="mb-2 text-2xl font-bold text-white">FINDINGS Setup</h3>
		<p class="mx-auto max-w-2xl text-sm text-gray-400">
			Choose how you want to structure your findings section. Each approach gives you different
			levels of control and flexibility.
		</p>
	</div>

	<!-- Carousel Container -->
	{#if showFullCarousel}
		<!-- Full Carousel View -->
		<div class="relative mx-auto mb-8 max-w-5xl">
			<!-- Main Card Display -->
			<div class="relative overflow-hidden">
				<div class="transition-all duration-500 ease-in-out">
					<!-- Current Card -->
					<div
						class="rounded-2xl border-2 border-purple-500/30 bg-gradient-to-br from-purple-900/20 to-blue-900/20 p-8 shadow-2xl"
					>
						<!-- Header Section -->
						<div class="mb-6 flex items-start justify-between">
							<div class="flex-1">
								<div class="mb-3 flex items-center gap-4">
									<span class="text-5xl">{currentStyle.icon}</span>
									<div>
										<h4 class="text-2xl font-bold text-white">{currentStyle.title}</h4>
										<p class="mt-1 text-sm italic text-purple-300">{currentStyle.tagline}</p>
									</div>
								</div>
								<p class="text-base leading-relaxed text-gray-300">
									{currentStyle.description}
								</p>
							</div>
						</div>

						<!-- Key Features -->
						<div class="mb-8">
							<h5 class="mb-3 text-sm font-semibold uppercase tracking-wide text-purple-400">
								Key Features:
							</h5>
							<div class="grid grid-cols-1 gap-3 md:grid-cols-2">
								{#each currentStyle.features as feature}
									<div class="flex items-center gap-2">
										<span class="flex-shrink-0 text-lg text-green-400">✓</span>
										<span class="text-sm text-gray-300">{feature}</span>
									</div>
								{/each}
							</div>
						</div>

						<!-- Workflow Preview -->
						<div class="mb-6">
							<div class="mb-4">
								<h5 class="text-sm font-semibold uppercase tracking-wide text-purple-400">
									How it works:
								</h5>
							</div>

							<!-- Clickable Compact Flow Diagram -->
							<button
								onclick={() => toggleAnimation(currentStyle.id)}
								class="group relative w-full text-left transition-all duration-300 hover:scale-[1.01]"
							>
								<!-- Floating "Click to expand" hint (shows initially, fades after interaction) -->
								{#if !hasInteractedWithWorkflow && showAnimation !== currentStyle.id}
									<div
										class="absolute -top-3 left-1/2 -translate-x-1/2 z-10
										       bg-gradient-to-r from-purple-500 to-blue-500 text-white text-xs px-3 py-1 rounded-full
										       shadow-lg shadow-purple-500/50
										       animate-pulse-subtle group-hover:opacity-0 transition-opacity duration-300
										       whitespace-nowrap"
									>
										👆 Click to see full example
									</div>
								{/if}

								<div
									class="relative rounded-lg border border-white/10 bg-black/40 p-6
									       hover:border-purple-500/50 hover:shadow-lg hover:shadow-purple-500/20 
									       transition-all duration-300 cursor-pointer
									       {showAnimation === currentStyle.id ? 'border-purple-500/50 shadow-lg shadow-purple-500/20' : ''}"
								>
									<!-- Expand/Collapse icon in top-right -->
									<div
										class="absolute top-3 right-3 text-gray-400 group-hover:text-purple-400 transition-colors duration-300
										       {showAnimation === currentStyle.id ? 'text-purple-400' : ''}"
									>
										{#if showAnimation === currentStyle.id}
											<svg
												class="h-5 w-5"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M5 15l7-7 7 7"
												/>
											</svg>
										{:else}
											<svg
												class="h-5 w-5"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M19 9l-7 7-7-7"
												/>
											</svg>
										{/if}
									</div>

									<!-- Icon-based Flow Diagram -->
									<div class="flex items-center justify-center gap-8 py-2">
										<div class="flex flex-col items-center gap-3 flex-1">
											<div
												class="w-16 h-16 rounded-xl bg-gradient-to-br from-purple-500/30 to-purple-600/20 
												       border border-purple-500/30 flex items-center justify-center text-3xl
												       group-hover:scale-105 transition-transform duration-300"
											>
												📄
											</div>
											<div class="text-center">
												<div class="text-xs font-semibold text-purple-400 mb-0.5">
													1. Template
												</div>
												<div class="text-[10px] text-gray-500 italic">
													What you create once
												</div>
											</div>
										</div>

										<div class="text-2xl text-gray-500 self-start mt-6">→</div>

										<div class="flex flex-col items-center gap-3 flex-1">
											<div
												class="w-16 h-16 rounded-xl bg-gradient-to-br from-blue-500/30 to-blue-600/20 
												       border border-blue-500/30 flex items-center justify-center text-3xl
												       group-hover:scale-105 transition-transform duration-300"
											>
												🎤
											</div>
											<div class="text-center">
												<div class="text-xs font-semibold text-blue-400 mb-0.5">
													2. You Dictate
												</div>
												<div class="text-[10px] text-gray-500 italic">
													Each time you report
												</div>
											</div>
										</div>

										<div class="text-2xl text-gray-500 self-start mt-6">→</div>

										<div class="flex flex-col items-center gap-3 flex-1">
											<div
												class="w-16 h-16 rounded-xl bg-gradient-to-br from-green-500/30 to-green-600/20 
												       border border-green-500/30 flex items-center justify-center text-3xl
												       group-hover:scale-105 transition-transform duration-300"
											>
												✨
											</div>
											<div class="text-center">
												<div class="text-xs font-semibold text-green-400 mb-0.5">
													3. AI Output
												</div>
												<div class="text-[10px] text-gray-500 italic">
													Final report section
												</div>
											</div>
										</div>
									</div>
								</div>
							</button>
						</div>

						<!-- Expandable Animation Section -->
						{#if showAnimation === currentStyle.id}
							<div
								class="animate-fadeIn mt-4 space-y-4 rounded-xl border border-purple-500/20 bg-black/60 p-6"
							>
								<div>
									<div class="mb-2 flex items-center gap-2">
										<span class="text-sm font-semibold text-purple-400">📄 TEMPLATE</span>
										<span class="text-xs text-gray-500">What you create once</span>
									</div>
									<div
										class="whitespace-pre-wrap rounded-lg border border-purple-500/30 bg-purple-500/10 p-4 font-mono text-sm leading-relaxed text-gray-200"
									>
										{currentStyle.workflow.step1.content}
									</div>
								</div>

								<div class="flex items-center justify-center">
									<div class="text-gray-400">↓</div>
								</div>

								<div>
									<div class="mb-2 flex items-center gap-2">
										<span class="text-sm font-semibold text-blue-400">🎤 YOU DICTATE</span>
										<span class="text-xs text-gray-500">Each time you generate a report</span>
									</div>
									<div
										class="whitespace-pre-wrap rounded-lg border border-blue-500/30 bg-blue-500/10 p-4 font-mono text-sm leading-relaxed text-blue-200"
									>
										{currentStyle.workflow.step2.content}
									</div>
								</div>

								<div class="flex items-center justify-center">
									<div class="text-gray-400">↓</div>
								</div>

								<div>
									<div class="mb-2 flex items-center gap-2">
										<span class="text-sm font-semibold text-green-400">✨ AI GENERATES</span>
										<span class="text-xs text-gray-500">Final report section</span>
									</div>
									<div
										class="whitespace-pre-wrap rounded-lg border border-green-500/30 bg-green-500/10 p-4 font-mono text-sm leading-relaxed text-green-200"
									>
										{currentStyle.workflow.step3.content}
									</div>
								</div>
							</div>
						{/if}

						<!-- Select Button -->
						<div class="mt-6 flex justify-center">
							<button
								onclick={() => selectStyle(currentStyle.id)}
								class="btn-primary px-8 py-3 text-lg"
							>
								Select {currentStyle.shortTitle}
							</button>
						</div>
					</div>
				</div>
			</div>

			<!-- Navigation Arrows -->
			<button
				onclick={prevCard}
				class="absolute left-0 top-1/2 flex h-12 w-12 -translate-x-4 -translate-y-1/2 items-center justify-center rounded-full bg-purple-600/80 text-white shadow-lg transition-all hover:scale-110 hover:bg-purple-600"
				aria-label="Previous option"
			>
				<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M15 19l-7-7 7-7"
					/>
				</svg>
			</button>
			<button
				onclick={nextCard}
				class="absolute right-0 top-1/2 flex h-12 w-12 -translate-y-1/2 translate-x-4 items-center justify-center rounded-full bg-purple-600/80 text-white shadow-lg transition-all hover:scale-110 hover:bg-purple-600"
				aria-label="Next option"
			>
				<svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
				</svg>
			</button>

			<!-- Dots Indicator -->
			<div class="mt-6 flex items-center justify-center gap-2">
				{#each styleOptions as style, index}
					<button
						onclick={() => goToCard(index)}
						class="rounded-full transition-all {index === currentCardIndex
							? 'h-3 w-8 bg-purple-500'
							: 'h-3 w-3 bg-gray-600 hover:bg-gray-500'}"
						aria-label={`Go to ${style.shortTitle}`}
					></button>
				{/each}
			</div>
		</div>
	{:else if findingsConfig.content_style}
		<!-- Collapsed View - Selected Style -->
		<div class="mx-auto mb-6 max-w-4xl">
			<div
				class="rounded-xl border-2 border-purple-500/30 bg-gradient-to-r from-purple-900/20 to-blue-900/20 p-4"
			>
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-4">
						<span class="text-3xl"
							>{styleOptions.find((s) => s.id === findingsConfig.content_style)?.icon}</span
						>
						<div>
							<h4 class="text-lg font-bold text-white">
								{styleOptions.find((s) => s.id === findingsConfig.content_style)?.title}
							</h4>
							<p class="text-xs italic text-purple-300">
								{styleOptions.find((s) => s.id === findingsConfig.content_style)?.tagline}
							</p>
						</div>
					</div>
					<button onclick={expandCarousel} class="btn-ghost flex items-center gap-2 text-sm">
						<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
							/>
						</svg>
						Change Style
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Part B: Template Editor (shows after selection) -->
	{#if findingsConfig.content_style}
		<div class="mx-auto max-w-4xl space-y-4">
			<div>
				<label class="mb-2 block text-sm font-medium text-gray-300">
					Template Content <span class="text-red-400">*</span>
				</label>
				<textarea
					bind:value={findingsConfig.template_content}
					oninput={handleChange}
					rows="15"
					placeholder="Your template structure will go here... Use AI to generate or write manually."
					class="input-dark font-mono text-sm"
					onkeydown={(e) => {
						// Allow Enter to create new lines in textarea
						if (e.key === 'Enter') {
							e.stopPropagation();
						}
					}}
				></textarea>

				{#if findingsConfig.content_style === 'structured_template' && findingsConfig.template_content}
					<button
						onclick={() => (showPreview = true)}
						class="mt-2 flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm text-white transition-colors hover:bg-purple-700"
					>
						<span>👁️</span> Preview Template Syntax
					</button>
				{/if}
			</div>

			<!-- Validation Panel for Structured Templates -->
			{#if findingsConfig.content_style === 'structured_template' && findingsConfig.template_content}
				{#await validateTemplate(findingsConfig.template_content) then validation}
					{@const hasErrors = validation.errors?.length > 0}
					{@const hasWarnings = validation.warnings?.length > 0}
					{@const isValid = !hasErrors && !hasWarnings}
					{@const hasOnlyWarnings = hasWarnings && !hasErrors}
					{@const validationClass = hasErrors
						? 'bg-red-900/20 border-red-500/30'
						: isValid
							? 'bg-green-900/20 border-green-500/30'
							: 'bg-yellow-900/20 border-yellow-500/30'}
					<div class="mt-4 rounded-lg border p-4 {validationClass}">
						{#if hasErrors}
							<div class="space-y-2">
								<h4 class="flex items-center gap-2 text-sm font-semibold text-red-300">
									❌ Template Errors ({validation.errors.length})
								</h4>
								{#each validation.errors as error}
									<p class="text-xs text-red-400">• {error.message}</p>
								{/each}
							</div>
						{/if}

						{#if hasWarnings}
							<div class="mt-3 space-y-2">
								<h4 class="flex items-center gap-2 text-sm font-semibold text-yellow-300">
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
										<p class="mb-1 text-xs font-semibold text-gray-400">
											Variables ({validation.stats.variables}):
										</p>
										<div class="flex flex-wrap gap-1">
											{#each validation.placeholders.variables as variable}
												<span
													class="rounded border border-green-500/30 bg-green-900/30 px-2 py-0.5 text-xs text-green-300"
												>
													~{variable}~
												</span>
											{/each}
										</div>
									</div>
								{/if}

								{#if validation.stats.measurements > 0}
									<p class="text-xs text-gray-400">
										<strong>Measurements:</strong>
										{validation.stats.measurements} (xxx)
									</p>
								{/if}
							</div>
						{/if}
					</div>
				{:catch error}
					<div class="mt-4 rounded-lg border border-red-500/30 bg-red-900/20 p-4">
						<p class="text-xs text-red-400">Validation error</p>
					</div>
				{/await}
			{/if}

			<div class="flex gap-2">
				<button
					onclick={generateWithAI}
					disabled={generating || !findingsConfig.content_style}
					class="btn-secondary flex items-center gap-2"
					class:opacity-50={generating || !findingsConfig.content_style}
				>
					{#if generating}
						<svg
							class="h-4 w-4 animate-spin"
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
						>
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
							></circle>
							<path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
							></path>
						</svg>
						Generating...
					{:else}
						🤖 Generate with AI
					{/if}
				</button>
				<button onclick={() => (findingsConfig.template_content = '')} class="btn-ghost">
					Clear & Write Manually
				</button>
			</div>

			<!-- Writing Style Section (always visible) -->
			<div class="writing-style-section mt-8">
				<div class="mb-4 flex items-center justify-between">
					<h4 class="flex items-center gap-2 text-lg font-semibold text-white">
						<span>✨</span>
						<span>Writing Style</span>
					</h4>
					{#if findingsConfig.content_style !== 'structured_template'}
						<button onclick={resetToDefaults} class="btn-sm text-xs"> Reset to Defaults </button>
					{/if}
				</div>

				<!-- Preset Cards (hidden for structured templates) -->
				{#if showFullStyleControls}
					<StylePresetCards
						section="findings"
						bind:selectedPresetId={selectedFindingsPreset as any}
						bind:advanced={findingsConfig.advanced as any}
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
						on:fieldChange={() => (selectedFindingsPreset = 'custom')}
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
			</div>
		</div>
	{/if}

	<!-- Next Button -->
	<div class="mx-auto mt-8 flex max-w-4xl justify-end">
		<button
			onclick={handleNext}
			disabled={!canProceed}
			class="btn-primary px-6 py-3"
			class:opacity-50={!canProceed}
			class:cursor-not-allowed={!canProceed}
		>
			Next: IMPRESSION Setup →
		</button>
	</div>
</div>

<!-- Preview Modal -->
<TemplateSyntaxPreview 
	bind:show={showPreview}
	templateContent={findingsConfig.template_content}
	on:close={() => showPreview = false}
/>

<style>
	@keyframes fadeIn {
		from {
			opacity: 0;
			transform: translateY(-10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	@keyframes pulse-subtle {
		0%, 100% {
			opacity: 1;
			transform: translateX(-50%) scale(1);
		}
		50% {
			opacity: 0.8;
			transform: translateX(-50%) scale(1.05);
		}
	}

	.animate-fadeIn {
		animation: fadeIn 0.3s ease-out;
	}

	.animate-pulse-subtle {
		animation: pulse-subtle 2s ease-in-out infinite;
	}

	/* Syntax colors for preview modal */
	:global(.highlight-measurement) {
		color: #fbbf24;
	} /* Amber - xxx */
	:global(.highlight-variable) {
		color: #34d399;
	} /* Green - {VAR} */
	:global(.highlight-instruction) {
		color: #60a5fa;
	} /* Blue - // instruction */
	:global(.highlight-alternative) {
		color: #c084fc;
	} /* Purple - Normal/increased */
</style>
