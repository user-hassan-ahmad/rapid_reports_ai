<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { tagsStore } from '$lib/stores/tags';
	import { getTagColor } from '$lib/utils/tagColors.js';

	const dispatch = createEventDispatcher();

	export let templateName = '';
	export let description = '';
	export let tags = [];
	export let isPinned = false;
	export let globalCustomInstructions = '';
	export let templateConfig = {};
	export let editingTemplate = null; // Template being edited

	let newTag = '';
	let saving = false;
	let error = null;
	let showTagSuggestions = false;
	let tagSuggestions = [];
	let selectedSuggestionIndex = -1;
	
	// Subscribe to tags store for autocomplete
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
	
	// Reactive statement to update suggestions when existingTags or newTag changes
	$: if (newTag && newTag.trim() && existingTags.length > 0) {
		updateTagSuggestions();
	} else if (!newTag || !newTag.trim()) {
		// Hide suggestions when input is cleared
		tagSuggestions = [];
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
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

	function addTag(tagValue = null) {
		const tagToAdd = tagValue || newTag.trim();
		if (!tagToAdd) return;

		const existingTag = existingTags.find(
			t => t.toLowerCase() === tagToAdd.toLowerCase()
		);

		const finalTag = existingTag || tagToAdd;

		const isDuplicate = tags.some(t => t.toLowerCase() === finalTag.toLowerCase());
		if (isDuplicate) {
			return;
		}

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
			// Cancel any pending blur timeout
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

	async function saveTemplate() {
		if (!templateName.trim()) {
			error = 'Template name is required';
			return;
		}

		saving = true;
		error = null;

		try {
			const url = editingTemplate 
				? `${API_URL}/api/templates/${editingTemplate.id}`
				: `${API_URL}/api/templates`;
			const method = editingTemplate ? 'PUT' : 'POST';

			const response = await fetch(url, {
				method: method,
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({
					name: templateName,
					description: description || null,
					tags: tags,
					template_config: templateConfig,
					is_pinned: false
				})
			});

			const data = await response.json();
			if (data.success) {
				// Refresh tags after saving template (tags may have changed)
				await tagsStore.refreshTags();
				dispatch('saveComplete');
			} else {
				error = data.error || `Failed to ${editingTemplate ? 'update' : 'save'} template`;
			}
		} catch (err) {
			console.error('Error saving template:', err);
			error = `Error ${editingTemplate ? 'updating' : 'saving'} template. Please try again.`;
		} finally {
			saving = false;
		}
	}
	
	onMount(async () => {
		// Load tags from store
		if (!$tagsStore.tags || $tagsStore.tags.length === 0) {
			await tagsStore.loadTags();
		}
	});
</script>

<div class="space-y-6">
	<h3 class="text-xl font-semibold text-white mb-4">{editingTemplate ? 'Update Template' : 'Save Template'}</h3>
	<p class="text-gray-400 text-sm mb-6">
		{editingTemplate ? 'Update your template name and tags.' : 'Give your template a name and add tags for easy organization.'}
	</p>

	<div class="space-y-4">
		<!-- Template Name -->
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

		<!-- Description -->
		<div>
			<label class="block text-sm font-medium text-gray-300 mb-2">
				Description <span class="text-gray-500 text-xs">(optional)</span>
			</label>
			<textarea
				bind:value={description}
				rows="2"
				placeholder="Brief description of this template"
				class="input-dark"
			></textarea>
		</div>

		<!-- Tags -->
		<div>
			<label class="block text-sm font-medium text-gray-300 mb-2">
				Tags:
			</label>
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
				<button
					onclick={() => addTag()}
					class="btn-secondary"
				>
					Add
				</button>
			</div>
		</div>

		<!-- Template-Wide Instructions -->
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

		<!-- Error Message -->
		{#if error}
			<div class="p-3 bg-red-600/20 border border-red-600/50 rounded text-red-300 text-sm">
				{error}
			</div>
		{/if}
	</div>

	<!-- Save Button -->
	<div class="flex justify-end mt-6">
		<button
			onclick={saveTemplate}
			disabled={saving || !templateName.trim()}
			class="btn-primary"
			class:opacity-50={saving || !templateName.trim()}
		>
			{saving ? (editingTemplate ? 'Updating...' : 'Saving...') : (editingTemplate ? '💾 Update Template' : '💾 Save Template')}
		</button>
	</div>
</div>

