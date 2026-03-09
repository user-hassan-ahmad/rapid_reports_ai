<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { tagsStore } from '$lib/stores/tags';
	import { getTagColor } from '$lib/utils/tagColors.js';

	const dispatch = createEventDispatcher();

	// Scan info (from Step1_ScanInfo)
	export let scanType = '';
	export let contrast = '';
	export let contrastOther = '';
	export let contrastPhases = [];
	export let protocolDetails = '';

	// Template metadata (from Step7_Save)
	export let templateName = '';
	export let description = '';
	export let tags = [];
	export let isPinned = false;
	export let globalCustomInstructions = '';

	export let editingTemplate = null;

	let newTag = '';
	let showTagSuggestions = false;
	let tagSuggestions = [];
	let selectedSuggestionIndex = -1;
	let blurTimeout = null;

	$: existingTags = $tagsStore.tags || [];

	function updateTagSuggestions() {
		if (!newTag || !newTag.trim()) {
			tagSuggestions = [];
			showTagSuggestions = false;
			selectedSuggestionIndex = -1;
			return;
		}
		const inputLower = newTag.toLowerCase();
		tagSuggestions = existingTags
			.filter(tag => tag.toLowerCase().includes(inputLower))
			.filter(tag => !tags.some(t => t.toLowerCase() === tag.toLowerCase()))
			.slice(0, 8);
		showTagSuggestions = tagSuggestions.length > 0;
		selectedSuggestionIndex = -1;
	}

	$: if (newTag && newTag.trim() && existingTags.length > 0) {
		updateTagSuggestions();
	} else if (!newTag || !newTag.trim()) {
		tagSuggestions = [];
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
	}

	function handleTagBlur() {
		if (blurTimeout) clearTimeout(blurTimeout);
		blurTimeout = setTimeout(() => {
			showTagSuggestions = false;
			blurTimeout = null;
		}, 200);
	}

	function cancelBlur() {
		if (blurTimeout) {
			clearTimeout(blurTimeout);
			blurTimeout = null;
		}
	}

	function addTag(tagValue = null) {
		const tagToAdd = tagValue || newTag.trim();
		if (!tagToAdd) return;
		const existingTag = existingTags.find(t => t.toLowerCase() === tagToAdd.toLowerCase());
		const finalTag = existingTag || tagToAdd;
		if (tags.some(t => t.toLowerCase() === finalTag.toLowerCase())) return;
		cancelBlur();
		tags = [...tags, finalTag];
		newTag = '';
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
	}

	function removeTag(tag) {
		tags = tags.filter(t => t !== tag);
	}

	function handleTagInput(e) {
		newTag = e.target.value;
		updateTagSuggestions();
	}

	function handleTagKeydown(e) {
		if (e.key === 'Enter' || e.key === ',') {
			e.preventDefault();
			cancelBlur();
			if (showTagSuggestions && selectedSuggestionIndex >= 0 && tagSuggestions[selectedSuggestionIndex]) {
				addTag(tagSuggestions[selectedSuggestionIndex]);
			} else {
				addTag();
			}
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			if (showTagSuggestions && tagSuggestions.length > 0) {
				selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, tagSuggestions.length - 1);
			}
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1);
		} else if (e.key === 'Escape') {
			showTagSuggestions = false;
		}
	}

	function handleContrastChange() {
		if (contrast === 'no_contrast') contrastPhases = [];
	}

	function handleNext() {
		if (!scanType?.trim() || !contrast || !templateName?.trim()) return;
		dispatch('next');
	}

	$: canProceed = scanType.trim() !== '' && contrast !== '' && templateName.trim() !== '';

	onMount(async () => {
		if (!$tagsStore.tags || $tagsStore.tags.length === 0) {
			await tagsStore.loadTags();
		}
	});
</script>

