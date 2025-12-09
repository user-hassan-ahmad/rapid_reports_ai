<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';
	import DiffMatchPatch from 'diff-match-patch';
	import { marked } from 'marked';
	import { htmlDiff } from '@benedicte/html-diff';

	export let reportId;
	export let refreshKey = 0;

	const dispatch = createEventDispatcher();
	const dmp = new DiffMatchPatch();

	marked.setOptions({
		breaks: true,
		gfm: true
	});

	function renderMarkdown(md) {
		if (!md) return '';
		return marked.parse(md);
	}

	let versions = [];
	let loading = false;
	let error = null;
	let selectedVersionId = null;
	let selectedVersion = null;
	let loadingVersion = false;
	let restoringVersionId = null;
	let showDiffView = false;
	let comparisonVersionId = null;
	let comparisonVersion = null;
	let loadingComparison = false;

	async function loadVersions() {
		if (!reportId) {
			versions = [];
			selectedVersionId = null;
			selectedVersion = null;
			dispatch('historyUpdate', { count: 0 });
			return;
		}

		loading = true;
		error = null;

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions`, { headers });
			const data = await response.json();

			if (!response.ok || !data.success) {
				throw new Error(data.error || `Request failed with status ${response.status}`);
			}

			versions = data.versions || [];
			dispatch('historyUpdate', { count: versions.length });

			if (versions.length > 0) {
				const currentVersion = versions.find((v) => v.is_current) || versions[0];
				comparisonVersion = null;
				await selectVersion(currentVersion, { silent: true });
			} else {
				selectedVersionId = null;
				selectedVersion = null;
				comparisonVersion = null;
			}
		} catch (err) {
			console.error('Failed to load report versions', err);
			error = err instanceof Error ? err.message : String(err);
			versions = [];
			selectedVersionId = null;
			selectedVersion = null;
			dispatch('historyUpdate', { count: 0 });
		} finally {
			loading = false;
		}
	}

	async function loadComparisonVersion(versionId) {
		if (!versionId || !reportId) return null;

		loadingComparison = true;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions/${versionId}`, { headers });
			const data = await response.json();

			if (response.ok && data.success) {
				return data.version;
			}
			return null;
		} catch (err) {
			console.error('Failed to load comparison version', err);
			return null;
		} finally {
			loadingComparison = false;
		}
	}

	async function selectVersion(version, { silent = false } = {}) {
		if (!version || !reportId) {
			selectedVersion = null;
			selectedVersionId = null;
			comparisonVersion = null;
			return;
		}

		if (selectedVersionId === version.id) {
			selectedVersionId = null;
			selectedVersion = null;
			comparisonVersion = null;
			return;
		}

		selectedVersionId = version.id;
		selectedVersion = null;
		comparisonVersion = null;
		loadingVersion = true;

		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions/${version.id}`, { headers });
			const data = await response.json();

			if (!response.ok || !data.success) {
				throw new Error(data.error || `Request failed with status ${response.status}`);
			}

			selectedVersion = data.version;
			
			// Reset comparison when version changes
			comparisonVersionId = null;
			comparisonVersion = null;
			
			// Auto-select a comparison version if diff view is enabled
			if (showDiffView && versions.length > 1) {
				const currentIndex = versions.findIndex(v => v.id === version.id);
				if (currentIndex > 0) {
					// Select previous version
					comparisonVersionId = versions[currentIndex - 1].id;
				} else if (versions.length > 1) {
					// If this is the first version, select the next one
					comparisonVersionId = versions[1].id;
				}
				if (comparisonVersionId) {
					comparisonVersion = await loadComparisonVersion(comparisonVersionId);
				}
			}

			if (!silent) {
				dispatch('versionSelected', { version: data.version });
			}
		} catch (err) {
			console.error('Failed to load version detail', err);
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loadingVersion = false;
		}
	}

	async function toggleDiffView() {
		showDiffView = !showDiffView;
		if (showDiffView && selectedVersion && versions.length > 1) {
			// Auto-select previous version if available, otherwise select first available
			const currentIndex = versions.findIndex(v => v.id === selectedVersionId);
			if (currentIndex > 0) {
				comparisonVersionId = versions[currentIndex - 1].id;
			} else if (versions.length > 1) {
				// If this is the first version, select the next one
				comparisonVersionId = versions[1].id;
			}
			if (comparisonVersionId) {
				comparisonVersion = await loadComparisonVersion(comparisonVersionId);
			}
		} else {
			comparisonVersionId = null;
			comparisonVersion = null;
		}
	}

	async function changeComparisonVersion(versionId) {
		comparisonVersionId = versionId;
		if (versionId && showDiffView) {
			comparisonVersion = await loadComparisonVersion(versionId);
		} else {
			comparisonVersion = null;
		}
	}

	// Get available versions for comparison (all versions except the currently selected one)
	$: availableComparisonVersions = selectedVersion && versions.length > 1
		? versions.filter(v => v.id !== selectedVersionId).reverse()
		: [];

	function renderDiffWithMarkdown(oldText, newText) {
		if (!oldText || !newText) return '';
		
		// Render both versions as markdown HTML first
		const oldHtml = renderMarkdown(oldText);
		const newHtml = renderMarkdown(newText);
		
		// Use html-diff to compute the diff on rendered HTML
		// This avoids spacing issues because we're diffing the final rendered output
		const diffedHtml = htmlDiff(oldHtml, newHtml);
		
		// html-diff uses <ins> for additions and <del> for deletions
		// We need to style these tags with our color scheme
		return diffedHtml
			.replace(/<ins>/g, '<ins class="bg-green-500/30 text-green-200 px-0.5 rounded no-underline">')
			.replace(/<del>/g, '<del class="bg-red-500/30 text-red-200 px-0.5 rounded line-through">');
	}

	async function restoreVersion(version) {
		if (!version || !reportId) return;
		if (restoringVersionId) return;

		const confirmRestore = confirm(`Restore report to version ${version.version_number}?`);
		if (!confirmRestore) return;

		restoringVersionId = version.id;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions/${version.id}/restore`, {
				method: 'POST',
				headers
			});
			const data = await response.json();

			if (!response.ok || !data.success) {
				throw new Error(data.error || `Restore failed with status ${response.status}`);
			}

			dispatch('restored', { report: data.report, version: data.version });
			await loadVersions();
		} catch (err) {
			console.error('Failed to restore version', err);
			alert(err instanceof Error ? err.message : 'Failed to restore version.');
		} finally {
			restoringVersionId = null;
		}
	}

	function formatDate(value) {
		if (!value) return 'Unknown';
		const date = new Date(value);
		return date.toLocaleString();
	}

	onMount(loadVersions);

	let lastReportId = null;
	let lastRefreshKey = -1;
	$: if (reportId && (reportId !== lastReportId || refreshKey !== lastRefreshKey)) {
		lastReportId = reportId;
		lastRefreshKey = refreshKey;
		loadVersions();
	}
