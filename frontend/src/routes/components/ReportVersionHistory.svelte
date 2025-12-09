<script>
	import { onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';
	import DiffMatchPatch from 'diff-match-patch';
	import { marked } from 'marked';
	import { htmlDiff } from '@benedicte/html-diff';

	export let reportId;
	export let show = false;
	export let onClose = () => {};
	export let refreshKey = 0;

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
	let selectedVersion = null;
	let loadingVersion = false;
	let showDiffView = false;
	let comparisonVersionId = null;
	let comparisonVersion = null;
	let loadingComparison = false;

	async function loadVersions() {
		if (!reportId || !show) return;
		loading = true;
		error = null;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions`, { headers });
			const data = await response.json();
			if (response.ok && data.success) {
				versions = data.versions || [];
				comparisonVersion = null;
			} else {
				error = data.error || 'Failed to load version history.';
			}
		} catch (err) {
			console.error(err);
			error = 'Failed to load version history.';
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

	async function openVersion(version) {
		if (!reportId || !version) return;
		loadingVersion = true;
		selectedVersion = null;
		comparisonVersion = null;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions/${version.id}`, { headers });
			const data = await response.json();
			if (response.ok && data.success) {
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
			} else {
				alert(data.error || 'Failed to load version details.');
			}
		} catch (err) {
			console.error(err);
			alert('Failed to load version details.');
		} finally {
			loadingVersion = false;
		}
	}

	async function toggleDiffView() {
		showDiffView = !showDiffView;
		if (showDiffView && selectedVersion && versions.length > 1) {
			// Auto-select previous version if available, otherwise select first available
			const currentIndex = versions.findIndex(v => v.id === selectedVersion.id);
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
		? versions.filter(v => v.id !== selectedVersion.id).reverse()
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

	function formatDate(value) {
		if (!value) return 'Unknown';
		const date = new Date(value);
		return date.toLocaleString();
	}

	onMount(() => {
		if (show) {
			loadVersions();
		}
	});

	let lastShow = false;
	let lastRefreshKey = -1;
	$: if (show && (show !== lastShow || refreshKey !== lastRefreshKey)) {
		lastShow = show;
		lastRefreshKey = refreshKey;
		loadVersions();
	}
</script>

{#if show}
	<div
		class="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center p-4 z-[11000]"
		role="dialog"
		aria-modal="true"
				onclick={(event) => {
			if (event.target === event.currentTarget) {
				onClose();
				selectedVersion = null;
				comparisonVersion = null;
				showDiffView = false;
			}
		}}
	>
		<div class="card-dark w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
			<div class="flex items-center justify-between px-6 py-4 border-b border-white/10">
				<div>
					<h3 class="text-xl font-semibold text-white">Report Version History</h3>
					<p class="text-xs text-gray-400">Review prior generations and applied actions.</p>
				</div>
				<button
					type="button"
					class="p-1 text-gray-400 hover:text-white transition-colors"
					onclick={() => { onClose(); selectedVersion = null; comparisonVersion = null; comparisonVersionId = null; showDiffView = false; }}
					aria-label="Close version history"
				>
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			<div class="flex-1 overflow-hidden flex">
				<div class="w-72 border-r border-white/10 overflow-y-auto">
					{#if loading}
						<div class="p-4 text-sm text-gray-400">Loading versions...</div>
					{:else if error}
						<div class="p-4 text-sm text-red-400">{error}</div>
					{:else if versions.length === 0}
						<div class="p-4 text-sm text-gray-400">No version history yet.</div>
					{:else}
						<ul class="divide-y divide-white/5">
							{#each versions as version}
								<li
									class="p-4 cursor-pointer hover:bg-white/5 transition-colors {selectedVersion?.id === version.id ? 'bg-white/10' : ''}"
									onclick={() => openVersion(version)}
								>
									<div class="flex items-center justify-between">
										<div class="flex items-center gap-2">
											<span class="text-sm font-semibold text-white">Version {version.version_number}</span>
											{#if version.is_current}
												<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/30 text-purple-200 font-medium">Current</span>
											{/if}
											{#if version.notes === 'Manual content update'}
												<span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/30 text-blue-200 font-medium">Manual Edit</span>
											{:else if version.notes === 'Chat edit'}
												<span class="text-[10px] px-2 py-0.5 rounded-full bg-green-500/30 text-green-200 font-medium">Chat Edit</span>
											{:else if version.notes === 'Comparison edit'}
												<span class="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/30 text-amber-200 font-medium">Comparison Edit</span>
											{/if}
										</div>
									</div>
									<p class="text-xs text-gray-400 mt-1">{formatDate(version.created_at)}</p>
									{#if version.actions_applied && version.actions_applied.length > 0}
										<p class="text-[11px] text-gray-500 mt-2 leading-snug">
											{version.actions_applied.length} actions applied
										</p>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</div>

				<div class="flex-1 overflow-y-auto">
					{#if loadingVersion}
						<div class="p-6 text-sm text-gray-400">Loading version details...</div>
					{:else if selectedVersion}
						<div class="p-6 space-y-6">
							<div>
								<h4 class="text-lg font-semibold text-white">Version {selectedVersion.version_number}</h4>
								<p class="text-xs text-gray-400">{formatDate(selectedVersion.created_at)}</p>
							</div>

							{#if selectedVersion.actions_applied && selectedVersion.actions_applied.length > 0}
								<div class="space-y-2">
									<h5 class="text-sm font-semibold text-white uppercase tracking-wide">Actions Applied</h5>
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
									<h5 class="text-sm font-semibold text-white uppercase tracking-wide">Report Content</h5>
									<div class="flex items-center gap-2">
										{#if versions.length > 1}
											<button
												type="button"
												onclick={toggleDiffView}
												class="px-3 py-1 text-xs rounded-md transition-colors {showDiffView ? 'bg-purple-600 text-white' : 'bg-white/10 text-gray-300 hover:bg-white/20'}"
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
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto">
											{@html renderDiffWithMarkdown(comparisonVersion.report_content, selectedVersion.report_content)}
										</div>
									{:else if comparisonVersionId}
										<div class="text-xs text-gray-400 py-2">Loading comparison version...</div>
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto">
											{@html renderMarkdown(selectedVersion.report_content)}
										</div>
									{:else}
										<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto">
											{@html renderMarkdown(selectedVersion.report_content)}
										</div>
									{/if}
								{:else}
									<div class="prose prose-invert prose-sm max-w-none text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 overflow-x-auto">
										{@html renderMarkdown(selectedVersion.report_content)}
									</div>
								{/if}
							</div>
						</div>
					{:else}
						<div class="p-6 text-sm text-gray-400">
							Select a version to view full details.
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}
