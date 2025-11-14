<script>
	import { createEventDispatcher, onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';

	export let reportId;
	export let refreshKey = 0;

	const dispatch = createEventDispatcher();

	let versions = [];
	let loading = false;
	let error = null;
	let selectedVersionId = null;
	let selectedVersion = null;
	let loadingVersion = false;
	let restoringVersionId = null;

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
				await selectVersion(currentVersion, { silent: true });
			} else {
				selectedVersionId = null;
				selectedVersion = null;
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

	async function selectVersion(version, { silent = false } = {}) {
		if (!version || !reportId) {
			selectedVersion = null;
			selectedVersionId = null;
			return;
		}

		if (selectedVersionId === version.id && selectedVersion) {
			return;
		}

		selectedVersionId = version.id;
		selectedVersion = null;
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
							</div>
							<p class="text-xs text-gray-400 mt-1">{formatDate(version.created_at)}</p>
							{#if version.actions_applied && version.actions_applied.length > 0}
								<p class="text-[11px] text-gray-500 mt-2 leading-snug">
									{version.actions_applied.length} action{version.actions_applied.length === 1 ? '' : 's'} applied
								</p>
							{/if}
							{#if version.report_content_preview}
								<p class="text-[11px] text-gray-500 mt-2 leading-snug line-clamp-3">
									{version.report_content_preview}
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
								<h5 class="text-xs font-semibold text-white uppercase tracking-wide mb-2">Report Content</h5>
								<pre class="text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 whitespace-pre-wrap overflow-x-auto max-h-80">{selectedVersion.report_content}</pre>
							</div>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>

