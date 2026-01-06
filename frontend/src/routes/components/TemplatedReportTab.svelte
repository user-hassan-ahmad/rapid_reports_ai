<script>
	import { onMount, afterUpdate, createEventDispatcher, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import TemplateForm from './TemplateForm.svelte';
	import { token } from '$lib/stores/auth';
	import { templatesStore, selectedTemplateId, selectedTemplate } from '$lib/stores/templates';
	import { settingsStore } from '$lib/stores/settings';
	import { tagsStore } from '$lib/stores/tags';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import { API_URL } from '$lib/config';

	const dispatch = createEventDispatcher();

	export let apiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false,
		using_user_keys: {
			deepgram: false
		}
	};
	
	// Always use Claude for template reports
	let templatedModel = 'claude';
export let reportUpdateLoading = false;
export let versionHistoryRefreshKey = 0;
export let templatesRefreshKey = 0;
export let externalResponseContent = null;
export let externalResponseVersion = 0;

// Enhancement state props
export let enhancementGuidelinesCount = 0;
export let enhancementLoading = false;
export let enhancementError = false;
	
	// No intermediate state needed - templatedModel is bound from parent
	// and changes will propagate automatically via two-way binding

	// Subscribe to templates store
	$: templates = $templatesStore.templates || [];
	$: loadingTemplates = $templatesStore.loading || false;
	
	// Subscribe to selectedTemplate store - automatically synced with templates array
	// This ensures that when a template is saved from the edit page, selectedTemplate
	// gets updated with the latest data (including manual/auto-generated inclusions)
	$: currentSelectedTemplate = $selectedTemplate;
	
	// Form state - manage in parent like Quick Reports to preserve across re-renders
	let variableValues; // No default - prevents Svelte from resetting on re-render
	let response = null;
	let responseModel = null;
	let loading = false;
	let error = null;
	let reportId = null;  // For enhancement sidebar
