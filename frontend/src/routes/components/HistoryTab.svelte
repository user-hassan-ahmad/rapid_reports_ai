<script>
	import { onMount, createEventDispatcher } from 'svelte';
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import Toast from '$lib/components/Toast.svelte';
	import { API_URL } from '$lib/config';
	
	const dispatch = createEventDispatcher();
	
	let toast;
	let reports = [];
	let loading = true;
	let selectedReport = null;
	let selectedReports = new Set();
	let searchTerm = '';
	let reportTypeFilter = 'all';
	let dateFilter = 'all'; // 'all', 'today', 'week', 'month', 'custom'
	let startDate = '';
	let endDate = '';
	let lastReportTypeFilter = 'all';
	let lastSearchTerm = '';
	let lastDateFilter = 'all';
	let lastStartDate = '';
	let lastEndDate = '';
	
	// Refresh key prop to trigger reload when reports are generated
	export let refreshKey = 0;
	let lastRefreshKey = 0;
	
	// Configure marked for safe rendering
	marked.setOptions({
		breaks: true,
		gfm: true
	});
	
	function renderMarkdown(md) {
		if (!md) return '';
		return marked.parse(md);
	}

	function getDateRange(filter) {
		const now = new Date();
		let start = null;
		let end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
		
		switch(filter) {
			case 'today':
				start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
				break;
			case 'week':
				start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7, 0, 0, 0, 0);
				break;
			case 'month':
				start = new Date(now.getFullYear(), now.getMonth() - 1, now.getDate(), 0, 0, 0, 0);
				break;
			case 'custom':
				// Use custom dates if provided
				if (startDate) start = new Date(startDate);
				if (endDate) end = new Date(endDate);
				break;
			default:
				return { start: null, end: null };
		}
		
		return { start, end };
	}

	async function loadHistory() {
		loading = true;
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const params = new URLSearchParams();
			if (reportTypeFilter !== 'all') {
				params.append('report_type', reportTypeFilter);
			}
			if (searchTerm) {
				params.append('search', searchTerm);
			}
			
			// Handle date filtering
			if (dateFilter !== 'all') {
				const { start, end } = getDateRange(dateFilter);
				if (start) {
					params.append('start_date', start.toISOString());
				}
				if (end) {
					params.append('end_date', end.toISOString());
				}
			}
			
			const url = `${API_URL}/api/reports?${params.toString()}`;
			const response = await fetch(url, { headers });
			
			if (response.ok) {
				const data = await response.json();
				if (data.success) {
					reports = data.reports || [];
				}
			}
		} catch (err) {
			console.error('Failed to load history:', err);
		} finally {
			loading = false;
		}
	}

	function handleViewReport(report) {
		selectedReport = report;
		dispatch('viewReport', report);
	}

	// Modal handling is now in parent component (+page.svelte)

	function formatDate(dateString) {
		const date = new Date(dateString);
		return date.toLocaleString();
	}
	
	function resetFilters() {
		searchTerm = '';
		reportTypeFilter = 'all';
		dateFilter = 'all';
		startDate = '';
		endDate = '';
	}

	function toggleReportSelection(reportId) {
		if (selectedReports.has(reportId)) {
			selectedReports.delete(reportId);
		} else {
			selectedReports.add(reportId);
		}
		selectedReports = selectedReports; // Trigger reactivity
	}

	function toggleSelectAll() {
		if (selectedReports.size === reports.length) {
			selectedReports.clear();
		} else {
			reports.forEach(report => selectedReports.add(report.id));
		}
		selectedReports = selectedReports; // Trigger reactivity
	}

	async function deleteReport(reportId) {
		if (!confirm('Are you sure you want to delete this report?')) return;
		
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/reports/${reportId}`, {
				method: 'DELETE',
				headers
			});
			
			if (response.ok) {
				await loadHistory();
				selectedReports.delete(reportId);
			}
		} catch (err) {
			console.error('Failed to delete report:', err);
		}
	}

	async function deleteSelectedReports() {
		if (selectedReports.size === 0) return;
		if (!confirm(`Are you sure you want to delete ${selectedReports.size} report(s)?`)) return;
		
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			// Delete each selected report
			const deletePromises = Array.from(selectedReports).map(reportId =>
				fetch(`http://localhost:8000/api/reports/${reportId}`, {
					method: 'DELETE',
					headers
				})
			);
			
			await Promise.all(deletePromises);
			selectedReports.clear();
			await loadHistory();
		} catch (err) {
			console.error('Failed to delete reports:', err);
		}
	}

	async function deleteAllReports() {
		if (reports.length === 0) return;
		if (!confirm(`Are you sure you want to delete all ${reports.length} reports?`)) return;
		
		try {
			const headers = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			// Delete all reports
			const deletePromises = reports.map(report =>
				fetch(`${API_URL}/api/reports/${report.id}`, {
					method: 'DELETE',
					headers
				})
			);
			
			await Promise.all(deletePromises);
			selectedReports.clear();
			await loadHistory();
		} catch (err) {
			console.error('Failed to delete all reports:', err);
		}
	}

	// Watch for refreshKey changes and reload history when reports are generated
	$: if (refreshKey !== lastRefreshKey) {
		lastRefreshKey = refreshKey;
		loadHistory();
	}
	
	// Track filter changes and reload history
	$: if (
		searchTerm !== lastSearchTerm ||
		reportTypeFilter !== lastReportTypeFilter ||
		dateFilter !== lastDateFilter ||
		startDate !== lastStartDate ||
		endDate !== lastEndDate
	) {
		lastSearchTerm = searchTerm;
		lastReportTypeFilter = reportTypeFilter;
		lastDateFilter = dateFilter;
		lastStartDate = startDate;
		lastEndDate = endDate;
		loadHistory();
	}
	
	// Clear selection when reports change (e.g., after deletion or filter change)
	$: if (reports.length > 0) {
		// Keep only selected IDs that still exist
		selectedReports = new Set(Array.from(selectedReports).filter(id => 
			reports.some(report => report.id === id)
		));
	} else {
		selectedReports.clear();
	}

	onMount(() => {
		loadHistory();
	});
