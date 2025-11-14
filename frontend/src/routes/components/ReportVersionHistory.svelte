<script>
	import { onMount } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { API_URL } from '$lib/config';

	export let reportId;
	export let show = false;
	export let onClose = () => {};
	export let refreshKey = 0;

	let versions = [];
	let loading = false;
	let error = null;
	let selectedVersion = null;
	let loadingVersion = false;

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

	async function openVersion(version) {
		if (!reportId || !version) return;
		loadingVersion = true;
		selectedVersion = null;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			const response = await fetch(`${API_URL}/api/reports/${reportId}/versions/${version.id}`, { headers });
			const data = await response.json();
			if (response.ok && data.success) {
				selectedVersion = data.version;
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
					onclick={() => { onClose(); selectedVersion = null; }}
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
										<span class="text-sm font-semibold text-white">Version {version.version_number}</span>
										{#if version.is_current}
											<span class="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/30 text-purple-200 font-medium">Current</span>
										{/if}
									</div>
									<p class="text-xs text-gray-400 mt-1">{formatDate(version.created_at)}</p>
									{#if version.actions_applied && version.actions_applied.length > 0}
										<p class="text-[11px] text-gray-500 mt-2 leading-snug">
											{version.actions_applied.length} actions applied
										</p>
									{/if}
									{#if version.report_content_preview}
										<p class="text-[11px] text-gray-500 mt-2 leading-snug line-clamp-3">
											{version.report_content_preview}
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
								<h5 class="text-sm font-semibold text-white uppercase tracking-wide mb-2">Report Content</h5>
								<pre class="text-sm text-gray-100 bg-gray-950/70 border border-gray-800 rounded-md p-4 whitespace-pre-wrap overflow-x-auto">{selectedVersion.report_content}</pre>
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