let lastExternalResponseVersion = 0;
$: if (externalResponseVersion && externalResponseVersion !== lastExternalResponseVersion) {
	lastExternalResponseVersion = externalResponseVersion;
	if (typeof externalResponseContent === 'string') {
		response = externalResponseContent;
	}
}

	// Watch for templatesRefreshKey changes and reload templates
	let lastTemplatesRefreshKey = 0;
	$: if (browser && templatesRefreshKey > 0 && templatesRefreshKey !== lastTemplatesRefreshKey) {
		lastTemplatesRefreshKey = templatesRefreshKey;
		templatesStore.refreshTemplates();
	}
	
	// Store variableValues per template ID to preserve when switching templates
	// This is handled intentionally in handleTemplateSelect - no reactive statements needed
	let variableValuesByTemplate = {};
	let lastTemplateId = null;
	
	// Ensure variableValues is never undefined
	if (typeof variableValues === 'undefined') {
		variableValues = {};
	}
	
	// Sync variableValues when selectedTemplate changes (automatically reactive via store)
	// This handles both new template selection and template updates (e.g., after saving)
	$: if (currentSelectedTemplate && currentSelectedTemplate.id) {
		const templateId = currentSelectedTemplate.id;
		const isNewTemplate = lastTemplateId !== templateId;
		
		// Sync variableValues with updated template structure
		// Build expected variable structure from template_config or variables array
		const expectedVariables = {};
		
		// Check if we have preserved values for this template
		const preservedValues = variableValuesByTemplate[templateId];
		
		// Always include CLINICAL_HISTORY and FINDINGS (they're always required)
		// If switching to a new template, only use preserved values or empty string
		// If same template, preserve current values
		if (isNewTemplate) {
			expectedVariables['CLINICAL_HISTORY'] = preservedValues?.['CLINICAL_HISTORY'] || '';
			expectedVariables['FINDINGS'] = preservedValues?.['FINDINGS'] || '';
		} else {
			// Same template - preserve current values
			expectedVariables['CLINICAL_HISTORY'] = variableValues?.['CLINICAL_HISTORY'] || '';
			expectedVariables['FINDINGS'] = variableValues?.['FINDINGS'] || '';
		}
		
		// For new structured templates (with template_config)
		if (currentSelectedTemplate.template_config && currentSelectedTemplate.template_config.sections) {
			currentSelectedTemplate.template_config.sections.forEach(section => {
				if (section.has_input_field && section.included) {
					const sectionName = section.name;
					// If switching to new template, use preserved values or empty
					// If same template, preserve current values
					if (isNewTemplate) {
						expectedVariables[sectionName] = preservedValues?.[sectionName] || '';
					} else {
						expectedVariables[sectionName] = variableValues?.[sectionName] || '';
					}
				}
			});
		} 
		// For legacy templates (with variables array)
		else if (currentSelectedTemplate.variables && Array.isArray(currentSelectedTemplate.variables)) {
			currentSelectedTemplate.variables.forEach(v => {
				if (v !== 'CLINICAL_HISTORY' && v !== 'FINDINGS') {
					// If switching to new template, use preserved values or empty
					// If same template, preserve current values
					if (isNewTemplate) {
						expectedVariables[v] = preservedValues?.[v] || '';
					} else {
						expectedVariables[v] = variableValues?.[v] || '';
					}
				}
			});
		}
		
		// Only update variableValues if this is a new template OR if structure changed
		if (isNewTemplate) {
			// New template - use expectedVariables which now has preserved values or empty strings
			variableValues = expectedVariables;
			lastTemplateId = templateId;
		} else {
			// Same template ID - check if structure changed (e.g., LIMITATIONS changed from manual to auto-generated)
			const currentKeys = Object.keys(variableValues || {}).sort();
			const expectedKeys = Object.keys(expectedVariables).sort();
			const structureChanged = JSON.stringify(currentKeys) !== JSON.stringify(expectedKeys);
			
			if (structureChanged) {
				// Structure changed - sync to new structure while preserving values
				variableValues = expectedVariables;
				// Update preserved values
				variableValuesByTemplate[templateId] = { ...variableValues };
			}
		}
	}
	
	let searchQuery = '';
	let selectedTags = [];
	let allUniqueTags = [];
	
	// Subscribe to settings store for tag colors
	$: customTagColors = ($settingsStore.settings && $settingsStore.settings.tag_colors) || {};
	
	// View state
	let viewMode = 'grid'; // 'grid' or 'kanban'
	let kanbanGroupBy = 'default'; // 'default' or 'tags'
	let sortBy = 'name'; // 'name', 'usage_count', 'last_used_at', 'created_at'
	let sortOrder = 'asc'; // 'asc' or 'desc'
	let hideEmptyColumns = false; // Hide empty columns in kanban view
	
	// 3D tilt state for cards
	let cardTilts = new Map();
	
	// Pin toggle state for optimistic updates
	let pinningTemplates = new Set(); // Track which templates are currently being toggled
	let optimisticPinStates = new Map(); // Map of templateId -> { originalState, pendingState }
	
	// Tag management state
	let editingTag = null;
	let renamingTag = null;
	let newTagName = '';
	let editingColorTag = null;
	let showColorPicker = false;
	let colorPickerTag = null;
	let colorPickerValue = '#8b5cf6';
	let previewTagColors = {}; // Temporary preview colors before saving
	
	// Kanban horizontal scroll references
	let kanbanHeadersContainer;
	let kanbanCardsContainer;
	let scrollbarTrack;
	let scrollbarThumb;
	let scrollbarVisible = false;
	let scrollPosition = 0;
	let thumbWidth = 100;
	let isDragging = false;
	let dragStartX = 0;
	let dragStartScrollLeft = 0;
	
	// Check if content is scrollable and update scrollbar visibility
	function checkScrollability() {
		if (!kanbanCardsContainer || !browser) {
			scrollbarVisible = false;
			return;
		}
		
		const { scrollWidth, clientWidth } = kanbanCardsContainer;
		const canScroll = scrollWidth > clientWidth;
		
		if (canScroll !== scrollbarVisible) {
			scrollbarVisible = canScroll;
		}
		
		if (canScroll) {
			updateScrollbar();
		}
	}
	
	// Update scrollbar position and size
	function updateScrollbar() {
		if (!kanbanCardsContainer || !scrollbarVisible) return;
		
		const { scrollLeft, scrollWidth, clientWidth } = kanbanCardsContainer;
		const maxScroll = scrollWidth - clientWidth;
		
		// Calculate scroll position (0 to 1)
		scrollPosition = maxScroll > 0 ? scrollLeft / maxScroll : 0;
		
		// Calculate thumb width as percentage
		thumbWidth = Math.max(15, Math.min(100, (clientWidth / scrollWidth) * 100));
	}
	
	function scrollKanban(direction) {
		if (!kanbanCardsContainer) return;
		
		const currentScroll = kanbanCardsContainer.scrollLeft;
		const scrollWidth = kanbanCardsContainer.scrollWidth;
		const clientWidth = kanbanCardsContainer.clientWidth;
		const maxScroll = scrollWidth - clientWidth;
		
		// Use a moderate scroll amount - about 50% of viewport width
		// Columns are typically 320px (w-80), so scroll by roughly 1 column worth
		const baseScrollAmount = Math.max(clientWidth * 0.5, 320); // 50% of viewport or 1 column (320px)
		
		// Calculate remaining scrollable distance
		const remainingDistance = direction === 'left' 
			? currentScroll 
			: maxScroll - currentScroll;
		
		// Scroll amount: use a moderate portion of remaining or base amount
		// If there's a lot remaining, scroll 50% of remaining. Otherwise use base amount
		let scrollDelta;
		if (remainingDistance > baseScrollAmount * 2) {
			// Lots of distance left - scroll 50% of remaining (but cap at baseScrollAmount * 1.5)
			scrollDelta = Math.min(remainingDistance * 0.5, baseScrollAmount * 1.5);
		} else {
			// Less distance - use base scroll amount (but don't exceed remaining)
			scrollDelta = Math.min(baseScrollAmount, remainingDistance);
		}
		
		// Ensure minimum scroll of at least 320px if possible (one column)
		if (remainingDistance > 320 && scrollDelta < 320) {
			scrollDelta = Math.min(320, remainingDistance);
		}
		
		const targetScroll = direction === 'left' 
			? Math.max(0, currentScroll - scrollDelta)
			: Math.min(maxScroll, currentScroll + scrollDelta);
		
		// Manual smooth animation using requestAnimationFrame
		const startScroll = currentScroll;
		const distance = targetScroll - startScroll;
		const duration = 400; // 400ms animation
		const startTime = performance.now();
		
		function animateScroll(currentTime) {
			const elapsed = currentTime - startTime;
			const progress = Math.min(elapsed / duration, 1);
			
			// Easing function (ease-out)
			const eased = 1 - Math.pow(1 - progress, 3);
			
			const currentPosition = startScroll + (distance * eased);
			
			kanbanCardsContainer.scrollLeft = currentPosition;
			if (kanbanHeadersContainer) {
				kanbanHeadersContainer.scrollLeft = currentPosition;
			}
			
			if (progress < 1) {
				requestAnimationFrame(animateScroll);
			}
		}
		
		requestAnimationFrame(animateScroll);
	}
	
	// Scrollbar track click handler
	function handleTrackClick(e) {
		if (!kanbanCardsContainer || !scrollbarTrack || !scrollbarVisible || isDragging) return;
		if (e.target === scrollbarThumb) return;
		
		const rect = scrollbarTrack.getBoundingClientRect();
		const clickX = e.clientX - rect.left;
		const clickRatio = Math.max(0, Math.min(1, clickX / rect.width));
		
		const { scrollWidth, clientWidth } = kanbanCardsContainer;
		const maxScroll = scrollWidth - clientWidth;
		const targetScroll = clickRatio * maxScroll;
		
		kanbanCardsContainer.scrollLeft = targetScroll;
		if (kanbanHeadersContainer) {
			kanbanHeadersContainer.scrollLeft = targetScroll;
		}
	}
	
	// Thumb drag handlers
	function handleThumbMouseDown(e) {
		if (!scrollbarVisible || !kanbanCardsContainer) return;
		e.preventDefault();
		e.stopPropagation();
		isDragging = true;
		dragStartX = e.clientX;
		dragStartScrollLeft = kanbanCardsContainer.scrollLeft;
	}
	
	function handleMouseMove(e) {
		if (!isDragging || !kanbanCardsContainer || !scrollbarTrack || !scrollbarVisible) return;
		
		const deltaX = e.clientX - dragStartX;
		const rect = scrollbarTrack.getBoundingClientRect();
		const trackWidth = rect.width;
		const { scrollWidth, clientWidth } = kanbanCardsContainer;
		const maxScroll = scrollWidth - clientWidth;
		
		const scrollDelta = (deltaX / trackWidth) * scrollWidth;
		const newScrollLeft = Math.max(0, Math.min(maxScroll, dragStartScrollLeft + scrollDelta));
		
		kanbanCardsContainer.scrollLeft = newScrollLeft;
		if (kanbanHeadersContainer) {
			kanbanHeadersContainer.scrollLeft = newScrollLeft;
		}
		// Update scrollbar immediately during drag (no transition)
		updateScrollbar();
	}
	
	function handleMouseUp() {
		isDragging = false;
	}

	function updateUniqueTags() {
		const tagsSet = new Set();
		templates.forEach(t => {
			if (t.tags && Array.isArray(t.tags)) {
				t.tags.forEach(tag => tagsSet.add(tag));
			}
		});
		allUniqueTags = Array.from(tagsSet).sort();
	}

	// Update unique tags whenever templates change
	$: if (templates) {
		updateUniqueTags();
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

	function handleTemplateSelect(template) {
		if (!template || !template.id) return;
		
		const templateId = template.id;
		const isSameTemplate = lastTemplateId === templateId;
		
		// If same template ID, preserve current values (don't reset)
		if (isSameTemplate) {
			// Preserve current values before updating template reference
			if (Object.keys(variableValues || {}).length > 0) {
				variableValuesByTemplate[templateId] = { ...variableValues };
			}
			// Just update the template ID in store - selectedTemplate will auto-update
			selectedTemplateId.set(templateId);
			// Ensure lastTemplateId is set (should already be set, but ensure it for safety)
			lastTemplateId = templateId;
			return;
		}
		
		// If switching to a different template, preserve current variableValues
		if (!isSameTemplate && lastTemplateId && Object.keys(variableValues || {}).length > 0) {
			variableValuesByTemplate[lastTemplateId] = { ...variableValues };
		}
		
		// Different template - clear response and set template ID (selectedTemplate will auto-update)
		selectedTemplateId.set(templateId);
		
		// Clear response when switching to a new template
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		dispatch('reportGenerated', { reportId: null });
		dispatch('reportCleared');
		
		// Note: variableValues will be synced by the reactive statement above
		// based on currentSelectedTemplate, which will update automatically
		// DO NOT update lastTemplateId here - let the reactive statement handle it
		// to ensure isNewTemplate is calculated correctly
	}

	function handleFormReset() {
		// Clear all form values and preserved values
		variableValues = {};
		variableValuesByTemplate = {};
		response = null;
		responseModel = null;
		error = null;
		reportId = null;
		dispatch('reportGenerated', { reportId: null });
		dispatch('reportCleared');
		// Re-initialize empty values for current template if one is selected
		// Build variableValues in the order from template.variables to preserve structure order
		// Note: variableValues will be synced by the reactive statement based on currentSelectedTemplate
		if (currentSelectedTemplate && currentSelectedTemplate.id) {
			variableValues = {};
			if (currentSelectedTemplate.variables && Array.isArray(currentSelectedTemplate.variables)) {
				currentSelectedTemplate.variables.forEach(variable => {
					variableValues[variable] = '';
				});
			} else {
				// Fallback for legacy templates without variables array
				variableValues = {
					'FINDINGS': '',
					'CLINICAL_HISTORY': ''
				};
			}
		}
	}

	function handleBackToList() {
		selectedTemplateId.set(null);
		reportId = null;
		dispatch('reportGenerated', { reportId: null });
		dispatch('reportCleared');
	}
	
	// Template Editor handlers
	function handleEditTemplate(template) {
		dispatch('openTemplateEditor', { template, model: templatedModel });
	}
	
	function handleEditorClose() {
		// No longer needed - parent handles this
	}
	
	async function handleEditorSaved() {
		// No longer needed - parent handles this
	}
	
	// Template Wizard handlers
	function handleOpenWizard() {
		dispatch('openTemplateWizard');
	}
	
	function handleCloseWizard() {
		// No longer needed - parent handles this
	}
	
	// Template Delete handler
	async function handleDeleteTemplate(template, e) {
		e.stopPropagation();
		if (!confirm(`Are you sure you want to delete "${template.name}"?`)) {
			return;
		}
		
		try {
			const headers = {};
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${template.id}`, {
				method: 'DELETE',
				headers
			});
			const data = await response.json();
			if (data.success) {
				await templatesStore.refreshTemplates();
				dispatch('templateDeleted');
			} else {
				alert('Failed to delete template: ' + data.error);
			}
		} catch (err) {
			alert('Failed to delete template');
		}
	}
	
	// Tag management functions (from TemplateManagementTab)
	async function updateTagColor(tag, color) {
		try {
			const currentSettings = $settingsStore || {};
			let currentTagColors = { ...(currentSettings.tag_colors || {}) };
			
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
			
			if (color !== '' && color) {
				currentTagColors[tag] = color;
			}
			
			const result = await settingsStore.updateSettings({
				tag_colors: currentTagColors
			});
			
			if (!result.success) {
				alert('Failed to update tag color: ' + (result.error || 'Unknown error'));
				await settingsStore.refreshSettings();
				return false;
			}
			
			return true;
		} catch (err) {
			alert('Failed to update tag color');
			await settingsStore.refreshSettings();
			return false;
		}
	}
	
	function openColorPicker(tag) {
		colorPickerTag = tag;
		
		const tagLower = tag.toLowerCase();
		let customColor = null;
		for (const [key, value] of Object.entries(customTagColors)) {
			if (key.toLowerCase() === tagLower && value) {
				customColor = value;
				break;
			}
		}
		
		const currentColor = customColor || getTagColor(tag, customTagColors);
		
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
		previewTagColors = {};
		showColorPicker = false;
		colorPickerTag = null;
	}
	
	async function saveTagColor() {
		if (!colorPickerTag || !colorPickerValue) {
			return;
		}
		
		const success = await updateTagColor(colorPickerTag, colorPickerValue);
		
		if (success) {
			previewTagColors = {};
			closeColorPicker();
		} else {
			await settingsStore.refreshSettings();
		}
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
				await settingsStore.refreshSettings();
				await templatesStore.refreshTemplates();
				await tagsStore.refreshTags();
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
				selectedTags = selectedTags.filter(t => t !== tag);
				await templatesStore.refreshTemplates();
				await tagsStore.refreshTags();
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
	
	// Reactive statement to update preview when color picker value changes
	$: if (showColorPicker && colorPickerTag && colorPickerValue) {
		previewTagColors = { ...customTagColors, [colorPickerTag]: colorPickerValue };
	}

	// Helper function to check if template was recently used (within 24-48 hours)
	function isRecentlyUsed(template) {
		if (!template.last_used_at) return false;
		try {
			const lastUsed = new Date(template.last_used_at);
			if (isNaN(lastUsed.getTime())) return false; // Invalid date
			const now = new Date();
			const hoursSince = (now - lastUsed) / (1000 * 60 * 60);
			return hoursSince <= 48 && hoursSince >= 0; // Must be in the past, within 48 hours
		} catch (e) {
			return false;
		}
	}
	
	// Sorting function
	function sortTemplates(templatesList, sortByField, order) {
		const sorted = [...templatesList];
		sorted.sort((a, b) => {
			let aVal, bVal;
			
			switch (sortByField) {
				case 'name':
					aVal = (a.name || '').toLowerCase();
					bVal = (b.name || '').toLowerCase();
					break;
				case 'usage_count':
					// Ensure numeric comparison - handle both number and string
					const aCount = typeof a.usage_count === 'number' ? a.usage_count : (parseInt(a.usage_count) || 0);
					const bCount = typeof b.usage_count === 'number' ? b.usage_count : (parseInt(b.usage_count) || 0);
					// Store actual values for comparison
					aVal = aCount;
					bVal = bCount;
					break;
				case 'last_used_at':
					// Handle both ISO string and Date object
					if (a.last_used_at) {
						const dateA = typeof a.last_used_at === 'string' ? new Date(a.last_used_at) : a.last_used_at;
						aVal = !isNaN(dateA.getTime()) ? dateA.getTime() : 0;
					} else {
						aVal = 0; // Null/undefined dates treated as 0 (oldest)
					}
					if (b.last_used_at) {
						const dateB = typeof b.last_used_at === 'string' ? new Date(b.last_used_at) : b.last_used_at;
						bVal = !isNaN(dateB.getTime()) ? dateB.getTime() : 0;
					} else {
						bVal = 0; // Null/undefined dates treated as 0 (oldest)
					}
					break;
				case 'created_at':
					// Handle both ISO string and Date object
					if (a.created_at) {
						const dateA = typeof a.created_at === 'string' ? new Date(a.created_at) : a.created_at;
						aVal = !isNaN(dateA.getTime()) ? dateA.getTime() : 0;
					} else {
						aVal = 0;
					}
					if (b.created_at) {
						const dateB = typeof b.created_at === 'string' ? new Date(b.created_at) : b.created_at;
						bVal = !isNaN(dateB.getTime()) ? dateB.getTime() : 0;
					} else {
						bVal = 0;
					}
					break;
				default:
					return 0;
			}
			
			// Calculate result based on order
			let result;
			if (aVal < bVal) {
				result = order === 'asc' ? -1 : 1;
			} else if (aVal > bVal) {
				result = order === 'asc' ? 1 : -1;
			} else {
				result = 0;
			}
			
			return result;
		});
		
		return sorted;
	}

	// Reactive statement to compute filtered templates
	$: filteredTemplates = (() => {
		let filtered = templates;
		
		// Text search
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
	
	// Sort filtered templates
	let sortedTemplates = [];
	$: {
		sortedTemplates = sortTemplates(filteredTemplates, sortBy, sortOrder);
	}
	
	// Group templates for kanban (default mode)
	// Note: These maintain the global sort order from sortedTemplates
	// IMPORTANT: Sorting happens BEFORE grouping, so all groups respect the global sort
	let pinnedTemplates = [];
	let recentlyUsedTemplates = [];
	let mostUsedTemplates = [];
	let allOtherTemplates = [];
	$: {
		// Filter templates into groups with cascading exclusion to prevent duplicates
		// Strategy: 
		// 1. Pinned templates (always first, excluded from other categories)
		// 2. Most Used - Top 20% by usage_count, max 3 templates
		// 3. Recently Used - Templates used in last 24-48 hours (excludes Pinned and Most Used)
		// 4. All Others - Everything else
		
		// Step 1: Pinned templates (always first, excluded from other categories)
		pinnedTemplates = sortedTemplates.filter(t => t.is_pinned === true);
		// Normalize IDs to strings for consistent comparison
		const pinnedIds = new Set(pinnedTemplates.map(t => String(t.id || '')));
		
		// Step 2: Get all non-pinned templates sorted by usage_count descending
		const nonPinned = sortedTemplates.filter(t => !t.is_pinned);
		const sortedByUsage = [...nonPinned].sort((a, b) => {
			const aCount = typeof a.usage_count === 'number' ? a.usage_count : (parseInt(a.usage_count) || 0);
			const bCount = typeof b.usage_count === 'number' ? b.usage_count : (parseInt(b.usage_count) || 0);
			if (bCount !== aCount) {
				return bCount - aCount; // Descending order (highest first)
			}
			// If usage_count is the same, sort by last_used_at descending
			if (a.last_used_at && b.last_used_at) {
				const dateA = typeof a.last_used_at === 'string' ? new Date(a.last_used_at) : a.last_used_at;
				const dateB = typeof b.last_used_at === 'string' ? new Date(b.last_used_at) : b.last_used_at;
				return dateB.getTime() - dateA.getTime();
			}
			if (a.last_used_at) return -1;
			if (b.last_used_at) return 1;
			return 0;
		});
		
		// Step 3: Most Used - Dynamic threshold: Top 20% by usage_count, max 3 templates
		// Calculate 20th percentile threshold
		if (sortedByUsage.length > 0) {
			const usageCounts = sortedByUsage
				.map(t => typeof t.usage_count === 'number' ? t.usage_count : (parseInt(t.usage_count) || 0))
				.filter(count => count > 0)
				.sort((a, b) => b - a); // Descending
			
			if (usageCounts.length > 0) {
				// Calculate 20th percentile (top 20% threshold)
				const percentileIndex = Math.floor(usageCounts.length * 0.2);
				const threshold = usageCounts[percentileIndex] || usageCounts[0];
				
				// Get templates above threshold, limited to max 3
				mostUsedTemplates = sortedByUsage
					.filter(t => {
						const count = typeof t.usage_count === 'number' ? t.usage_count : (parseInt(t.usage_count) || 0);
						return count >= threshold && count > 0;
					})
					.slice(0, 3); // Max 3 templates
			} else {
				mostUsedTemplates = [];
			}
		} else {
			mostUsedTemplates = [];
		}
		
		// Normalize IDs to strings for consistent comparison
		const mostUsedIds = new Set(mostUsedTemplates.map(t => String(t.id || '')));
		
		// Step 4: Recently Used - Templates used in last 24-48 hours that aren't in "Pinned" or "Most Used"
		recentlyUsedTemplates = sortedTemplates.filter(t => {
			const templateId = String(t.id || '');
			if (pinnedIds.has(templateId)) return false; // Don't duplicate from "Pinned"
			if (mostUsedIds.has(templateId)) return false; // Don't duplicate from "Most Used"
			return isRecentlyUsed(t);
		});
		
		// Normalize IDs to strings for consistent comparison
		const recentlyUsedIds = new Set(recentlyUsedTemplates.map(t => String(t.id || '')));
		
		// Step 5: All Others - Everything else that isn't pinned, in "Most Used", or "Recently Used"
		allOtherTemplates = sortedTemplates.filter(t => {
			const templateId = String(t.id || '');
			if (pinnedIds.has(templateId)) return false;
			if (mostUsedIds.has(templateId)) return false;
			if (recentlyUsedIds.has(templateId)) return false;
			return true;
		});
	}
	
	// Group templates for kanban (tag mode)
	$: tagGroupedTemplates = (() => {
		if (kanbanGroupBy !== 'tags') return {};
		const grouped = {};
		sortedTemplates.forEach(template => {
			if (template.tags && template.tags.length > 0) {
				template.tags.forEach(tag => {
					if (!grouped[tag]) {
						grouped[tag] = [];
					}
					grouped[tag].push(template);
				});
			} else {
				if (!grouped['Untagged']) {
					grouped['Untagged'] = [];
				}
				grouped['Untagged'].push(template);
			}
		});
		return grouped;
	})();
	
	// Helper function to revert optimistic updates
	function revertOptimisticPin(templateId) {
		const optimisticState = optimisticPinStates.get(templateId);
		if (optimisticState) {
			const index = templates.findIndex(t => t.id === templateId);
			if (index !== -1) {
				templates[index] = { ...templates[index], is_pinned: optimisticState.originalState };
				templates = [...templates]; // Trigger reactivity
			}
			optimisticPinStates.delete(templateId);
		}
	}
	
	// Toggle pin function with optimistic updates
	async function handleTogglePin(template, e) {
		e.stopPropagation();
		
		// Prevent multiple clicks
		if (pinningTemplates.has(template.id)) {
			return;
		}
		
		const templateId = template.id;
		const currentPinState = template.is_pinned === true;
		const newPinState = !currentPinState;
		
		// Store original state for potential rollback
		optimisticPinStates.set(templateId, {
			originalState: currentPinState,
			pendingState: newPinState
		});
		
		// OPTIMISTIC UPDATE: Immediately update UI
		const index = templates.findIndex(t => t.id === templateId);
		if (index !== -1) {
			templates[index] = { ...templates[index], is_pinned: newPinState };
			templates = [...templates]; // Trigger reactivity
		}
		
		// Add to loading set (for visual feedback)
		pinningTemplates.add(templateId);
		pinningTemplates = new Set(pinningTemplates);
		
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${templateId}/toggle-pin`, {
				method: 'POST',
				headers
			});
			
			if (response.ok) {
				const data = await response.json();
				if (data.success) {
					// Confirm optimistic update matches server response
					const index = templates.findIndex(t => t.id === templateId);
					if (index !== -1) {
						templates[index] = data.template;
						templates = [...templates]; // Trigger reactivity
					}
					// Clear optimistic state
					optimisticPinStates.delete(templateId);
				} else {
					// Server returned error - revert optimistic update
					revertOptimisticPin(templateId);
				}
			} else {
				// HTTP error - revert optimistic update
				revertOptimisticPin(templateId);
			}
		} catch (err) {
			// Network error - revert optimistic update
			revertOptimisticPin(templateId);
		} finally {
			// Remove from loading set
			pinningTemplates.delete(templateId);
			pinningTemplates = new Set(pinningTemplates);
		}
	}
	
	// 3D tilt handlers
	function handleCardMouseMove(event, templateId) {
		if (!browser) return;
		const card = event.currentTarget;
		const rect = card.getBoundingClientRect();
		const x = event.clientX - rect.left;
		const y = event.clientY - rect.top;
		
		const centerX = rect.width / 2;
		const centerY = rect.height / 2;
		
		const rotateX = ((y - centerY) / centerY) * 5; // Max 5 degrees
		const rotateY = ((centerX - x) / centerX) * 5; // Max 5 degrees
		
		cardTilts.set(templateId, { rotateX, rotateY });
		cardTilts = new Map(cardTilts);
	}
	
	function handleCardMouseLeave(templateId) {
		cardTilts.set(templateId, { rotateX: 0, rotateY: 0 });
		cardTilts = new Map(cardTilts);
	}

	let resizeObserver;
	let mutationObserver;

	onMount(async () => {
		if (browser) {
			// Load stores if empty
			if (!$settingsStore.settings) {
				await settingsStore.loadSettings();
			}
			if (!$templatesStore.templates || $templatesStore.templates.length === 0) {
				await templatesStore.loadTemplates();
			}
			if (!$tagsStore.tags || $tagsStore.tags.length === 0) {
				await tagsStore.refreshTags();
			}
			
			// Set up global mouse handlers for dragging
			window.addEventListener('mousemove', handleMouseMove);
			window.addEventListener('mouseup', handleMouseUp);
		}
	});
	
	onDestroy(() => {
		if (browser) {
			window.removeEventListener('mousemove', handleMouseMove);
			window.removeEventListener('mouseup', handleMouseUp);
		}
		if (resizeObserver) {
			resizeObserver.disconnect();
		}
		if (mutationObserver) {
			mutationObserver.disconnect();
		}
	});
	
	// Set up observers when container is available
	afterUpdate(() => {
		if (browser && viewMode === 'kanban' && kanbanCardsContainer) {
			// Cleanup old observers
			if (resizeObserver) resizeObserver.disconnect();
			if (mutationObserver) mutationObserver.disconnect();
			
			// ResizeObserver to detect container size changes
			resizeObserver = new ResizeObserver(() => {
				checkScrollability();
			});
			resizeObserver.observe(kanbanCardsContainer);
			
			// MutationObserver to detect child changes (columns added/removed)
			mutationObserver = new MutationObserver(() => {
				setTimeout(checkScrollability, 50);
			});
			mutationObserver.observe(kanbanCardsContainer, {
				childList: true,
				subtree: false
			});
			
			// Initial check
			checkScrollability();
		}
	});
	
	// Reactive check when columns or filters change
	$: if (browser && viewMode === 'kanban' && kanbanCardsContainer && (hideEmptyColumns !== undefined || filteredTemplates)) {
		setTimeout(() => {
			checkScrollability();
		}, 100);
	}
	
