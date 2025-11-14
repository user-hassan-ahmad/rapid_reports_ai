<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import VersionHistory from './VersionHistory.svelte';
	import { API_URL } from '$lib/config';

	export let editingTemplate = null;
	export let selectedModel = 'claude';
	export let cameFromTab = null;

	let showVersionHistory = false;
	let versionHistoryRefreshKey = 0; // Used to trigger version history refresh

	const dispatch = createEventDispatcher();

	let name = '';
	let description = '';
	let tags = [];
	let tagInput = '';
	let existingTags = [];
	let showTagSuggestions = false;
	let tagSuggestions = [];
	let selectedSuggestionIndex = -1;
	let templateContent = '';
	let masterPromptInstructions = '';
	let variables = [];
	let customTagColors = {};

	// Example template to show in placeholder
	const examplePlaceholder = `Comparison:

{{COMPARISON}}

Limitations:

{{LIMITATIONS}}

Findings:

Main body of report

Comment first on brain parenchyma, specifically any infarcts, haemorrhage, lesions and mass effect.

Then CSF spaces and midline structures.

Then bones, orbits, paranasal sinuses.

Impression:`;
	const exampleInfo = `Describe the structure/approach for your report to follow, be as specific or general as needed.
Use {{VARIABLE_NAME}} for dynamic content (e.g., {{COMPARISON}}) — these will create form fields when using the template. The {{FINDINGS}} and {{CLINICAL_HISTORY}} fields are added automatically.`

	function extractVariables(text) {
		const regex = /\{\{(\w+)\}\}/g;
		const matches = [];
		let match;
		while ((match = regex.exec(text)) !== null) {
			if (!matches.includes(match[1])) {
				matches.push(match[1]);
			}
		}
		return matches;
	}

	// Load user settings for custom tag colors
	async function loadUserSettings() {
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/settings`, {
				headers
			});
			
			if (response.ok) {
				const data = await response.json();
				if (data.success && data.tag_colors) {
					customTagColors = data.tag_colors || {};
				}
			}
		} catch (err) {
			console.error('Failed to load user settings:', err);
		}
	}

	// Load existing tags for autocomplete
	async function loadExistingTags() {
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/tags`, {
				headers
			});
			const data = await response.json();
			if (data.success) {
				existingTags = data.tags || [];
			}
		} catch (err) {
			console.error('Failed to load tags:', err);
		}
	}

	// Track the last template ID to only initialize once per template
	let lastTemplateId = null;
	
	// Reactive initialization - watch for editingTemplate changes
	// Only initialize when editingTemplate actually changes to a different template
	$: if (editingTemplate) {
		// Only initialize if this is a different template than we've seen
		if (editingTemplate.id !== lastTemplateId) {
			lastTemplateId = editingTemplate.id;
			name = editingTemplate.name;
			description = editingTemplate.description || '';
			// Create new array reference to ensure reactivity
			tags = [...(editingTemplate.tags || [])];
			templateContent = editingTemplate.template_content;
			masterPromptInstructions = editingTemplate.master_prompt_instructions || '';
			variables = editingTemplate.variables || [];
		}
		// If editingTemplate exists but same ID, don't reset - user might be editing
	} else if (!editingTemplate && lastTemplateId !== null) {
		// Reset form when creating new template (only if we were editing before)
		lastTemplateId = null;
		name = '';
		description = '';
		tags = [];
		templateContent = '';
		masterPromptInstructions = '';
		variables = [];
	}

	onMount(async () => {
		await loadUserSettings();
		loadExistingTags();
	});

	function handleTagInput(event) {
		tagInput = event.target.value;
		updateTagSuggestions();
	}

	function updateTagSuggestions() {
		if (!tagInput.trim()) {
			tagSuggestions = [];
			showTagSuggestions = false;
			return;
		}

		const inputLower = tagInput.toLowerCase();
		tagSuggestions = existingTags
			.filter(tag => tag.toLowerCase().includes(inputLower))
			.filter(tag => !tags.some(t => t.toLowerCase() === tag.toLowerCase()))
			.slice(0, 8);

		showTagSuggestions = tagSuggestions.length > 0;
		selectedSuggestionIndex = -1;
	}

	function handleTagKeydown(event) {
		if (event.key === 'Enter' || event.key === ',') {
			event.preventDefault();
			addTag();
		} else if (event.key === 'ArrowDown') {
			event.preventDefault();
			if (showTagSuggestions && tagSuggestions.length > 0) {
				selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, tagSuggestions.length - 1);
			}
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1);
		} else if (event.key === 'Escape') {
			showTagSuggestions = false;
		}
	}

	function addTag(tagValue = null) {
		const tagToAdd = tagValue || tagInput.trim();
		if (!tagToAdd) return;

		// Check for existing tag match (case-insensitive)
		const existingTag = existingTags.find(
			t => t.toLowerCase() === tagToAdd.toLowerCase()
		);

		// Use existing tag's casing if found, otherwise use typed casing
		const finalTag = existingTag || tagToAdd;

		// Check if tag already in list (case-insensitive)
		const isDuplicate = tags.some(t => t.toLowerCase() === finalTag.toLowerCase());
		if (isDuplicate) {
			return;
		}

		// Create new array to ensure reactivity
		tags = [...tags, finalTag];
		tagInput = '';
		showTagSuggestions = false;
		selectedSuggestionIndex = -1;
	}

	function removeTag(index) {
		// Create new array to ensure reactivity
		tags = tags.filter((_, i) => i !== index);
	}

	function selectSuggestion(suggestion) {
		addTag(suggestion);
	}

	function handleTemplateContentChange() {
		variables = extractVariables(templateContent);
	}

	async function handleSubmit() {
		if (!name.trim() || !templateContent.trim()) {
			alert('Please fill in name and template content');
			return;
		}

		// Ensure tags is an array (defensive check)
		const tagsToSave = Array.isArray(tags) ? tags : [];
		
		const payload = {
			name,
			description,
			tags: tagsToSave,
			template_content: templateContent,
			master_prompt_instructions: masterPromptInstructions,
			model_compatibility: [selectedModel],
			variables
		};

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			let response;
			if (editingTemplate) {
				// Update
				response = await fetch(`${API_URL}/api/templates/${editingTemplate.id}`, {
					method: 'PUT',
					headers,
					body: JSON.stringify(payload)
				});
			} else {
				// Create
				response = await fetch(`${API_URL}/api/templates`, {
					method: 'POST',
					headers,
					body: JSON.stringify(payload)
				});
			}

			const data = await response.json();
			if (data.success) {
				// Update editingTemplate with the saved data
				if (editingTemplate && data.template) {
					editingTemplate = data.template;
				}
				// Refresh version history if it's open
				if (showVersionHistory && editingTemplate) {
					versionHistoryRefreshKey += 1;
				}
				// If we came from the templated reports tab, dispatch backToSource to return there
				if (cameFromTab === 'templated') {
					dispatch('backToSource');
				} else {
					dispatch('saved');
				}
			} else {
				alert('Failed to save template: ' + data.error);
			}
		} catch (err) {
			console.error('Failed to save template:', err);
			alert('Failed to save template');
		}
	}
