<script>
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import { onMount } from 'svelte';

	export let sections = {
		comparison: { included: false, has_input_field: true },
		technique: { included: false, has_input_field: false },
		limitations: { included: false, has_input_field: true },
		clinical_history: { include_in_output: false }
	};

	// Accept initial section order from parent (for edit mode)
	export let initialSectionOrder = null;

	// Default section order (required sections first, then optional)
	const DEFAULT_SECTION_ORDER = [
		{ id: 'clinical_history', name: 'CLINICAL HISTORY', required: true, description: 'Manual input' },
		{ id: 'comparison', name: 'COMPARISON', required: false, description: 'Optional' },
		{ id: 'technique', name: 'TECHNIQUE', required: false, description: 'Optional' },
		{ id: 'limitations', name: 'LIMITATIONS', required: false, description: 'Optional' },
		{ id: 'findings', name: 'FINDINGS', required: true, description: 'Manual input' },
		{ id: 'impression', name: 'IMPRESSION', required: true, description: 'Auto-generated' }
	];

	// Normalize section order - preserve order but enrich with required flags and descriptions
	function normalizeSectionOrder(order) {
		if (!order || order.length === 0) {
			return [...DEFAULT_SECTION_ORDER];
		}
		
		const idMap = {};
		DEFAULT_SECTION_ORDER.forEach(s => {
			idMap[s.id] = s;
		});
		
		// Preserve order from input, but enrich with required flags, names, and descriptions
		const normalized = order.map(item => {
			const defaultSection = idMap[item.id];
			if (defaultSection) {
				return {
					...item,
					name: defaultSection.name, // Always use default name for consistent display
					required: defaultSection.required,
					description: defaultSection.description // Always use default description for consistency
				};
			}
			return item;
		});
		
		// Add any missing sections from defaults at the end
		const existingIds = new Set(normalized.map(s => s.id));
		for (const defaultSection of DEFAULT_SECTION_ORDER) {
			if (!existingIds.has(defaultSection.id)) {
				normalized.push({ ...defaultSection });
			}
		}
		
		return normalized;
	}
	
	// Initialize sectionOrder once - use initialSectionOrder if provided, otherwise use default
	// Only initialize on mount or when initialSectionOrder is first set
	let sectionOrder = null;
	let initialized = false;
	
	onMount(() => {
		if (!initialized) {
			sectionOrder = normalizeSectionOrder(initialSectionOrder);
			initialized = true;
		}
	});
	
	// Also handle case where initialSectionOrder is set before mount
	$: if (initialSectionOrder && !initialized) {
		sectionOrder = normalizeSectionOrder(initialSectionOrder);
		initialized = true;
	} else if (!initialSectionOrder && !initialized) {
		sectionOrder = [...DEFAULT_SECTION_ORDER];
		initialized = true;
	}

	function moveUp(index) {
		if (index === 0) return;
		const currentSection = sectionOrder[index];
		// Don't allow moving required sections
		if (currentSection?.required) return;
		
		// Optional sections can move freely - swap with the section above
		// Required sections maintain their relative order because they can't be moved
		[sectionOrder[index], sectionOrder[index - 1]] = [sectionOrder[index - 1], sectionOrder[index]];
	}

	function moveDown(index) {
		if (index === sectionOrder.length - 1) return;
		const currentSection = sectionOrder[index];
		// Don't allow moving required sections
		if (currentSection?.required) return;
		
		// Optional sections can move freely - swap with the section below
		// Required sections maintain their relative order because they can't be moved
		[sectionOrder[index], sectionOrder[index + 1]] = [sectionOrder[index + 1], sectionOrder[index]];
	}

	function handleNext() {
		dispatch('next', sectionOrder);
	}

	function getSectionConfig(id) {
		if (id === 'clinical_history') return sections.clinical_history;
		if (id === 'comparison') return sections.comparison;
		if (id === 'technique') return sections.technique;
		if (id === 'limitations') return sections.limitations;
		return null;
	}
</script>