<div class="space-y-8">
	<h3 class="text-xl font-semibold text-white mb-4">Template Basics</h3>
	<p class="text-gray-400 text-sm mb-6">
		Provide scan information and template metadata. You can refine section configuration in the next steps.
	</p>

	<!-- Section: Scan Information -->
	<section class="space-y-4">
		<h4 class="text-sm font-medium text-gray-400 uppercase tracking-wide">Scan Information</h4>
		<div class="space-y-4">
			<div>
				<label class="block text-sm font-medium text-gray-300 mb-2">
					Scan Type <span class="text-red-400">*</span>
				</label>
				<input
					type="text"
					bind:value={scanType}
					placeholder="e.g., Chest CT, MRI Brain, CT Abdomen Pelvis"
					class="input-dark"
					required
				/>
			</div>

			<div class="bg-black/40 border border-white/10 rounded-lg p-4 hover:border-blue-400/30 hover:shadow-lg hover:shadow-blue-500/10 transition-all">
				<label class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
					<svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
					</svg>
					Contrast Administration <span class="text-red-400">*</span>
				</label>
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
								onchange={handleContrastChange}
								class="hidden"
							/>
							<span class="pill-btn {contrast === option.value ? 'selected' : ''} justify-center">
								<span class="pill-icon">{option.icon}</span>
								<span class="pill-label">{option.label}</span>
							</span>
						</label>
					{/each}
				</div>
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
									<input type="checkbox" bind:group={contrastPhases} value={phase.value} class="hidden" />
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

			<div>
				<label class="block text-sm font-medium text-gray-300 mb-2">
					Additional protocol details <span class="text-gray-500 text-xs">(optional)</span>
				</label>
				<textarea
					bind:value={protocolDetails}
					placeholder="e.g., 3mm slices, delayed phase, DWI sequences"
					rows="2"
					class="input-dark"
					onkeydown={(e) => e.key === 'Enter' && e.stopPropagation()}
				></textarea>
			</div>
		</div>
	</section>

	<!-- Section: Template Details -->
	<section class="space-y-4 pt-4 border-t border-white/10">
		<h4 class="text-sm font-medium text-gray-400 uppercase tracking-wide">Template Details</h4>
		<div class="space-y-4">
			<div>
				<label class="block text-sm font-medium text-gray-300 mb-2">
					Template Name <span class="text-red-400">*</span>
				</label>
				<input
					type="text"
					bind:value={templateName}
					placeholder="e.g., CT Chest - Oncology"
					class="input-dark"
					required
				/>
			</div>

			<div>
				<label class="block text-sm font-medium text-gray-300 mb-2">
					Description <span class="text-gray-500 text-xs">(optional)</span>
				</label>
				<textarea
					bind:value={description}
					rows="2"
					placeholder="Brief description of this template"
					class="input-dark"
					onkeydown={(e) => e.key === 'Enter' && e.stopPropagation()}
				></textarea>
			</div>

			<div>
				<label class="block text-sm font-medium text-gray-300 mb-2">Tags</label>
				<div class="flex flex-wrap gap-2 mb-2">
					{#each tags as tag}
						<span
							class="inline-flex items-center gap-1 px-2 py-1 rounded text-sm"
							style="background-color: {getTagColor(tag, {})}; color: white;"
						>
							{tag}
							<button
								onclick={() => removeTag(tag)}
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
				<div class="relative flex gap-2">
					<div class="flex-1 relative">
						<input
							type="text"
							bind:value={newTag}
							oninput={handleTagInput}
							onkeydown={handleTagKeydown}
							onblur={handleTagBlur}
							placeholder="Type and press Enter..."
							class="input-dark w-full"
						/>
						{#if showTagSuggestions && tagSuggestions.length > 0}
							<div
								class="absolute z-20 w-full mt-2 bg-gray-900 border border-white/10 rounded-lg shadow-2xl overflow-hidden animate-fade-in"
								onmousedown={(e) => e.preventDefault()}
							>
								{#each tagSuggestions as suggestion, index}
									<button
										type="button"
										onclick={() => addTag(suggestion)}
										class="w-full text-left px-4 py-2.5 hover:bg-white/5 {index === selectedSuggestionIndex ? 'bg-white/5' : ''} transition-colors"
										onmouseenter={() => selectedSuggestionIndex = index}
									>
										<span class="text-white text-sm">{suggestion}</span>
									</button>
								{/each}
							</div>
						{/if}
					</div>
					<button type="button" onclick={() => addTag()} class="btn-secondary">Add</button>
				</div>
			</div>

			<div class="bg-white/[0.02] border border-white/5 hover:border-purple-500/30 rounded-xl p-4 transition-all">
				<label class="block text-sm font-medium text-gray-300 mb-2">
					Template-Wide Instructions <span class="text-gray-500 text-xs">(optional)</span>
				</label>
				<textarea
					bind:value={globalCustomInstructions}
					rows="3"
					placeholder="e.g., Always report lymph node stations. Use 'tumour' not 'mass'..."
					class="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 focus:ring-2 focus:ring-purple-500/30 transition-all resize-none"
					onkeydown={(e) => e.key === 'Enter' && e.stopPropagation()}
				></textarea>
				<p class="text-xs text-gray-500 mt-2">
					Apply instructions to all sections for consistent terminology and reporting requirements.
				</p>
			</div>
		</div>
	</section>

	<div class="flex justify-end pt-4">
		<button
			onclick={handleNext}
			disabled={!canProceed}
			class="btn-primary"
			class:opacity-50={!canProceed}
			class:cursor-not-allowed={!canProceed}
		>
			Next →
		</button>
	</div>
</div>

<style>
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
