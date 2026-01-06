<script>
	import { createEventDispatcher } from 'svelte';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';

	const dispatch = createEventDispatcher();

	export let templateName = '';
	export let description = '';
	export let tags = [];
	export let isPinned = false;
	export let scanType = '';
	export let contrast = '';
	export let contrastOther = '';
	export let contrastPhases = [];
	export let protocolDetails = '';
	export let sections = {};
	export let sectionOrder = null;
	export let tagInput = '';
	export let showTagSuggestions = false;
	export let tagSuggestions = [];
	export let selectedSuggestionIndex = -1;
	export let customTagColors = {};
	export let globalCustomInstructions = '';

	let editingScanType = false;
	let editingProtocol = false;

	// Default section order structure (matching Step3_SectionBuilder)
	const DEFAULT_SECTION_ORDER = [
		{ id: 'clinical_history', name: 'CLINICAL HISTORY', required: true, description: 'Manual input' },
		{ id: 'comparison', name: 'COMPARISON', required: false, description: 'Optional' },
		{ id: 'technique', name: 'TECHNIQUE', required: false, description: 'Optional' },
		{ id: 'limitations', name: 'LIMITATIONS', required: false, description: 'Optional' },
		{ id: 'findings', name: 'FINDINGS', required: true, description: 'Manual input' },
		{ id: 'impression', name: 'IMPRESSION', required: true, description: 'Auto-generated' }
	];

	// Normalize section order - STRICTLY preserves existing order
	// Only enriches sections with missing properties (required, description)
	// Does NOT reorder or add sections - order must be preserved exactly
	function normalizeSectionOrder(order) {
		if (!order || order.length === 0) {
			return [...DEFAULT_SECTION_ORDER];
		}

		// Create a map of default sections for quick lookup
		const defaultMap = {};
		DEFAULT_SECTION_ORDER.forEach(s => {
			defaultMap[s.id] = s;
		});

		// STRICTLY preserve existing order - .map() preserves array order exactly
		// Only enrich with missing properties, NEVER change order
		const normalized = order.map(existing => {
			const defaultSection = defaultMap[existing.id];
			if (defaultSection) {
				// Preserve ALL existing properties including order position
				// But always use default name, required, and description for consistency
				return {
					...existing, // Preserves all properties including any custom ones and position
					name: defaultSection.name, // Always use default name for consistent display
					required: defaultSection.required, // Always use default required (system property)
					description: defaultSection.description // Always use default description for consistency
				};
			}
			// If section not in defaults, return as-is (shouldn't happen for valid templates)
			return existing;
		});
		
		// CRITICAL: Only add missing sections at the END to preserve existing order
		// This should rarely happen for valid templates (all sections should be saved with order)
		const existingIds = new Set(normalized.map(s => s.id));
		const allRequiredIds = DEFAULT_SECTION_ORDER.filter(s => s.required).map(s => s.id);
		const missingRequired = allRequiredIds.filter(id => !existingIds.has(id));
		
		// Add missing required sections at the end (preserves order of existing sections)
		if (missingRequired.length > 0) {
			for (const defaultSection of DEFAULT_SECTION_ORDER) {
				if (missingRequired.includes(defaultSection.id)) {
					normalized.push({ ...defaultSection });
				}
			}
		}
		
		// Add missing optional sections at the end (preserves order of existing sections)
		const missingOptional = DEFAULT_SECTION_ORDER
			.filter(s => !s.required && !existingIds.has(s.id))
			.map(s => s.id);
		if (missingOptional.length > 0) {
			for (const defaultSection of DEFAULT_SECTION_ORDER) {
				if (missingOptional.includes(defaultSection.id)) {
					normalized.push({ ...defaultSection });
				}
			}
		}
		
		// Return normalized array - order of existing sections is preserved, missing ones appended
		return normalized;
	}

	// Normalize sectionOrder to ensure required flags are always set
	// This reactive statement creates a normalized version for display
	// IMPORTANT: This should be idempotent - if sectionOrder already has all properties,
	// normalization should return the same order WITHOUT creating a new array
	$: normalizedSectionOrder = (() => {
		// If sectionOrder is null or empty, return default (but don't modify sectionOrder)
		// The parent component (TemplateEditorNew) will set sectionOrder from template config
		if (!sectionOrder || sectionOrder.length === 0) {
			return [...DEFAULT_SECTION_ORDER];
		}
		
		// Check if normalization is needed (if any section has outdated name/description or missing properties)
		const needsNormalization = sectionOrder.some(s => {
			const defaultSection = DEFAULT_SECTION_ORDER.find(d => d.id === s.id);
			if (!defaultSection) return true; // Unknown section, needs normalization
			// Check if required flag is missing, or if name/description doesn't match current defaults
			return s.required === undefined || s.name !== defaultSection.name || s.description !== defaultSection.description;
		});
		
		if (!needsNormalization) {
			// Already normalized - return the EXACT same array reference to preserve order
			// This ensures no reordering happens
			return sectionOrder;
		}
		
		// Normalize preserves order, only enriches with missing properties
		// The normalizeSectionOrder function uses .map() which preserves array order
		return normalizeSectionOrder(sectionOrder);
	})();

	function moveUp(index) {
		if (index === 0) return;
		// Use normalizedSectionOrder for display/validation, but update sectionOrder directly
		const currentSection = normalizedSectionOrder[index];
		// Don't allow moving required sections
		if (currentSection?.required) return;
		
		// CRITICAL: Always use sectionOrder directly, not normalizedSectionOrder
		// normalizedSectionOrder is just for display - sectionOrder is the source of truth
		if (!sectionOrder || sectionOrder.length === 0) {
			// Fallback to normalizedSectionOrder if sectionOrder is not set
			sectionOrder = [...normalizedSectionOrder];
		}
		
		const newOrder = [...sectionOrder];
		[newOrder[index], newOrder[index - 1]] = [newOrder[index - 1], newOrder[index]];
		sectionOrder = newOrder;
		handleChange();
	}

	function moveDown(index) {
		if (index === normalizedSectionOrder.length - 1) return;
		const currentSection = normalizedSectionOrder[index];
		// Don't allow moving required sections
		if (currentSection?.required) return;
		
		// CRITICAL: Always use sectionOrder directly, not normalizedSectionOrder
		// normalizedSectionOrder is just for display - sectionOrder is the source of truth
		if (!sectionOrder || sectionOrder.length === 0) {
			// Fallback to normalizedSectionOrder if sectionOrder is not set
			sectionOrder = [...normalizedSectionOrder];
		}
		
		const newOrder = [...sectionOrder];
		[newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]];
		sectionOrder = newOrder;
		handleChange();
	}

	function getSectionConfig(id) {
		if (id === 'clinical_history') return sections.clinical_history;
		if (id === 'comparison') return sections.comparison;
		if (id === 'technique') return sections.technique;
		if (id === 'limitations') return sections.limitations;
		return null;
	}

	function handleChange() {
		dispatch('change');
	}

	function handleTagInput(e) {
		// Pass the event object so parent can access target.value
		dispatch('tagInput', e);
		handleChange();
	}

	function handleTagKeydown(e) {
		// Pass both the event and the current input value
		dispatch('tagKeydown', {
			event: e,
			value: tagInput
		});
	}
	
	function handleTagBlur(e) {
		dispatch('tagBlur', e);
	}

	function getContrastDisplay() {
		if (contrast === 'no_contrast') return 'Non-contrast';
		if (contrast === 'with_contrast') {
			if (contrastPhases.length === 0) return 'With contrast (phases not specified)';
			const phaseLabels = {
				'pre': 'Pre-contrast',
				'arterial': 'Arterial',
				'portal_venous': 'Portal venous',
				'delayed': 'Delayed',
				'oral': 'Oral'
			};
			const phases = contrastPhases.map(p => phaseLabels[p] || p).join(', ');
			return `With contrast (${phases})`;
		}
		return 'Not specified';
	}
