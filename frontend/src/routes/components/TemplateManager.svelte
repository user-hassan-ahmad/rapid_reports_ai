<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { browser } from '$app/environment';
	import TemplateEditor from './TemplateEditor.svelte';
	import { token } from '$lib/stores/auth';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import { API_URL } from '$lib/config';

	export let templates = [];
	export let selectedModel = 'claude';
	export let hideUseButton = false;
	export let customTagColors = {}; // Accept from parent or load if not provided
	export let initialEditTemplate = null;
	export let cameFromTab = null;


	async function loadUserSettings() {
		if (!browser) return;
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

	onMount(() => {
		// Only load if not provided as prop or empty
		if (!customTagColors || Object.keys(customTagColors).length === 0) {
			loadUserSettings();
		}
	});

	const dispatch = createEventDispatcher();

	let showEditor = false;
	let editingTemplate = null;
	let hasHandledInitialEdit = false;

	// Handle initialEditTemplate prop - open editor when template is provided
	$: if (initialEditTemplate && !hasHandledInitialEdit) {
		editingTemplate = initialEditTemplate;
		showEditor = true;
		hasHandledInitialEdit = true;
		dispatch('editorStateChange', { open: true });
	}

	// Reset flag when initialEditTemplate is cleared
	$: if (!initialEditTemplate && hasHandledInitialEdit) {
		hasHandledInitialEdit = false;
	}

	function handleCreate() {
		editingTemplate = null;
		showEditor = true;
		dispatch('editorStateChange', { open: true });
	}

	function handleEdit(template) {
		editingTemplate = template;
		showEditor = true;
		dispatch('editorStateChange', { open: true });
	}

	function handleSelect(template) {
		dispatch('templateSelect', template);
	}

	async function handleDelete(template) {
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
				dispatch('templateDeleted');
			} else {
				alert('Failed to delete template: ' + data.error);
			}
		} catch (err) {
			console.error('Failed to delete template:', err);
			alert('Failed to delete template');
		}
	}

	function handleEditorClose() {
		showEditor = false;
		editingTemplate = null;
		dispatch('editorStateChange', { open: false });
	}

	function handleEditorSaved() {
		showEditor = false;
		editingTemplate = null;
		dispatch('editorStateChange', { open: false });
		dispatch('templateCreated');
	}
</script>

{#if showEditor}
	<TemplateEditor
		{editingTemplate}
		{selectedModel}
		{cameFromTab}
		on:close={handleEditorClose}
		on:saved={handleEditorSaved}
		on:backToSource={() => dispatch('backToSource')}
	/>
{:else}
	<div class="p-6">
		<!-- Header with Create Button -->
		<div class="flex justify-between items-center mb-6">
			<h2 class="text-2xl font-bold text-white">My Templates</h2>
		<button
			onclick={handleCreate}
			class="btn-primary"
		>
			+ Create Template
		</button>
		</div>

		<!-- Template List -->
		{#if templates.length === 0}
			<div class="text-center py-12 bg-white/5 backdrop-blur-xl rounded-lg border border-white/10">
				<p class="text-gray-400 mb-4">No templates yet</p>
				<button
					onclick={handleCreate}
					class="btn-primary"
				>
					Create your first template
				</button>
			</div>
		{:else}
			<div class="grid gap-4">
				{#each templates as template}
					<div class="p-4 bg-white/5 backdrop-blur-xl rounded-lg border border-white/10 hover:border-white/20 hover:shadow-lg hover:shadow-purple-500/10 transition-all duration-300">
						<div class="flex justify-between items-start">
							<div class="flex-1">
								<h3 class="text-lg font-semibold text-white mb-1">
									{template.name}
								</h3>
								{#if template.description}
									<p class="text-sm text-gray-400 mb-2">
										{template.description}
									</p>
								{/if}
								{#if template.tags && template.tags.length > 0}
									<div class="flex flex-wrap gap-1 mb-2">
										{#each template.tags as tag}
											<span 
												class="inline-block text-xs px-2 py-1 rounded-full border font-medium"
												style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
											>
												{tag}
											</span>
										{/each}
									</div>
								{/if}
								<div class="flex items-center gap-4 text-xs text-gray-500">
									<span>{template.variables?.length || 0} variable{template.variables?.length !== 1 ? 's' : ''}</span>
									{#if template.usage_count > 0}
										<span class="flex items-center gap-1">
											<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
											</svg>
											Used {template.usage_count} time{template.usage_count !== 1 ? 's' : ''}
										</span>
									{/if}
									{#if template.last_used_at}
										<span class="text-gray-400">
											Last: {new Date(template.last_used_at).toLocaleDateString()}
										</span>
									{/if}
								</div>
							</div>
							<div class="flex gap-2">
								{#if !hideUseButton}
									<button
										onclick={() => handleSelect(template)}
										class="px-3 py-1 bg-gradient-to-r from-purple-600 to-blue-600 text-white text-sm rounded hover:shadow-lg hover:shadow-purple-500/50 transition-all duration-300"
									>
										Use
									</button>
								{/if}
								<button
									onclick={() => handleEdit(template)}
									class="px-3 py-1 btn-secondary text-sm"
								>
									Edit
								</button>
								<button
									onclick={() => handleDelete(template)}
									class="px-3 py-1 btn-danger text-sm"
								>
									Delete
								</button>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

