<script>
	import { onMount, createEventDispatcher } from 'svelte';
	import { browser } from '$app/environment';
	import TemplateManager from './TemplateManager.svelte';
	import { token } from '$lib/stores/auth';
	import { templatesStore } from '$lib/stores/templates';
	import { settingsStore } from '$lib/stores/settings';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import { API_URL } from '$lib/config';
	
	export let selectedModel = 'claude';
	export let initialEditTemplate = null;
	export let cameFromTab = null;

	const dispatch = createEventDispatcher();
	
	// Subscribe to templates store
	$: templates = $templatesStore.templates || [];
	$: loadingTemplates = $templatesStore.loading || false;
	
	// Subscribe to settings store for tag colors
	$: customTagColors = ($settingsStore.settings && $settingsStore.settings.tag_colors) || {};
	
	let searchQuery = '';
	let selectedTags = [];
	let allUniqueTags = [];
	let isEditorOpen = false;
	let editingTag = null;
	let renamingTag = null;
	let newTagName = '';
	let editingColorTag = null;
	let showColorPicker = false;
	let colorPickerTag = null;
	let colorPickerValue = '#8b5cf6';
	let previewTagColors = {}; // Temporary preview colors before saving

	// Reactive statement to update preview when color picker value changes
	$: if (showColorPicker && colorPickerTag && colorPickerValue) {
		previewTagColors = { ...customTagColors, [colorPickerTag]: colorPickerValue };
	}

	async function handleTemplateCreated() {
		// Small delay to ensure backend has processed the save
		await new Promise(resolve => setTimeout(resolve, 100));
		await templatesStore.refreshTemplates();
		// Dispatch event to parent to trigger refresh in TemplatedReportTab
		dispatch('templateCreated');
	}

	async function handleTemplateDeleted() {
		// Small delay to ensure backend has processed the delete
		await new Promise(resolve => setTimeout(resolve, 100));
		await templatesStore.refreshTemplates();
		// Dispatch event to parent to trigger refresh in TemplatedReportTab
		dispatch('templateDeleted');
	}
	
	function handleEditorStateChange(event) {
		isEditorOpen = event.detail.open;
	}

	function updateUniqueTags() {
		const tagsSet = new Set();
		templates.forEach(t => {
			if (t.tags && Array.isArray(t.tags)) {
				t.tags.forEach(tag => tagsSet.add(tag));
			}
		});
		allUniqueTags = Array.from(tagsSet).sort(); // Alphabetical order
	}

	// Reactive tag counts - recalculates whenever templates array changes
	// Create a tracking value that includes tag data to detect tag changes
	let tagCounts = {};
	let templatesSignature = '';
	$: templatesSignature = templates ? templates.map(t => `${t.id}:${JSON.stringify(t.tags || [])}`).join(';') : '';
	$: templatesSignature, tagCounts = (() => {
		const counts = {};
		if (templates && templates.length > 0) {
			templates.forEach(t => {
				if (t.tags && Array.isArray(t.tags)) {
					t.tags.forEach(tag => {
						counts[tag] = (counts[tag] || 0) + 1;
					});
				}
			});
		}
		return counts;
	})();

	function getTagCount(tag) {
		return tagCounts[tag] || 0;
	}

	async function updateTagColor(tag, color) {
		try {
			// Get current settings from store
			const currentSettings = $settingsStore || {};
			let currentTagColors = { ...(currentSettings.tag_colors || {}) };

			// Find and remove any existing color mapping for this tag (case-insensitive)
			const tagLower = tag.toLowerCase();
			let keyToRemove = null;
			for (const key of Object.keys(currentTagColors)) {
				if (key.toLowerCase() === tagLower) {
					keyToRemove = key;
					break;
				}
			}
			if (keyToRemove) {
				delete currentTagColors[keyToRemove];
			}

			// Add or remove color
			if (color !== '' && color) {
				currentTagColors[tag] = color; // Use exact tag name (not the old key)
			}

			// Update via store (which will update API and store)
			const result = await settingsStore.updateSettings({
				tag_colors: currentTagColors
			});

			if (!result.success) {
				alert('Failed to update tag color: ' + (result.error || 'Unknown error'));
				// Reload settings to revert
				await settingsStore.refreshSettings();
				return false;
			}
			
			return true;
		} catch (err) {
			alert('Failed to update tag color');
			// Reload settings to revert
			await settingsStore.refreshSettings();
			return false;
		}
	}

	function openColorPicker(tag) {
		colorPickerTag = tag;
		
		// First check if there's a custom color (case-insensitive)
		const tagLower = tag.toLowerCase();
		let customColor = null;
		for (const [key, value] of Object.entries(customTagColors)) {
			if (key.toLowerCase() === tagLower && value) {
				customColor = value;
				break;
			}
		}
		
		// Use custom color if available, otherwise use current displayed color
		const currentColor = customColor || getTagColor(tag, customTagColors);
		
		// Convert RGB to hex if needed
		if (currentColor.startsWith('rgb')) {
			const match = currentColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
			if (match) {
				const [, r, g, b] = match;
				colorPickerValue = '#' + [r, g, b].map(x => {
					const hex = parseInt(x).toString(16);
					return hex.length === 1 ? '0' + hex : hex;
				}).join('');
			} else {
				colorPickerValue = '#8b5cf6';
			}
		} else if (currentColor.startsWith('#')) {
			colorPickerValue = currentColor;
		} else {
			colorPickerValue = '#8b5cf6';
		}
		showColorPicker = true;
	}

	function closeColorPicker() {
		previewTagColors = {}; // Clear preview on close
		showColorPicker = false;
		colorPickerTag = null;
	}

	async function saveTagColor() {
		if (!colorPickerTag || !colorPickerValue) {
			return;
		}
		
		// Save to backend first
		const success = await updateTagColor(colorPickerTag, colorPickerValue);
		
		if (success) {
			// Settings are automatically updated via store subscription
			previewTagColors = {}; // Clear preview
			closeColorPicker();
		} else {
			// Revert local state on failure
			await settingsStore.refreshSettings();
		}
	}

	function toggleTag(tag) {
		if (selectedTags.includes(tag)) {
			selectedTags = selectedTags.filter(t => t !== tag);
		} else {
			selectedTags = [...selectedTags, tag];
		}
	}

	function clearTagFilters() {
		selectedTags = [];
	}

	async function renameTag(oldTag, newTag) {
		if (!newTag.trim() || newTag.trim().toLowerCase() === oldTag.toLowerCase()) {
			return;
		}

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/templates/tags/rename`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					old_tag: oldTag,
					new_tag: newTag.trim()
				})
			});

			const data = await response.json();
			if (data.success) {
				// Reload settings FIRST to get the updated color mappings from backend
				// The backend should have already transferred the color mapping
				await settingsStore.refreshSettings();
				
				// Reload templates to get updated tags
				await templatesStore.refreshTemplates();
				
				renamingTag = null;
				newTagName = '';
			} else {
				alert('Failed to rename tag: ' + (data.error || 'Unknown error'));
			}
		} catch (err) {
			alert('Failed to rename tag');
		}
	}

	async function handleDeleteTag(tag) {
		if (!confirm(`Are you sure you want to delete the tag "${tag}" from all templates?`)) {
			return;
		}

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/templates/tags/delete`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					tag: tag
				})
			});

			const data = await response.json();
			if (data.success) {
				// Remove from selected tags if it was selected
				selectedTags = selectedTags.filter(t => t !== tag);
				// Reload templates to get updated tags
				await templatesStore.refreshTemplates();
			} else {
				alert('Failed to delete tag: ' + (data.error || 'Unknown error'));
			}
		} catch (err) {
			alert('Failed to delete tag');
		}
	}

	function startRenamingTag(tag) {
		renamingTag = tag;
		newTagName = tag;
	}

	function cancelRename() {
		renamingTag = null;
		newTagName = '';
	}

	function handleRenameKeydown(event, oldTag) {
		if (event.key === 'Enter') {
			renameTag(oldTag, newTagName);
		} else if (event.key === 'Escape') {
			cancelRename();
		}
	}

	// Make filtered templates reactive
	$: filteredTemplates = (() => {
		let filtered = templates;
		
		if (searchQuery) {
			const query = searchQuery.toLowerCase();
			filtered = filtered.filter(t => 
				t.name.toLowerCase().includes(query) ||
				t.description?.toLowerCase().includes(query) ||
				(t.tags && t.tags.some(tag => tag.toLowerCase().includes(query)))
			);
		}
		
		// Tag filtering (OR logic - templates with ANY selected tag)
		if (selectedTags.length > 0) {
			filtered = filtered.filter(t => 
				t.tags && t.tags.some(tag => selectedTags.includes(tag))
			);
		}
		
		return filtered;
	})();

	onMount(async () => {
		if (browser) {
			// Load stores if empty
			if (!$settingsStore.settings) {
				await settingsStore.loadSettings();
			}
			if (!$templatesStore.templates || $templatesStore.templates.length === 0) {
				await templatesStore.loadTemplates();
			}
		}
	});