</script>

<div class="p-6">
	{#if !currentSelectedTemplate}
		<!-- Template Selector Console -->
		<div class="flex items-center justify-between mb-6">
			<div class="flex items-center gap-3">
				<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
				</svg>
				<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">Personalised Reports</h1>
			</div>
			<button
				onclick={handleOpenWizard}
				class="btn-primary"
			>
				+ Create Template
			</button>
		</div>

		<!-- Filters and Controls -->
		<div class="mb-6 space-y-4">
			<!-- Search and View Toggle -->
			<div class="flex items-center gap-4">
				<div class="flex-1">
				<input
					type="text"
					placeholder="Search templates..."
					bind:value={searchQuery}
					class="input-dark w-full"
				/>
			</div>
				<!-- View Toggle -->
				<div class="flex items-center gap-2 bg-white/5 backdrop-blur-xl rounded-lg border border-white/10 p-1">
					<button
						type="button"
						onclick={() => viewMode = 'grid'}
						class="px-3 py-1.5 rounded transition-all relative group/tooltip {
							viewMode === 'grid' 
								? 'bg-purple-600 text-white' 
								: 'text-gray-400 hover:text-white'
						}"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
						</svg>
						<span class="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-black/90 text-white text-xs rounded whitespace-nowrap opacity-0 group-hover/tooltip:opacity-100 transition-opacity pointer-events-none z-50">
							Grid View
						</span>
					</button>
					<button
						type="button"
						onclick={() => viewMode = 'kanban'}
						class="px-3 py-1.5 rounded transition-all relative group/tooltip {
							viewMode === 'kanban' 
								? 'bg-purple-600 text-white' 
								: 'text-gray-400 hover:text-white'
						}"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 16a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1H5a1 1 0 01-1-1v-3zM14 16a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1h-4a1 1 0 01-1-1v-3z" />
						</svg>
						<span class="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-black/90 text-white text-xs rounded whitespace-nowrap opacity-0 group-hover/tooltip:opacity-100 transition-opacity pointer-events-none z-50">
							Kanban View
						</span>
					</button>
				</div>
				<!-- Sort Controls -->
				<div class="flex items-center gap-2">
				<select
					bind:value={sortBy}
					class="select-dark text-sm px-4 py-2 min-w-[140px]"
				>
						<option value="name">Name</option>
						<option value="usage_count">Usage Count</option>
						<option value="last_used_at">Last Used</option>
						<option value="created_at">Date Created</option>
					</select>
					<button
						type="button"
						onclick={() => {
							sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
						}}
						class="px-3 py-1.5 btn-secondary text-sm rounded"
						title={sortOrder === 'asc' ? 'Ascending' : 'Descending'}
					>
						{#if sortOrder === 'asc'}
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
							</svg>
						{:else}
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						{/if}
					</button>
				</div>
			</div>
			<!-- Kanban Group Toggle (only in kanban mode) -->
			{#if viewMode === 'kanban'}
				<div class="flex items-center gap-4">
					<div class="flex items-center gap-2">
						<p class="text-sm text-gray-400">Group by:</p>
						<div class="flex items-center gap-2 bg-white/5 backdrop-blur-xl rounded-lg border border-white/10 p-1">
							<button
								type="button"
								onclick={() => kanbanGroupBy = 'default'}
								class="px-3 py-1.5 rounded text-sm transition-all {
									kanbanGroupBy === 'default' 
										? 'bg-purple-600 text-white' 
										: 'text-gray-400 hover:text-white'
								}"
							>
								Default
							</button>
							<button
								type="button"
								onclick={() => kanbanGroupBy = 'tags'}
								class="px-3 py-1.5 rounded text-sm transition-all {
									kanbanGroupBy === 'tags' 
										? 'bg-purple-600 text-white' 
										: 'text-gray-400 hover:text-white'
								}"
							>
								Tags
							</button>
						</div>
					</div>
					<button
						type="button"
						onclick={() => hideEmptyColumns = !hideEmptyColumns}
						class="flex items-center gap-2 px-3 py-1.5 rounded text-sm transition-all {
							hideEmptyColumns 
								? 'bg-purple-600 text-white' 
								: 'text-gray-400 hover:text-white bg-white/5 backdrop-blur-xl border border-white/10'
						}"
						title="Hide empty columns"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a10.05 10.05 0 011.825-3.875m15.75 0a10.05 10.05 0 011.825 3.875M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
						</svg>
						<span>Hide Empty</span>
					</button>
				</div>
			{/if}
			
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

		<div class="flex flex-col" style="height: calc(100vh - 200px); max-height: calc(100vh - 200px);">
		{#if loadingTemplates}
			<div class="flex items-center justify-center py-12">
				<div class="text-gray-400">Loading templates...</div>
			</div>
		{:else if !loadingTemplates && templates.length === 0}
			<div class="card-dark text-center py-12">
				<svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
				</svg>
				<p class="text-gray-400 text-lg mb-2">No templates found</p>
				<p class="text-gray-500 text-sm mb-4">
					Create your first template to get started
				</p>
				<button
					onclick={handleOpenWizard}
					class="btn-primary"
				>
					+ Create Template
				</button>
			</div>
		{:else if filteredTemplates.length === 0}
			<div class="card-dark text-center py-12">
				<svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
				</svg>
				<p class="text-gray-400 text-lg mb-2">No templates match "{searchQuery}"</p>
				<p class="text-gray-500 text-sm">Try adjusting your search query</p>
			</div>
		{:else}
				{#if viewMode === 'grid'}
				<!-- Grid View -->
				<div class="space-y-6 view-container overflow-y-auto flex-1 scrollbar-thin" style="min-height: 0; padding: 8px; overflow-x: hidden;">
					{#if pinnedTemplates.length > 0}
						<!-- Favourites Section -->
						<div>
							<div class="flex items-center gap-2 mb-4">
								<svg class="w-6 h-6 text-yellow-400" fill="currentColor" viewBox="0 0 24 24">
									<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
								</svg>
								<h2 class="text-xl font-semibold text-white">Favourites</h2>
								<span class="px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-300 text-xs">
									{pinnedTemplates.length}
								</span>
							</div>
							<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" style="overflow: visible;">
								{#each pinnedTemplates as template (template.id)}
									{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
									<div 
										class="template-card relative group"
										onmousemove={(e) => handleCardMouseMove(e, template.id)}
										onmouseleave={() => handleCardMouseLeave(template.id)}
										style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
									>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
						onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
										<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
										<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-10">
											<button
												type="button"
												onclick={(e) => handleTogglePin(template, e)}
												disabled={pinningTemplates.has(template.id)}
												class="px-2.5 py-2 rounded-full bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40 transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative"
												title="Unpin"
											>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full bg-yellow-400/20 animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 text-yellow-400 relative z-10" fill="currentColor" viewBox="0 0 24 24">
													<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
												</svg>
											</button>
											<button
												type="button"
												onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
												class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
												title="Edit template"
											>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
											<button
												type="button"
												onclick={(e) => handleDeleteTemplate(template, e)}
												class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
												title="Delete template"
											>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}
					
					<!-- All Templates Section -->
					{#if allOtherTemplates.length > 0 || mostUsedTemplates.length > 0}
						<div>
							{#if pinnedTemplates.length > 0}
								<div class="flex items-center gap-2 mb-4">
									<svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
									</svg>
									<h2 class="text-xl font-semibold text-white">All Templates</h2>
									<span class="px-2 py-0.5 rounded-full bg-white/10 text-gray-300 text-xs">
										{allOtherTemplates.length + mostUsedTemplates.length}
									</span>
								</div>
							{/if}
							<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" style="overflow: visible;">
								{#each (() => {
									// Combine ALL non-pinned templates in sorted order to respect global sort
									const combined = sortedTemplates.filter(t => !t.is_pinned);
									return combined;
								})() as template (template.id)}
									{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
									<div 
										class="template-card relative group"
										onmousemove={(e) => handleCardMouseMove(e, template.id)}
										onmouseleave={() => handleCardMouseLeave(template.id)}
										style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
									>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
											onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
									<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
									<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
										<button
											type="button"
											onclick={(e) => handleTogglePin(template, e)}
											disabled={pinningTemplates.has(template.id)}
											class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
												template.is_pinned === true 
													? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
													: 'bg-white/10 hover:bg-white/20 border border-white/20'
											}"
											title={template.is_pinned === true ? 'Unpin' : 'Pin'}
										>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full {
														template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
													} animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 relative z-10 {
													template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
												}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
													{#if template.is_pinned === true}
														<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
													{:else}
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
													{/if}
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
											class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
											title="Edit template"
										>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => handleDeleteTemplate(template, e)}
											class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
											title="Delete template"
										>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{:else}
				<!-- Kanban View -->
				<div class="view-container flex-1 overflow-hidden flex flex-col" style="min-height: 0;">
					{#if kanbanGroupBy === 'default'}
						<!-- Horizontal Navigation Controls -->
						<div class="flex items-center justify-between mb-3 px-2 flex-shrink-0">
							<button
								type="button"
								onclick={() => scrollKanban('left')}
								class="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
								title="Scroll left"
								disabled={!scrollbarVisible}
							>
								<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
								</svg>
							</button>
							{#if scrollbarVisible}
								<div 
									bind:this={scrollbarTrack}
									class="flex-1 mx-4 h-2 bg-white/10 rounded-full overflow-hidden cursor-pointer relative flex-shrink-0"
									onmousedown={(e) => handleTrackClick(e)}
									role="slider"
									tabindex="0"
									aria-label="Horizontal scroll position"
									aria-valuemin="0"
									aria-valuemax="100"
									aria-valuenow={Math.round(scrollPosition * 100)}
									onkeydown={(e) => {
										if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
											e.preventDefault();
											scrollKanban(e.key === 'ArrowLeft' ? 'left' : 'right');
										}
									}}
								>
									<div 
										bind:this={scrollbarThumb}
										class="h-full bg-purple-500 rounded-full absolute cursor-grab active:cursor-grabbing {isDragging ? '' : 'transition-all duration-100'}"
										style="width: {thumbWidth}%; left: {scrollPosition * (100 - thumbWidth)}%;"
										onmousedown={(e) => handleThumbMouseDown(e)}
									></div>
								</div>
							{:else}
								<div class="flex-1 mx-4"></div>
							{/if}
							<button
								type="button"
								onclick={() => scrollKanban('right')}
								class="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
								title="Scroll right"
								disabled={!scrollbarVisible}
							>
								<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
								</svg>
							</button>
						</div>
						
						<!-- Fixed Column Headers Row -->
						<div 
							bind:this={kanbanHeadersContainer}
							class="kanban-headers-container flex gap-4 mb-3 flex-shrink-0 overflow-x-auto overflow-y-hidden" 
							style="padding: 8px 8px 0.5rem 8px;"
							onscroll={(e) => {
								const target = e.target;
								if (kanbanCardsContainer) {
									kanbanCardsContainer.scrollLeft = target.scrollLeft;
								}
								updateScrollbar();
							}}
						>
							{#if !hideEmptyColumns || pinnedTemplates.length > 0}
								<div class="flex-shrink-0 w-80">
									<div class="bg-black/50 backdrop-blur-sm p-3 rounded-lg border border-yellow-500/30">
										<div class="flex items-center gap-2">
											<svg class="w-5 h-5 text-yellow-400" fill="currentColor" viewBox="0 0 24 24">
												<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
											</svg>
											<h3 class="font-semibold text-white">Pinned</h3>
											<span class="px-2 py-0.5 rounded-full bg-yellow-500/20 text-yellow-300 text-xs">
												{pinnedTemplates.length}
											</span>
										</div>
									</div>
								</div>
							{/if}
							{#if !hideEmptyColumns || mostUsedTemplates.length > 0}
								<div class="flex-shrink-0 w-80">
									<div class="bg-black/50 backdrop-blur-sm p-3 rounded-lg border border-blue-500/30">
										<div class="flex items-center gap-2">
											<svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
											</svg>
											<h3 class="font-semibold text-white">Most Used</h3>
											<span class="px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 text-xs">
												{mostUsedTemplates.length}
											</span>
										</div>
									</div>
								</div>
							{/if}
							{#if !hideEmptyColumns || recentlyUsedTemplates.length > 0}
								<div class="flex-shrink-0 w-80">
									<div class="bg-black/50 backdrop-blur-sm p-3 rounded-lg border border-purple-500/30">
										<div class="flex items-center gap-2">
											<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
											</svg>
											<h3 class="font-semibold text-white">Recently Used</h3>
											<span class="px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 text-xs">
												{recentlyUsedTemplates.length}
											</span>
										</div>
									</div>
								</div>
							{/if}
							{#if !hideEmptyColumns || allOtherTemplates.length > 0}
								<div class="flex-shrink-0 w-80">
									<div class="bg-black/50 backdrop-blur-sm p-3 rounded-lg border border-white/10">
										<div class="flex items-center gap-2">
											<svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
											</svg>
											<h3 class="font-semibold text-white">All Others</h3>
											<span class="px-2 py-0.5 rounded-full bg-white/10 text-gray-300 text-xs">
												{allOtherTemplates.length}
											</span>
										</div>
									</div>
								</div>
							{/if}
						</div>
						
						<!-- Scrollable Cards Container -->
						<div 
							bind:this={kanbanCardsContainer}
							class="kanban-container flex gap-4 overflow-x-auto overflow-y-hidden flex-1" 
							style="padding: 8px; padding-bottom: 1rem;"
							onscroll={(e) => {
								const target = e.target;
								if (kanbanHeadersContainer) {
									kanbanHeadersContainer.scrollLeft = target.scrollLeft;
								}
								updateScrollbar();
							}}
						>
						<!-- Pinned Column (must match header order) -->
						{#if !hideEmptyColumns || pinnedTemplates.length > 0}
							<div class="flex-shrink-0 w-80" style="overflow: visible; height: 100%; display: flex; flex-direction: column; max-height: 100%;">
							<div class="space-y-3 overflow-y-auto flex-1 scrollbar-thin" style="padding: 8px; min-height: 0; max-height: 100%;">
								{#if pinnedTemplates.length > 0}
									{#each pinnedTemplates as template (template.id)}
										{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
										<div 
											class="template-card relative group"
											onmousemove={(e) => handleCardMouseMove(e, template.id)}
											onmouseleave={() => handleCardMouseLeave(template.id)}
											style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
										>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
											onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
									<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
									<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
										<button
											type="button"
											onclick={(e) => handleTogglePin(template, e)}
											disabled={pinningTemplates.has(template.id)}
											class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
												template.is_pinned === true 
													? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
													: 'bg-white/10 hover:bg-white/20 border border-white/20'
											}"
											title={template.is_pinned === true ? 'Unpin' : 'Pin'}
										>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full {
														template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
													} animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 relative z-10 {
													template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
												}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke={template.is_pinned === true ? 'none' : 'currentColor'} viewBox="0 0 24 24">
													{#if template.is_pinned === true}
														<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
													{:else}
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
													{/if}
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
											class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
											title="Edit template"
										>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => handleDeleteTemplate(template, e)}
											class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
											title="Delete template"
										>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
									</div>
											{/each}
									{:else}
										<div class="text-center py-8 text-gray-500 text-sm">
											No pinned templates
										</div>
									{/if}
								</div>
							</div>
							{/if}
						
						<!-- Most Used Column (must match header order) -->
						{#if !hideEmptyColumns || mostUsedTemplates.length > 0}
							<div class="flex-shrink-0 w-80" style="overflow: visible; height: 100%; display: flex; flex-direction: column; max-height: 100%;">
							<div class="space-y-3 overflow-y-auto flex-1 scrollbar-thin" style="padding: 8px; min-height: 0; max-height: 100%;">
								{#if mostUsedTemplates.length > 0}
									{#each mostUsedTemplates as template (template.id)}
										{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
										<div 
											class="template-card relative group"
											onmousemove={(e) => handleCardMouseMove(e, template.id)}
											onmouseleave={() => handleCardMouseLeave(template.id)}
											style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
										>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
											onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
									<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
									<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
										<button
											type="button"
											onclick={(e) => handleTogglePin(template, e)}
											disabled={pinningTemplates.has(template.id)}
											class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
												template.is_pinned === true 
													? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
													: 'bg-white/10 hover:bg-white/20 border border-white/20'
											}"
											title={template.is_pinned === true ? 'Unpin' : 'Pin'}
										>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full {
														template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
													} animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 relative z-10 {
													template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
												}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke={template.is_pinned === true ? 'none' : 'currentColor'} viewBox="0 0 24 24">
													{#if template.is_pinned === true}
														<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
													{:else}
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
													{/if}
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
											class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
											title="Edit template"
										>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => handleDeleteTemplate(template, e)}
											class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
											title="Delete template"
										>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
					</div>
				{/each}
									{:else}
										<div class="text-center py-8 text-gray-500 text-sm">
											No most used templates
										</div>
									{/if}
								</div>
							</div>
						{/if}
						
						<!-- Recently Used Column (must match header order) -->
						{#if !hideEmptyColumns || recentlyUsedTemplates.length > 0}
							<div class="flex-shrink-0 w-80" style="overflow: visible; height: 100%; display: flex; flex-direction: column; max-height: 100%;">
							<div class="space-y-3 overflow-y-auto flex-1 scrollbar-thin" style="padding: 8px; min-height: 0; max-height: 100%;">
									{#if recentlyUsedTemplates.length > 0}
										{#each recentlyUsedTemplates as template (template.id)}
											{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
											<div 
												class="template-card relative group"
												onmousemove={(e) => handleCardMouseMove(e, template.id)}
												onmouseleave={() => handleCardMouseLeave(template.id)}
												style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
											>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
											onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
									<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
									<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
										<button
											type="button"
											onclick={(e) => handleTogglePin(template, e)}
											disabled={pinningTemplates.has(template.id)}
											class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
												template.is_pinned === true 
													? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
													: 'bg-white/10 hover:bg-white/20 border border-white/20'
											}"
											title={template.is_pinned === true ? 'Unpin' : 'Pin'}
										>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full {
														template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
													} animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 relative z-10 {
													template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
												}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke={template.is_pinned === true ? 'none' : 'currentColor'} viewBox="0 0 24 24">
													{#if template.is_pinned === true}
														<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
													{:else}
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
													{/if}
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
											class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
											title="Edit template"
										>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => handleDeleteTemplate(template, e)}
											class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
											title="Delete template"
										>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
					</div>
				{/each}
									{:else}
										<div class="text-center py-8 text-gray-500 text-sm">
											No recently used templates
			</div>
		{/if}
								</div>
							</div>
						{/if}
						
						<!-- All Others Column (must match header order) -->
						{#if !hideEmptyColumns || allOtherTemplates.length > 0}
							<div class="flex-shrink-0 w-80" style="overflow: visible; height: 100%; display: flex; flex-direction: column; max-height: 100%;">
							<div class="space-y-3 overflow-y-auto flex-1 scrollbar-thin" style="padding: 8px; min-height: 0; max-height: 100%;">
								{#if allOtherTemplates.length > 0}
									{#each allOtherTemplates as template (template.id)}
										{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
										<div 
											class="template-card relative group"
											onmousemove={(e) => handleCardMouseMove(e, template.id)}
											onmouseleave={() => handleCardMouseLeave(template.id)}
											style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
										>
										<!-- Main clickable area for selecting template -->
										<div
											class="cursor-pointer pr-12 flex flex-col h-full"
											onclick={() => handleTemplateSelect(template)}
											role="button"
											tabindex="0"
											onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
										>
											<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
											{#if template.description}
												<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
											{:else}
												<div class="flex-grow"></div>
											{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
										</div>
									<!-- Action buttons - Pin, Edit, Delete (shown on hover) -->
									<div class="absolute top-3 right-3 flex flex-col gap-1.5 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
										<button
											type="button"
											onclick={(e) => handleTogglePin(template, e)}
											disabled={pinningTemplates.has(template.id)}
											class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
												template.is_pinned === true 
													? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
													: 'bg-white/10 hover:bg-white/20 border border-white/20'
											}"
											title={template.is_pinned === true ? 'Unpin' : 'Pin'}
										>
												{#if pinningTemplates.has(template.id)}
													<div class="absolute inset-0 rounded-full {
														template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
													} animate-pulse"></div>
												{/if}
												<svg class="w-4 h-4 relative z-10 {
													template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
												}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke={template.is_pinned === true ? 'none' : 'currentColor'} viewBox="0 0 24 24">
													{#if template.is_pinned === true}
														<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
													{:else}
														<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
													{/if}
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => { e.stopPropagation(); handleEditTemplate(template); }}
											class="px-2.5 py-2 rounded-full bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 transition-all hover:scale-110"
											title="Edit template"
										>
												<svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
												</svg>
											</button>
										<button
											type="button"
											onclick={(e) => handleDeleteTemplate(template, e)}
											class="px-2.5 py-2 rounded-full bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 transition-all hover:scale-110"
											title="Delete template"
										>
												<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
												</svg>
											</button>
										</div>
									</div>
											{/each}
									{:else}
										<div class="text-center py-8 text-gray-500 text-sm">
											No other templates
										</div>
									{/if}
								</div>
							</div>
						{/if}
						</div>
				{:else}
					<!-- Tag-based Kanban -->
					<!-- Horizontal Navigation Controls -->
					<div class="flex items-center justify-between mb-3 px-2 flex-shrink-0">
						<button
							type="button"
							onclick={() => scrollKanban('left')}
							class="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
							title="Scroll left"
							disabled={!scrollbarVisible}
						>
							<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
							</svg>
						</button>
						{#if scrollbarVisible}
							<div 
								bind:this={scrollbarTrack}
								class="flex-1 mx-4 h-2 bg-white/10 rounded-full overflow-hidden cursor-pointer relative flex-shrink-0"
								onmousedown={(e) => handleTrackClick(e)}
								role="slider"
								tabindex="0"
								aria-label="Horizontal scroll position"
								aria-valuemin="0"
								aria-valuemax="100"
								aria-valuenow={Math.round(scrollPosition * 100)}
								onkeydown={(e) => {
									if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
										e.preventDefault();
										scrollKanban(e.key === 'ArrowLeft' ? 'left' : 'right');
									}
								}}
							>
								<div 
									bind:this={scrollbarThumb}
									class="h-full bg-purple-500 rounded-full absolute cursor-grab active:cursor-grabbing {isDragging ? '' : 'transition-all duration-100'}"
									style="width: {thumbWidth}%; left: {scrollPosition * (100 - thumbWidth)}%;"
									onmousedown={(e) => handleThumbMouseDown(e)}
								></div>
							</div>
						{:else}
							<div class="flex-1 mx-4"></div>
						{/if}
						<button
							type="button"
							onclick={() => scrollKanban('right')}
							class="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-colors flex-shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
							title="Scroll right"
							disabled={!scrollbarVisible}
						>
							<svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
							</svg>
						</button>
					</div>
					
					<!-- Fixed Column Headers Row for Tags -->
					<div 
						bind:this={kanbanHeadersContainer}
						class="kanban-headers-container flex gap-4 mb-3 flex-shrink-0 overflow-x-auto overflow-y-hidden" 
						style="padding: 8px 8px 0.5rem 8px;"
						onscroll={(e) => {
							const target = e.target;
							if (kanbanCardsContainer) {
								kanbanCardsContainer.scrollLeft = target.scrollLeft;
							}
							updateScrollbar();
						}}
					>
						{#each Object.entries(tagGroupedTemplates) as [tag, templates] (tag)}
							{#if !hideEmptyColumns || templates.length > 0}
								<div class="flex-shrink-0 w-80">
									<div class="bg-black/50 backdrop-blur-sm p-3 rounded-lg border" style="border-color: {getTagColorWithOpacity(tag, 0.3, customTagColors)};">
										<div class="flex items-center gap-2">
											<div class="w-3 h-3 rounded-full" style="background-color: {getTagColor(tag, customTagColors)};"></div>
											<h3 class="font-semibold text-white">{tag}</h3>
											<span class="px-2 py-0.5 rounded-full bg-white/10 text-gray-300 text-xs">
												{templates.length}
											</span>
										</div>
									</div>
								</div>
							{/if}
						{/each}
					</div>
					
					<!-- Scrollable Cards Container for Tags -->
					<div 
						bind:this={kanbanCardsContainer}
						class="kanban-container flex gap-4 overflow-x-auto overflow-y-hidden flex-1" 
						style="padding: 8px; padding-bottom: 1rem;"
						onscroll={(e) => {
							const target = e.target;
							if (kanbanHeadersContainer) {
								kanbanHeadersContainer.scrollLeft = target.scrollLeft;
							}
							updateScrollbar();
						}}
					>
						{#each Object.entries(tagGroupedTemplates) as [tag, templates] (tag)}
							{#if !hideEmptyColumns || templates.length > 0}
								<div class="flex-shrink-0 w-80" style="overflow: visible; height: 100%; display: flex; flex-direction: column; max-height: 100%;">
								<div class="space-y-5 overflow-y-auto flex-1 scrollbar-thin" style="padding: 8px; min-height: 0; max-height: 100%;">
									{#each templates as template (template.id)}
										{@const tilt = cardTilts.get(template.id) || { rotateX: 0, rotateY: 0 }}
										<div 
											class="template-card relative group"
											onmousemove={(e) => handleCardMouseMove(e, template.id)}
											onmouseleave={() => handleCardMouseLeave(template.id)}
											style="transform: perspective(1000px) rotateX({tilt.rotateX}deg) rotateY({tilt.rotateY}deg); transform-style: preserve-3d; transition: transform 0.1s ease-out;"
										>
											<!-- Main clickable area for selecting template -->
											<div
												class="cursor-pointer pr-12 flex flex-col h-full"
												onclick={() => handleTemplateSelect(template)}
												role="button"
												tabindex="0"
												onkeydown={(e) => e.key === 'Enter' && handleTemplateSelect(template)}
											>
												<h3 class="text-lg font-semibold text-white mb-2 break-words">{template.name}</h3>
												{#if template.description}
													<p class="text-sm text-gray-400 mb-3 flex-grow">{template.description}</p>
												{:else}
													<div class="flex-grow"></div>
												{/if}
											<!-- Tags at bottom -->
											{#if template.tags && template.tags.length > 0}
												<div class="flex flex-wrap gap-1.5 mt-auto pt-4 border-t border-white/10">
													{#each template.tags.slice(0, 3) as tag}
														<span 
															class="text-xs px-2.5 py-1 rounded-lg border font-medium transition-transform group-hover:scale-105"
															style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
														>
															{tag}
														</span>
													{/each}
													{#if template.tags.length > 3}
														<span class="text-xs px-2.5 py-1 text-gray-400 bg-white/5 rounded-lg border border-white/10">
															+{template.tags.length - 3}
														</span>
													{/if}
												</div>
											{/if}
											</div>
										<!-- Pin button - styled as floating action button (shown on hover) -->
										<div class="absolute top-3 right-3 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none group-hover:pointer-events-auto z-10">
											<button
												type="button"
												onclick={(e) => handleTogglePin(template, e)}
												disabled={pinningTemplates.has(template.id)}
												class="px-2.5 py-2 rounded-full transition-all hover:scale-110 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100 relative {
													template.is_pinned === true 
														? 'bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/40' 
														: 'bg-white/10 hover:bg-white/20 border border-white/20'
												}"
												title={template.is_pinned === true ? 'Unpin' : 'Pin'}
											>
													{#if pinningTemplates.has(template.id)}
														<!-- Subtle pulsing indicator -->
														<div class="absolute inset-0 rounded-full {
															template.is_pinned === true ? 'bg-yellow-400/20' : 'bg-white/20'
														} animate-pulse"></div>
													{/if}
													<svg class="w-4 h-4 relative z-10 {
														template.is_pinned === true ? 'text-yellow-400' : 'text-gray-400'
													}" fill={template.is_pinned === true ? 'currentColor' : 'none'} stroke={template.is_pinned === true ? 'none' : 'currentColor'} viewBox="0 0 24 24">
														{#if template.is_pinned === true}
															<path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" />
														{:else}
															<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
														{/if}
													</svg>
												</button>
											</div>
					</div>
				{/each}
			</div>
							</div>
							{/if}
						{/each}
					</div>
				{/if}
				</div>
			{/if}
		{/if}
		</div>
	{:else}
		<!-- Template Form -->
		<button
			onclick={handleBackToList}
			class="mb-4 text-gray-400 hover:text-white flex items-center gap-2"
		>
			<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
			</svg>
			Back to Templates
		</button>

		<TemplateForm
			selectedTemplate={currentSelectedTemplate}
			bind:selectedModel={templatedModel}
			bind:variableValues
			bind:response
			bind:responseModel
			bind:loading
			bind:error
			{apiKeyStatus}
			{reportUpdateLoading}
			reportId={reportId}
			{versionHistoryRefreshKey}
			enhancementGuidelinesCount={enhancementGuidelinesCount}
			enhancementLoading={enhancementLoading}
			enhancementError={enhancementError}
			on:editTemplate={(e) => handleEditTemplate(e.detail.template)}
			on:resetForm={handleFormReset}
			on:reportGenerated={(e) => {
				// CRITICAL: Preserve variableValues IMMEDIATELY when report is generated
				// This must happen before any re-renders or state updates that might clear them
				if (currentSelectedTemplate && currentSelectedTemplate.id && variableValues && Object.keys(variableValues).length > 0) {
					const templateId = currentSelectedTemplate.id;
					const hasRealValues = Object.values(variableValues).some(v => v && v.trim().length > 0);
					if (hasRealValues) {
						variableValuesByTemplate[templateId] = { ...variableValues };
					}
				}
				
				reportId = e.detail.reportId;
				dispatch('reportGenerated', { reportId: e.detail.reportId });
			}}
			on:openSidebar={(e) => dispatch('openSidebar', e.detail)}
			on:showHoverPopup={(e) => dispatch('showHoverPopup', e.detail)}
			on:hideHoverPopup={() => dispatch('hideHoverPopup')}
			on:historyUpdate={(event) => dispatch('historyUpdate', event.detail)}
			on:historyRestored={(event) => dispatch('historyRestored', event.detail)}
			on:reportCleared={() => dispatch('reportCleared')}
		/>
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
</div>
