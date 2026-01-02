<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
import AutoReportTab from './components/AutoReportTab.svelte';
import TemplatedReportTab from './components/TemplatedReportTab.svelte';
import TemplateManagementTab from './components/TemplateManagementTab.svelte';
import HistoryTab from './components/HistoryTab.svelte';
import SettingsTab from './components/SettingsTab.svelte';
import ReportEnhancementSidebar from './components/ReportEnhancementSidebar.svelte';
import ReportVersionHistory from './components/ReportVersionHistory.svelte';
import ReportVersionInline from './components/ReportVersionInline.svelte';
import EnhancementDock from './components/EnhancementDock.svelte';
import EnhancementPreviewCards from './components/EnhancementPreviewCards.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { logout, user, token, isAuthenticated } from '$lib/stores/auth';
	import { reportsStore } from '$lib/stores/reports';
	import { templatesStore } from '$lib/stores/templates';
	import { settingsStore } from '$lib/stores/settings';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { marked } from 'marked';
	import { API_URL } from '$lib/config';
	import { logger } from '$lib/utils/logger';
	
	type UseCaseOption = { name: string; description?: string };
	type ApiKeyUsage = { deepgram: boolean };
	type ApiKeyStatus = {
		anthropic_configured: boolean;
		groq_configured: boolean;
		deepgram_configured: boolean;
		has_at_least_one_model: boolean;
		using_user_keys: ApiKeyUsage;
	};
	type HistoryModalInput = {
		variables?: Record<string, string>;
		message?: string;
		model?: string;
		use_case?: string;
	};
	type HistoryModal = {
		id?: string | null;
		report_content?: string;
		report_type?: string;
		input_data?: HistoryModalInput;
	};
	type ReportHistoryDetail = { count: number };
	type RestoredReportDetail = {
		report: { id: string | null; report_content: string; model_used?: string | null };
		version?: unknown;
	};
	
	// Configure marked for safe rendering
	marked.setOptions({
		breaks: true,
		gfm: true
	});
	
	function renderMarkdown(md: string | null | undefined): string {
		if (!md) return '';
		return marked.parse(md) as string;
	}

	// Valid tab names for hash routing
	const VALID_TABS = ['auto', 'templated', 'templates', 'history', 'settings'];

	let activeTab = 'auto';
	let sidebarCollapsed = false;
	let isInitializingFromHash = false;

	// Sync activeTab to URL hash
	function updateHash(tab: string) {
		if (browser && !isInitializingFromHash) {
			window.history.pushState(null, '', `#${tab}`);
		}
	}

	// Read tab from URL hash
	function getTabFromHash(): string {
		if (!browser) return 'auto';
		const hash = window.location.hash.slice(1); // Remove '#'
		return VALID_TABS.includes(hash) ? hash : 'auto';
	}

	// Handle browser back/forward buttons
	function handleHashChange() {
		if (!browser) return;
		const newTab = getTabFromHash();
		if (newTab !== activeTab) {
			isInitializingFromHash = true;
			activeTab = newTab;
			// Allow one tick for activeTab to update, then reset flag
			setTimeout(() => {
				isInitializingFromHash = false;
			}, 0);
		}
	}
	let initialized = false;
	let selectedUseCase = '';
	let availableUseCases: UseCaseOption[] = [];
	let promptVariables: string[] = [];
	let variableValues: Record<string, string> = {};
	let response: any = null;
	let responseModel: any = null;
	let loading = false;
	let error: any = null;
	let reportId: any = null;  // For enhancement sidebar (auto reports)
	let autoReportSelectedModel = 'claude';  // Track model selected in AutoReportTab
	let templatedReportId: any = null;  // For enhancement sidebar (templated reports)
	let sidebarVisible = false;  // Control sidebar visibility
	let historyModalReport: HistoryModal | null = null;
	let inputsExpanded = false;  // For collapsible input data section in history modal
	let lastModalReportId: string | null = null;  // Track which report is open to reset inputsExpanded
	let templateToEdit: any = null;  // Template to auto-open in editor
	let editSourceTab: any = null;  // Track which tab the edit came from ('templated' or 'templates')
