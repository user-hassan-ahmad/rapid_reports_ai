<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { slide, fade } from 'svelte/transition';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import StyleGranularControls from './StyleGranularControls.svelte';
	import TemplateSyntaxPreview from '../shared/TemplateSyntaxPreview.svelte';
	import { highlightSyntax } from '$lib/utils/templateSyntaxHighlighting';

	const dispatch = createEventDispatcher();

	export let findingsConfig = {
		content_style: null,
		template_content: '',
		advanced: {
			instructions: '',
			writing_style: 'prose',
			format: 'prose',
			use_subsection_headers: false,
			organization: 'clinical_priority',
			measurement_style: 'inline',
			negative_findings_style: 'grouped',
			descriptor_density: 'standard',
			paragraph_grouping: 'by_finding'
		}
	};

	function handleChange() {
		dispatch('change');
	}

	function resetToDefaults() {
		findingsConfig.advanced = {
			instructions: '',
			writing_style: 'prose',
			organization: 'clinical_priority',
			format: 'prose',
			use_subsection_headers: false
		};
	}

	onMount(() => {
		// No preset loading needed
	});

	export let scanType = '';
	export let contrast = '';
	export let protocolDetails = '';
	/** When true, hide the Next button (used when embedded in ContentConfig) */
	export let embedded = false;

	let generating = false;
	let suggesting = false;
	let showAdvanced = false;
	let currentCardIndex = 0;
	let showAnimation: string | null = null;
	let showFullCarousel = true;
	let showInstructionsGuide = false;
	let showPreview = false;
	let hasInteractedWithWorkflow = false;
	let previewedStyle: string | null = null;
	let hoverLeaveTimer: ReturnType<typeof setTimeout> | null = null;

	function onTabEnter(id: string) {
		if (hoverLeaveTimer) { clearTimeout(hoverLeaveTimer); hoverLeaveTimer = null; }
		previewedStyle = id;
	}

	function onTabLeave() {
		hoverLeaveTimer = setTimeout(() => { previewedStyle = null; }, 100);
	}

	$: displayStyleId = previewedStyle ?? findingsConfig.content_style ?? styleOptions[0].id;
	$: displayStyle = styleOptions.find(s => s.id === displayStyleId) ?? styleOptions[0];

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
			writing_style: 'prose',
			organization: 'clinical_priority',
			format: 'prose',
			use_subsection_headers: false
		};
	}

	// For UI display: hide full style controls for structured templates
	$: showFullStyleControls = findingsConfig.content_style !== 'structured_template';

	const styleOptions = [
		{
			id: 'normal_template',
			icon: '📋',
			title: 'Normal Template',
			shortTitle: 'Normal Template',
			tagline: 'Write a complete normal report — AI swaps in what\'s abnormal',
			aiRole: 'AI replaces',
			aiRoleColor: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
			bestFor: 'You own the prose and the phrasing. Dictate abnormalities only — AI identifies which normal sentences they correspond to and replaces them. Everything else is left exactly as written.',
			example: {
				label: 'Your template',
				input: 'The lungs are clear. The pleural spaces are clear with no effusion. The mediastinum is unremarkable.',
				templateLine: null,
				output: 'There is a 4cm mass in the right upper lobe. A small left pleural effusion is present. The mediastinum is unremarkable.',
				note: 'Everything you didn\'t mention stays exactly as written'
			}
		},
		{
			id: 'guided_template',
			icon: '📝',
			title: 'Guided Template',
			shortTitle: 'Guided',
			tagline: 'Normal template + annotations that teach AI what each section covers',
			aiRole: 'AI replaces + interprets',
			aiRoleColor: 'text-violet-400 bg-violet-500/10 border-violet-500/20',
			bestFor: 'Your prose defines the structure, but a single normal sentence can represent a broader finding category. The // annotations tell AI the full scope of what each section covers, so it can interpret and expand correctly — without those notes appearing in the output.',
			example: {
				label: 'Your template',
				input: 'The pleural spaces are clear.\n// covers pneumothorax, effusions, thickening',
				templateLine: null,
				output: 'No pneumothorax. No pleural effusion or thickening.',
				note: '// lines are instructions to AI — stripped from output entirely'
			}
		},
		{
			id: 'structured_template',
			icon: '📐',
			title: 'Structured Fill-In',
			shortTitle: 'Structured',
			tagline: 'Locked sentence frames — AI fills blanks, selects options, inserts values',
			aiRole: 'AI fills blanks',
			aiRoleColor: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
			bestFor: 'Every report needs the same sentence structures with only values changing. Placeholders define exactly what gets filled — measurement fields, graded alternatives, named variables. AI never rewrites a sentence; it only completes what you\'ve pre-framed.',
			example: {
				label: 'Your template',
				input: 'Systolic function [preserved/reduced] (EF {LVEF}%, volumes: EDV xxx ml/m²)',
				templateLine: null,
				output: 'Systolic function reduced (EF 35%, volumes: EDV 145 ml/m²)',
				note: 'Sentences are never rewritten — only blanks are filled'
			}
		},
		{
			id: 'checklist',
			icon: '✓',
			title: 'Systematic Checklist',
			shortTitle: 'Checklist',
			tagline: 'Define broad review areas — AI generates all the language',
			aiRole: 'AI writes all',
			aiRoleColor: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
			bestFor: 'You define what gets assessed — anatomical regions, systems, or clinical categories — as a list. AI writes complete prose for every item from scratch, guided by your dictation. The list is the review agenda; nothing gets skipped.',
			example: {
				label: 'Your template',
				input: '- Liver\n- Gallbladder\n- Pancreas\n- Spleen',
				templateLine: null,
				output: 'Liver: Normal in size, homogeneous parenchyma, no focal lesions.\nGallbladder: Mildly distended with a 8mm calculus at the neck...',
				note: 'AI writes complete findings for every item — normal or abnormal'
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
	<div class="mb-6">
		<h3 class="mb-1 text-xl font-bold text-white">FINDINGS Setup</h3>
		<p class="text-sm text-gray-500">Choose how your findings template is written and how AI uses it.</p>
	</div>

	<!-- Style Picker -->
	{#if showFullCarousel}
		<!-- Wrap tabs + panel so hover only resets when leaving the whole block -->
		<div class="mb-6"
			onmouseleave={() => { if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer); previewedStyle = null; }}
			role="group"
		>
		<!-- Tab row — no bottom margin so panel sits flush -->
		<div class="grid grid-cols-4 gap-2">
			{#each styleOptions as style}
				{@const isActive = displayStyle.id === style.id}
				{@const isSelected = findingsConfig.content_style === style.id}
				<button
					type="button"
					class="relative rounded-xl rounded-b-none border border-b-0 px-3 py-3 text-left transition-all duration-150 cursor-pointer
						{isActive
							? 'border-purple-500/60 bg-purple-900/30'
							: 'border-white/10 bg-white/[0.025] hover:border-white/15 hover:bg-white/[0.04]'}"
					onmouseenter={() => onTabEnter(style.id)}
					onmouseleave={() => { if (hoverLeaveTimer) clearTimeout(hoverLeaveTimer); }}
					onclick={() => selectStyle(style.id)}
				>
					<div class="flex items-center gap-1.5 mb-2">
						<span class="text-base leading-none">{style.icon}</span>
						<span class="text-xs font-semibold text-white leading-tight">{style.shortTitle}</span>
						{#if isSelected}
							<span class="ml-auto text-purple-400 text-[10px]">✓</span>
						{/if}
					</div>
					<span class="inline-block text-[9px] font-medium px-1.5 py-0.5 rounded border {style.aiRoleColor}">
						{style.aiRole}
					</span>
					<!-- Active connector line at bottom -->
					{#if isActive}
						<div class="absolute bottom-0 left-0 right-0 h-px bg-purple-500/60"></div>
					{/if}
				</button>
			{/each}
		</div>

		<!-- Detail panel — flush against tabs, top border matches active tab border -->
		{#key displayStyle.id}
			<div class="rounded-xl rounded-tl-none border border-purple-500/20 bg-white/[0.025] p-4" in:fade={{ duration: 120 }}>
				<div class="flex items-start justify-between gap-4 mb-1">
					<div class="min-w-0">
						<div class="flex items-center gap-2 mb-0.5">
							<span class="text-lg">{displayStyle.icon}</span>
							<h4 class="text-sm font-semibold text-white">{displayStyle.title}</h4>
						</div>
						<p class="text-[11px] text-gray-500">{displayStyle.tagline}</p>
					</div>
					<button
						type="button"
						onclick={() => selectStyle(displayStyle.id)}
						class="shrink-0 px-4 py-1.5 rounded-lg text-xs font-medium transition-colors
							{findingsConfig.content_style === displayStyle.id
								? 'bg-purple-600/40 text-purple-300 border border-purple-500/40 cursor-default'
								: 'bg-purple-600 hover:bg-purple-500 text-white'}"
					>
						{findingsConfig.content_style === displayStyle.id ? '✓ Selected' : 'Select'}
					</button>
				</div>

				<p class="text-[11px] text-gray-600 mb-4">When to use: <span class="text-gray-400">{displayStyle.bestFor}</span></p>

				<div class="grid grid-cols-2 gap-3">
					<div>
						<p class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">{displayStyle.example.label}</p>
						<div class="rounded-lg bg-black/40 border border-white/[0.06] p-3 font-mono text-[11px] text-purple-200/80 whitespace-pre-wrap leading-relaxed h-full">
							{displayStyle.example.input}
						</div>
					</div>
					<div>
						<p class="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">AI output</p>
						<div class="rounded-lg bg-black/40 border border-green-500/20 p-3 font-mono text-[11px] text-green-200/70 whitespace-pre-wrap leading-relaxed">
							{displayStyle.example.output}
						</div>
					</div>
				</div>
				<p class="text-[10px] text-gray-600 italic mt-2">{displayStyle.example.note}</p>
			</div>
		{/key}
		</div><!-- end hover container -->
	{:else if findingsConfig.content_style}
		<!-- Collapsed View - Selected Style -->
		<div class="mb-6 flex items-center gap-2 rounded-lg border border-purple-500/20 bg-gradient-to-r from-purple-900/10 to-blue-900/10 px-3 py-2">
			<span class="text-sm">{styleOptions.find((s) => s.id === findingsConfig.content_style)?.icon}</span>
			<span class="text-xs font-medium text-gray-400">{styleOptions.find((s) => s.id === findingsConfig.content_style)?.title}</span>
			<span class="text-gray-700">·</span>
			<span class="text-[11px] text-gray-600 italic">{styleOptions.find((s) => s.id === findingsConfig.content_style)?.tagline}</span>
			<button onclick={expandCarousel} class="ml-auto text-[11px] text-gray-500 hover:text-gray-300 transition-colors">
				Change
			</button>
		</div>
	{/if}

	<!-- Part B: Template Editor (shows after selection) -->
	{#if findingsConfig.content_style}
		<div class="mx-auto max-w-4xl space-y-4">
			<div>
				<label class="mb-2 block text-sm font-medium text-gray-300">
					Template Content <span class="text-red-400">*</span>
				</label>
				{#if findingsConfig.content_style === 'structured_template'}
					<div class="mb-3 rounded-lg border border-white/10 bg-black/30 px-4 py-3">
						<div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Syntax</div>
						<div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
							<div class="flex items-center gap-2">
								<span class="highlight-measurement font-mono">xxx</span>
								<span class="text-gray-500">Measurements</span>
							</div>
							<div class="flex items-center gap-2">
								<span class="highlight-variable font-mono">{'{VAR}'}</span>
								<span class="text-gray-500">Variables</span>
							</div>
							<div class="flex items-center gap-2">
								<span class="highlight-instruction font-mono">//</span>
								<span class="text-gray-500">AI instructions</span>
							</div>
							<div class="flex items-center gap-2">
								<span class="highlight-alternative font-mono">[opt1/opt2]</span>
								<span class="text-gray-500">Alternatives</span>
							</div>
						</div>
					</div>
				{/if}
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

				<!-- Style Controls -->
				<div class="mt-6">
					{#if showFullStyleControls}
					<StyleGranularControls
						section="findings"
						bind:advanced={findingsConfig.advanced}
						templateType={findingsConfig.content_style}
						on:fieldChange={handleChange}
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

	<!-- Next Button (hidden when embedded in ContentConfig) -->
	{#if !embedded}
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
	{/if}
</div>

<!-- Preview Modal -->
<TemplateSyntaxPreview 
	bind:show={showPreview}
	templateContent={findingsConfig.template_content}
	on:close={() => showPreview = false}
/>

<style>
	.style-card {
		transition: border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
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
