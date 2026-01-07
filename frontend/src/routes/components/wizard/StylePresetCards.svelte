<script>
	import { createEventDispatcher } from 'svelte';
	import { onMount } from 'svelte';
	import { customPresets, fetchCustomPresets, savePreset, deletePreset, updatePreset, trackPresetUsage } from '$lib/stores/presets';

	const dispatch = createEventDispatcher();

	export let section = 'findings'; // 'findings' or 'impression'
	export let selectedPresetId = null;
	export let advanced = {}; // Current config

	let activeTab = 'default'; // 'default' or 'custom'
	let showSaveModal = false;
	let showEditModal = false;
	let editingPreset = null;
	let newPresetName = '';
	let newPresetColor = '#8b5cf6'; // Default purple color
	let newPresetDescription = '';
	let saving = false;
	let deletingPresetId = null;
	let saveButtonElement = null;
	let modalContainer = null;

	// Color palette for quick selection
	const colorPalette = [
		'#8b5cf6', // Purple
		'#3b82f6', // Blue
		'#10b981', // Green
		'#f59e0b', // Orange
		'#ef4444', // Red
		'#ec4899', // Pink
		'#14b8a6', // Teal
		'#6366f1', // Indigo
	];

	function openSaveModal() {
		showSaveModal = true;
		newPresetName = '';
		newPresetColor = '#8b5cf6';
		newPresetDescription = '';
	}

	// Portal action to render modal at body level
	function portal(node) {
		const target = document.body;
		target.appendChild(node);
		return {
			destroy() {
				if (node.parentNode) {
					node.parentNode.removeChild(node);
				}
			}
		};
	}

	// Lock/unlock body scroll when modal opens/closes
	$: if (showSaveModal || showEditModal) {
		document.body.style.overflow = 'hidden';
	} else {
		document.body.style.overflow = '';
	}

	onMount(() => {
		fetchCustomPresets(section);
		
		// Cleanup on unmount
		return () => {
			document.body.style.overflow = '';
		};
	});

	$: userPresets = $customPresets[section] || [];

	// FINDINGS Presets
	const findingsPresets = {
		concise_consultant: {
			id: 'concise_consultant',
			icon: '⚡',
			title: 'Concise Consultant',
			description: 'Brief, confident statements',
			settings: {
				writing_style: 'concise',
				format: 'prose',
				organization: 'clinical_priority',
				measurement_style: 'inline',
				negative_findings_style: 'grouped',
				descriptor_density: 'sparse',
				paragraph_grouping: 'by_finding'
			}
		},
		balanced_standard: {
			id: 'balanced_standard',
			icon: '⚖️',
			title: 'Balanced Standard',
			description: 'Standard NHS reporting',
			settings: {
				writing_style: 'standard',
				format: 'prose',
				organization: 'clinical_priority',
				measurement_style: 'inline',
				negative_findings_style: 'grouped',
				descriptor_density: 'standard',
				paragraph_grouping: 'by_finding'
			}
		},
		thorough_academic: {
			id: 'thorough_academic',
			icon: '📚',
			title: 'Thorough Academic',
			description: 'Comprehensive documentation',
			settings: {
				writing_style: 'detailed',
				format: 'prose',
				organization: 'systematic',
				measurement_style: 'separate',
				negative_findings_style: 'comprehensive',
				descriptor_density: 'rich',
				paragraph_grouping: 'by_region'
			}
		}
	};

	// IMPRESSION Presets
	const impressionPresets = {
		ultra_concise: {
			id: 'ultra_concise',
			icon: '⚡',
			title: 'Ultra-Concise',
			description: '1-2 lines maximum',
			settings: {
				verbosity_style: 'brief',
				impression_format: 'prose',
				differential_style: 'none',
				comparison_terminology: 'measured',
				measurement_inclusion: 'none',
				incidental_handling: 'omit'
			}
		},
		standard_summary: {
			id: 'standard_summary',
			icon: '⚖️',
			title: 'Standard Summary',
			description: '2-3 lines, balanced',
			settings: {
				verbosity_style: 'standard',
				impression_format: 'prose',
				differential_style: 'if_needed',
				comparison_terminology: 'measured',
				measurement_inclusion: 'key_only',
				incidental_handling: 'action_threshold'
			}
		},
		detailed_differential: {
			id: 'detailed_differential',
			icon: '📚',
			title: 'Detailed + Differential',
			description: 'Comprehensive with DDx',
			settings: {
				verbosity_style: 'detailed',
				impression_format: 'prose',
				differential_style: 'always_detailed',
				comparison_terminology: 'explicit',
				measurement_inclusion: 'full',
				incidental_handling: 'comprehensive'
			}
		}
	};

	$: presets = section === 'findings' ? findingsPresets : impressionPresets;
	$: presetArray = Object.values(presets);
	$: isSelected = (presetId) => selectedPresetId === presetId;

	function selectPreset(presetId, isCustom = false) {
		let preset;
		if (isCustom) {
			preset = userPresets.find(p => p.id === presetId);
			if (!preset) return;
			// Track usage
			trackPresetUsage(presetId);
		} else {
			preset = presets[presetId];
			if (!preset) return;
		}

		// Prevent auto-detection from interfering during manual selection
		isAutoDetecting = true;
		
		// Switch to appropriate tab first
		if (isCustom) {
			activeTab = 'custom';
		} else {
			activeTab = 'default';
		}

		// Apply preset settings to advanced config
		Object.keys(preset.settings).forEach(key => {
			advanced[key] = preset.settings[key];
		});

		// Set selectedPresetId after applying settings
		selectedPresetId = presetId;
		
		// Update hash to prevent auto-detection from triggering
		lastAdvancedHash = JSON.stringify(advanced);
		
		dispatch('presetChange', { presetId, isCustom });
		
		// Reset flag after a tick to allow future auto-detection
		setTimeout(() => { isAutoDetecting = false; }, 0);
	}

	async function handleSavePreset() {
		if (!newPresetName.trim()) return;
		
		saving = true;
		const result = await savePreset(
			newPresetName.trim(),
			{ ...advanced },
			section,
			newPresetColor,
			newPresetDescription.trim() || null
		);

		if (result.success) {
			showSaveModal = false;
			newPresetName = '';
			newPresetColor = '#8b5cf6';
			newPresetDescription = '';
			// Switch to custom tab and select the new preset
			activeTab = 'custom';
			selectedPresetId = result.preset.id;
			dispatch('presetChange', { presetId: result.preset.id, isCustom: true });
		} else {
			alert(result.error || 'Failed to save preset');
		}
		saving = false;
	}

	function handleEditPreset(preset) {
		editingPreset = preset;
		newPresetName = preset.name;
		newPresetColor = preset.icon || '#8b5cf6'; // Reuse icon field for color
		newPresetDescription = preset.description || '';
		showEditModal = true;
	}

	async function handleUpdatePreset() {
		if (!newPresetName.trim() || !editingPreset) return;
		
		saving = true;
		const result = await updatePreset(editingPreset.id, {
			name: newPresetName.trim(),
			icon: newPresetColor, // Reuse icon field for color
			description: newPresetDescription.trim() || null,
			settings: { ...advanced }
		});

		if (result.success) {
			showEditModal = false;
			editingPreset = null;
			newPresetName = '';
			newPresetColor = '#8b5cf6';
			newPresetDescription = '';
		} else {
			alert(result.error || 'Failed to update preset');
		}
		saving = false;
	}

	async function handleDeletePreset(presetId) {
		if (!confirm('Are you sure you want to delete this preset?')) return;
		
		deletingPresetId = presetId;
		const result = await deletePreset(presetId, section);
		
		if (result.success) {
			// If deleted preset was selected, clear selection
			if (selectedPresetId === presetId) {
				selectedPresetId = null;
				dispatch('presetChange', { presetId: null });
			}
		} else {
			alert(result.error || 'Failed to delete preset');
		}
		deletingPresetId = null;
	}

	// Helper function to check if settings match a preset
	function settingsMatchPreset(presetSettings) {
		// Check if all preset settings match current advanced config
		// Only compare keys that exist in the preset settings
		return Object.keys(presetSettings).every(key => {
			const presetValue = presetSettings[key];
			const advancedValue = advanced[key];
			
			// Handle nested objects (like recommendations)
			if (typeof presetValue === 'object' && presetValue !== null && !Array.isArray(presetValue)) {
				if (typeof advancedValue !== 'object' || advancedValue === null || Array.isArray(advancedValue)) {
					return false;
				}
				// Deep compare nested objects
				return Object.keys(presetValue).every(nestedKey => {
					return advancedValue[nestedKey] === presetValue[nestedKey];
				});
			}
			
			return advancedValue === presetValue;
		});
	}

	// Find which preset (default or custom) matches the current settings
	function findMatchingPreset() {
		// First check default presets
		for (const presetId in presets) {
			const preset = presets[presetId];
			if (settingsMatchPreset(preset.settings)) {
				return { id: presetId, isCustom: false };
			}
		}
		
		// Then check custom presets
		for (const preset of userPresets) {
			if (settingsMatchPreset(preset.settings)) {
				return { id: preset.id, isCustom: true };
			}
		}
		
		return null;
	}

	// Check if current config matches a preset (returns preset ID or 'custom')
	function checkPresetMatch() {
		// First check if selected preset matches
		if (selectedPresetId) {
			let presetSettings = null;
			
			if (presets[selectedPresetId]) {
				presetSettings = presets[selectedPresetId].settings;
			} else {
				const customPreset = userPresets.find(p => p.id === selectedPresetId);
				if (customPreset) {
					presetSettings = customPreset.settings;
				}
			}
			
			// If we have preset settings, check if they match
			if (presetSettings && settingsMatchPreset(presetSettings)) {
				return selectedPresetId;
			}
		}
		
		// If selected preset doesn't match, check all presets to find a match
		const match = findMatchingPreset();
		return match ? match.id : 'custom';
	}

	// Auto-detect and set matching preset when advanced settings change or presets load
	let lastAdvancedHash = '';
	let isAutoDetecting = false;
	let lastUserPresetsLength = 0;
	
	$: {
		if (advanced && Object.keys(advanced).length > 0 && !isAutoDetecting) {
			// Create a hash of advanced settings to detect actual changes
			const currentHash = JSON.stringify(advanced);
			const presetsChanged = userPresets.length !== lastUserPresetsLength;
			
			if (currentHash !== lastAdvancedHash || presetsChanged) {
				lastAdvancedHash = currentHash;
				lastUserPresetsLength = userPresets.length;
				
				// Check if current selection matches
				const currentMatch = checkPresetMatch();
				
				// If current selection doesn't match, try to find a matching preset
				if (currentMatch === 'custom' || !selectedPresetId) {
					const match = findMatchingPreset();
					if (match && selectedPresetId !== match.id) {
						isAutoDetecting = true;
						selectedPresetId = match.id;
						if (match.isCustom) {
							activeTab = 'custom';
						} else {
							activeTab = 'default';
						}
						// Reset flag after a tick to allow future auto-detection
						setTimeout(() => { isAutoDetecting = false; }, 0);
					}
				}
			}
		}
	}

	// Make currentPresetId reactive to both selectedPresetId and advanced changes
	// Explicitly include advanced in the dependency to ensure reactivity
	let currentPresetId = null;
	$: if (advanced) {
		currentPresetId = checkPresetMatch();
	}
	$: isCustomSelected = activeTab === 'custom' && selectedPresetId && userPresets.some(p => p.id === selectedPresetId);