let reportUpdateLoading = false;
let versionHistoryRefreshKey = 0;
let showVersionHistoryModal = false;
let templatedResponseOverride: any = null;
let templatedResponseVersion = 0;
let currentHistoryCount = 0;
let isEnhancementContext = activeTab === 'auto' || activeTab === 'templated';
let currentReportId: string | null = null;
let shouldAutoLoadEnhancements = false;

// Enhancement dock/cards state
let enhancementGuidelinesCount = 0;
let enhancementLoading = false;
let enhancementError = false;
let sidebarTabToOpen: 'guidelines' | 'comparison' | 'chat' | null = null;
	
	// Sync URL hash when activeTab changes (for programmatic tab changes)
	$: if (browser && !isInitializingFromHash) {
		updateHash(activeTab);
	}

	// Reset inputsExpanded when a new report is opened
	$: {
		const modalId = historyModalReport?.id ?? null;
		if (modalId !== lastModalReportId) {
			inputsExpanded = false;
			lastModalReportId = modalId;
		}
		if (!historyModalReport) {
			lastModalReportId = null;
		}
	}
	
	// API key status
	let apiKeyStatus: ApiKeyStatus = {
		anthropic_configured: false,
		groq_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false,
		using_user_keys: {
			deepgram: false
		}
	};
	let loadingApiStatus = true;
	let loadingUseCases = true;
	
	// Initialize once on first mount - prevents resets on re-render
	if (!initialized) {
		variableValues = {};
		initialized = true;
	}

	
	// Load user settings - now using store
	async function loadUserSettings() {
		if (!$settingsStore.settings) {
			await settingsStore.loadSettings();
		}
	}
	
	// Load API key status
	async function loadApiKeyStatus() {
		loadingApiStatus = true;
		try {
			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}
			
			const response = await fetch(`${API_URL}/api/settings/status`, {
				headers
			});
			
			if (response.ok) {
				const data = await response.json();
				if (data.success) {
					apiKeyStatus = {
						anthropic_configured: data.anthropic_configured || false,
						groq_configured: data.groq_configured || false,
						deepgram_configured: data.deepgram_configured || false,
						has_at_least_one_model: data.has_at_least_one_model || false,
						using_user_keys: data.using_user_keys || {
							deepgram: false
						}
					};
				}
			}
		} catch (err) {
			logger.error('Failed to load API key status:', err);
		} finally {
			loadingApiStatus = false;
		}
	}
	
	// Model selection is now handled internally by each tab component
	
	// Track when activeTab changes
	$: if (browser) {
		// Track state changes
	}

	function handleLogout(): void {
		logout();
		goto('/login');
	}

	function handleTabChange(event: CustomEvent<string>): void {
		activeTab = event.detail;
		// Clear templateToEdit and editSourceTab when switching away from templates tab
		if (event.detail !== 'templates') {
			templateToEdit = null;
			editSourceTab = null;
		}
	}

	function handleEditTemplate(event: CustomEvent<{ template: Record<string, unknown> }>): void {
		templateToEdit = event.detail.template;
		editSourceTab = 'templated';  // Track that we came from templated tab
		activeTab = 'templates';
		// Clear after a short delay to allow component to receive it
		setTimeout(() => {
			templateToEdit = null;
		}, 100);
	}

	let templatesRefreshKey = 0;
	let historyRefreshKey = 0;
	
	function handleBackToSourceTab(): void {
		if (editSourceTab === 'templated') {
			activeTab = 'templated';
			editSourceTab = null;
			templateToEdit = null; // Clear the template edit state
			// Increment refresh key to trigger template reload in TemplatedReportTab
			templatesRefreshKey += 1;
		}
	}

	function handleLogoutFromSidebar(): void {
		handleLogout();
	}

	function handleSettingsUpdated(_event: CustomEvent) {
		// Reload API key status after settings update
		loadApiKeyStatus();
	}

	function clearEnhancementState(): void {
		sidebarVisible = false;
		reportUpdateLoading = false;
		showVersionHistoryModal = false;
		currentHistoryCount = 0;
	}

	function handleHistoryRestored(detail: RestoredReportDetail): void {
		if (!detail || !detail.report) return;
		const restored = detail.report;
		response = restored.report_content;
		responseModel = restored.model_used ?? responseModel;
		versionHistoryRefreshKey += 1;
		reportUpdateLoading = false;
		showVersionHistoryModal = false;

		if (restored.id) {
			if (restored.id === templatedReportId) {
				templatedResponseOverride = restored.report_content;
				templatedResponseVersion += 1;
			}
			if (restored.id === reportId) {
				reportId = restored.id;
			}
		}
	}

	function handleHistoryUpdate(detail: ReportHistoryDetail): void {
		currentHistoryCount = detail?.count ?? 0;
	}

	function handleTemplateCleared(): void {
		templatedReportId = null;
		templatedResponseOverride = null;
		templatedResponseVersion = 0;
		versionHistoryRefreshKey += 1;
		clearEnhancementState();
	}

	// Load available use cases - model selection is now handled in AutoReportTab
	async function loadUseCases(onlyIfEmpty = false): Promise<void> {
		loadingUseCases = true;
		try {
			// Default to Claude for initial use case loading
			const res = await fetch(`${API_URL}/api/use-cases?model=claude`);
			const data = await res.json();
			if (data.success) {
				availableUseCases = (data.use_cases || []) as UseCaseOption[];
				
				if (selectedUseCase && !availableUseCases.some((uc: UseCaseOption) => uc.name === selectedUseCase)) {
					selectedUseCase = '';
					promptVariables = [];
					variableValues = {};
				}
				
				// Only set default if explicitly requested (e.g., on initial load or reset)
				// Don't reset when just switching tabs
				if (!onlyIfEmpty && !selectedUseCase && availableUseCases.length > 0) {
					const radiologyReport = availableUseCases.find((uc: UseCaseOption) => uc.name === 'radiology_report');
					if (radiologyReport) {
						selectedUseCase = 'radiology_report';
						// Trigger use case change to load prompt details
						await onUseCaseChange();
					}
				}
			}
		} catch (err) {
			// Failed to load use cases
		} finally {
			loadingUseCases = false;
		}
	}


	onMount(async () => {
		if (browser) {
			// Immediate auth check - redirect if no token (prevents any flash)
			const token = localStorage.getItem('token');
			if (!token) {
				goto('/home');
				return;
			}
			
			// Auth check is handled by +layout.ts load function
			// If we reach here, user has a token (may still be verifying)
			
			// Initialize tab from URL hash
			const hashTab = getTabFromHash();
			if (hashTab !== activeTab) {
				isInitializingFromHash = true;
				activeTab = hashTab;
				setTimeout(() => {
					isInitializingFromHash = false;
				}, 0);
			}

			// Listen for browser back/forward button
			window.addEventListener('hashchange', handleHashChange);

			// Initialize stores
			await Promise.all([
				settingsStore.loadSettings(),
				reportsStore.loadReports(),
				templatesStore.loadTemplates()
			]);
			
			await loadApiKeyStatus(); // Load API key status
			await loadUseCases(false); // Allow setting default on initial load
		}
	});

	onDestroy(() => {
		if (browser) {
			window.removeEventListener('hashchange', handleHashChange);
		}
	});

	// Handle use case change in AutoReportTab
	async function onUseCaseChange(preserveValues = false): Promise<void> {
		// Save existing values if we're preserving them (e.g., when model changes)
		const existingValues = preserveValues ? { ...variableValues } : {};
		
		if (!preserveValues) {
			variableValues = {};
		}
		
		if (!selectedUseCase) {
			promptVariables = [];
			return;
		}

		try {
			// Default to Claude for prompt details loading
			const res = await fetch(`${API_URL}/api/prompt-details/${selectedUseCase}?model=claude`);
			const data = await res.json();
			if (data.success) {
				promptVariables = (data.details.variables || []) as string[];
				// Initialize or preserve values
				promptVariables.forEach((v: string) => {
					if (preserveValues && existingValues[v] !== undefined) {
						// Keep existing value
						variableValues[v] = existingValues[v];
					} else {
						// Initialize with empty string
						variableValues[v] = '';
					}
				});
			}
		} catch (err) {
			promptVariables = [];
		}
	}
	
	// Wrapper for event handler - resets values when use case actually changes
	function handleUseCaseChange(): void {
		onUseCaseChange(false);
	}
	
	// Handle form reset from AutoReportTab
	async function handleFormReset(): Promise<void> {
		variableValues = {};
		selectedUseCase = '';
		promptVariables = [];
		error = null;
		response = null;
	responseModel = null;
	reportId = null;
	clearEnhancementState();
	versionHistoryRefreshKey += 1;
		// Reload default use case (radiology_report)
		await loadUseCases();
	}

	// Handle submit from AutoReportTab - Model selection is now handled in the tab component
	async function handleSubmit(): Promise<void> {
		// Require a use case to be selected
		if (!selectedUseCase) {
			error = 'Please select a use case';
			return;
		}
		
		// For use cases with variables, check if they're filled
		if (promptVariables.length > 0) {
			const hasEmptyFields = promptVariables.some(v => !variableValues[v] || !variableValues[v].trim());
			if (hasEmptyFields) {
				error = 'Please fill in all required fields';
				return;
			}
		}
		
		loading = true;
		error = null;
		response = null;
		responseModel = null;

		try {
			const payload: {
				message: string;
				model: string;
				use_case: string;
				variables?: Record<string, string>;
			} = {
				message: '', // Required by backend, but not used when variables are provided
				model: autoReportSelectedModel, // Use model selected in AutoReportTab
				use_case: selectedUseCase
			};
			
			if (promptVariables.length > 0) {
				payload.variables = variableValues;
			}

			const headers: Record<string, string> = { 'Content-Type': 'application/json' };
			if ($token) {
				headers['Authorization'] = `Bearer ${$token}`;
			}

			const res = await fetch(`${API_URL}/api/chat`, {
				method: 'POST',
				headers,
				body: JSON.stringify(payload),
			});

			const data = await res.json();
			
			if (data.success) {
				response = data.response;
				responseModel = data.model;
				reportId = data.report_id || null;
				if (reportId) {
					versionHistoryRefreshKey += 1;
					historyRefreshKey += 1; // Trigger history reload
					// Refresh reports store to include new report
					reportsStore.refreshReports();
				}
			} else {
				error = data.error || 'Failed to get response';
			}
		} catch (err) {
			error = 'Failed to connect to API. Make sure the backend is running.';
		} finally {
			loading = false;
		}
	}

