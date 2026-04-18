<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { fade } from 'svelte/transition';
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
import IntelliDictateTab from './components/IntelliDictateTab.svelte';
import TemplatedReportTab from './components/TemplatedReportTab.svelte';
import HistoryTab from './components/HistoryTab.svelte';
import SettingsTab from './components/SettingsTab.svelte';
import ReportEnhancementSidebar from './components/ReportEnhancementSidebar.svelte';
import IntervalAnalysisDrawer from './components/IntervalAnalysisDrawer.svelte';
import TemplateRefinePanel from './components/TemplateRefinePanel.svelte';
import ReportVersionHistory from './components/ReportVersionHistory.svelte';
import ReportVersionInline from './components/ReportVersionInline.svelte';
import TemplateEditorNew from './components/TemplateEditorNew.svelte';
import TemplateWizard from './components/wizard/TemplateWizard.svelte';
	import SkillSheetCreator from './components/SkillSheetCreator.svelte';
	import { selectedTemplateId } from '$lib/stores/templates';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import UnfilledItemHoverPopup from './components/UnfilledItemHoverPopup.svelte';
	import type { UnfilledItem } from '$lib/utils/placeholderDetection';
	import { applyEditsToReport } from '$lib/utils/reportEditing';
	import type { UnfilledEdit } from '$lib/stores/unfilledEditor';
	import { detectUnfilledPlaceholders } from '$lib/utils/placeholderDetection';
	import { logout, user, token, isAuthenticated } from '$lib/stores/auth';
	import { reportsStore } from '$lib/stores/reports';
	import { templatesStore } from '$lib/stores/templates';
	import { draftStore, hasIntelliDraft, hasTemplateDraft } from '$lib/stores/draft.js';
	import { settingsStore } from '$lib/stores/settings';
	import bgCircuit from '$lib/assets/background circuit board effect.png';
	import { marked } from 'marked';
	import { API_URL } from '$lib/config';
	import { logger } from '$lib/utils/logger';
	
	type UseCaseOption = { name: string; description?: string };
	type ApiKeyStatus = {
		anthropic_configured: boolean;
		groq_configured: boolean;
		cerebras_configured: boolean;
		deepgram_configured: boolean;
		has_at_least_one_model: boolean;
		using_user_keys?: { deepgram: boolean };  // backward compat, same as deepgram_configured
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
	const VALID_TABS = ['auto', 'templated', 'history', 'settings'];

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
	
	// Separate state for auto reports
	let autoVariableValues: Record<string, string> = {};
	let autoResponse: any = null;
	let autoResponseModel: any = null;
	let autoLoading = false;
	let autoError: any = null;
	let reportId: any = null;  // For enhancement sidebar (auto reports)
	let autoReportSelectedModel = 'claude';  // Track model selected in AutoReportTab
	let autoScanType = '';  // Captured from API response for audit
	
	// Separate state for templated reports
	let templatedReportId: any = null;  // For enhancement sidebar (templated reports)
	
	// Legacy variables for backward compatibility (will be removed after migration)
	let variableValues: Record<string, string> = {};
	let response: any = null;
	let responseModel: any = null;
	let loading = false;
	let error: any = null;
	let sidebarVisible = false;  // Control sidebar visibility
	let historyModalReport: HistoryModal | null = null;
	let inputsExpanded = false;  // For collapsible input data section in history modal
	let lastModalReportId: string | null = null;  // Track which report is open to reset inputsExpanded
let reportUpdateLoading = false;
let versionHistoryRefreshKey = 0;
let showVersionHistoryModal = false;
let templatedResponseOverride: any = null;
let templatedReportContent: string = '';  // Live content from TemplatedReportTab for sidebar preview
let templatedResponseVersion = 0;
let currentHistoryCount = 0;

let isEnhancementContext = activeTab === 'auto' || activeTab === 'templated';
let currentReportId: string | null = null;
let shouldAutoLoadEnhancements = false;

// Enhancement dock/cards state
let enhancementGuidelinesCount = 0;
let enhancementLoading = false;
let enhancementError = false;
let sidebarTabToOpen: 'guidelines' | 'comparison' | 'chat' | 'qa' | null = null;

// Audit guideline references — lifted from ReportResponseViewer so the Copilot
// Guidelines tab can show the QA Reference section alongside Perplexity cards.
// Both arrays clear on audit start/error and populate on success.
let auditGuidelineReferences: any[] = [];
let auditCriteriaForSidebar: any[] = [];
	let chatInitialMessage: string | null = null;
	let chatAutoSend: boolean = false;
	let chatAutoSendLabel: { type: string; name: string; itemType?: string } | null = null;
	/** One-shot structured grounding for Fix with AI — cleared after first chat POST */
	let chatAuditFixContext: import('$lib/types/auditFixContext').AuditFixContext | null = null;

// Hover popup state (rendered at root level)
let hoverPopupVisible = false;
let hoverPopupItem: UnfilledItem | null = null;
let hoverPopupPosition = { x: 0, y: 0 };
let hoverPopupReportContent = '';
let hoverPopupReportId: string | null = null;

// Track if enhancements have finished loading (for Ask AI button)
let enhancementsLoaded = false;

// Copilot workbench: nav collapse + auto-open
let navStateBeforeCopilot = false;
let copilotAutoOpened = false;
let copilotPanelWide = false;
let copilotLayoutMode: 'narrow' | 'dual' | 'tri' = 'narrow';

/** Viewport tracking for Copilot width cap and layout tiers (md+ inline reserve). */
let viewportWidth = 1200;
const COPILOT_IDEAL_WIDTH: Record<'narrow' | 'dual' | 'tri', number> = {
	narrow: 420,
	dual: 700,
	tri: 940
};
/** Max Copilot width as a fraction of viewport — keeps report + Copilot usable side by side. */
const COPILOT_VIEWPORT_CAP = 0.4;
/** Minimum capped viewport budget to offer dual / tri layouts. */
const COPILOT_DUAL_MIN_CAP = 640;
const COPILOT_TRI_MIN_CAP = 880;

$: copilotMaxWidthPx = browser ? Math.floor(viewportWidth * COPILOT_VIEWPORT_CAP) : COPILOT_IDEAL_WIDTH.tri;
$: copilotMaxLayoutTier = (
	copilotMaxWidthPx >= COPILOT_TRI_MIN_CAP ? 'tri' : copilotMaxWidthPx >= COPILOT_DUAL_MIN_CAP ? 'dual' : 'narrow'
) as 'narrow' | 'dual' | 'tri';
$: copilotAsideWidthPx = Math.min(COPILOT_IDEAL_WIDTH[copilotLayoutMode], copilotMaxWidthPx);
/** Right padding for main column when Copilot or peek rail is open (md+ only).
 *  Uses viewingReport so the rail gap closes on the templates list view. */
$: copilotMainPaddingRightPx =
	browser && viewportWidth >= 768
		? sidebarVisible && isEnhancementContext
			? copilotAsideWidthPx
			: viewingReport && !sidebarVisible
				? 40
				: 0
		: 0;
let intervalDrawerOpen = false;
let refiningTemplate: any = null;
let auditState: {
	status: string;
	result: unknown;
	auditId: string | null;
	error: string | null;
	activeCriterion: string | null;
	saveInFlight?: boolean;
} | null = null;

function openCopilot(options: {
	tab?: typeof sidebarTabToOpen;
	initialMessage?: string | null;
	autoSend?: boolean;
	labelInfo?: typeof chatAutoSendLabel;
	auditFixContext?: typeof chatAuditFixContext;
} = {}) {
	if (options.tab === 'comparison') {
		intervalDrawerOpen = true;
		return;
	}
	navStateBeforeCopilot = !sidebarCollapsed;
	sidebarCollapsed = true;
	if (options.tab !== undefined) sidebarTabToOpen = options.tab ?? null;
	if (options.initialMessage !== undefined) chatInitialMessage = options.initialMessage ?? null;
	if (options.autoSend !== undefined) chatAutoSend = options.autoSend;
	if (options.labelInfo !== undefined) chatAutoSendLabel = options.labelInfo ?? null;
	if (options.auditFixContext !== undefined) chatAuditFixContext = options.auditFixContext ?? null;
	sidebarVisible = true;
}

function closeCopilot() {
	sidebarVisible = false;
	sidebarTabToOpen = null;
	chatInitialMessage = null;
	chatAutoSend = false;
	chatAutoSendLabel = null;
	chatAuditFixContext = null;
	// Preserve copilotPanelWide / copilotLayoutMode so the main column
	// reserves the correct width immediately when the sidebar re-opens.
	// The sidebar itself will re-emit panelWide on the visibility rising edge.
	//
	// Delay nav restoration until after the padding-right transition (300ms)
	// completes — otherwise both animations fire simultaneously and the content
	// area visually "rebounds" from being pushed from both sides at once.
	if (navStateBeforeCopilot) {
		setTimeout(() => { sidebarCollapsed = false; }, 310);
	}
}

// Template modal state (rendered at root level)
let showTemplateEditor = false;
let editingTemplate: any = null;
let showTemplateWizard = false;
let showSkillSheetCreator = false;
let templatedModel = 'claude'; // Track model for template editor
	
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
		cerebras_configured: false,
		deepgram_configured: false,
		has_at_least_one_model: false
	};
	let apiKeyStatusError: string | null = null;  // Soft message when load fails (stale token etc.)
	let loadingApiStatus = true;
	let loadingUseCases = true;
	
	// Initialize once on first mount - prevents resets on re-render
	if (!initialized) {
		autoVariableValues = {};
		variableValues = {}; // Legacy
		initialized = true;
	}
	
	// Clear auto report state when switching away from auto tab
	$: if (activeTab !== 'auto') {
		// Don't clear immediately - let user switch back and see their work
		// Only clear when explicitly switching tabs if needed
	}
	
	// Clear templated report state when switching away from templated tab
	$: if (activeTab !== 'templated') {
		// Don't clear immediately - let user switch back and see their work
		// Only clear when explicitly switching tabs if needed
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
		apiKeyStatusError = null;
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
						cerebras_configured: data.cerebras_configured || false,
						deepgram_configured: data.deepgram_configured || false,
						has_at_least_one_model: Boolean(data.has_at_least_one_model ?? (data.anthropic_configured || data.groq_configured || data.cerebras_configured)),
						using_user_keys: data.using_user_keys || { deepgram: data.deepgram_configured || false }
					};
				}
			} else {
				apiKeyStatusError = 'Unable to verify service status. You can still try. If you have issues, try refreshing or logging in again.';
			}
		} catch (err) {
			logger.error('Failed to load API key status:', err);
			apiKeyStatusError = 'Unable to verify service status. You can still try. If you have issues, try refreshing or logging in again.';
		} finally {
			loadingApiStatus = false;
		}
	}
	
	// Model selection is now handled internally by each tab component
	
	// Reload API key status when auth state changes (e.g. after login/refresh)
	let lastAuthToken: string | null = null;
	$: if (browser && $token && $isAuthenticated) {
		if (lastAuthToken !== $token) {
			lastAuthToken = $token;
			loadApiKeyStatus();
		}
	} else {
		lastAuthToken = null;
	}

	function handleLogout(): void {
		logout();
		goto('/login');
	}

	function handleTabChange(event: CustomEvent<string>): void {
		activeTab = event.detail;
	}

	type ExternalAuditTabRef = {
		restoreFromParent: () => Promise<void>;
		dismissFromParent: () => void;
		handleExternalAuditAcknowledge?: (detail: { criterion: string; resolutionMethod: string }) => void;
		handleExternalAuditRestore?: (detail: { criterion: string }) => void;
		handleExternalAuditSuggestFix?: (detail: unknown) => void;
		handleExternalAuditApplyFix?: (detail: unknown) => void;
		handleExternalAuditInsertBanner?: (bannerText: string) => void;
		handleExternalAuditReaudit?: () => void;
	};

	// Tab refs for draft restore (called from page-level banners)
	let intelliTabRef: ExternalAuditTabRef | null = null;
	let templateTabRef: ExternalAuditTabRef | null = null;

	// Banner visibility is captured once at mount, not reactive — prevents banner firing while typing
	let showIntelliDraftBanner = false;
	let showTemplateDraftBanner = false;

	async function handleRestoreIntelli(): Promise<void> {
		showIntelliDraftBanner = false;
		activeTab = 'auto';
		await tick();
		intelliTabRef?.restoreFromParent();
	}

	function handleDismissIntelli(): void {
		showIntelliDraftBanner = false;
		intelliTabRef?.dismissFromParent();
	}

	async function handleRestoreTemplate(): Promise<void> {
		showTemplateDraftBanner = false;
		activeTab = 'templated';
		await tick();
		templateTabRef?.restoreFromParent();
	}

	function handleDismissTemplate(): void {
		showTemplateDraftBanner = false;
		templateTabRef?.dismissFromParent();
	}

	function handleEditTemplate(event: CustomEvent<{ template: Record<string, unknown> }>): void {
		// Editing now happens inline in TemplatedReportTab, so this handler is kept for compatibility
		// but doesn't need to switch tabs anymore
	}

	// Template modal handlers
	function handleOpenTemplateEditor(event: CustomEvent<{ template: any; model: string }>): void {
		editingTemplate = event.detail.template;
		templatedModel = event.detail.model;
		showTemplateEditor = true;
	}

	function handleCloseTemplateEditor(): void {
		showTemplateEditor = false;
		editingTemplate = null;
	}

	function handleTemplateEditorSaved(): void {
		showTemplateEditor = false;
		editingTemplate = null;
		// Refresh templates
		templatesStore.refreshTemplates();
	}

	function handleOpenTemplateWizard(): void {
		showSkillSheetCreator = true;
	}

	function handleCloseTemplateWizard(): void {
		showTemplateWizard = false;
	}

	function handleTemplateWizardCreated(): void {
		showTemplateWizard = false;
		// Refresh templates
		templatesStore.refreshTemplates();
	}

	function handleCloseSkillSheetCreator(): void {
		showSkillSheetCreator = false;
	}

	function handleSkillSheetCreated(): void {
		showSkillSheetCreator = false;
		templatesStore.refreshTemplates();
		templatesRefreshKey += 1;
	}

	let templatesRefreshKey = 0;
	let historyRefreshKey = 0;

	function handleLogoutFromSidebar(): void {
		handleLogout();
	}

	function handleSettingsUpdated(_event: CustomEvent) {
		// Reload API key status after settings update
		loadApiKeyStatus();
	}

	function clearEnhancementState(): void {
		closeCopilot();
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
    templatedReportContent = '';
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
					autoVariableValues = {};
					variableValues = {}; // Legacy
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

	function handleViewportResize(): void {
		if (browser) viewportWidth = window.innerWidth;
	}

	onMount(async () => {
		if (browser) {
			// Capture draft banner state once at mount — banners must not react to live typing
			showIntelliDraftBanner = $hasIntelliDraft;
			showTemplateDraftBanner = $hasTemplateDraft;

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
			viewportWidth = window.innerWidth;
			window.addEventListener('resize', handleViewportResize);

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
			window.removeEventListener('resize', handleViewportResize);
		}
	});

	// Handle use case change in AutoReportTab
	async function onUseCaseChange(preserveValues = false): Promise<void> {
		// Save existing values if we're preserving them (e.g., when model changes)
		const existingValues = preserveValues ? { ...autoVariableValues } : {};
		
		if (!preserveValues) {
			autoVariableValues = {};
			variableValues = {}; // Legacy
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
						autoVariableValues[v] = existingValues[v];
						variableValues[v] = existingValues[v]; // Legacy
					} else {
						// Initialize with empty string
						autoVariableValues[v] = '';
						variableValues[v] = ''; // Legacy
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
	
	// Handle form reset from IntelliDictateTab (or legacy AutoReportTab)
	async function handleFormReset(): Promise<void> {
		autoVariableValues = {};
		variableValues = {}; // Legacy
		selectedUseCase = '';
		promptVariables = [];
		autoResponse = null;
		autoResponseModel = null;
		autoError = null;
		error = null;
		response = null;
		responseModel = null;
		reportId = null;
		clearEnhancementState();
		versionHistoryRefreshKey += 1;
		// Reload default use case (radiology_report) - for legacy/templated flows
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
			const hasEmptyFields = promptVariables.some(v => !autoVariableValues[v] || !autoVariableValues[v].trim());
			if (hasEmptyFields) {
				error = 'Please fill in all required fields';
				return;
			}
		}
		
		loading = true;
		error = null;
		response = null;
		responseModel = null;

		const _flowT0 = typeof performance !== 'undefined' ? performance.now() : 0;
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
				payload.variables = autoVariableValues;
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
			const _flowT1 = typeof performance !== 'undefined' ? performance.now() : 0;
			console.debug(
				'[FLOW_TIMING] auto POST /api/chat roundtrip_ms=',
				Math.round(_flowT1 - _flowT0),
				'report_id=',
				data.report_id
			);

			if (data.success) {
				autoResponse = data.response;
				autoResponseModel = data.model;
				autoScanType = data.scan_type || '';
				reportId = data.report_id || null;
				if (reportId) {
					versionHistoryRefreshKey += 1;
					historyRefreshKey += 1; // Trigger history reload
					// Refresh reports store to include new report
					reportsStore.refreshReports();
				}
			} else {
				autoError = 'Something went wrong. Please try again.';
			}
		} catch (err) {
			autoError = 'Failed to connect. Please try again.';
		} finally {
			autoLoading = false;
		}
	}

$: isEnhancementContext = activeTab === 'auto' || activeTab === 'templated';
// True when the user is actively looking at a report (not at the templates list view).
// templatedReportId is intentionally preserved across list-navigation for fast re-entry,
// so we can't rely on currentReportId alone — also require $selectedTemplateId when on
// the templated tab. This hides the Copilot peek rail / mobile FAB when browsing the list.
$: viewingReport =
	isEnhancementContext &&
	!!currentReportId &&
	(activeTab !== 'templated' || $selectedTemplateId !== null);
$: {
	const newReportId = isEnhancementContext
		? (activeTab === 'auto' ? reportId : templatedReportId)
		: null;

	// Close sidebar if switching between different reports or leaving enhancement context
	if (currentReportId !== newReportId && sidebarVisible) {
		closeCopilot();
	}

	// Reset enhancement/audit state ONLY on genuine report transitions:
	// (a) switching from one report to a different report, or
	// (b) starting a brand new report (null → uuid).
	// Transitions through null (e.g. tabbing away to history/settings and
	// back) must NOT reset state — the viewer is CSS-hidden, not unmounted,
	// and its local auditStore still holds the data. Resetting auditState
	// here would leave the sidebar banner blank on return because the
	// viewer's dispatch reactive only re-fires when $auditStore changes,
	// which it didn't during the hide.
	const isRealReportTransition =
		newReportId !== null && currentReportId !== newReportId;
	if (isRealReportTransition) {
		enhancementGuidelinesCount = 0;
		enhancementLoading = false;
		enhancementError = false;
		copilotAutoOpened = false;
		auditState = null;
		enhancementsLoaded = false;
	}

	// Preserve currentReportId across tab-hides. Only advance it on a real
	// report transition — otherwise the next return trip (null → uuid) would
	// look like a transition and trigger the reset above.
	if (newReportId !== null) {
		currentReportId = newReportId;
	}
}
$: shouldAutoLoadEnhancements = Boolean(isEnhancementContext && currentReportId);
$: if (!isEnhancementContext && sidebarVisible) {
	closeCopilot();
}

// Auto-open Copilot once per report when guideline enhancement finishes loading (QA tab first)
$: if (enhancementsLoaded && !copilotAutoOpened && !sidebarVisible && isEnhancementContext) {
	const autoOpenEnabled = (() => {
		try {
			return localStorage.getItem('copilotAutoOpen') !== 'false';
		} catch {
			return true;
		}
	})();
	if (autoOpenEnabled) {
		copilotAutoOpened = true;
		openCopilot({ tab: 'qa' });
	}
}

$: if (
	auditState?.status === 'complete' &&
	enhancementError &&
	!copilotAutoOpened &&
	!sidebarVisible &&
	isEnhancementContext
) {
	copilotAutoOpened = true;
	openCopilot({ tab: 'qa' });
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

	<!-- Main + workbench row; right inset reserved when peek rail or desktop Copilot is open (those layers are fixed). -->
	<div
		class="relative z-10 flex min-h-screen md:items-start transition-[padding] duration-300 {($isAuthenticated || ($token && !$isAuthenticated)) ? (sidebarCollapsed ? 'md:ml-16' : 'md:ml-64') : ''}"
		style:padding-right={copilotMainPaddingRightPx > 0 ? `${copilotMainPaddingRightPx}px` : undefined}
	>
	<main class="flex-1 min-w-0 relative min-h-screen">
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
				{#if apiKeyStatusError}
					<div class="mb-4 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-200 text-sm flex items-start justify-between gap-3">
						<span>{apiKeyStatusError}</span>
						<button
							type="button"
							onclick={() => loadApiKeyStatus()}
							class="shrink-0 text-amber-400 hover:text-amber-300 underline text-sm"
						>
							Retry
						</button>
					</div>
				{/if}
				<!-- Draft restore banners (always visible when drafts exist) -->
			{#if showIntelliDraftBanner || showTemplateDraftBanner}
				<div class="space-y-2 mb-4">
					{#if showIntelliDraftBanner}
							<div
								class="flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-amber-950/40 border border-amber-500/25 text-sm"
								in:fade={{ duration: 200 }}
								out:fade={{ duration: 150 }}
							>
								<div class="flex items-center gap-2.5 min-w-0">
									<svg class="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
									<span class="shrink-0 px-2 py-0.5 rounded-md bg-blue-500/15 border border-blue-500/25 text-blue-300 text-[11px] font-medium">
										Quick Report
									</span>
									<span class="text-amber-200/80 truncate">
										{new Date($draftStore.savedAt ?? 0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} — restore your previous work?
									</span>
								</div>
								<div class="flex items-center gap-2 shrink-0">
									<button
										type="button"
										onclick={handleRestoreIntelli}
										class="px-3 py-1 text-xs font-medium rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors border border-amber-500/30"
									>
										Restore
									</button>
									<button
										type="button"
										onclick={handleDismissIntelli}
										class="px-3 py-1 text-xs rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
									>
										Dismiss
									</button>
								</div>
							</div>
						{/if}
						{#if showTemplateDraftBanner}
							{@const templateName = ($templatesStore.templates || []).find(
								(t) => t.id === $draftStore.templateTab?.templateId
							)?.name}
							<div
								class="flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-amber-950/40 border border-amber-500/25 text-sm"
								in:fade={{ duration: 200 }}
								out:fade={{ duration: 150 }}
							>
								<div class="flex items-center gap-2.5 min-w-0">
									<svg class="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
									<span class="shrink-0 px-2 py-0.5 rounded-md bg-purple-500/15 border border-purple-500/25 text-purple-300 text-[11px] font-medium">
										Template{templateName ? `: ${templateName}` : ''}
									</span>
									<span class="text-amber-200/80 truncate">
										{new Date($draftStore.savedAt ?? 0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} — restore your previous work?
									</span>
								</div>
								<div class="flex items-center gap-2 shrink-0">
									<button
										type="button"
										onclick={handleRestoreTemplate}
										class="px-3 py-1 text-xs font-medium rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors border border-amber-500/30"
									>
										Restore
									</button>
									<button
										type="button"
										onclick={handleDismissTemplate}
										class="px-3 py-1 text-xs rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
									>
										Dismiss
									</button>
								</div>
							</div>
						{/if}
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
						<IntelliDictateTab
							bind:this={intelliTabRef}
							bind:response={autoResponse}
							bind:responseModel={autoResponseModel}
							bind:loading={autoLoading}
							bind:error={autoError}
							bind:reportId={reportId}
							reportUpdateLoading={reportUpdateLoading}
							versionHistoryRefreshKey={versionHistoryRefreshKey}
							apiKeyStatus={apiKeyStatus}
							enhancementGuidelinesCount={enhancementGuidelinesCount}
							enhancementLoading={enhancementLoading}
							enhancementError={enhancementError}
							on:resetForm={handleFormReset}
							on:openSidebar={(e) => {
								openCopilot({
									tab: e.detail?.tab || null,
									initialMessage: e.detail?.initialMessage || null,
									autoSend: e.detail?.autoSend ?? false,
									labelInfo: e.detail?.labelInfo || null,
									auditFixContext: e.detail?.auditFixContext ?? null
								});
							}}
							on:auditStateChange={(e) => {
								if (isEnhancementContext) auditState = e.detail;
							}}
						on:showHoverPopup={(e) => {
							hoverPopupItem = e.detail.item;
							hoverPopupPosition = e.detail.position;
							hoverPopupReportContent = e.detail.reportContent || '';
							hoverPopupReportId = reportId;
								hoverPopupVisible = true;
							}}
							on:hideHoverPopup={() => {
								hoverPopupVisible = false;
								hoverPopupItem = null;
							}}
						on:historyRestored={(e) => handleHistoryRestored(e.detail as RestoredReportDetail)}
						on:historyUpdate={(e) => handleHistoryUpdate(e.detail as ReportHistoryDetail)}
						on:auditComplete={(e) => {
							auditGuidelineReferences = e.detail?.guidelineReferences ?? [];
							auditCriteriaForSidebar = e.detail?.auditCriteria ?? [];
						}}
					on:openVersionHistory={() => {
						if (currentReportId) showVersionHistoryModal = true;
					}}
					on:openCompare={() => { intervalDrawerOpen = true; }}
				/>
			{/if}
		</div>
		
		<!-- Templated Report Tab - Keep component alive, just hide/show -->
				<div class={activeTab === 'templated' ? '' : 'hidden'}>
					{#if showSkillSheetCreator}
						<SkillSheetCreator
							on:close={handleCloseSkillSheetCreator}
							on:templateCreated={handleSkillSheetCreated}
						/>
					{:else if loadingApiStatus}
						<!-- Skeleton loader for API status -->
						<div class="card-dark space-y-4">
							<div class="h-8 bg-gray-700/50 rounded animate-pulse w-1/3"></div>
							<div class="h-10 bg-gray-700/50 rounded animate-pulse"></div>
							<div class="h-4 bg-gray-700/50 rounded animate-pulse w-1/2"></div>
							<div class="h-32 bg-gray-700/50 rounded animate-pulse"></div>
						</div>
					{:else}
					<TemplatedReportTab
						bind:this={templateTabRef}
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
						on:openTemplateEditor={handleOpenTemplateEditor}
						on:openTemplateWizard={handleOpenTemplateWizard}
						on:templateCreated={() => {
							templatesRefreshKey += 1;
						}}
						on:templateDeleted={() => {
							templatesRefreshKey += 1;
						}}
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
						openCopilot({
							tab: e.detail?.tab || null,
							initialMessage: e.detail?.initialMessage || null,
							autoSend: e.detail?.autoSend ?? false,
							labelInfo: e.detail?.labelInfo || null,
							auditFixContext: e.detail?.auditFixContext ?? null
						});
					}}
					on:auditStateChange={(e) => {
						if (isEnhancementContext) auditState = e.detail;
					}}
					on:showHoverPopup={(e) => {
							hoverPopupItem = e.detail.item;
							hoverPopupPosition = e.detail.position;
							hoverPopupReportContent = e.detail.reportContent || '';
							hoverPopupReportId = templatedReportId;
							hoverPopupVisible = true;
						}}
						on:hideHoverPopup={() => {
							hoverPopupVisible = false;
							hoverPopupItem = null;
						}}
					on:historyRestored={(e) => handleHistoryRestored(e.detail as RestoredReportDetail)}
					on:historyUpdate={(e) => handleHistoryUpdate(e.detail as ReportHistoryDetail)}
					on:auditComplete={(e) => {
						auditGuidelineReferences = e.detail?.guidelineReferences ?? [];
						auditCriteriaForSidebar = e.detail?.auditCriteria ?? [];
					}}
				on:openVersionHistory={() => {
					if (currentReportId) showVersionHistoryModal = true;
				}}
				on:openCompare={() => { intervalDrawerOpen = true; }}
				on:openRefine={(e) => { refiningTemplate = e.detail.template; }}
				on:reportCleared={handleTemplateCleared}
					on:templateListOpen={() => {
							// User clicked "Back to Templates" — just close the sidebar.
							// Do NOT clear templatedReportId or enhancement state so that
							// re-selecting the same template is seamless.
							closeCopilot();
						}}
						on:reportContentChange={(e) => {
							templatedReportContent = e.detail?.content ?? '';
						}}
					/>
					{/if}
				</div>
				
				<!-- Tab components - all loaded on app initialization -->
				<!-- Template Management Tab removed - functionality consolidated into TemplatedReportTab -->
				
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

	<!-- Mount when a report exists so /enhance + prefetch can run before Copilot is opened. -->
	{#if isEnhancementContext && currentReportId}
		<aside
			class="fixed inset-0 z-[10000] flex min-h-0 w-full flex-col border-l border-white/10 bg-black/70 backdrop-blur-2xl overflow-hidden shadow-2xl shadow-purple-500/10 transition-[width] duration-300 ease-in-out md:inset-y-0 md:left-auto md:right-0 md:z-[35] {!sidebarVisible ? 'hidden' : ''}"
			style={browser && viewportWidth >= 768
				? `width: ${copilotAsideWidthPx}px; max-width: min(100vw, ${copilotMaxWidthPx}px);`
				: 'width: 100%;'}
			aria-hidden={!sidebarVisible}
		>
			<ReportEnhancementSidebar
				reportId={currentReportId}
				reportContent={activeTab === 'auto' ? (autoResponse || '') : (templatedResponseOverride || templatedReportContent || response || '')}
				visible={sidebarVisible}
				inFlow={true}
				autoLoad={shouldAutoLoadEnhancements}
				historyAvailable={currentHistoryCount > 1}
				initialTab={sidebarTabToOpen}
				initialMessage={chatInitialMessage}
				autoSend={chatAutoSend}
				autoSendLabel={chatAutoSendLabel}
				auditFixContext={chatAuditFixContext}
				auditGuidelineReferences={auditGuidelineReferences}
				auditCriteriaForSidebar={auditCriteriaForSidebar}
				auditState={auditState}
				panelWide={copilotPanelWide}
				maxLayoutTier={copilotMaxLayoutTier}
				on:close={closeCopilot}
	on:auditAcknowledge={(e) => {
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditAcknowledge?.(e.detail);
		else templateTabRef?.handleExternalAuditAcknowledge?.(e.detail);
	}}
	on:auditRestore={(e) => {
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditRestore?.(e.detail);
		else templateTabRef?.handleExternalAuditRestore?.(e.detail);
	}}
	on:auditSuggestFix={(e) => {
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditSuggestFix?.(e.detail);
		else templateTabRef?.handleExternalAuditSuggestFix?.(e.detail);
	}}
	on:auditApplyFix={(e) => {
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditApplyFix?.(e.detail);
		else templateTabRef?.handleExternalAuditApplyFix?.(e.detail);
	}}
	on:auditInsertBanner={(e) => {
		const t = e.detail?.bannerText;
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditInsertBanner?.(t);
		else templateTabRef?.handleExternalAuditInsertBanner?.(t);
	}}
	on:auditReaudit={() => {
		if (activeTab === 'auto') intelliTabRef?.handleExternalAuditReaudit?.();
		else templateTabRef?.handleExternalAuditReaudit?.();
	}}
	on:auditFixContextConsumed={() => {
		chatAuditFixContext = null;
	}}
	on:reportUpdated={(e) => {
		if (e.detail.report) {
			const newContent = e.detail.report.report_content;
			versionHistoryRefreshKey += 1;
			// Push updated content to the correct tab's response variable
			if (activeTab === 'auto') {
				autoResponse = newContent;
			} else {
				// For templated tab, always update the override so ReportResponseViewer sees it
				templatedResponseOverride = newContent;
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
	on:openCompare={() => {
		intervalDrawerOpen = true;
	}}
	on:panelWide={(e) => {
		copilotPanelWide = Boolean(e.detail?.wide);
		if (e.detail?.mode) copilotLayoutMode = e.detail.mode;
	}}
	on:enhancementState={(e) => {
		const state = e.detail;
		enhancementGuidelinesCount = state.guidelinesCount || 0;
		enhancementLoading = state.isLoading || false;
		enhancementError = state.hasError || false;
		// Ready when this event matches the active report (avoids stale sidebar emissions)
		enhancementsLoaded =
			!state.isLoading &&
			!!currentReportId &&
			String(state.reportId ?? '') === String(currentReportId);
	}}
			/>
		</aside>
	{/if}
	</div>

	<!-- Mobile Copilot FAB: visible only on < md when the copilot rail is hidden -->
	{#if viewingReport && !sidebarVisible}
		<button
			type="button"
			class="md:hidden fixed bottom-5 right-5 z-[45] w-12 h-12 rounded-full bg-purple-600/90 backdrop-blur-lg text-white shadow-lg shadow-purple-500/30 flex items-center justify-center hover:bg-purple-500 active:scale-95 transition-all"
			title="Open Copilot"
			onclick={() => openCopilot()}
		>
			<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M13 10V3L4 14h7v7l9-11h-7z" />
			</svg>
			{#if (Array.isArray((auditState?.result as any)?.criteria) && (auditState?.result as any).criteria.filter((c: any) => c.status === 'flag' && !c.acknowledged).length > 0)}
				<span class="absolute -top-0.5 -right-0.5 w-3 h-3 bg-rose-500 rounded-full border-2 border-black"></span>
			{/if}
		</button>
	{/if}

	<!-- Viewport-locked rail: sticky fails when ancestors use overflow-hidden (page root). -->
	{#if viewingReport && !sidebarVisible}
		{@const _railLoading = enhancementLoading || auditState?.status === 'loading'}
		{@const _railLoaded = !enhancementLoading && (enhancementGuidelinesCount > 0 || auditState?.status === 'complete' || auditState?.status === 'stale')}
		{@const _qaFlagCount = Array.isArray((auditState?.result as any)?.criteria)
			? (auditState?.result as any).criteria.filter((c: any) => c.status === 'flag' && !c.acknowledged).length
			: 0}
		<div
			class="copilot-rail hidden md:flex fixed top-0 bottom-0 right-0 z-[25] flex-col items-stretch gap-1 py-4 overflow-hidden"
			class:copilot-rail--loading={_railLoading}
			class:copilot-rail--loaded={_railLoaded}
			aria-label="Copilot quick actions"
		>
			{#if _railLoading}
				<div class="rail-shimmer" aria-hidden="true"></div>
			{/if}

			<!-- Identity header -->
			<div class="rail-header flex items-center gap-2 px-2 pb-3 mb-1 border-b border-white/8">
				<div class="rail-icon-wrap flex-shrink-0 w-6 h-6 rounded-md bg-purple-600/20 flex items-center justify-center">
					<svg class="w-3.5 h-3.5 text-purple-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
						<path d="M13 10V3L4 14h7v7l9-11h-7z" />
					</svg>
				</div>
				<span class="rail-label text-[11px] font-semibold text-purple-300/80 uppercase tracking-widest whitespace-nowrap overflow-hidden">Copilot</span>
			</div>

			<!-- Guidelines button -->
			<button
				type="button"
				class="rail-btn relative flex items-center gap-2.5 px-2 py-2 text-gray-400 hover:text-green-400 transition-colors rounded-lg hover:bg-green-500/5 mx-1"
				title="Guidelines"
				onclick={() => openCopilot({ tab: 'guidelines' })}
			>
				<div class="relative flex-shrink-0 w-6 flex items-center justify-center">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
					</svg>
					{#if enhancementLoading}
						<span class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full border border-green-400 border-t-transparent animate-spin"></span>
					{:else if enhancementGuidelinesCount > 0}
						<span class="absolute -top-1 -right-1 min-w-[14px] h-3.5 px-0.5 bg-green-600 text-white text-[8px] font-bold rounded-full flex items-center justify-center">
							{enhancementGuidelinesCount > 9 ? '9+' : enhancementGuidelinesCount}
						</span>
					{/if}
				</div>
				<span class="rail-label text-xs font-medium whitespace-nowrap overflow-hidden">Guidelines</span>
			</button>

			<!-- QA / Audit button -->
			<button
				type="button"
				class="rail-btn relative flex items-center gap-2.5 px-2 py-2 text-gray-400 hover:text-rose-300 transition-colors rounded-lg hover:bg-white/5 mx-1"
				title="QA Audit"
				onclick={() => openCopilot({ tab: 'qa' })}
			>
				<div class="relative flex-shrink-0 w-6 flex items-center justify-center">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
					</svg>
					{#if auditState?.status === 'loading'}
						<span class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full border border-rose-400 border-t-transparent animate-spin"></span>
					{:else if _qaFlagCount > 0}
						<span class="absolute -top-1 -right-1 min-w-[14px] h-3.5 px-0.5 bg-rose-600 text-white text-[8px] font-bold rounded-full flex items-center justify-center">
							{_qaFlagCount > 9 ? '9+' : _qaFlagCount}
						</span>
					{/if}
				</div>
				<span class="rail-label text-xs font-medium whitespace-nowrap overflow-hidden">QA Audit</span>
			</button>

			<!-- Chat button -->
			<button
				type="button"
				class="rail-btn flex items-center gap-2.5 px-2 py-2 text-gray-400 hover:text-purple-300 transition-colors rounded-lg hover:bg-white/5 mx-1"
				title="Ask AI"
				onclick={() => openCopilot({ tab: 'chat' })}
			>
				<div class="flex-shrink-0 w-6 flex items-center justify-center">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
					</svg>
				</div>
				<span class="rail-label text-xs font-medium whitespace-nowrap overflow-hidden">Ask AI</span>
			</button>

			<!-- Interval analysis button -->
			<button
				type="button"
				class="rail-btn flex items-center gap-2.5 px-2 py-2 text-gray-400 hover:text-orange-300 transition-colors rounded-lg hover:bg-white/5 mx-1"
				title="Interval Analysis"
				onclick={() => (intervalDrawerOpen = true)}
			>
				<div class="flex-shrink-0 w-6 flex items-center justify-center">
					<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
					</svg>
				</div>
				<span class="rail-label text-xs font-medium whitespace-nowrap overflow-hidden">Compare</span>
			</button>

			<!-- Expand chevron hint at bottom -->
			<div class="mt-auto flex flex-col items-center gap-1 px-2">
				<div class="rail-expand-hint w-full flex items-center gap-2 px-1 py-1.5 rounded-md opacity-40">
					<svg class="flex-shrink-0 w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
					</svg>
					<span class="rail-label text-[10px] text-gray-500 whitespace-nowrap overflow-hidden">Open panel</span>
				</div>
			</div>
		</div>
	{/if}

<ReportVersionHistory
	reportId={currentReportId}
	show={showVersionHistoryModal}
	refreshKey={versionHistoryRefreshKey}
	onClose={() => showVersionHistoryModal = false}
/>

<IntervalAnalysisDrawer
	open={intervalDrawerOpen && isEnhancementContext}
	reportId={currentReportId}
	reportContent={activeTab === 'auto' ? (autoResponse || '') : (templatedResponseOverride || templatedReportContent || response || '')}
	on:close={() => (intervalDrawerOpen = false)}
	on:reportUpdated={(e) => {
		if (e.detail.report) {
			const newContent = e.detail.report.report_content;
			versionHistoryRefreshKey += 1;
			if (activeTab === 'auto') {
				autoResponse = newContent;
			} else {
				templatedResponseOverride = newContent;
				templatedResponseVersion += 1;
			}
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
/>

<TemplateRefinePanel
	template={refiningTemplate}
	on:close={() => { refiningTemplate = null; }}
	on:saved={() => { refiningTemplate = null; }}
/>

<!-- Template Editor Modal - Rendered at root level -->
{#if showTemplateEditor}
	<div 
		class="fixed inset-0 bg-black/90 backdrop-blur-lg overflow-y-auto"
		style="z-index: 9999;"
		onclick={handleCloseTemplateEditor}
		onkeydown={(e) => e.key === 'Escape' && handleCloseTemplateEditor()}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div 
			class="min-h-screen p-4 md:p-6"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<TemplateEditorNew
				editingTemplate={editingTemplate}
				selectedModel={templatedModel}
				on:close={handleCloseTemplateEditor}
				on:saved={handleTemplateEditorSaved}
			/>
		</div>
	</div>
{/if}

<!-- Template Wizard Modal - Rendered at root level -->
{#if showTemplateWizard}
	<TemplateWizard
		onClose={handleCloseTemplateWizard}
		on:templateCreated={handleTemplateWizardCreated}
	/>
{/if}

	<!-- History Modal - Rendered at root level to avoid stacking context issues -->
	{#if historyModalReport}
		<div 
			class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 md:p-6"
			style="z-index: 9999;"
			tabindex="-1"
			onclick={(e) => { if (e.target === e.currentTarget) { historyModalReport = null; inputsExpanded = false; } }}
			onkeydown={(event) => {
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
							onclick={() => {
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
							onclick={() => { historyModalReport = null; inputsExpanded = false; }}
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
								onclick={() => inputsExpanded = !inputsExpanded}
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
	
	<!-- Template Wizard Modal - Now handled by TemplatedReportTab component -->
	
	<!-- Hover Popup (rendered at root level) -->
	<UnfilledItemHoverPopup
		visible={hoverPopupVisible}
		item={hoverPopupItem}
		position={hoverPopupPosition}
		reportContent={hoverPopupReportContent}
		enhancementsLoaded={enhancementsLoaded && !!hoverPopupReportId}
		on:apply={async (e) => {
			if (!hoverPopupItem || !hoverPopupReportContent || !hoverPopupReportId) return;
			const { item, value } = e.detail;
			
			
			// Convert markdown/HTML to plain text for position matching
			// Detection happens on plain text (via stripNonProseContent), so we need plain text for replacement too
			// Use the same method as detection to ensure positions match
			const temp = document.createElement('div');
			temp.innerHTML = hoverPopupReportContent;
			// Remove code blocks like detection does
			const codeBlocks = temp.querySelectorAll('pre, code');
			codeBlocks.forEach(el => el.remove());
			// Get text content (same as stripNonProseContent)
			let plainTextContent = temp.textContent || temp.innerText || hoverPopupReportContent;
			// Remove URLs and emails like detection does
			plainTextContent = plainTextContent.replace(/https?:\/\/[^\s]+/gi, '');
			plainTextContent = plainTextContent.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/g, '');
			
			
			// Create edit
			const edit: UnfilledEdit = {
				itemId: `${item.type}-${item.index}`,
				originalText: item.text,
				newValue: value,
				type: item.type,
				context: item.surroundingContext,
				position: item.index
			};
			
			
			// Apply edit to plain text
			const edits = new Map<string, UnfilledEdit>();
			edits.set(edit.itemId, edit);
			const updatedPlainText = applyEditsToReport(plainTextContent, edits);
			
			
			// Use the updated plain text as the report content
			const updatedReport = updatedPlainText;
			
			
			
			// Save to API
			try {
				reportUpdateLoading = true;
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) {
					headers['Authorization'] = `Bearer ${$token}`;
				}
				
				const res = await fetch(`${API_URL}/api/reports/${hoverPopupReportId}/update`, {
					method: 'PUT',
					headers,
					body: JSON.stringify({ content: updatedReport })
				});
				
				const data = await res.json();
				
				if (data.success) {
					// Update response in the appropriate tab
					if (activeTab === 'auto' && reportId === hoverPopupReportId) {
						response = data.report.report_content;
					} else if (activeTab === 'templated' && templatedReportId === hoverPopupReportId) {
						// For templated reports, we need to update via the override mechanism
						templatedResponseOverride = data.report.report_content;
						templatedResponseVersion += 1;
					}
					versionHistoryRefreshKey += 1;
				} else {
					console.error('Failed to save report:', data.error);
				}
			} catch (err) {
				console.error('Error saving report:', err);
			} finally {
				reportUpdateLoading = false;
				// Note: Highlighting state will be restored by ReportResponseViewer's reactive statement
				// when it detects unfilled items after updateLoading becomes false
			}
			
			// Hide popup
			hoverPopupVisible = false;
			hoverPopupItem = null;
		}}
		on:deleteSection={async (e) => {
			if (!hoverPopupReportContent || !hoverPopupReportId) return;
			const { sectionName } = e.detail;
			
			// Remove section and its //UNFILLED marker from report
			const lines = hoverPopupReportContent.split('\n');
			let updatedLines = [];
			let skipUntilNextSection = false;
			
			for (let i = 0; i < lines.length; i++) {
				const line = lines[i];
				
				// Check if this is the section header we want to delete
				if (line.trim().toUpperCase() === sectionName.toUpperCase()) {
					skipUntilNextSection = true;
					continue;
				}
				
				// Stop skipping when we hit next section header (all caps line) or end
				if (skipUntilNextSection) {
					if (line.trim() && line === line.toUpperCase() && !line.startsWith('//')) {
						skipUntilNextSection = false;
					} else {
						continue;  // Skip this line
					}
				}
				
				// Remove only the //UNFILLED marker for this specific section
				if (line.startsWith('//UNFILLED:')) {
					const markerSectionName = line.replace(/^\/\/UNFILLED:\s*/, '').trim();
					if (markerSectionName.toUpperCase() === sectionName.toUpperCase()) {
						continue;  // Skip only this specific marker
					}
				}
				
				updatedLines.push(line);
			}
			
			const updatedReport = updatedLines.join('\n').replace(/\n{3,}/g, '\n\n');  // Clean up extra blank lines
			
			// Save to API
			try {
				reportUpdateLoading = true;
				const headers: Record<string, string> = { 'Content-Type': 'application/json' };
				if ($token) {
					headers['Authorization'] = `Bearer ${$token}`;
				}
				
				const res = await fetch(`${API_URL}/api/reports/${hoverPopupReportId}/update`, {
					method: 'PUT',
					headers,
					body: JSON.stringify({ content: updatedReport })
				});
				
				const data = await res.json();
				
				if (data.success) {
					if (activeTab === 'auto' && reportId === hoverPopupReportId) {
						response = data.report.report_content;
					} else if (activeTab === 'templated' && templatedReportId === hoverPopupReportId) {
						templatedResponseOverride = data.report.report_content;
						templatedResponseVersion += 1;
					}
					versionHistoryRefreshKey += 1;
				} else {
					console.error('Failed to save report:', data.error);
				}
			} catch (err) {
				console.error('Error deleting section:', err);
			} finally {
				reportUpdateLoading = false;
			}
			
			// Hide popup
			hoverPopupVisible = false;
			hoverPopupItem = null;
		}}
	on:askAI={(e) => {
		openCopilot({
			tab: 'chat',
			initialMessage: e.detail.message,
			autoSend: true,
			labelInfo: e.detail.labelInfo || null,
			auditFixContext: null
		});
		hoverPopupVisible = false;
		hoverPopupItem = null;
	}}
		on:close={() => {
			hoverPopupVisible = false;
			hoverPopupItem = null;
		}}
		on:keepVisible={() => {
			// Keep popup visible - do nothing, just prevent hiding
		}}
	/>
	
	<!-- Footer -->
	{#if $isAuthenticated}
		<footer class="relative px-4 md:px-6 py-6 border-t border-white/5 mt-auto">
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

<style>
/* ── Collapsed Copilot rail ────────────────────────────── */
.copilot-rail {
	width: 40px;
	background: rgba(0, 0, 0, 0.5);
	border-left: 1px solid rgba(255, 255, 255, 0.08);
	backdrop-filter: blur(10px);
	-webkit-backdrop-filter: blur(10px);
	transition:
		width 0.22s cubic-bezier(0.4, 0, 0.2, 1),
		background 0.4s ease,
		border-color 0.4s ease,
		box-shadow 0.4s ease;
	overflow: hidden;
}

/* Expand on hover */
.copilot-rail:hover {
	width: 158px;
	background: rgba(12, 6, 28, 0.82);
	border-left-color: rgba(139, 92, 246, 0.3);
	box-shadow: -4px 0 32px rgba(139, 92, 246, 0.16);
}

/* Labels are hidden by default and revealed on hover */
.copilot-rail .rail-label {
	max-width: 0;
	opacity: 0;
	transition:
		max-width 0.2s cubic-bezier(0.4, 0, 0.2, 1),
		opacity 0.18s ease;
	display: block;
	overflow: hidden;
}

.copilot-rail:hover .rail-label {
	max-width: 120px;
	opacity: 1;
}

.copilot-rail--loading {
	border-left-color: rgba(139, 92, 246, 0.25);
	box-shadow: -2px 0 20px rgba(139, 92, 246, 0.08);
}

.copilot-rail--loaded {
	background: rgba(20, 10, 40, 0.6);
	border-left-color: rgba(139, 92, 246, 0.22);
	box-shadow: -2px 0 24px rgba(139, 92, 246, 0.12);
}

.copilot-rail--loaded:hover {
	border-left-color: rgba(139, 92, 246, 0.4);
}

/* Rail buttons take full width when expanded */
.rail-btn {
	width: 100%;
	text-align: left;
}

/* Vertical shimmer — sweeps bottom→top in a loop */
.rail-shimmer {
	position: absolute;
	inset: 0;
	pointer-events: none;
	background: linear-gradient(
		to top,
		transparent 20%,
		rgba(139, 92, 246, 0.1) 40%,
		rgba(167, 139, 250, 0.28) 50%,
		rgba(139, 92, 246, 0.1) 60%,
		transparent 80%
	);
	background-size: 100% 300%;
	animation: rail-shimmer-sweep 2s ease-in-out infinite;
}

@keyframes rail-shimmer-sweep {
	0%   { background-position: 0 150%; opacity: 0.5; }
	50%  { opacity: 1; }
	100% { background-position: 0 -150%; opacity: 0.5; }
}

/* Expand hint fades in when rail is hovered */
.rail-expand-hint {
	transition: opacity 0.2s ease;
}

.copilot-rail:hover .rail-expand-hint {
	opacity: 0 !important;
}
</style>