</script>

<div class="p-6">
	<div class="flex items-center justify-between mb-6">
		<div class="flex items-center gap-3">
			{#if cameFromTab === 'templated'}
				<button
					type="button"
					onclick={() => dispatch('backToSource')}
					class="text-gray-400 hover:text-white flex items-center gap-2 transition-colors"
					title="Back to Personalised Reports"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
					</svg>
					<span class="text-sm">Back to Reports</span>
				</button>
			{/if}
			<h2 class="text-2xl font-bold text-white">
				{editingTemplate ? 'Edit' : 'Create'} Template
			</h2>
		</div>
		{#if editingTemplate}
			<div class="flex items-center gap-3">
					{#if showVersionHistory}
						<button
							type="button"
							onclick={() => showVersionHistory = false}
							class="px-3 py-1.5 btn-secondary text-sm"
						>
							Hide History
						</button>
					{:else}
						<button
							type="button"
							onclick={() => showVersionHistory = true}
							class="px-3 py-1.5 btn-secondary text-sm flex items-center gap-2"
						>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
						</svg>
						Version History
					</button>
					{/if}
			</div>
		{/if}
	</div>

	{#if showVersionHistory && editingTemplate}
		<div class="mb-6">
			<VersionHistory 
				templateId={editingTemplate.id}
				refreshKey={versionHistoryRefreshKey}
				onRestore={async () => {
					// Reload template data after restore
					try {
						const headers = { 'Content-Type': 'application/json' };
						if ($token) {
							headers['Authorization'] = `Bearer ${$token}`;
						}
						
						const response = await fetch(`${API_URL}/api/templates/${editingTemplate.id}`, {
							headers
						});
						
						const data = await response.json();
						if (data.success && data.template) {
							// Update the editingTemplate with refreshed data
							editingTemplate = data.template;
							// Re-initialize form fields
							name = editingTemplate.name;
							description = editingTemplate.description || '';
							tags = [...(editingTemplate.tags || [])];
							templateContent = editingTemplate.template_content;
							masterPromptInstructions = editingTemplate.master_prompt_instructions || '';
							variables = editingTemplate.variables || [];
						}
					} catch (err) {
						console.error('Failed to reload template:', err);
					}
				}}
			/>
		</div>
	{/if}

	<form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
		<div class="space-y-4">
			<!-- Name -->
			<div>
				<label for="template-name" class="block text-sm font-medium text-gray-300 mb-1">
					Template Name *
				</label>
				<input
					type="text"
					id="template-name"
					bind:value={name}
					required
					placeholder="e.g., Trauma CT Head"
					class="input-dark"
				/>
			</div>

			<!-- Description -->
			<div>
				<label for="template-description" class="block text-sm font-medium text-gray-300 mb-1">
					Description (Optional)
				</label>
				<input
					type="text"
					id="template-description"
					bind:value={description}
					placeholder="e.g., Specific template for Trauma CT Head."
					class="input-dark"
				/>
			</div>

			<!-- Tags -->
			<div>
				<label for="template-tags" class="block text-sm font-medium text-gray-300 mb-1">
					Tags (Optional)
				</label>
				<div class="relative">
					<input
						type="text"
						id="template-tags"
						bind:value={tagInput}
						oninput={handleTagInput}
						onkeydown={handleTagKeydown}
						placeholder="Type a tag and press Enter"
						class="input-dark"
					/>
					<!-- Tag Suggestions Dropdown -->
					{#if showTagSuggestions && tagSuggestions.length > 0}
						<div class="absolute z-10 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-lg max-h-48 overflow-y-auto">
							{#each tagSuggestions as suggestion, index}
								<button
									type="button"
									onclick={() => selectSuggestion(suggestion)}
									class="w-full text-left px-3 py-2 hover:bg-gray-700 {index === selectedSuggestionIndex ? 'bg-gray-700' : ''}"
									onmouseenter={() => selectedSuggestionIndex = index}
								>
									<span class="text-white">{suggestion}</span>
								</button>
							{/each}
						</div>
					{/if}
				</div>
				<!-- Display Tags as Chips -->
				{#if tags.length > 0}
					<div class="flex flex-wrap gap-2 mt-2">
						{#each tags as tag, index}
							<span 
								class="inline-flex items-center gap-1 px-2 py-1 rounded-full border text-xs font-medium"
								style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
							>
								{tag}
								<button
									type="button"
									onclick={() => removeTag(index)}
									class="hover:opacity-70 ml-0.5"
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
				<p class="text-xs text-gray-500 mt-1">
					Press Enter or comma to add a tag. Tags help organize and filter templates.
				</p>
			</div>

			<!-- Template Content -->
			<div>
				<label for="template-content" class="block text-sm font-medium text-gray-300 mb-1">
					Template Content *
				</label>
				<p class="text-xs text-gray-500 mb-2 whitespace-pre-line">
					{exampleInfo}
				</p>
				<textarea
					id="template-content"
					bind:value={templateContent}
					oninput={handleTemplateContentChange}
					required
					placeholder={examplePlaceholder}
					rows="8"
					class="input-dark resize-none font-mono text-sm"
				></textarea>
				{#if variables.length > 0}
					<p class="text-xs text-purple-400 mt-1">
						Detected variables: <span class="text-purple-300">{variables.join(', ')}</span>
					</p>
				{/if}
			</div>

			<!-- Master Prompt Instructions -->
			<div>
				<label for="master-instructions" class="block text-sm font-medium text-gray-300 mb-1">
					Custom Instructions (Optional)
				</label>
				<textarea
					id="master-instructions"
					bind:value={masterPromptInstructions}
					placeholder="Write in prose, with a clear and consistent clinical narrative."
					rows="4"
					class="input-dark resize-none"
				></textarea>
			</div>
		</div>

		<!-- Actions -->
		<div class="flex gap-3 mt-6">
		<button
			type="button"
			onclick={() => dispatch('close')}
			class="btn-secondary flex-1"
		>
			Cancel
		</button>
			<button
				type="submit"
				class="btn-primary flex-1"
			>
				{editingTemplate ? 'Update' : 'Create'} Template
			</button>
		</div>
	</form>
</div>