$: isEnhancementContext = activeTab === 'auto' || activeTab === 'templated';
$: {
	const newReportId = isEnhancementContext
		? (activeTab === 'auto' ? reportId : templatedReportId)
		: null;
	
	// Close sidebar if switching between different reports or leaving enhancement context
	if (currentReportId !== newReportId && sidebarVisible) {
		sidebarVisible = false;
		sidebarTabToOpen = null;
	}
	
	// Reset enhancement state when report changes
	if (currentReportId !== newReportId) {
		enhancementGuidelinesCount = 0;
		enhancementLoading = false;
		enhancementError = false;
	}
	
	currentReportId = newReportId;
}
$: shouldAutoLoadEnhancements = Boolean(isEnhancementContext && currentReportId);
$: if (!isEnhancementContext && sidebarVisible) {
	sidebarVisible = false;
}
</script>

<div class="min-h-screen bg-gradient-to-br from-gray-900 via-slate-900 to-gray-950 relative overflow-hidden">
	<!-- Background Circuit Board Overlay -->
	<div class="absolute inset-0 pointer-events-none">
		<!-- Vignette effect - darker at edges, lighter in center -->
		<div class="absolute inset-0" style="background: radial-gradient(ellipse at center, transparent 0%, rgba(0,0,0,0.4) 70%, rgba(0,0,0,0.7) 100%);"></div>
		<!-- Circuit board pattern with overlay blend -->
		<div class="absolute inset-0 opacity-30 mix-blend-overlay">
			<img src={bgCircuit} alt="" class="w-full h-full object-cover" />
		</div>
	</div>

	<!-- Sidebar - Only show when authenticated or checking auth -->
	{#if $isAuthenticated || ($token && !$isAuthenticated)}
		<Sidebar 
			{activeTab}
			bind:isCollapsed={sidebarCollapsed}
			on:tabChange={handleTabChange}
			on:logout={handleLogoutFromSidebar}
		/>
	{/if}

	<!-- Main Content Area -->
	<main class="relative z-10 transition-all duration-300 {($isAuthenticated || ($token && !$isAuthenticated)) ? (sidebarCollapsed ? 'md:ml-16' : 'md:ml-64') : ''} min-h-screen">
		{#if $token && !$isAuthenticated}
			<!-- Still checking auth status - show loading -->
			<div class="min-h-screen flex items-center justify-center">
				<div class="flex flex-col items-center gap-3">
					<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
					<p class="text-sm text-gray-400">Verifying authentication...</p>
				</div>
			</div>
		{:else if $isAuthenticated}
			<div class="p-4 md:p-6">
				<!-- Warning Banner for Missing API Keys -->
				{#if !loadingApiStatus && !apiKeyStatus.has_at_least_one_model}
					<div class="mb-6 p-4 rounded-lg border-2 border-yellow-500/50 bg-yellow-500/10 text-yellow-300">
						<div class="flex items-start gap-3">
							<svg class="w-6 h-6 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
							</svg>
							<div class="flex-1">
								<h3 class="font-bold text-lg mb-1">⚠️ Setup Required</h3>
								<p class="text-sm mb-3">
									You need to configure at least one AI model (Claude or Gemini) to use this app. 
									Please add your API keys in the Settings page.
								</p>
								<button
								on:click={() => { activeTab = 'settings'; }}
									class="text-sm px-4 py-2 bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/50 rounded-lg transition-colors font-medium"
								>
									Go to Settings →
								</button>
							</div>
						</div>
					</div>
				{/if}
				
				<!-- Auto Report Tab - Keep component alive, just hide/show -->
				<div class={activeTab === 'auto' ? '' : 'hidden'}>
					{#if loadingApiStatus || loadingUseCases}
						<!-- Skeleton loader for API status and use cases -->
						<div class="card-dark space-y-4">
							<div class="h-8 bg-gray-700/50 rounded animate-pulse w-1/3"></div>
							<div class="h-10 bg-gray-700/50 rounded animate-pulse"></div>
							<div class="h-4 bg-gray-700/50 rounded animate-pulse w-1/2"></div>
							<div class="h-32 bg-gray-700/50 rounded animate-pulse"></div>
						</div>
					{:else}
						<AutoReportTab
							bind:availableUseCases
							bind:selectedUseCase
							bind:promptVariables
							bind:variableValues
							bind:response
							bind:responseModel
							bind:loading
							bind:error
							bind:selectedModel={autoReportSelectedModel}
							reportId={reportId}
							reportUpdateLoading={reportUpdateLoading}
							versionHistoryRefreshKey={versionHistoryRefreshKey}
							apiKeyStatus={apiKeyStatus}
							enhancementGuidelinesCount={enhancementGuidelinesCount}
							enhancementLoading={enhancementLoading}
							enhancementError={enhancementError}
							on:useCaseChange={handleUseCaseChange}
							on:submit={handleSubmit}
							on:resetForm={handleFormReset}
							on:openSidebar={(e) => {
								sidebarTabToOpen = e.detail?.tab || null;
								sidebarVisible = true;
							}}
							on:historyRestored={(e) => handleHistoryRestored(e.detail as RestoredReportDetail)}
							on:historyUpdate={(e) => handleHistoryUpdate(e.detail as ReportHistoryDetail)}
						/>
					{/if}
				</div>
				
				<!-- Templated Report Tab - Keep component alive, just hide/show -->
				<div class={activeTab === 'templated' ? '' : 'hidden'}>
					{#if loadingApiStatus}
						<!-- Skeleton loader for API status -->
						<div class="card-dark space-y-4">
							<div class="h-8 bg-gray-700/50 rounded animate-pulse w-1/3"></div>
							<div class="h-10 bg-gray-700/50 rounded animate-pulse"></div>
							<div class="h-4 bg-gray-700/50 rounded animate-pulse w-1/2"></div>
							<div class="h-32 bg-gray-700/50 rounded animate-pulse"></div>
						</div>
					{:else}
						<TemplatedReportTab
							apiKeyStatus={apiKeyStatus}
							reportUpdateLoading={reportUpdateLoading}
							versionHistoryRefreshKey={versionHistoryRefreshKey}
							templatesRefreshKey={templatesRefreshKey}
							externalResponseContent={templatedResponseOverride}
							externalResponseVersion={templatedResponseVersion}
							enhancementGuidelinesCount={enhancementGuidelinesCount}
							enhancementLoading={enhancementLoading}
							enhancementError={enhancementError}
							on:editTemplate={handleEditTemplate}
							on:reportGenerated={(e) => {
								templatedReportId = e.detail.reportId;
								if (templatedReportId) {
									versionHistoryRefreshKey += 1;
									historyRefreshKey += 1; // Trigger history reload
									// Refresh reports store to include new report
									reportsStore.refreshReports();
								}
							}}
							on:openSidebar={(e) => {
								sidebarTabToOpen = e.detail?.tab || null;
								sidebarVisible = true;
							}}
							on:historyRestored={(e) => handleHistoryRestored(e.detail as RestoredReportDetail)}
							on:historyUpdate={(e) => handleHistoryUpdate(e.detail as ReportHistoryDetail)}
							on:reportCleared={handleTemplateCleared}
						/>
					{/if}
				</div>
				
				<!-- Tab components - all loaded on app initialization -->
				<!-- Templates Tab -->
				<div class={activeTab === 'templates' ? '' : 'hidden'}>
					<TemplateManagementTab
						initialEditTemplate={templateToEdit}
						cameFromTab={editSourceTab}
						on:backToSource={handleBackToSourceTab}
						on:templateCreated={() => {
							// Increment refresh key to trigger template reload in TemplatedReportTab
							templatesRefreshKey += 1;
						}}
						on:templateDeleted={() => {
							// Increment refresh key to trigger template reload in TemplatedReportTab
							templatesRefreshKey += 1;
						}}
					/>
				</div>
				
				<!-- History Tab -->
				<div class={activeTab === 'history' ? '' : 'hidden'}>
					<HistoryTab
						refreshKey={historyRefreshKey}
						on:viewReport={(e) => historyModalReport = e.detail as HistoryModal}
					/>
				</div>
				
				<!-- Settings Tab -->
				<div class={activeTab === 'settings' ? '' : 'hidden'}>
					<SettingsTab
						on:settingsUpdated={handleSettingsUpdated}
					/>
				</div>
			</div>
		{:else}
			<!-- Not authenticated - redirect handled by layout, show nothing to prevent flash -->
			<div class="min-h-screen flex items-center justify-center">
				<div class="flex flex-col items-center gap-3">
					<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
					<p class="text-sm text-gray-400">Redirecting...</p>
				</div>
			</div>
		{/if}
	</main>

<!-- Enhancement Sidebar - Rendered at root level like history modal -->
<ReportEnhancementSidebar
	reportId={currentReportId}
	reportContent={response || ''}
	visible={sidebarVisible && isEnhancementContext}
	autoLoad={shouldAutoLoadEnhancements}
	historyAvailable={currentHistoryCount > 1}
	initialTab={sidebarTabToOpen}
	on:close={() => {
		sidebarVisible = false;
		sidebarTabToOpen = null;
	}}
	on:reportUpdated={(e) => {
		// Update response when report is updated
		if (e.detail.report) {
			response = e.detail.report.report_content;
			versionHistoryRefreshKey += 1;
			const updatedReportId = e.detail.report.id;
			if (templatedReportId && updatedReportId === templatedReportId) {
				templatedResponseOverride = e.detail.report.report_content;
				templatedResponseVersion += 1;
			}
			// Refresh reports store to reflect updated report
			reportsStore.refreshReports();
		}
		reportUpdateLoading = false;
	}}
	on:reportUpdating={(e) => {
		if (e.detail?.status === 'start') {
			reportUpdateLoading = true;
		} else if (e.detail?.status === 'end') {
			reportUpdateLoading = false;
		}
	}}
	on:openVersionHistory={() => {
		if (currentReportId) {
			showVersionHistoryModal = true;
		}
	}}
	on:enhancementState={(e) => {
		const state = e.detail;
		enhancementGuidelinesCount = state.guidelinesCount || 0;
		enhancementLoading = state.isLoading || false;
		enhancementError = state.hasError || false;
	}}
/>
<ReportVersionHistory
	reportId={currentReportId}
	show={showVersionHistoryModal}
	refreshKey={versionHistoryRefreshKey}
	onClose={() => showVersionHistoryModal = false}
/>

<!-- Enhancement Dock - Floating button (Hidden for now) -->
<!--
{#if isEnhancementContext && currentReportId}
	<EnhancementDock
		guidelinesCount={enhancementGuidelinesCount}
		isLoading={enhancementLoading}
		hasError={enhancementError}
		reportId={currentReportId}
		on:openSidebar={(e) => {
			sidebarTabToOpen = e.detail?.tab || null;
			sidebarVisible = true;
		}}
	/>
{/if}
-->
	
	<!-- History Modal - Rendered at root level to avoid stacking context issues -->
	{#if historyModalReport}
		<div 
			class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 md:p-6"
			style="z-index: 9999;"
			tabindex="-1"
			on:click|self={() => { historyModalReport = null; inputsExpanded = false; }}
			on:keydown={(event) => {
				if (event.key === 'Escape') {
					historyModalReport = null;
					inputsExpanded = false;
				}
			}}
			role="dialog"
			aria-modal="true"
			aria-labelledby="history-modal-title"
		>
			<div 
				class="card-dark max-w-4xl w-full max-h-[95vh] sm:max-h-[90vh] overflow-hidden flex flex-col relative mx-auto"
				tabindex="-1"
				role="document"
			>
				<!-- Modal Header -->
				<div class="flex items-center justify-between mb-6 flex-shrink-0 pb-4 border-b border-white/10">
					<h2 id="history-modal-title" class="text-xl md:text-2xl font-bold text-white">Report Details</h2>
					<div class="flex items-center gap-2">
						<button
							on:click={() => {
								if (historyModalReport?.report_content) {
									navigator.clipboard.writeText(historyModalReport.report_content);
								}
							}}
							class="p-2 text-gray-400 hover:text-purple-400 transition-colors rounded-lg hover:bg-white/5"
							title="Copy to clipboard"
							aria-label="Copy report"
						>
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
							</svg>
						</button>
						<button
							on:click={() => { historyModalReport = null; inputsExpanded = false; }}
							class="p-2 text-gray-400 hover:text-red-400 transition-colors rounded-lg hover:bg-white/5"
							title="Close report"
							aria-label="Close report"
						>
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>
				</div>
				
				<!-- Modal Content - Scrollable -->
				<div class="flex-1 overflow-y-auto min-h-0 -mx-6 px-6">
					<!-- Input Data Section - Collapsible -->
					{#if historyModalReport?.input_data && (
						(historyModalReport.input_data?.variables && Object.keys(historyModalReport.input_data.variables ?? {}).length > 0) ||
						(historyModalReport.input_data?.message && historyModalReport.input_data.message.trim().length > 0)
					)}
						<div class="mb-6 border border-white/10 rounded-lg overflow-hidden">
							<button
								on:click={() => inputsExpanded = !inputsExpanded}
								class="w-full flex items-center justify-between p-4 bg-gray-800/50 hover:bg-gray-800/70 transition-colors"
							>
								<div class="flex items-center gap-2">
									<svg class="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
									</svg>
									<h3 class="text-sm font-semibold text-white">Input Data</h3>
								</div>
								<svg
									class="w-5 h-5 text-gray-400 transform transition-transform {inputsExpanded ? 'rotate-180' : ''}"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							
							{#if inputsExpanded}
								<div class="p-4 bg-gray-900/50 space-y-4">
									{#if historyModalReport?.input_data?.variables && Object.keys(historyModalReport.input_data.variables ?? {}).length > 0}
										<div>
											<h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">Variables</h4>
											<div class="space-y-2">
												{#each Object.entries(historyModalReport.input_data.variables ?? {}) as [key, value]}
													<div class="border-l-2 border-purple-500/50 pl-3">
														<div class="text-xs font-medium text-purple-400 mb-1">{key.replace(/_/g, ' ')}</div>
														<div class="text-sm text-gray-300 whitespace-pre-wrap">{value || '(empty)'}</div>
													</div>
												{/each}
											</div>
										</div>
									{/if}
									
									{#if historyModalReport?.input_data?.message && historyModalReport.input_data.message.trim().length > 0 && historyModalReport?.report_type === 'auto'}
										<div>
											<h4 class="text-xs font-semibold text-gray-400 uppercase mb-2">Message</h4>
											<div class="text-sm text-gray-300 whitespace-pre-wrap">{historyModalReport.input_data.message}</div>
										</div>
									{/if}
								</div>
							{/if}
						</div>
					{/if}
					
					<!-- Version History Section -->
					{#if historyModalReport?.id}
						<div class="mb-6">
							<h3 class="text-sm font-semibold text-white uppercase tracking-wide mb-4 flex items-center gap-2">
								<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
								</svg>
								Version History
							</h3>
							<ReportVersionInline
								reportId={historyModalReport.id}
								refreshKey={versionHistoryRefreshKey}
								on:restored={(e) => {
									// Refresh the report data when a version is restored
									if (e.detail?.report) {
										historyModalReport = { ...historyModalReport, ...e.detail.report };
										versionHistoryRefreshKey += 1;
										reportsStore.refreshReports();
									}
								}}
							/>
						</div>
					{/if}
					
					<!-- Report Content (Current Version) -->
					<div class="mb-6">
						<h3 class="text-sm font-semibold text-white uppercase tracking-wide mb-4 flex items-center gap-2">
							<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
							</svg>
							Current Report Content
						</h3>
						<div class="prose prose-invert max-w-none text-gray-300">
							{@html renderMarkdown(historyModalReport?.report_content)}
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}
	
	<!-- Footer -->
	{#if $isAuthenticated}
		<footer class="relative z-10 px-4 md:px-6 py-6 border-t border-white/5 mt-auto">
			<div class="max-w-7xl mx-auto text-center">
				<p class="text-xs text-gray-500 mb-1">
					© 2026 H&A LABS LTD | Company No. 16114480
				</p>
				<p class="text-xs text-gray-600">
					RadFlow is a product of H&A LABS LTD
				</p>
			</div>
		</footer>
	{/if}
</div>