</script>

<div class="max-w-6xl mx-auto space-y-6 py-2">
	<!-- Header with gradient -->
	<div class="flex items-center justify-between mb-6">
		<div>
			<h2 class="text-3xl font-bold bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Quick Edit</h2>
			<p class="text-sm text-gray-400 mt-2 flex items-center gap-2">
				<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
				</svg>
				Make quick changes to your template
			</p>
		</div>
	</div>

	<!-- Essential Info & Scan Config - Two Column Layout -->
	<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
		<!-- Left Column: Essential Info -->
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-purple-500/30 transition-all duration-300 group">
			<div class="flex items-center gap-3 mb-6">
				<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-purple-600 shadow-lg shadow-purple-500/30">
					<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
				</div>
				<h3 class="text-sm font-bold text-white uppercase tracking-wider">Essential Information</h3>
			</div>
			
			<div class="space-y-5">
				<!-- Template Name -->
				<div class="group/field">
					<label class="flex items-center gap-2 text-xs font-medium text-gray-400 mb-2 uppercase tracking-wide">
						<svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
						</svg>
						Template Name <span class="text-red-400">*</span>
					</label>
					<input
						type="text"
						bind:value={templateName}
						oninput={handleChange}
						placeholder="Enter template name..."
						class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all group-hover/field:border-white/20"
						required
					/>
				</div>

				<!-- Description -->
				<div class="group/field">
					<label class="flex items-center gap-2 text-xs font-medium text-gray-400 mb-2 uppercase tracking-wide">
						<svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7" />
						</svg>
						Description
					</label>
					<textarea
						bind:value={description}
						oninput={handleChange}
						rows="3"
						placeholder="Brief description of this template..."
						class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all resize-none group-hover/field:border-white/20"
					></textarea>
				</div>

				<!-- Tags -->
				<div class="group/field">
					<label class="flex items-center gap-2 text-xs font-medium text-gray-400 mb-2 uppercase tracking-wide">
						<svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
						</svg>
						Tags
					</label>
					<div class="relative">
						<input
							type="text"
							bind:value={tagInput}
							oninput={handleTagInput}
							onkeydown={handleTagKeydown}
							onblur={handleTagBlur}
							placeholder="Type and press Enter..."
							class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all group-hover/field:border-white/20"
						/>
						{#if showTagSuggestions && tagSuggestions.length > 0}
							<div 
								class="absolute z-20 w-full mt-2 bg-gray-900 border border-white/10 rounded-lg shadow-2xl overflow-hidden animate-fade-in"
								onmousedown={(e) => e.preventDefault()}
							>
								{#each tagSuggestions as suggestion, index}
									<button
										type="button"
										onclick={() => {
											dispatch('selectSuggestion', suggestion);
											handleChange();
										}}
										class="w-full text-left px-4 py-2.5 hover:bg-white/5 {index === selectedSuggestionIndex ? 'bg-white/5' : ''} transition-colors"
										onmouseenter={() => selectedSuggestionIndex = index}
									>
										<span class="text-white text-sm">{suggestion}</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
					{#if tags.length > 0}
						<div class="flex flex-wrap gap-2 mt-3">
							{#each tags as tag, index}
								<span 
									class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-transform hover:scale-105"
									style="background-color: {getTagColor(tag, customTagColors)}; color: white;"
								>
									{tag}
									<button
										type="button"
										onclick={() => {
											dispatch('removeTag', index);
											handleChange();
										}}
										class="hover:bg-white/20 rounded-full p-0.5 transition-colors"
										aria-label="Remove tag"
									>
										<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
										</svg>
									</button>
								</span>
							{/each}
						</div>
					{/if}
				</div>

			</div>
		</section>

		<!-- Right Column: Scan Configuration -->
		<section class="bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 rounded-xl p-6 shadow-xl hover:border-blue-500/30 transition-all duration-300 group">
			<div class="flex items-center gap-3 mb-6">
				<div class="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 shadow-lg shadow-blue-500/30">
					<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" />
					</svg>
				</div>
				<h3 class="text-sm font-bold text-white uppercase tracking-wider">Scan Configuration</h3>
			</div>

			<div class="space-y-4">
				<!-- Scan Type -->
				<div class="bg-black/40 border border-white/10 rounded-lg p-4 hover:border-blue-400/30 hover:shadow-lg hover:shadow-blue-500/10 transition-all group/scan">
					<div class="flex items-center justify-between mb-2">
						<label class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wide">
							<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
							</svg>
							Scan Type
						</label>
						{#if !editingScanType}
							<button
								type="button"
								onclick={() => editingScanType = true}
								class="opacity-0 group-hover/scan:opacity-100 transition-opacity"
							>
								<svg class="w-4 h-4 text-gray-400 hover:text-blue-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
								</svg>
							</button>
						{/if}
					</div>
					{#if editingScanType}
						<input
							type="text"
							bind:value={scanType}
							onblur={() => {
								editingScanType = false;
								handleChange();
							}}
							onkeydown={(e) => {
								if (e.key === 'Enter') {
									editingScanType = false;
									handleChange();
								}
							}}
							class="w-full bg-transparent border-b border-purple-500 px-0 py-1 text-white placeholder-gray-600 focus:outline-none"
							placeholder="e.g., CT Chest"
							autofocus
						/>
					{:else}
						<p class="text-white">{scanType || 'Not specified'}</p>
					{/if}
				</div>

				<!-- Contrast -->
				<div class="bg-black/40 border border-white/10 rounded-lg p-4 hover:border-blue-400/30 hover:shadow-lg hover:shadow-blue-500/10 transition-all">
					<label class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
						<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
						</svg>
						Contrast Administration
					</label>
					
					<!-- Contrast Status -->
					<div class="flex gap-2 mb-3">
						{#each [
							{ value: 'no_contrast', label: 'Non-contrast', icon: '⭕' },
							{ value: 'with_contrast', label: 'With Contrast', icon: '💉' }
						] as option}
							<label class="contrast-pill cursor-pointer flex-1">
								<input
									type="radio"
									bind:group={contrast}
									value={option.value}
									onchange={handleChange}
									class="hidden"
								/>
								<span class="pill-btn {contrast === option.value ? 'selected' : ''} justify-center">
									<span class="pill-icon">{option.icon}</span>
									<span class="pill-label">{option.label}</span>
								</span>
							</label>
						{/each}
					</div>

					<!-- Phase Selection (only if contrast is used) -->
					{#if contrast === 'with_contrast'}
						<div class="mt-3 pt-3 border-t border-white/10">
							<label class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 block">
								Phases (select all that apply)
							</label>
							<div class="flex flex-wrap gap-2">
								{#each [
									{ value: 'pre', label: 'Pre-contrast', icon: '⚪' },
									{ value: 'arterial', label: 'Arterial', icon: '🔴' },
									{ value: 'portal_venous', label: 'Portal venous', icon: '🟣' },
									{ value: 'delayed', label: 'Delayed', icon: '🔵' },
									{ value: 'oral', label: 'Oral', icon: '🥤' }
								] as phase}
									<label class="phase-pill cursor-pointer">
										<input
											type="checkbox"
											bind:group={contrastPhases}
											value={phase.value}
											onchange={handleChange}
											class="hidden"
										/>
										<span class="pill-btn-small {contrastPhases.includes(phase.value) ? 'selected' : ''}">
											<span class="pill-icon">{phase.icon}</span>
											<span class="pill-label">{phase.label}</span>
										</span>
									</label>
								{/each}
							</div>
						</div>
					{/if}
				</div>

				<!-- Protocol -->
				<div class="bg-black/40 border border-white/10 rounded-lg p-4 hover:border-blue-400/30 hover:shadow-lg hover:shadow-blue-500/10 transition-all group/protocol">
					<div class="flex items-center justify-between mb-2">
						<label class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wide">
							<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
							</svg>
							Additional Protocol Details
						</label>
						{#if !editingProtocol}
							<button
								type="button"
								onclick={() => editingProtocol = true}
								class="opacity-0 group-hover/protocol:opacity-100 transition-opacity"
							>
								<svg class="w-4 h-4 text-gray-400 hover:text-blue-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
								</svg>
							</button>
						{/if}
					</div>
					{#if editingProtocol}
						<textarea
							bind:value={protocolDetails}
							onblur={() => {
								editingProtocol = false;
								handleChange();
							}}
							rows="3"
							placeholder="Details..."
							class="w-full bg-transparent border-b border-purple-500 px-0 py-1 text-white placeholder-gray-600 focus:outline-none resize-none text-sm"
							autofocus
						></textarea>
					{:else}
						<p class="text-white text-sm">{protocolDetails || 'Not specified'}</p>
					{/if}
				</div>
			</div>
		</section>
	</div>

	<!-- Report Structure -->
	<section class="bg-white/[0.02] border border-white/5 hover:border-emerald-500/30 rounded-2xl p-6 backdrop-blur-sm transition-all duration-300">
		<div class="mb-5">
			<div class="flex items-center gap-3 mb-1.5">
				<div class="flex items-center justify-center w-7 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
					<svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
					</svg>
				</div>
				<h3 class="text-lg font-semibold text-white">Report Structure</h3>
			</div>
			<p class="text-gray-400 text-xs pl-10">
				Select sections to include and use arrows to reorder.
			</p>
		</div>

		<!-- Sections List -->
		<div class="space-y-1.5">
			{#each normalizedSectionOrder as section, index}
				{@const config = getSectionConfig(section.id)}
				{@const defaultSection = DEFAULT_SECTION_ORDER.find(d => d.id === section.id)}
				{@const isRequired = section.required === true || (defaultSection && defaultSection.required === true)}
				{@const isIncluded = isRequired || (config && config.included)}
				
				<div class="group flex items-start gap-3 px-3.5 py-2.5 rounded-xl transition-all duration-200 {isRequired ? 'bg-purple-500/[0.06] border border-purple-500/20' : 'bg-white/[0.03] border border-white/[0.06] hover:border-white/10 hover:bg-white/[0.05]'}">
					<!-- Reorder Buttons (only for optional sections) -->
					{#if !isRequired}
						<div class="flex flex-col gap-0.5 pt-0.5 opacity-50 group-hover:opacity-100 transition-opacity">
							<button
								type="button"
								onclick={() => moveUp(index)}
								disabled={index === 0}
								class="text-gray-400 hover:text-emerald-400 disabled:opacity-20 disabled:cursor-not-allowed text-[10px] leading-none w-3.5 h-3 flex items-center justify-center transition-colors"
								title="Move up"
							>
								▲
							</button>
							<button
								type="button"
								onclick={() => moveDown(index)}
								disabled={index === normalizedSectionOrder.length - 1}
								class="text-gray-400 hover:text-emerald-400 disabled:opacity-20 disabled:cursor-not-allowed text-[10px] leading-none w-3.5 h-3 flex items-center justify-center transition-colors"
								title="Move down"
							>
								▼
							</button>
						</div>
					{:else}
						<div class="w-3.5"></div>
					{/if}

					<!-- Checkbox -->
					{#if section.id === 'comparison'}
						<input
							type="checkbox"
							bind:checked={sections.comparison.included}
							onchange={handleChange}
							class="w-4 h-4 rounded border-white/20 text-emerald-500 focus:ring-2 focus:ring-emerald-500/30 flex-shrink-0 mt-0.5 cursor-pointer transition-all"
						/>
					{:else if section.id === 'technique'}
						<input
							type="checkbox"
							bind:checked={sections.technique.included}
							onchange={handleChange}
							class="w-4 h-4 rounded border-white/20 text-emerald-500 focus:ring-2 focus:ring-emerald-500/30 flex-shrink-0 mt-0.5 cursor-pointer transition-all"
						/>
					{:else if section.id === 'limitations'}
						<input
							type="checkbox"
							bind:checked={sections.limitations.included}
							onchange={handleChange}
							class="w-4 h-4 rounded border-white/20 text-emerald-500 focus:ring-2 focus:ring-emerald-500/30 flex-shrink-0 mt-0.5 cursor-pointer transition-all"
						/>
					{:else}
						<!-- Required sections (clinical_history, findings, impression) -->
						<div class="w-4 h-4 rounded border border-purple-500/30 bg-purple-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
							<svg class="w-2.5 h-2.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
							</svg>
						</div>
					{/if}

					<!-- Section Info -->
					<div class="flex-1 min-w-0 flex flex-col gap-1.5">
						<div class="flex items-center justify-between gap-2 flex-wrap">
							<div class="flex items-center gap-2.5 flex-wrap">
								<span class="text-white font-medium text-sm tracking-wide">{section.name}</span>
								{#if isRequired}
									<div class="flex items-center gap-1.5">
										<span class="text-[10px] text-purple-400 font-medium uppercase tracking-wider bg-purple-500/10 px-1.5 py-0.5 rounded">required</span>
										{#if section.description === 'Manual input'}
											<span class="flex items-center gap-1 text-[10px] text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
												<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
												<span>Manual</span>
											</span>
										{:else if section.description === 'Auto-generated'}
											<span class="flex items-center gap-1 text-[10px] text-purple-300 bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 rounded">
												<svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
												</svg>
												<span>Auto-generated</span>
											</span>
										{/if}
									</div>
								{:else}
									<span class="text-[11px] text-gray-500 font-normal">{section.description}</span>
								{/if}
							</div>
							
							<!-- Configure buttons for FINDINGS and IMPRESSION - aligned to the right -->
							{#if section.id === 'findings' || section.id === 'impression'}
								<button
									type="button"
									onclick={() => dispatch('switchTab', section.id === 'findings' ? 'findings' : 'impression')}
									class="px-3 py-1 text-xs font-medium text-emerald-300 hover:text-emerald-200 bg-emerald-500/10 hover:bg-emerald-500/15 border border-emerald-500/20 hover:border-emerald-500/30 rounded-lg transition-all flex-shrink-0 group/config"
								>
									Configure
									<span class="inline-block transition-transform group-hover/config:translate-x-0.5">→</span>
								</button>
							{/if}
						</div>
						
						<!-- Additional Options (with smooth expansion) -->
						{#if section.id === 'clinical_history' && (isRequired || sections.clinical_history.include_in_output !== undefined)}
							<div class="mt-2.5 animate-slideDown">
								<label class="flex items-center gap-2 cursor-pointer px-2 py-1.5 rounded-lg hover:bg-white/[0.02] transition-colors">
									<input
										type="checkbox"
										bind:checked={sections.clinical_history.include_in_output}
										onchange={handleChange}
										class="w-3.5 h-3.5 rounded border-white/20 text-emerald-500 focus:ring-2 focus:ring-emerald-500/30 cursor-pointer transition-all"
									/>
									<span class="text-xs text-gray-400">Include in report output</span>
								</label>
							</div>
						{/if}
						
						{#if section.id === 'comparison' && sections.comparison.included}
							<div class="mt-2.5 animate-slideDown space-y-2.5">
								<!-- Segmented Control with Icons -->
								<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
									<button
										type="button"
										onclick={() => { sections.comparison.has_input_field = true; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.comparison.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
										</svg>
										<span>Manual input</span>
									</button>
									<button
										type="button"
										onclick={() => { sections.comparison.has_input_field = false; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {!sections.comparison.has_input_field ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
										</svg>
										<span>Auto-generated</span>
									</button>
								</div>
							</div>
						{/if}
						
						{#if section.id === 'technique' && sections.technique.included}
							<div class="mt-2.5 animate-slideDown">
								<!-- Segmented Control with Icons -->
								<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
									<button
										type="button"
										onclick={() => { sections.technique.has_input_field = true; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.technique.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
										</svg>
										<span>Manual input</span>
									</button>
									<button
										type="button"
										onclick={() => { sections.technique.has_input_field = false; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {!sections.technique.has_input_field ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
										</svg>
										<span>Auto-generated</span>
									</button>
								</div>
							</div>
						{/if}
						
						{#if section.id === 'limitations' && sections.limitations.included}
							<div class="mt-2.5 animate-slideDown space-y-2.5">
								<!-- Segmented Control with Icons -->
								<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
									<button
										type="button"
										onclick={() => { sections.limitations.has_input_field = true; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.limitations.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
										</svg>
										<span>Manual input</span>
									</button>
									<button
										type="button"
										onclick={() => { sections.limitations.has_input_field = false; handleChange(); }}
										class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {!sections.limitations.has_input_field ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
										</svg>
										<span>Auto-generated</span>
									</button>
								</div>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	</section>

	<!-- Global Custom Instructions -->
	<section class="bg-white/[0.02] border border-white/5 hover:border-purple-500/30 rounded-2xl p-6 backdrop-blur-sm transition-all duration-300">
		<div class="mb-5">
			<div class="flex items-center gap-3 mb-1.5">
				<div class="flex items-center justify-center w-7 h-7 rounded-lg bg-purple-500/10 border border-purple-500/20">
					<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
					</svg>
				</div>
				<h3 class="text-lg font-semibold text-white">Template-Wide Instructions</h3>
			</div>
			<p class="text-gray-400 text-xs pl-10">
				Apply instructions to all sections of this template for consistent terminology and reporting requirements.
			</p>
		</div>

		<div class="space-y-4">
			<textarea
				bind:value={globalCustomInstructions}
				oninput={handleChange}
				rows="4"
				placeholder="e.g., Always report lymph node stations. Use 'tumour' not 'mass'..."
				class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all resize-none"
			></textarea>

			<!-- Hint Box -->
			<div class="bg-purple-500/10 border border-purple-500/20 rounded-lg p-4">
				<div class="flex items-start gap-3">
					<svg class="w-5 h-5 text-purple-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
					<div class="flex-1">
						<div class="text-xs font-semibold text-purple-300 uppercase tracking-wide mb-2">HINT</div>
						<div class="text-xs text-gray-300">
							<p>These instructions apply to all sections of this template for consistent terminology and reporting requirements.</p>
						</div>
					</div>
				</div>
			</div>
		</div>
	</section>

</div>

<style>
	.line-clamp-2 {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	@keyframes slideDown {
		from {
			opacity: 0;
			max-height: 0;
			transform: translateY(-10px);
		}
		to {
			opacity: 1;
			max-height: 200px;
			transform: translateY(0);
		}
	}

	.animate-slideDown {
		animation: slideDown 0.3s ease-out forwards;
	}

	/* Ensure disabled checked checkboxes show the checkmark */
	input[type="checkbox"]:disabled:checked {
		opacity: 1;
		background-color: rgb(147, 51, 234); /* purple-600 */
		border-color: rgb(147, 51, 234);
	}

	input[type="checkbox"]:disabled:checked::after {
		content: '';
		display: block;
		width: 4px;
		height: 8px;
		border: solid white;
		border-width: 0 2px 2px 0;
		transform: rotate(45deg);
		position: absolute;
		left: 6px;
		top: 2px;
	}

	/* Contrast Pills */
	.contrast-pill,
	.phase-pill {
		display: inline-block;
	}

	.pill-btn {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.875rem;
		font-size: 0.8125rem;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.5rem;
		color: rgba(255, 255, 255, 0.7);
		transition: all 0.2s ease;
		white-space: nowrap;
	}

	.pill-btn:hover {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(139, 92, 246, 0.4);
		color: white;
		transform: translateY(-1px);
		box-shadow: 0 4px 8px rgba(139, 92, 246, 0.2);
	}

	.pill-btn.selected {
		background: rgba(139, 92, 246, 0.3);
		border-color: rgb(139, 92, 246);
		color: white;
		font-weight: 500;
		box-shadow: 0 2px 8px rgba(139, 92, 246, 0.3);
	}

	/* Smaller pills for phases */
	.pill-btn-small {
		display: flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.375rem 0.625rem;
		font-size: 0.75rem;
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 0.375rem;
		color: rgba(255, 255, 255, 0.7);
		transition: all 0.2s ease;
		white-space: nowrap;
	}

	.pill-btn-small:hover {
		background: rgba(255, 255, 255, 0.1);
		border-color: rgba(59, 130, 246, 0.4);
		color: white;
		transform: translateY(-1px);
		box-shadow: 0 4px 8px rgba(59, 130, 246, 0.2);
	}

	.pill-btn-small.selected {
		background: rgba(59, 130, 246, 0.3);
		border-color: rgb(59, 130, 246);
		color: white;
		font-weight: 500;
		box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
	}

	.pill-icon {
		font-size: 1rem;
		line-height: 1;
	}

	.pill-label {
		font-size: 0.8125rem;
		line-height: 1;
	}
</style>