</script>

<div class="space-y-4">
	{#if loading}
		<div class="flex justify-center py-10">
			<div class="w-6 h-6 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
		</div>
	{:else if error}
		<div class="p-4 rounded-lg border border-red-500/30 bg-red-500/10 text-sm text-red-300">
			{error}
		</div>
	{:else if versions.length === 0}
		<div class="text-sm text-gray-400">
			Version history will appear here after the report is modified.
		</div>
	{:else}
		<div class="space-y-2">
			{#each versions as version}
				<div class="rounded-lg border border-white/10 bg-white/5 transition-colors hover:border-purple-500/40">
					<button
						type="button"
						class="w-full flex items-center justify-between px-4 py-3 text-left"
						onclick={() => selectVersion(version)}
					>
						<div>
							<div class="flex items-center gap-2">
								<span class="text-sm font-semibold text-white">Version {version.version_number}</span>
								{#if version.is_current}
									<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/30 text-purple-200 font-medium uppercase tracking-wide">Current</span>
								{/if}
								{#if version.notes === 'Manual content update'}
									<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/30 text-blue-200 font-medium uppercase tracking-wide">Manual Edit</span>
								{:else if version.notes === 'Chat edit'}
									<span class="text-[10px] px-2 py-0.5 rounded-full bg-green-500/30 text-green-200 font-medium uppercase tracking-wide">Chat Edit</span>
								{:else if version.notes === 'Comparison edit'}
									<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/30 text-amber-200 font-medium uppercase tracking-wide">Comparison Edit</span>
								{/if}
							</div>
							<p class="text-xs text-gray-400 mt-1">{formatDate(version.created_at)}</p>
							{#if version.actions_applied && version.actions_applied.length > 0}
								<p class="text-[11px] text-gray-500 mt-2 leading-snug">
									{version.actions_applied.length} action{version.actions_applied.length === 1 ? '' : 's'} applied
								</p>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							{#if !version.is_current}
								<button
									type="button"
									onclick={(event) => {
										event.stopPropagation();
										restoreVersion(version);
									}}
									class="px-3 py-1 text-xs font-medium rounded-md bg-purple-600 hover:bg-purple-700 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
									disabled={restoringVersionId === version.id}
								>
									{restoringVersionId === version.id ? 'Restoring...' : 'Restore'}
								</button>
							{/if}
							<svg
								class="w-4 h-4 text-gray-400 transition-transform {selectedVersionId === version.id ? 'rotate-180' : ''}"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
							</svg>
						</div>
					</button>
					{#if selectedVersionId === version.id && selectedVersion}
						<div class="px-4 pb-4 space-y-4">
							{#if loadingVersion}
								<div class="text-sm text-gray-400 py-4 flex items-center gap-2">
									<div class="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
									Loading details...
								</div>
							{:else}
							{#if selectedVersion.actions_applied && selectedVersion.actions_applied.length > 0}
								<div class="space-y-2">
									<h5 class="text-xs font-semibold text-white uppercase tracking-wide">Actions Applied</h5>
									<ul class="space-y-2">
										{#each selectedVersion.actions_applied as action, idx}
											<li class="p-3 rounded-lg border border-white/10 bg-white/5">
												<p class="text-xs text-gray-400 mb-1">Action {idx + 1}: {action.title || action.id}</p>
												{#if action.details}
													<p class="text-sm text-gray-300 mb-2">{action.details}</p>
												{/if}
												{#if action.patch}
													<pre class="text-xs text-gray-200 bg-gray-950/70 border border-gray-800 rounded-md p-3 whitespace-pre-wrap overflow-x-auto">{action.patch}</pre>
												{/if}
											</li>
										{/each}
									</ul>
								</div>
							{/if}
							<div>
								<div class="flex items-center justify-between mb-2">
									<h5 class="text-xs font-semibold text-white uppercase tracking-wide">Report Content</h5>
									<div class="flex items-center gap-2">
										{#if versions.length > 1}
											<button
												type="button"
												onclick={toggleDiffView}
												class="px-2 py-1 text-xs rounded-md transition-colors {showDiffView ? 'bg-purple-600 text-white' : 'bg-white/10 text-gray-300 hover:bg-white/20'}"
											>
												{showDiffView ? 'Hide Changes' : 'Track Changes'}
											</button>
										{/if}
									</div>
								</div>
								{#if showDiffView && versions.length > 1}
									<div class="mb-2 flex items-center gap-2">
										<span class="text-xs text-gray-400">Compare with:</span>
										<select
											onchange={(e) => changeComparisonVersion(e.target.value)}
											value={comparisonVersionId || ''}
											class="px-3 py-1.5 pr-8 text-xs rounded-md bg-white/10 text-gray-300 border border-white/20 focus:outline-none focus:ring-2 focus:ring-purple-500 min-w-[160px] appearance-none bg-[url('data:image/svg+xml;charset=UTF-8,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23d1d5db%22 stroke-width=%222%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22%3E%3Cpath d=%22M6 9l6 6 6-6%22/%3E%3C/svg%3E')] bg-[length:16px_16px] bg-[right_0.5rem_center] bg-no-repeat"
										>
											<option value="">Select version...</option>
											{#each availableComparisonVersions as compVersion}
												<option value={compVersion.id}>
													Version {compVersion.version_number}
													{#if compVersion.is_current}
														(Current)
													{/if}
												</option>
											{/each}
										</select>
									</div>
									{#if loadingComparison}
										<div class="text-xs text-gray-400 py-2">Loading comparison...</div>
									{:else if comparisonVersion}
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto max-h-80">
											{@html renderDiffWithMarkdown(comparisonVersion.report_content, selectedVersion.report_content)}
										</div>
									{:else if comparisonVersionId}
										<div class="text-xs text-gray-400 py-2">Loading comparison version...</div>
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto max-h-80">
											{@html renderMarkdown(selectedVersion.report_content)}
										</div>
									{:else}
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto max-h-80">
											{@html renderMarkdown(selectedVersion.report_content)}
										</div>
									{/if}
								{:else}
									<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto max-h-80">
										{@html renderMarkdown(selectedVersion.report_content)}
									</div>
								{/if}
							</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