</script>

<div class="p-6">
	<div class="flex items-center gap-3 mb-6">
		<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
		</svg>
		<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Manage My Templates</h1>
	</div>
	
	<!-- Filters -->
	{#if !isEditorOpen}
		<div class="mb-6 space-y-4">
			<div>
				<input
					type="text"
					placeholder="Search templates..."
					bind:value={searchQuery}
					class="input-dark w-full"
				/>
			</div>
			
			{#if allUniqueTags.length > 0}
				<div>
					<div class="flex items-center justify-between mb-2">
						<p class="text-sm text-gray-400">Filter by tags:</p>
						<button
							type="button"
							onclick={() => editingTag = editingTag ? null : 'all'}
							class="text-xs text-gray-400 hover:text-white underline"
						>
							{editingTag ? 'Done Editing' : 'Edit Tags'}
						</button>
					</div>
					<div class="flex flex-wrap gap-2">
						{#each allUniqueTags as tag}
							<div class="relative group">
								{#if renamingTag === tag}
									<div class="flex items-center gap-1">
										<input
											type="text"
											bind:value={newTagName}
											onkeydown={(e) => handleRenameKeydown(e, tag)}
											class="px-3 py-1 rounded-full border text-xs font-medium bg-gray-800 border-gray-600 text-white min-w-[100px]"
											autofocus
										/>
										<button
											type="button"
											onclick={() => renameTag(tag, newTagName)}
											class="p-1 text-green-400 hover:text-green-300"
											title="Save"
										>
											<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
											</svg>
										</button>
										<button
											type="button"
											onclick={cancelRename}
											class="p-1 text-red-400 hover:text-red-300"
											title="Cancel"
										>
											<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
											</svg>
										</button>
									</div>
								{:else}
									<div class="flex items-center gap-1">
										<button
											type="button"
											onclick={() => toggleTag(tag)}
											class="px-3 py-1 rounded-full border text-xs font-medium transition-all flex items-center gap-1.5 group {
												selectedTags.includes(tag) 
													? 'ring-2 ring-white/50' 
													: 'hover:opacity-80'
											}"
											style="background-color: {showColorPicker && colorPickerTag === tag ? getTagColor(tag, previewTagColors) : getTagColor(tag, customTagColors)}; color: white; border-color: {selectedTags.includes(tag) ? 'rgba(255,255,255,0.5)' : getTagColorWithOpacity(tag, 0.5, showColorPicker && colorPickerTag === tag ? previewTagColors : customTagColors)};"
										>
											<span>{tag}</span>
											<span 
												class="rounded-full bg-white/95 flex items-center justify-center flex-shrink-0 text-[10px] font-semibold transition-all duration-200 group-hover:w-5 group-hover:h-5 {
													selectedTags.includes(tag) ? 'w-5 h-5' : 'w-1.5 h-1.5'
												}"
												style="color: {getTagColor(tag, customTagColors)};"
												title="{(tagCounts[tag] || 0)} template{(tagCounts[tag] || 0) !== 1 ? 's' : ''}"
											>
												<span class="transition-opacity duration-200 {
													selectedTags.includes(tag) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
												}">
													{tagCounts[tag] || 0}
												</span>
											</span>
										</button>
										{#if editingTag}
											<div class="flex gap-1">
												<button
													type="button"
													onclick={() => openColorPicker(tag)}
													class="p-1 text-yellow-400 hover:text-yellow-300"
													title="Change tag color"
												>
													<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
													</svg>
												</button>
												<button
													type="button"
													onclick={() => startRenamingTag(tag)}
													class="p-1 text-blue-400 hover:text-blue-300"
													title="Rename tag"
												>
													<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
													</svg>
												</button>
												<button
													type="button"
													onclick={() => handleDeleteTag(tag)}
													class="p-1 text-red-400 hover:text-red-300"
													title="Delete tag"
												>
													<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
													</svg>
												</button>
											</div>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
					{#if selectedTags.length > 0}
						<button
							type="button"
							onclick={clearTagFilters}
							class="mt-2 text-xs text-gray-400 hover:text-white underline"
						>
							Clear tag filters
						</button>
					{/if}
				</div>
			{/if}
		</div>
	{/if}

	<!-- Color Picker Modal -->
	{#if showColorPicker && colorPickerTag}
		<div 
			class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-3 z-50"
			onclick={closeColorPicker}
			role="dialog"
			aria-modal="true"
		>
			<div 
				class="card-dark p-6 max-w-sm w-full"
				onclick={(e) => e.stopPropagation()}
			>
				<h3 class="text-lg font-semibold text-white mb-4">Change Tag Color</h3>
				<div class="space-y-4">
					<div>
						<label for="tag-color-picker" class="block text-sm font-medium text-gray-300 mb-2">
							Color for "{colorPickerTag}"
						</label>
						<input
							id="tag-color-picker"
							type="color"
							bind:value={colorPickerValue}
							oninput={(e) => {
								colorPickerValue = e.target.value;
							}}
							class="w-full h-12 rounded cursor-pointer"
						/>
						<!-- Preview -->
						<div class="mt-3 flex items-center gap-3">
							<span class="text-xs text-gray-400">Preview:</span>
							<span 
								class="px-3 py-1 rounded-full border text-xs font-medium"
								style="background-color: {colorPickerValue}; color: white; border-color: {colorPickerValue}80;"
							>
								{colorPickerTag}
							</span>
						</div>
					</div>
					<div class="flex gap-3">
						<button
							type="button"
							onclick={saveTagColor}
							class="btn-primary flex-1"
						>
							Save Color
						</button>
						<button
							type="button"
							onclick={closeColorPicker}
							class="btn-secondary flex-1"
						>
							Cancel
						</button>
					</div>
				</div>
			</div>
		</div>
	{/if}

	{#if loadingTemplates}
		<!-- Skeleton loader for templates -->
		<div class="space-y-4">
			<!-- Header skeleton -->
			<div class="flex justify-between items-center mb-6">
				<div class="h-8 bg-gray-700/50 rounded animate-pulse w-48"></div>
				<div class="h-10 bg-gray-700/50 rounded animate-pulse w-40"></div>
			</div>
			<!-- Template cards skeleton -->
			{#each Array(3) as _}
				<div class="card-dark p-6 space-y-4">
					<div class="h-6 bg-gray-700/50 rounded animate-pulse w-3/4"></div>
					<div class="h-4 bg-gray-700/50 rounded animate-pulse w-full"></div>
					<div class="h-4 bg-gray-700/50 rounded animate-pulse w-2/3"></div>
					<div class="flex gap-2">
						<div class="h-6 bg-gray-700/50 rounded-full animate-pulse w-20"></div>
						<div class="h-6 bg-gray-700/50 rounded-full animate-pulse w-24"></div>
					</div>
					<div class="flex gap-2 mt-4">
						<div class="h-9 bg-gray-700/50 rounded animate-pulse w-24"></div>
						<div class="h-9 bg-gray-700/50 rounded animate-pulse w-24"></div>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<TemplateManager 
			templates={filteredTemplates}
			{selectedModel} 
			hideUseButton={true}
			customTagColors={customTagColors}
			{initialEditTemplate}
			{cameFromTab}
			on:templateCreated={handleTemplateCreated}
			on:templateDeleted={handleTemplateDeleted}
			on:editorStateChange={handleEditorStateChange}
			on:backToSource={() => dispatch('backToSource')}
		/>
	{/if}
</div>