</script>

<div class="p-6">
	<div class="flex items-center gap-3 mb-6">
		<svg class="w-8 h-8 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
		</svg>
		<h1 class="text-3xl font-bold text-white bg-gradient-to-r from-purple-400 to-blue-400 bg-clip-text text-transparent">History</h1>
	</div>
	
	<!-- Bulk Actions -->
	{#if reports.length > 0}
		<div class="mb-4 flex items-center justify-between">
			<div class="flex items-center gap-2">
				<button
					onclick={toggleSelectAll}
					class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors"
				>
					{selectedReports.size === reports.length ? 'Deselect All' : 'Select All'}
				</button>
				{#if selectedReports.size > 0}
					<button
						onclick={deleteSelectedReports}
						class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
					>
						Delete Selected ({selectedReports.size})
					</button>
				{/if}
			</div>
			<button
				onclick={deleteAllReports}
				class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
			>
				Delete All ({reports.length})
			</button>
		</div>
	{/if}
	
	<!-- Filters -->
	<div class="mb-6 grid grid-cols-1 md:grid-cols-4 gap-4">
		<div>
			<input
				type="text"
				placeholder="Search reports..."
				bind:value={searchTerm}
				class="input-dark w-full"
			/>
		</div>
		<div>
			<select bind:value={reportTypeFilter} class="select-dark w-full">
				<option value="all">All Types</option>
				<option value="auto">Auto Report</option>
				<option value="templated">Templated Report</option>
			</select>
		</div>
		<div>
			<select bind:value={dateFilter} class="select-dark w-full">
				<option value="all">All Time</option>
				<option value="today">Today</option>
				<option value="week">Last 7 Days</option>
				<option value="month">Last 30 Days</option>
				<option value="custom">Custom Range</option>
			</select>
		</div>
	</div>
	
	<!-- Custom Date Range -->
	{#if dateFilter === 'custom'}
		<div class="mb-6 grid grid-cols-1 md:grid-cols-2 gap-4">
			<div>
				<label class="block text-sm font-medium text-gray-300 mb-1">Start Date</label>
				<div class="relative">
					<input
						type="date"
						bind:value={startDate}
						class="input-dark w-full pr-10"
					/>
					<svg class="absolute right-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
					</svg>
				</div>
			</div>
			<div>
				<label class="block text-sm font-medium text-gray-300 mb-1">End Date</label>
				<div class="relative">
					<input
						type="date"
						bind:value={endDate}
						class="input-dark w-full pr-10"
					/>
					<svg class="absolute right-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
					</svg>
				</div>
			</div>
		</div>
	{/if}
	
	<!-- Reset Filters Button -->
	{#if searchTerm || reportTypeFilter !== 'all' || dateFilter !== 'all'}
		<div class="mb-4 flex justify-end">
			<button
				onclick={resetFilters}
				class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded transition-colors flex items-center gap-2"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
				</svg>
				Reset Filters
			</button>
		</div>
	{/if}
	
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<div class="text-gray-400">Loading...</div>
		</div>
	{:else if reports.length === 0}
		<div class="card-dark text-center py-12">
			<svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
			</svg>
			<p class="text-gray-400 text-lg">No reports found</p>
			<p class="text-gray-500 text-sm mt-2">
				{#if searchTerm || reportTypeFilter !== 'all' || dateFilter !== 'all'}
					Try adjusting your filters
				{:else}
					Your report generation history will appear here
				{/if}
			</p>
		</div>
	{:else}
		<div class="space-y-3">
			{#each reports as report}
				<div class="card-dark">
					<div class="flex items-start gap-3">
						<input
							type="checkbox"
							checked={selectedReports.has(report.id)}
							onchange={() => toggleReportSelection(report.id)}
							class="mt-1 h-5 w-5 rounded border-gray-600 bg-gray-700 text-purple-600 focus:ring-purple-500"
						/>
						<div class="flex-1 flex items-start justify-between">
							<div class="flex-1">
								<!-- First line: Template/Scan Type + Description -->
								<h3 class="text-white font-medium mb-1">
									{report.description || (report.report_type === 'auto' ? 'Auto Report' : 'Templated Report')}
								</h3>
								<!-- Second line: Date/Time -->
								<p class="text-gray-400 text-sm">
									{formatDate(report.created_at)}
								</p>
							</div>
							<div class="flex gap-2">
								<button
									onclick={() => handleViewReport(report)}
									class="btn-ghost text-sm"
								>
									View
								</button>
								<button
									onclick={() => deleteReport(report.id)}
									class="px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-sm rounded transition-colors"
									aria-label="Delete report"
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

<!-- Modal is now rendered at root level in +page.svelte to avoid stacking context issues -->

<Toast bind:this={toast} />