<div class="space-y-3">
	<h3 class="text-xl font-semibold text-white mb-1">Report Structure</h3>
	<p class="text-gray-400 text-xs mb-4">
		Select sections to include and use arrows to reorder. Required sections are always included.
	</p>

	<!-- Sections List -->
	<div class="space-y-1.5">
		{#each sectionOrder as section, index}
			{@const config = getSectionConfig(section.id)}
			{@const isRequired = section.required}
			{@const isIncluded = isRequired || (config && config.included)}
			
			<div class="flex items-start gap-2.5 p-2 rounded-lg border {isRequired ? 'border-purple-500/30 bg-purple-500/10 backdrop-blur-sm' : 'border-white/10 bg-white/10 backdrop-blur-sm'} hover:border-white/20 transition-all">
				<!-- Reorder Buttons (only for optional sections) -->
				{#if !isRequired}
					<div class="flex flex-col gap-0.5 pt-0.5">
						<button
							onclick={() => moveUp(index)}
							disabled={index === 0}
							class="text-gray-500 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed text-xs leading-none w-4 h-3 flex items-center justify-center"
							title="Move up"
						>
							▲
						</button>
						<button
							onclick={() => moveDown(index)}
							disabled={index === sectionOrder.length - 1}
							class="text-gray-500 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed text-xs leading-none w-4 h-3 flex items-center justify-center"
							title="Move down"
						>
							▼
						</button>
					</div>
				{:else}
					<div class="w-4"></div>
				{/if}

				<!-- Checkbox -->
				{#if section.id === 'comparison'}
					<input
						type="checkbox"
						bind:checked={sections.comparison.included}
						class="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5"
					/>
				{:else if section.id === 'technique'}
					<input
						type="checkbox"
						bind:checked={sections.technique.included}
						class="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5"
					/>
				{:else if section.id === 'limitations'}
					<input
						type="checkbox"
						bind:checked={sections.limitations.included}
						class="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5"
					/>
				{:else}
					<input
						type="checkbox"
						checked={isIncluded}
						disabled={isRequired}
						class="w-4 h-4 text-purple-600 flex-shrink-0 mt-0.5"
					/>
				{/if}

				<!-- Section Info -->
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 flex-wrap">
						<span class="text-white font-medium text-sm">{section.name}</span>
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
							<span class="text-xs text-gray-500">{section.description}</span>
						{/if}
					</div>
					
					<!-- Additional Options (with smooth expansion) -->
					{#if section.id === 'clinical_history' && (isRequired || sections.clinical_history.include_in_output !== undefined)}
						<div class="mt-2 animate-slideDown">
							<label class="flex items-center gap-2 cursor-pointer p-2 rounded bg-black/30 hover:bg-black/40 transition-colors">
								<input
									type="checkbox"
									bind:checked={sections.clinical_history.include_in_output}
									class="w-3.5 h-3.5 text-purple-600"
								/>
								<span class="text-xs text-gray-300">Include in report output</span>
							</label>
						</div>
					{/if}
					
					{#if section.id === 'comparison' && sections.comparison.included}
						<div class="mt-2 animate-slideDown space-y-2">
							<!-- Segmented Control with Icons -->
							<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
								<button
									type="button"
									onclick={() => sections.comparison.has_input_field = true}
									class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.comparison.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
								>
									<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
									</svg>
									<span>Manual input</span>
								</button>
								<button
									type="button"
									onclick={() => sections.comparison.has_input_field = false}
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
						<div class="mt-2 animate-slideDown">
							<!-- Segmented Control with Icons -->
							<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
								<button
									type="button"
									onclick={() => sections.technique.has_input_field = true}
									class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.technique.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
								>
									<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
									</svg>
									<span>Manual input</span>
								</button>
								<button
									type="button"
									onclick={() => sections.technique.has_input_field = false}
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
						<div class="mt-2 animate-slideDown space-y-2">
							<!-- Segmented Control with Icons -->
							<div class="inline-flex bg-white/[0.03] border border-white/10 rounded-lg p-0.5 gap-0.5">
								<button
									type="button"
									onclick={() => sections.limitations.has_input_field = true}
									class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200 {sections.limitations.has_input_field ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm' : 'text-gray-400 hover:text-gray-300 hover:bg-white/[0.02]'}"
								>
									<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
									</svg>
									<span>Manual input</span>
								</button>
								<button
									type="button"
									onclick={() => sections.limitations.has_input_field = false}
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

	<!-- Next Button -->
	<div class="flex justify-end mt-5">
		<button
			onclick={handleNext}
			class="btn-primary"
		>
			Next →
		</button>
	</div>
</div>

<style>
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
</style>
