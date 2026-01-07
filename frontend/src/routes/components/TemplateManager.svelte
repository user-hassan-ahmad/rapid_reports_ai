<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { browser } from '$app/environment';
	// NOTE: TemplateEditorNew is the active template editor component
	// TemplateEditor.svelte exists but is legacy/unused
	import TemplateEditorNew from './TemplateEditorNew.svelte';
	import { token } from '$lib/stores/auth';
	import { settingsStore } from '$lib/stores/settings';
	import { getTagColor, getTagColorWithOpacity } from '$lib/utils/tagColors.js';
	import { API_URL } from '$lib/config';

	export let templates = [];
	export let selectedModel = 'claude';
	export let hideUseButton = false;
	export let hideCreateButton = false;
	export let customTagColors = {}; // Accept from parent or load if not provided
	export let initialEditTemplate = null;
	export let cameFromTab = null;

	onMount(() => {
		// Only load settings if customTagColors not provided as prop
		if ((!customTagColors || Object.keys(customTagColors).length === 0) && !$settingsStore.settings) {
			settingsStore.loadSettings();
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
		<TemplateEditorNew
		{editingTemplate}
		{selectedModel}
		{cameFromTab}
		on:close={handleEditorClose}
		on:saved={handleEditorSaved}
		on:backToSource={() => dispatch('backToSource')}
	/>
{:else}
	<div class="p-6">
		<!-- Header -->
		{#if !hideCreateButton}
			<div class="flex justify-between items-center mb-6">
				<h2 class="text-2xl font-bold text-white">My Templates</h2>
				<button
					onclick={handleCreate}
					class="btn-primary"
				>
					+ Create Template
				</button>
			</div>
		{:else}
			<div class="mb-6">
				<h2 class="text-2xl font-bold text-white">My Templates</h2>
			</div>
		{/if}

		<!-- Template List -->
		{#if templates.length === 0}
			<div class="text-center py-12 bg-white/5 backdrop-blur-xl rounded-lg border border-white/10">
				<p class="text-gray-400 mb-4">No templates yet</p>
				{#if !hideCreateButton}
					<button
						onclick={handleCreate}
						class="btn-primary"
					>
						Create your first template
					</button>
				{/if}
			</div>
		{:else}
			<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
				{#each templates as template}
					<div class="group relative bg-gradient-to-br from-white/5 via-white/[0.03] to-white/5 backdrop-blur-xl rounded-xl border border-white/10 hover:border-purple-500/30 hover:shadow-2xl hover:shadow-purple-500/20 transition-all duration-300 overflow-hidden">
						<!-- Gradient overlay on hover -->
						<div class="absolute inset-0 bg-gradient-to-br from-purple-500/0 to-blue-500/0 group-hover:from-purple-500/5 group-hover:to-blue-500/5 transition-all duration-300 pointer-events-none"></div>
						
						<div class="relative p-6 flex flex-col h-full">
							<div class="flex-1">
								<!-- Header with icon -->
								<div class="flex items-start justify-between mb-4">
									<div class="flex-1 min-w-0">
										<div class="flex items-center gap-2 mb-2">
											<div class="flex-shrink-0 w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500/20 to-blue-500/20 border border-purple-500/30 flex items-center justify-center">
												<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
													<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
												</svg>
											</div>
											<h3 class="text-lg font-bold text-white break-words leading-tight">
												{template.name}
											</h3>
										</div>
										{#if template.description}
											<p class="text-sm text-gray-400 mb-4 line-clamp-2">
												{template.description}
											</p>
										{/if}
									</div>
								</div>
								
								<!-- Tags -->
								{#if template.tags && template.tags.length > 0}
									<div class="flex flex-wrap gap-2 mb-4">
										{#each template.tags.slice(0, 4) as tag}
											<span 
												class="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium border transition-all group-hover:scale-105"
												style="background-color: {getTagColor(tag, customTagColors)}; color: white; border-color: {getTagColorWithOpacity(tag, 0.5, customTagColors)};"
											>
												{tag}
											</span>
										{/each}
										{#if template.tags.length > 4}
											<span class="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium text-gray-400 bg-white/5 border border-white/10">
												+{template.tags.length - 4}
											</span>
										{/if}
									</div>
								{/if}
								{#if template.usage_count > 0 || template.last_used_at}
									<div class="flex items-center gap-4 text-xs text-gray-500 mt-2">
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
								{/if}
							</div>
							<!-- Footer with stats and actions -->
							<div class="mt-auto pt-4 border-t border-white/10">
								{#if template.usage_count > 0 || template.last_used_at}
									<div class="flex items-center gap-4 text-xs text-gray-500 mb-4">
										{#if template.usage_count > 0}
											<span class="flex items-center gap-1.5">
												<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
								{/if}
								
								<!-- Action buttons -->
								<div class="flex gap-2">
									{#if !hideUseButton}
										<button
											onclick={() => handleSelect(template)}
											class="flex-1 px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white text-sm font-medium rounded-lg hover:shadow-lg hover:shadow-purple-500/50 transition-all duration-300 hover:scale-105"
										>
											Use Template
										</button>
									{/if}
									<button
										onclick={() => handleEdit(template)}
										class="px-4 py-2 btn-secondary text-sm font-medium rounded-lg hover:scale-105 transition-transform"
									>
										Edit
									</button>
									<button
										onclick={() => handleDelete(template)}
										class="px-4 py-2 btn-danger text-sm font-medium rounded-lg hover:scale-105 transition-transform"
									>
										Delete
									</button>
								</div>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

