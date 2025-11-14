<script>
	import { onMount } from 'svelte';
	import { token } from '$lib/stores/auth';

	export let templateId;
	export let onRestore = () => {};
	export let refreshKey = 0; // Increment this to trigger a reload

	let versions = [];
	let loading = false;
	let error = null;
	let showVersionDetail = false;
	let selectedVersion = null;
	const API_URL = 'http://localhost:8000';

	async function loadVersions() {
		if (!templateId) return;
		
		loading = true;
		error = null;
		
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${templateId}/versions`, {
				headers
			});
			
			const data = await response.json();
			if (data.success) {
				versions = data.versions || [];
			} else {
				error = data.error || 'Failed to load versions';
			}
		} catch (err) {
			error = 'Failed to load versions';
			console.error(err);
		} finally {
			loading = false;
		}
	}

	async function handleRestore(version) {
		if (!confirm(`Are you sure you want to restore this template to version ${version.version_number}? This will create a new version snapshot of the current state before restoring.`)) {
			return;
		}

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${templateId}/versions/${version.id}/restore`, {
				method: 'POST',
				headers
			});
			
			const data = await response.json();
			if (data.success) {
				// Reload versions to show the new snapshot
				await loadVersions();
				// Call the restore callback
				onRestore();
			} else {
				alert('Failed to restore version: ' + (data.error || 'Unknown error'));
			}
		} catch (err) {
			alert('Failed to restore version');
			console.error(err);
		}
	}

	async function handleDelete(version) {
		if (!confirm(`Are you sure you want to delete version ${version.version_number}? This action cannot be undone.`)) {
			return;
		}

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${templateId}/versions/${version.id}`, {
				method: 'DELETE',
				headers
			});
			
			const data = await response.json();
			if (data.success) {
				// Reload versions after deletion
				await loadVersions();
			} else {
				alert('Failed to delete version: ' + (data.error || 'Unknown error'));
			}
		} catch (err) {
			alert('Failed to delete version');
			console.error(err);
		}
	}

	async function viewVersionDetails(version) {
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/templates/${templateId}/versions/${version.id}`, {
				headers
			});
			
			const data = await response.json();
			if (data.success) {
				selectedVersion = data.version;
				showVersionDetail = true;
			} else {
				alert('Failed to load version details: ' + (data.error || 'Unknown error'));
			}
		} catch (err) {
			alert('Failed to load version details');
			console.error(err);
		}
	}

	function formatDate(dateString) {
		if (!dateString) return 'Unknown';
		const date = new Date(dateString);
		return date.toLocaleString();
	}

	onMount(() => {
		if (templateId) {
			loadVersions();
		}
	});

	// Reload when templateId or refreshKey changes (combined to avoid double-loading)
	let lastTemplateId = null;
	let lastRefreshKey = -1;
	$: if (templateId && (templateId !== lastTemplateId || refreshKey !== lastRefreshKey)) {
		lastTemplateId = templateId;
		lastRefreshKey = refreshKey;
		loadVersions();
	}
</script>