</script>

<div class="mb-6">
	<!-- Tab Switcher -->
	<div class="flex gap-2 mb-4 border-b border-purple-500/20">
		<button 
			type="button"
			onclick={() => activeTab = 'default'}
			class="px-4 py-2 text-sm font-medium transition-colors {activeTab === 'default' ? 'text-purple-400 border-b-2 border-purple-500' : 'text-gray-400 hover:text-gray-300'}"
		>
			Default Presets
		</button>
		<button 
			type="button"
			onclick={() => activeTab = 'custom'}
			class="px-4 py-2 text-sm font-medium transition-colors {activeTab === 'custom' ? 'text-purple-400 border-b-2 border-purple-500' : 'text-gray-400 hover:text-gray-300'}"
		>
			My Presets ({userPresets.length})
		</button>
	</div>

	<!-- Save Current Button (always visible) -->
	<div class="mb-4">
		<button 
			type="button"
			bind:this={saveButtonElement}
			onclick={openSaveModal}
			class="px-4 py-2.5 bg-gradient-to-r from-purple-600 to-purple-700 hover:from-purple-700 hover:to-purple-800 text-white text-sm font-semibold rounded-lg transition-all shadow-md hover:shadow-lg flex items-center gap-2.5"
		>
			<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
			</svg>
			Save Current as Preset
		</button>
	</div>

	<!-- Preset Cards -->
	<div class="flex gap-4 flex-wrap justify-center">
		{#if activeTab === 'default'}
			{#each presetArray as preset}
				<button
					type="button"
					onclick={() => selectPreset(preset.id, false)}
					class="relative bg-gradient-to-br from-purple-900/20 to-blue-900/20 border-2 rounded-xl p-4 min-w-[140px] transition-all duration-200 cursor-pointer hover:border-purple-500/50 hover:shadow-lg hover:scale-105 {currentPresetId === preset.id && !isCustomSelected ? 'border-purple-500 bg-purple-900/30 shadow-lg ring-2 ring-purple-500/50' : 'border-purple-500/30'}"
				>
					<div class="flex flex-col items-center text-center gap-2">
						<div class="text-3xl mb-1">{preset.icon}</div>
						<div class="text-sm font-semibold text-white">{preset.title}</div>
						<div class="text-xs text-gray-400">{preset.description}</div>
						{#if currentPresetId === preset.id && !isCustomSelected}
							<div class="absolute top-2 right-2 w-5 h-5 bg-green-500 rounded-full flex items-center justify-center text-white text-xs font-bold">✓</div>
						{/if}
					</div>
				</button>
			{/each}
		{:else}
			{#if userPresets.length === 0}
				<div class="text-center py-8 text-gray-400">
					<p class="text-sm">No custom presets yet.</p>
					<p class="text-xs mt-1">Click "Save Current as Preset" to create one.</p>
				</div>
			{:else}
				{#each userPresets as preset}
					<div class="relative group">
						<button
							type="button"
							onclick={() => selectPreset(preset.id, true)}
							class="relative bg-gradient-to-br from-gray-900/50 to-gray-800/50 border-2 rounded-xl p-4 min-w-[140px] transition-all duration-200 cursor-pointer hover:shadow-lg hover:scale-105 {selectedPresetId === preset.id && isCustomSelected ? 'shadow-lg ring-2' : ''}"
							style="border-color: {preset.icon || '#8b5cf6'}40; {selectedPresetId === preset.id && isCustomSelected ? `--tw-ring-color: ${preset.icon || '#8b5cf6'}80; border-color: ${preset.icon || '#8b5cf6'};` : ''}"
						>
							<div class="flex flex-col items-center text-center gap-2">
								<div 
									class="w-12 h-12 rounded-full mb-1 flex items-center justify-center shadow-md"
									style="background: linear-gradient(135deg, {preset.icon || '#8b5cf6'}, {preset.icon || '#8b5cf6'}cc);"
								>
									<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
									</svg>
								</div>
								<div class="text-sm font-semibold text-white">{preset.name}</div>
								{#if preset.description}
									<div class="text-xs text-gray-400">{preset.description}</div>
								{/if}
								{#if selectedPresetId === preset.id && isCustomSelected}
									<div class="absolute top-2 right-2 w-6 h-6 rounded-full flex items-center justify-center text-white shadow-md" style="background-color: {preset.icon || '#8b5cf6'}">
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
										</svg>
									</div>
								{/if}
							</div>
						</button>
						<!-- Edit/Delete buttons (show on hover) -->
						<div class="absolute top-2 left-2 flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
							<button
								type="button"
								onclick={(e) => { e.stopPropagation(); handleEditPreset(preset); }}
								class="w-7 h-7 bg-gray-700 hover:bg-gray-600 rounded-lg flex items-center justify-center text-white shadow-md transition-colors border border-gray-600"
								title="Edit preset"
							>
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
								</svg>
							</button>
							<button
								type="button"
								onclick={(e) => { e.stopPropagation(); handleDeletePreset(preset.id); }}
								disabled={deletingPresetId === preset.id}
								class="w-7 h-7 bg-red-600 hover:bg-red-700 rounded-lg flex items-center justify-center text-white shadow-md transition-colors disabled:opacity-50 border border-red-500"
								title="Delete preset"
							>
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
								</svg>
							</button>
						</div>
					</div>
				{/each}
			{/if}
		{/if}
	</div>

	{#if currentPresetId === 'custom' && !isCustomSelected}
		<div class="text-center mt-2">
			<span class="text-xs text-gray-400 italic">Custom settings applied</span>
		</div>
	{/if}
</div>

<!-- Save Preset Modal - Rendered at body level -->
{#if showSaveModal}
	<div 
		use:portal
		class="fixed inset-0 bg-black/80 backdrop-blur-sm z-[9999] flex items-center justify-center animate-fadeIn"
		style="position: fixed; top: 0; left: 0; right: 0; bottom: 0;"
		onclick={() => showSaveModal = false}
		onkeydown={(e) => e.key === 'Escape' && (showSaveModal = false)}
		role="dialog"
		aria-modal="true"
		aria-labelledby="save-preset-title"
	>
		<div 
			class="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-6 w-[400px] max-w-[90vw] border border-gray-700 shadow-2xl animate-slideUp max-h-[90vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-center gap-3 mb-6">
				<div 
					class="w-12 h-12 rounded-xl flex items-center justify-center shadow-lg"
					style="background: linear-gradient(135deg, {newPresetColor}, {newPresetColor}cc);"
				>
					<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
					</svg>
				</div>
				<h3 id="save-preset-title" class="text-xl font-bold text-white">Save Preset</h3>
			</div>
			
			<div class="space-y-5">
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Name *</label>
					<input
						type="text"
						bind:value={newPresetName}
						placeholder="e.g., My Custom Style"
						class="w-full bg-black/30 border border-gray-600 rounded-lg px-3.5 py-2.5 text-white placeholder-gray-500 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 focus:outline-none transition-all"
						maxlength="100"
					/>
				</div>

				<div>
					<label class="block text-sm font-medium text-gray-300 mb-3">Color</label>
					<div class="flex items-center gap-3">
						<div class="flex gap-2 flex-wrap flex-1">
							{#each colorPalette as color}
								<button
									type="button"
									onclick={() => newPresetColor = color}
									class="w-10 h-10 rounded-lg transition-all shadow-md hover:scale-110 {newPresetColor === color ? 'ring-2 ring-white ring-offset-2 ring-offset-gray-800' : 'hover:shadow-lg'}"
									style="background-color: {color};"
									title={color}
								/>
							{/each}
						</div>
						<div class="flex items-center gap-2">
							<input
								type="color"
								bind:value={newPresetColor}
								class="w-10 h-10 rounded-lg cursor-pointer border-2 border-gray-600"
								title="Custom color"
							/>
						</div>
					</div>
					<p class="text-xs text-gray-400 mt-2">Click a color or choose custom</p>
				</div>

				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Description (optional)</label>
					<textarea
						bind:value={newPresetDescription}
						placeholder="Brief description of this preset..."
						rows="2"
						class="w-full bg-black/30 border border-gray-600 rounded-lg px-3.5 py-2.5 text-white placeholder-gray-500 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 focus:outline-none transition-all resize-none"
						maxlength="200"
						onkeydown={(e) => {
							// Allow Enter to create new lines in textarea
							if (e.key === 'Enter') {
								e.stopPropagation();
							}
						}}
					/>
				</div>
			</div>

			<div class="flex gap-3 mt-6">
				<button
					type="button"
					onclick={handleSavePreset}
					disabled={!newPresetName.trim() || saving}
					class="flex-1 px-4 py-2.5 bg-gradient-to-r from-purple-600 to-purple-700 hover:from-purple-700 hover:to-purple-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-all shadow-md hover:shadow-lg"
				>
					{saving ? 'Saving...' : 'Save Preset'}
				</button>
				<button
					type="button"
					onclick={() => { showSaveModal = false; newPresetName = ''; newPresetColor = '#8b5cf6'; newPresetDescription = ''; }}
					class="px-4 py-2.5 bg-gray-700 hover:bg-gray-600 text-white font-medium rounded-lg transition-colors"
				>
					Cancel
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Edit Preset Modal - Rendered at body level -->
{#if showEditModal && editingPreset}
	<div 
		use:portal
		class="fixed inset-0 bg-black/80 backdrop-blur-sm z-[9999] flex items-center justify-center animate-fadeIn"
		style="position: fixed; top: 0; left: 0; right: 0; bottom: 0;"
		onclick={() => { showEditModal = false; editingPreset = null; }}
		onkeydown={(e) => e.key === 'Escape' && (showEditModal = false)}
		role="dialog"
		aria-modal="true"
		aria-labelledby="edit-preset-title"
	>
		<div 
			class="bg-gradient-to-br from-gray-900 to-gray-800 rounded-2xl p-6 max-w-md w-full mx-4 my-8 border border-gray-700 shadow-2xl animate-slideUp max-h-[90vh] overflow-y-auto" 
			onclick={(e) => e.stopPropagation()}
		>
			<div class="flex items-center gap-3 mb-6">
				<div 
					class="w-12 h-12 rounded-xl flex items-center justify-center shadow-lg"
					style="background: linear-gradient(135deg, {newPresetColor}, {newPresetColor}cc);"
				>
					<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
					</svg>
				</div>
				<h3 id="edit-preset-title" class="text-xl font-bold text-white">Edit Preset</h3>
			</div>
			
			<div class="space-y-5">
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Name *</label>
					<input
						type="text"
						bind:value={newPresetName}
						placeholder="e.g., My Custom Style"
						class="w-full bg-black/30 border border-gray-600 rounded-lg px-3.5 py-2.5 text-white placeholder-gray-500 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 focus:outline-none transition-all"
						maxlength="100"
					/>
				</div>

				<div>
					<label class="block text-sm font-medium text-gray-300 mb-3">Color</label>
					<div class="flex items-center gap-3">
						<div class="flex gap-2 flex-wrap flex-1">
							{#each colorPalette as color}
								<button
									type="button"
									onclick={() => newPresetColor = color}
									class="w-10 h-10 rounded-lg transition-all shadow-md hover:scale-110 {newPresetColor === color ? 'ring-2 ring-white ring-offset-2 ring-offset-gray-800' : 'hover:shadow-lg'}"
									style="background-color: {color};"
									title={color}
								/>
							{/each}
						</div>
						<div class="flex items-center gap-2">
							<input
								type="color"
								bind:value={newPresetColor}
								class="w-10 h-10 rounded-lg cursor-pointer border-2 border-gray-600"
								title="Custom color"
							/>
						</div>
					</div>
					<p class="text-xs text-gray-400 mt-2">Click a color or choose custom</p>
				</div>

				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Description (optional)</label>
					<textarea
						bind:value={newPresetDescription}
						placeholder="Brief description of this preset..."
						rows="2"
						class="w-full bg-black/30 border border-gray-600 rounded-lg px-3.5 py-2.5 text-white placeholder-gray-500 focus:border-purple-500 focus:ring-2 focus:ring-purple-500/20 focus:outline-none transition-all resize-none"
						maxlength="200"
						onkeydown={(e) => {
							// Allow Enter to create new lines in textarea
							if (e.key === 'Enter') {
								e.stopPropagation();
							}
						}}
					/>
				</div>
			</div>

			<div class="flex gap-3 mt-6">
				<button
					type="button"
					onclick={handleUpdatePreset}
					disabled={!newPresetName.trim() || saving}
					class="flex-1 px-4 py-2.5 bg-gradient-to-r from-purple-600 to-purple-700 hover:from-purple-700 hover:to-purple-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-all shadow-md hover:shadow-lg"
				>
					{saving ? 'Updating...' : 'Update Preset'}
				</button>
				<button
					type="button"
					onclick={() => { showEditModal = false; editingPreset = null; newPresetName = ''; newPresetColor = '#8b5cf6'; newPresetDescription = ''; }}
					class="px-4 py-2.5 bg-gray-700 hover:bg-gray-600 text-white font-medium rounded-lg transition-colors"
				>
					Cancel
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes slideUp {
		from {
			transform: translateY(20px);
			opacity: 0;
		}
		to {
			transform: translateY(0);
			opacity: 1;
		}
	}

	:global(.animate-fadeIn) {
		animation: fadeIn 0.2s ease-out;
	}

	:global(.animate-slideUp) {
		animation: slideUp 0.3s ease-out;
	}
</style>