<div class="space-y-4">
	<div class="flex items-center justify-between">
		<h3 class="text-lg font-semibold text-white">Version History</h3>
		{#if versions.length > 0}
			<span class="text-xs text-gray-400">
				Showing {versions.length} of up to 10 versions
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="text-center py-8">
			<div class="text-gray-400">Loading versions...</div>
		</div>
	{:else if error}
		<div class="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
			<p class="text-red-400 text-sm">{error}</p>
		</div>
	{:else if versions.length === 0}
		<div class="text-center py-8">
			<p class="text-gray-400 text-sm">No version history yet</p>
			<p class="text-gray-500 text-xs mt-1">Versions are created automatically when you edit templates</p>
		</div>
	{:else}
		<div class="space-y-2 max-h-96 overflow-y-auto">
			{#each versions as version}
				<div class="p-3 rounded-lg border flex items-center justify-between {version.is_current ? 'bg-blue-500/20 border-blue-500/50' : 'bg-white/5 border-white/10'}">
					<div class="flex-1">
						<div class="flex items-center gap-2 mb-1">
							<span class="text-sm font-medium text-white">Version {version.version_number}</span>
							{#if version.is_current}
								<span class="text-xs px-2 py-0.5 rounded-full bg-blue-500/30 text-blue-300 font-medium">Current</span>
							{/if}
							<span class="text-xs text-gray-400">{formatDate(version.created_at)}</span>
						</div>
						{#if version.name}
							<p class="text-xs text-gray-500 truncate">{version.name}</p>
						{/if}
					</div>
					<div class="flex gap-2 ml-4">
							{#if !version.is_current}
								<button
									type="button"
									onclick={() => viewVersionDetails(version)}
									class="px-2 py-1 text-xs btn-secondary"
								>
									View
								</button>
								<button
									type="button"
									onclick={() => handleRestore(version)}
									class="px-2 py-1 text-xs btn-primary"
								>
									Restore
								</button>
								<button
									type="button"
									onclick={() => handleDelete(version)}
									class="px-2 py-1 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded transition-colors"
									title="Delete version"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
									</svg>
								</button>
							{:else}
								<span class="px-2 py-1 text-xs text-gray-500 italic">Current</span>
							{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<!-- Version Detail Modal -->
{#if showVersionDetail && selectedVersion}
	<div 
		class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-3 z-50"
		onclick={() => { showVersionDetail = false; selectedVersion = null; }}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
		onkeydown={(e) => e.key === 'Escape' && (showVersionDetail = false, selectedVersion = null)}
	>
		<div 
			class="card-dark p-6 max-w-2xl w-full max-h-[90vh] overflow-y-auto"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<div class="flex items-center justify-between mb-4">
				<div class="flex items-center gap-3">
					<h3 class="text-xl font-bold text-white">Version {selectedVersion.version_number}</h3>
					{#if selectedVersion.is_current}
						<span class="text-xs px-2 py-1 rounded-full bg-blue-500/30 text-blue-300 font-medium">Current Version</span>
					{/if}
				</div>
				<button
					type="button"
					onclick={() => { showVersionDetail = false; selectedVersion = null; }}
					class="p-1 text-gray-400 hover:text-white"
					aria-label="Close version details"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			
			<div class="space-y-4">
				<div>
					<div class="block text-sm font-medium text-gray-300 mb-1">Created</div>
					<p class="text-sm text-gray-400">{formatDate(selectedVersion.created_at)}</p>
				</div>
				
				<div>
					<div class="block text-sm font-medium text-gray-300 mb-1">Name</div>
					<p class="text-sm text-white">{selectedVersion.name || 'N/A'}</p>
				</div>
				
				{#if selectedVersion.description}
					<div>
						<div class="block text-sm font-medium text-gray-300 mb-1">Description</div>
						<p class="text-sm text-gray-400">{selectedVersion.description}</p>
					</div>
				{/if}
				
				{#if selectedVersion.tags && selectedVersion.tags.length > 0}
					<div>
						<div class="block text-sm font-medium text-gray-300 mb-1">Tags</div>
						<div class="flex flex-wrap gap-1">
							{#each selectedVersion.tags as tag}
								<span class="text-xs px-2 py-1 rounded bg-gray-700 text-gray-300">{tag}</span>
							{/each}
						</div>
					</div>
				{/if}
				
				{#if selectedVersion.variables && selectedVersion.variables.length > 0}
					<div>
						<div class="block text-sm font-medium text-gray-300 mb-1">Variables</div>
						<p class="text-sm text-gray-400">{selectedVersion.variables.join(', ')}</p>
					</div>
				{/if}
				
				<div>
					<div class="block text-sm font-medium text-gray-300 mb-1">Template Content</div>
					<pre class="text-xs text-gray-300 bg-gray-900 p-3 rounded overflow-x-auto whitespace-pre-wrap">{selectedVersion.template_content}</pre>
				</div>
				
				{#if selectedVersion.master_prompt_instructions}
					<div>
						<div class="block text-sm font-medium text-gray-300 mb-1">Custom Instructions</div>
						<p class="text-sm text-gray-400 whitespace-pre-wrap">{selectedVersion.master_prompt_instructions}</p>
					</div>
				{/if}
			</div>
			
			<div class="mt-6 flex justify-end">
				<button
					type="button"
					onclick={() => { showVersionDetail = false; selectedVersion = null; }}
					class="btn-secondary"
				>
					Close
				</button>
			</div>
		</div>
	</div>
{/if}

