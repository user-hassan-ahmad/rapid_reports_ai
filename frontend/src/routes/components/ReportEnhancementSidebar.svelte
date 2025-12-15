<script context="module" lang="ts">
	interface Finding {
		finding: string;
		[key: string]: unknown;
	}
	
	interface SourceLink {
		url: string;
		title?: string;
	snippet?: string;
		[key: string]: unknown;
	}
	
	interface ClassificationSystem {
		name: string;
		grade_or_category: string;
		criteria: string;
	}

	interface MeasurementProtocol {
		parameter: string;
		technique: string;
		normal_range?: string;
		threshold?: string;
	}

	interface ImagingCharacteristic {
		feature: string;
		description: string;
		significance: string;
	}

	interface DifferentialDiagnosis {
		diagnosis: string;
		imaging_features: string;
		supporting_findings: string;
	}

	interface FollowUpImaging {
		indication: string;
		modality: string;
		timing: string;
		technical_specs?: string;
	}
	
	interface GuidelineEntry {
		finding: Finding;
		diagnostic_overview?: string;
		guideline_summary?: string;
		classification_systems?: ClassificationSystem[];
		measurement_protocols?: MeasurementProtocol[];
		imaging_characteristics?: ImagingCharacteristic[];
		differential_diagnoses?: DifferentialDiagnosis[];
		follow_up_imaging?: FollowUpImaging[];
		sources?: SourceLink[];
		body_names?: string[];
		reasoning?: string;
		[key: string]: unknown;
	}
	
interface AnalysisSummary {
	title: string;
	details: string;
	[key: string]: unknown;
}

interface ReviewQuestion {
	id: string;
	prompt: string;
	[key: string]: unknown;
}

interface SuggestedAction {
	id: string;
	title: string;
	details: string;
	patch: string;
	[key: string]: unknown;
}

interface StructuredCompleteness {
	summary?: AnalysisSummary | null;
	questions?: ReviewQuestion[];
	suggested_actions?: SuggestedAction[];
	feedback?: string;
	[key: string]: unknown;
}

interface CompletenessAnalysis {
	analysis: string;
	structured?: StructuredCompleteness;
	warning?: string;
	[key: string]: unknown;
}
	
	type CompletenessEntry = CompletenessAnalysis | null;
	
	interface EnhancementCacheEntry {
		findings: Finding[];
		guidelines: GuidelineEntry[];
		completeness: CompletenessEntry;
		timestamp: number;
		pending: boolean;
		error?: string | null;
		chatMessages?: ChatMessage[];
		appliedActionIds?: string[];
	}
	
	type ChatMessage = {
		role: 'user' | 'assistant';
		content: string;
		sources?: string[];
		error?: boolean;
		editProposal?: string;
		applied?: boolean;
	};
	
	const enhancementCache = new Map<string, EnhancementCacheEntry>();
</script>

<script lang="ts">
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import { onDestroy } from 'svelte';
	import pilotIcon from '$lib/assets/pilot.png';
	import { API_URL } from '$lib/config';
	import { logger } from '$lib/utils/logger';
	
	export let reportId: string | null = null;
	export let reportContent: string = '';
	export let visible: boolean = false;
	export let autoLoad: boolean = false;
	export let historyAvailable: boolean = false;
	export let initialTab: 'guidelines' | 'comparison' | 'chat' | null = null;
	
	let activeTab: 'guidelines' | 'analysis' | 'comparison' | 'chat' = 'guidelines';
	
	// Hide Analysis tab temporarily - redirect to guidelines if analysis is selected
	$: if (activeTab === 'analysis') {
		activeTab = 'guidelines';
	}
	
	// Set initial tab when sidebar opens or when initialTab changes
	let lastInitialTab: 'guidelines' | 'comparison' | 'chat' | null = null;
	$: if (visible && initialTab && initialTab !== 'analysis') {
		// Only update if the tab actually changed to avoid unnecessary updates
		if (initialTab !== lastInitialTab) {
			activeTab = initialTab;
			lastInitialTab = initialTab;
		}
	}
	
	// Reset lastInitialTab when sidebar closes
	$: if (!visible) {
		lastInitialTab = null;
	}
	let loading = false;
	let error: string | null = null;
	let hasLoaded = false;
	let lastReportId: string | null = null;
	let isExpanded = false;
	
	let findings: Finding[] = [];
	let guidelinesData: GuidelineEntry[] = [];
	let completenessAnalysis: CompletenessEntry = null;
	
	let chatMessages: ChatMessage[] = [];
	let chatInput = '';
	let chatLoading = false;

let selectedActionIds: string[] = [];
let applyActionsLoading = false;
let applyActionsError: string | null = null;
let availableSuggestedActions: SuggestedAction[] = [];
let selectedActions: SuggestedAction[] = [];
let selectedActionsWithPatch: SuggestedAction[] = [];
let canApplySelectedActions = false;
let summary: AnalysisSummary | null | undefined = null;
let reviewQuestions: ReviewQuestion[] = [];
let appliedActionIds: string[] = [];
type SectionKey = 'summary' | 'questions' | 'actions';
let sectionsExpanded: Record<SectionKey, boolean> = {
	summary: true,
	questions: true,
	actions: true
};
let guidelinesExpanded: Record<string, boolean> = {};

// Edit proposal modal state
let expandedEditProposalIndex: number | null = null;

// Comparison state
let priorReports: any[] = [];
let showAddPriorModal = false;
let editingPriorIndex: number | null = null;
let newPrior = { text: '', date: '', scan_type: '' };
let studyDateInput: HTMLInputElement;
let comparing = false;
let comparisonResult: any = null;
let applyRevisedReportLoading = false;
let showRevisedReportPreview = false;
let revisedReportApplied = false;

// Date formatting helper
function formatDateUK(dateStr: string): string {
	if (!dateStr) return '';
	try {
		const [year, month, day] = dateStr.split('-');
		return `${day}/${month}/${year}`;
	} catch {
		return dateStr;
	}
}

const COMPLETENESS_POLL_INTERVAL = 5000;
let completenessPending = false;
let completenessPollTimer: ReturnType<typeof setInterval> | null = null;
	
	marked.setOptions({
		breaks: true,
		gfm: true
	});
	
	const cloneValue = (value: unknown) => {
		if (value === null || value === undefined) return value;
		if (typeof structuredClone === 'function') {
			return structuredClone(value);
		}
		return JSON.parse(JSON.stringify(value));
	};
	
	function applyCacheEntry(entry: EnhancementCacheEntry | undefined): boolean {
		if (!entry) return false;
		findings = (cloneValue(entry.findings) as Finding[]) || [];
		guidelinesData = (cloneValue(entry.guidelines) as GuidelineEntry[]) || [];
		completenessAnalysis = entry.completeness ? (cloneValue(entry.completeness) as CompletenessEntry) : null;
		completenessPending = entry.pending ?? false;
		error = entry.error ?? null;
		chatMessages = entry.chatMessages ? (cloneValue(entry.chatMessages) as ChatMessage[]) : [];
		appliedActionIds = entry.appliedActionIds ? [...entry.appliedActionIds] : [];
		hasLoaded = true;
		loading = false;
		resetActionSelections();
		if (completenessPending) {
			startCompletenessPoll();
		} else {
			stopCompletenessPoll();
		}
		return true;
	}
	
	function saveCacheEntry(id?: string): void {
		const cacheId = id || reportId;
		if (!cacheId) return;
		enhancementCache.set(cacheId, {
			findings: cloneValue(findings) as Finding[],
			guidelines: cloneValue(guidelinesData) as GuidelineEntry[],
			completeness: cloneValue(completenessAnalysis) as CompletenessEntry,
			timestamp: Date.now(),
			pending: completenessPending,
			error,
			chatMessages: cloneValue(chatMessages) as ChatMessage[],
			appliedActionIds: [...appliedActionIds]
		});
	}
	
	function resetAllSidebarState(): void {
		// Guidelines tab state
		findings = [];
		guidelinesData = [];
		guidelinesExpanded = {};
		
		// Analysis tab state
		completenessAnalysis = null;
		completenessPending = false;
		appliedActionIds = [];
		sectionsExpanded = {
			summary: true,
			questions: true,
			actions: true
		};
		
		// Chat tab state
		chatMessages = [];
		chatInput = '';
		chatLoading = false;
		expandedEditProposalIndex = null;
		
		// Comparison tab state
		priorReports = [];
		comparisonResult = null;
		showAddPriorModal = false;
		editingPriorIndex = null;
		newPrior = { text: '', date: '', scan_type: '' };
		comparing = false;
		applyRevisedReportLoading = false;
		revisedReportApplied = false;
		showRevisedReportPreview = false;
		
		// General state
		error = null;
		stopCompletenessPoll();
		resetActionSelections();
	}
	
	function invalidateCache(): void {
		if (reportId) {
			enhancementCache.delete(reportId);
		}
		resetAllSidebarState();
	}

function stopCompletenessPoll() {
	if (completenessPollTimer) {
		clearInterval(completenessPollTimer);
		completenessPollTimer = null;
	}
}

async function pollCompleteness() {
	if (!reportId) return;
	const currentReport = reportId;
	try {
		const headers = {
			'Content-Type': 'application/json',
			...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
		};
		const response = await fetch(`${API_URL}/api/reports/${reportId}/completeness`, { headers });
		if (!response.ok) {
			return;
		}
		const data = await response.json();
		if (reportId !== currentReport) {
			return;
		}
		if (!data.success) {
			completenessPending = Boolean(data.pending);
			if (!completenessPending) {
				stopCompletenessPoll();
			}
			return;
		}
		completenessPending = Boolean(data.pending);
		if (data.completeness) {
			completenessAnalysis = cloneValue(data.completeness) as CompletenessEntry;
			hasLoaded = true;
			saveCacheEntry();
			if (!completenessPending) {
				stopCompletenessPoll();
			}
		} else if (!completenessPending) {
			stopCompletenessPoll();
			saveCacheEntry();
		}
	} catch (err) {
		// Error handled silently
	}
}

function startCompletenessPoll() {
	if (completenessPollTimer || !reportId) return;
	pollCompleteness();
	completenessPollTimer = setInterval(pollCompleteness, COMPLETENESS_POLL_INTERVAL);
	}
	
function renderMarkdown(md: string) {
		if (!md) return '';
		
		// Convert literal \n strings to actual newlines
		let processed = md.replace(/\\n/g, '\n');
		
		// Preprocess: Fix inline bullet points (• or -) that should be list items
		// Convert "• Item1 • Item2" or ". • Item" to proper markdown lists
		
		// Pattern 1: ". • Text" → "\n- Text" (period followed by bullet)
		processed = processed.replace(/\.\s*•\s*/g, '.\n- ');
		
		// Pattern 2: "• Text" at start or after newline → "- Text"
		processed = processed.replace(/(^|[\n\r])•\s*/g, '$1- ');
		
		// Pattern 3: Multiple inline bullets "text • more • more" → convert to list
		processed = processed.replace(/([.!?])\s+•\s+/g, '$1\n- ');
		
		// Pattern 4: Standalone • in middle of text
		processed = processed.replace(/\s+•\s+/g, '\n- ');
		
		// Fix: Remove accidental nested list markdown (lines starting with "- -" or "  -")
		processed = processed.replace(/^[\s]*-[\s]+-[\s]+/gm, '- ');
		processed = processed.replace(/^[\s]{2,}-[\s]+/gm, '- ');
		
		return marked.parse(processed);
	}

	async function loadEnhancements(force = false): Promise<void> {
		if (!reportId) {
			error = 'No report ID available';
			return;
		}
		
		if (!force) {
			const cached = enhancementCache.get(reportId);
			if (cached) {
				applyCacheEntry(cached);
				return;
			}
		} else {
			invalidateCache();
			hasLoaded = false;
		}
		
		loading = true;
		error = null;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			// Add a longer timeout for this API call (enhancement can take 30-60 seconds)
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minutes
			
			let response: Response;
			try {
				// Skip completeness analysis since Analysis tab is hidden
				response = await fetch(`${API_URL}/api/reports/${reportId}/enhance?skip_completeness=true`, {
					method: 'POST',
					headers,
					signal: controller.signal
				});
				clearTimeout(timeoutId);
			} catch (fetchErr: unknown) {
				clearTimeout(timeoutId);
				const abortName =
					(typeof fetchErr === 'object' && fetchErr !== null && 'name' in fetchErr)
						? (fetchErr as { name?: string }).name
						: undefined;
				if (abortName === 'AbortError') {
					error = 'Request timed out. The enhancement process may be taking longer than expected.';
					loading = false;
					return;
				} else {
					throw fetchErr;
				}
			}
			
			if (!response.ok) {
				const errorText = await response.text();
				logger.error('loadEnhancements: HTTP error:', response.status, errorText);
				error = `HTTP ${response.status}: ${errorText}`;
				loading = false;
				return;
			}
			
			let data: any;
			try {
				data = await response.json();
			} catch (jsonErr) {
				// If connection reset happens after response starts, we might have partial data
				// Try to continue if we have status 200
				if (response.status === 200) {
					error = 'Failed to parse response, but request succeeded';
					loading = false;
					return;
				}
				throw jsonErr;
			}
			
			if (data && data.success) {
				// Force reactive updates by creating new arrays/objects
				findings = [...(data.findings || [])];
				guidelinesData = [...(data.guidelines || [])];
				completenessAnalysis = data.completeness ? (cloneValue(data.completeness) as CompletenessEntry) : null;
				completenessPending = Boolean(data.completeness_pending);
				error = null; // Clear any previous errors
				if (completenessPending) {
					startCompletenessPoll();
				} else {
					stopCompletenessPoll();
				}
				resetActionSelections();
				saveCacheEntry();
				hasLoaded = true;
				loading = false;
			} else if (data && !data.success) {
				logger.error('loadEnhancements: API returned error:', data.error);
				error = data.error || 'Failed to load enhancements';
				completenessPending = false;
				stopCompletenessPoll();
			} else {
				logger.error('loadEnhancements: No data in response');
				error = 'No data received from server';
				completenessPending = false;
				stopCompletenessPoll();
			}
		} catch (err: unknown) {
			// Only set error if we don't already have successful data
			const hasData = findings.length > 0 || guidelinesData.length > 0;
			
			if (err instanceof TypeError && err.message.includes('fetch')) {
				// Network error - but check if we already got the data
				if (!hasData) {
					logger.error('loadEnhancements: Network error:', err);
					error = `Network error: ${err.message}. The connection may have been reset, but data was received.`;
				} else {
					error = null; // Clear error if we have data
				}
			} else {
				const errMsg = err instanceof Error ? err.message : String(err);
				if (!hasData) {
					logger.error('loadEnhancements: Exception:', err);
					error = `Failed to connect: ${errMsg}`;
				} else {
					error = null; // Clear error if we have data
				}
			}
			if (!hasData) {
				completenessPending = false;
				stopCompletenessPoll();
			}
		} finally {
			loading = false;
			if (!error && (findings.length > 0 || guidelinesData.length > 0 || completenessAnalysis)) {
				hasLoaded = true;
			}
		}
	}
	
	async function sendChatMessage(): Promise<void> {
		if (!chatInput.trim() || !reportId) return;
		
		const userMessage = chatInput.trim();
		chatInput = '';
		chatMessages.push({ role: 'user', content: userMessage });
		chatMessages = [...chatMessages];
		
		chatLoading = true;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			const response = await fetch(`${API_URL}/api/reports/${reportId}/chat`, {
				method: 'POST',
				headers,
				body: JSON.stringify({
					message: userMessage,
					history: chatMessages.slice(0, -1) // Exclude the current message we just added
				})
			});
			
			const data: any = await response.json();
			
			if (data.success) {
				let content = data.response;
				let editProposal = data.edit_proposal;

				chatMessages.push({
					role: 'assistant',
					content: content,
					sources: data.sources || [],
					editProposal
				});
				chatMessages = [...chatMessages];
			} else {
				chatMessages.push({
					role: 'assistant',
					content: `Error: ${data.error || 'Failed to get response'}`,
					error: true
				});
				chatMessages = [...chatMessages];
			}
		} catch (err) {
			chatMessages.push({
				role: 'assistant',
				content: `Error: ${err instanceof Error ? err.message : String(err)}`,
				error: true
			});
			chatMessages = [...chatMessages];
		} finally {
			chatLoading = false;
			saveCacheEntry(); // Save chat history to cache
		}
	}
	
	async function applySuggestion(suggestion: string) {
		if (!reportId || !reportContent) return;
		
		const newContent = `${reportContent}\n\n${suggestion}`;
		await updateReportContent(newContent);
	}
	
	async function updateReportContent(newContent: string, editSource: 'manual' | 'chat' = 'manual') {
		if (!reportId) return;
		
		try {
			dispatch('reportUpdating', { status: 'start' });
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			const response = await fetch(`${API_URL}/api/reports/${reportId}/update`, {
				method: 'PUT',
				headers,
				body: JSON.stringify({ content: newContent, edit_source: editSource })
			});
			
			const data = await response.json();
			
			if (data.success) {
				// Don't invalidate cache - we want manual refresh
				// invalidateCache();
				// hasLoaded = false;
				dispatch('reportUpdated', { report: data.report });
			} else {
				error = data.error || 'Failed to update report';
			}
		} catch (err) {
			error = `Failed to update: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			dispatch('reportUpdating', { status: 'end' });
		}
	}

function resetActionSelections(): void {
	selectedActionIds = [];
	applyActionsError = null;
}

function toggleSection(section: SectionKey): void {
	sectionsExpanded = {
		...sectionsExpanded,
		[section]: !sectionsExpanded[section]
	};
}

function toggleActionSelection(action: SuggestedAction): void {
	if (!action || !action.id) return;
	const hasPatch = Boolean(action.patch && action.patch.trim().length > 0);
	if (!hasPatch) return;

	if (selectedActionIds.includes(action.id)) {
		selectedActionIds = selectedActionIds.filter((id) => id !== action.id);
	} else {
		selectedActionIds = [...selectedActionIds, action.id];
	}
}

async function applySelectedActions(): Promise<void> {
	if (!reportId) return;
	if (!selectedActionsWithPatch || selectedActionsWithPatch.length === 0) {
		applyActionsError = 'Select at least one action with editable content.';
		return;
	}

		dispatch('reportUpdating', { status: 'start' });
		applyActionsLoading = true;
	applyActionsError = null;

	try {
		const headers = {
			'Content-Type': 'application/json',
			...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
		};

		const response = await fetch(`${API_URL}/api/reports/${reportId}/apply-actions`, {
			method: 'POST',
			headers,
			body: JSON.stringify({
				actions: selectedActionsWithPatch.map((action) => ({
					id: action.id,
					title: action.title ?? '',
					details: action.details ?? '',
					patch: getActionPatch(action)
				}))
			})
		});

		const data = await response.json();
		if (!response.ok || !data.success) {
			applyActionsError = data.error || `Failed to apply actions (status ${response.status})`;
			return;
		}

		if (data.report?.report_content) {
			reportContent = data.report.report_content;
			dispatch('reportUpdated', { report: data.report });
			
			// Track applied action IDs so they don't appear again
			const appliedIds = selectedActionsWithPatch.map((action) => action.id);
			appliedActionIds = [...appliedActionIds, ...appliedIds];
			saveCacheEntry();
		}

		resetActionSelections();
	} catch (err) {
		applyActionsError = err instanceof Error ? err.message : String(err);
	} finally {
		applyActionsLoading = false;
		dispatch('reportUpdating', { status: 'end', error: applyActionsError });
	}
}
	
function hasActionPatch(action: SuggestedAction): boolean {
	return Boolean(action?.patch && action.patch.trim().length > 0);
}

function getActionPatch(action: SuggestedAction): string {
	return action?.patch ? action.patch.trim() : '';
}

function normalizeQuestionPrompt(prompt: string | undefined): string {
	if (!prompt) return '';
	return prompt.replace(/^\s*(?:\d+[\).\s]+|[-•]\s*)/, '').trim();
}

$: summary = completenessAnalysis?.structured?.summary ?? null;
$: reviewQuestions = completenessAnalysis?.structured?.questions
	? completenessAnalysis.structured.questions.map((question, index) => ({
			...question,
			prompt: normalizeQuestionPrompt(question.prompt) || question.prompt || `Question ${index + 1}`
	  }))
	: [];
$: availableSuggestedActions = completenessAnalysis?.structured?.suggested_actions
	? completenessAnalysis.structured.suggested_actions.filter((action) => !appliedActionIds.includes(action.id))
	: [];
$: selectedActions = availableSuggestedActions.filter((action) =>
	selectedActionIds.includes(action.id)
);
$: selectedActionsWithPatch = selectedActions.filter((action) => hasActionPatch(action));
$: canApplySelectedActions = selectedActionsWithPatch.length > 0 && !applyActionsLoading;

	function handleKeyPress(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendChatMessage();
		}
	}
	
	// Comparison functions
	async function addPriorReport() {
		if (!newPrior.text.trim() || !newPrior.date || !newPrior.scan_type.trim()) return;
		
		if (editingPriorIndex !== null) {
			// Update existing report
			priorReports[editingPriorIndex] = {
				text: newPrior.text,
				date: newPrior.date,
				scan_type: newPrior.scan_type.trim()
			};
			editingPriorIndex = null;
		} else {
			// Add new report
			priorReports = [...priorReports, { 
				text: newPrior.text, 
				date: newPrior.date,
				scan_type: newPrior.scan_type.trim()
			}];
		}
		
		newPrior = { text: '', date: '', scan_type: '' };
		showAddPriorModal = false;
	}
	
	function editPriorReport(index: number) {
		const prior = priorReports[index];
		newPrior = {
			text: prior.text,
			date: prior.date,
			scan_type: prior.scan_type || ''
		};
		editingPriorIndex = index;
		showAddPriorModal = true;
	}
	
	function removePriorReport(index: number) {
		priorReports = priorReports.filter((_, i) => i !== index);
		if (editingPriorIndex === index) {
			editingPriorIndex = null;
			showAddPriorModal = false;
		} else if (editingPriorIndex !== null && editingPriorIndex > index) {
			editingPriorIndex--;
		}
	}
	
	function cancelEdit() {
		newPrior = { text: '', date: '', scan_type: '' };
		editingPriorIndex = null;
		showAddPriorModal = false;
	}
	
	async function runComparison() {
		if (!reportId || priorReports.length === 0) {
			return;
		}
		comparing = true;
		error = null;
		revisedReportApplied = false;
		try {
			const response = await fetch(`${API_URL}/api/reports/${reportId}/compare`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({ prior_reports: priorReports })
			});
			
			if (!response.ok) {
				const errorText = await response.text();
				error = `HTTP ${response.status}: ${errorText}`;
				return;
			}
			
			const data = await response.json();
			
			if (data.success && data.comparison) {
				comparisonResult = data.comparison;
			} else {
				logger.error('runComparison: API returned error:', data.error);
				error = data.error || 'Comparison analysis failed';
			}
		} catch (err) {
			logger.error('runComparison: Exception:', err);
			error = `Failed to compare: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			comparing = false;
		}
	}
	
	async function applyRevisedReport() {
		if (!comparisonResult?.revised_report || applyRevisedReportLoading || revisedReportApplied) return;
		
		applyRevisedReportLoading = true;
		dispatch('reportUpdating', { status: 'start' });
		
		try {
			const response = await fetch(`${API_URL}/api/reports/${reportId}/apply-comparison`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'Authorization': `Bearer ${$token}`
				},
				body: JSON.stringify({ revised_report: comparisonResult.revised_report })
			});
			const data = await response.json();
			if (data.success) {
				revisedReportApplied = true;
				dispatch('reportUpdated', { report: { report_content: data.updated_content } });
			} else {
				error = data.error || 'Failed to apply revised report';
			}
		} catch (err) {
			logger.error('Apply failed:', err);
			error = `Failed to apply: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			applyRevisedReportLoading = false;
			dispatch('reportUpdating', { status: 'end' });
		}
	}
	
	function clearComparison() {
		comparisonResult = null;
		priorReports = [];
		newPrior = { text: '', date: '', scan_type: '' };
		applyRevisedReportLoading = false;
		revisedReportApplied = false;
	}
	
onDestroy(() => {
	stopCompletenessPoll();
});

	// Apply cache when report changes
	$: if (reportId !== lastReportId) {
		if (!reportId) {
			resetAllSidebarState();
		} else {
			// Switching to a different report - save current state first
			// IMPORTANT: Save cache using lastReportId BEFORE reportId changes
			if (lastReportId) {
				saveCacheEntry(lastReportId);
			}
			
			// ALWAYS reset state when switching reports to prevent stale data
			hasLoaded = false;
			
			// Try to load cached data for the new report
			const cachedData = enhancementCache.get(reportId);
			if (cachedData && applyCacheEntry(cachedData)) {
				// Cache applied successfully - no need to load from API
				hasLoaded = true;
				loading = false;
			} else {
				// No cache found - prepare for loading
				// Set loading state BEFORE resetting to show loading UI immediately
				loading = true;
				resetAllSidebarState();
				
				// Always load enhancements when reportId changes (auto-load in background)
				// Use force=true to bypass cache check since we already checked above
				loadEnhancements(true);
			}
		}
		lastReportId = reportId;
	}
	
	// Load enhancements when sidebar becomes visible
	$: if ((visible || autoLoad) && reportId && !loading && !hasLoaded) {
		loadEnhancements();
	}

// Manage polling based on visibility or auto-loading
$: if ((visible || autoLoad) && completenessPending) {
	startCompletenessPoll();
} else if (!visible && !autoLoad) {
	stopCompletenessPoll();
}
	
	import { createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	
	// Emit enhancement state updates for dock/cards
	$: {
		dispatch('enhancementState', {
			guidelinesCount: guidelinesData.length,
			isLoading: loading,
			hasError: Boolean(error),
			reportId
		});
	}
</script>

{#if visible}
	<div class="fixed right-0 top-0 h-full {isExpanded ? 'w-[50vw]' : 'w-96'} bg-gray-900 border-l border-gray-700 shadow-2xl z-[10000] flex flex-col transition-all duration-300 ease-in-out">
		<!-- Header -->
		<div class="p-4 border-b border-gray-700">
			<div class="flex items-center justify-between mb-4 gap-3">
				<div class="flex items-center gap-3">
					<!-- Copilot Icon -->
					<img src={pilotIcon} alt="Copilot" class="w-9 h-9" />
					<h2 class="text-2xl font-bold text-white">Copilot</h2>
				</div>
				<div class="flex items-center gap-2">
					<button
						type="button"
						onclick={() => isExpanded = !isExpanded}
						class="p-1 text-gray-400 hover:text-white transition-colors"
						title={isExpanded ? "Collapse sidebar" : "Expand sidebar"}
					>
						{#if isExpanded}
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7" />
							</svg>
						{:else}
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
							</svg>
						{/if}
					</button>
					<button
						type="button"
						onclick={() => dispatch('openVersionHistory')}
						class="px-3 py-1.5 text-xs font-medium rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
						title="Open version history"
						disabled={!reportId || !historyAvailable}
					>
						Version History
					</button>
					<button
						onclick={() => dispatch('close')}
						class="p-1 text-gray-400 hover:text-white transition-colors"
						aria-label="Close sidebar"
						title="Close sidebar"
					>
						<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>
			</div>
			
			<!-- Tabs -->
			<div class="flex gap-2">
				<button
					onclick={() => activeTab = 'guidelines'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'guidelines' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Guidelines
				</button>
				<!-- Analysis tab hidden temporarily -->
				<button
					onclick={() => activeTab = 'analysis'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'analysis' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
					style="display: none;"
				>
					Analysis
				</button>
				<button
					onclick={() => activeTab = 'comparison'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'comparison' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Comparison
				</button>
				<button
					onclick={() => activeTab = 'chat'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'chat' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Chat
				</button>
			</div>
		</div>
		
		<!-- Content -->
		<div class="flex-1 overflow-y-auto p-4">
			{#if loading}
				<div class="flex items-center justify-center h-full">
					<div class="text-gray-400">Loading enhancements...</div>
				</div>
			{:else if error}
				<div class="border border-red-500/30 bg-red-500/10 rounded-lg p-4">
					<p class="text-red-400 font-medium mb-1">Error</p>
					<p class="text-red-300 text-sm">{error}</p>
					<button
						onclick={() => loadEnhancements(true)}
						class="mt-2 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg transition-colors"
					>
						Retry
					</button>
				</div>
			{:else if activeTab === 'guidelines'}
				{#if guidelinesData.length === 0}
					<div class="text-gray-400 text-center py-8">
						No guidelines found for this report.
					</div>
				{:else}
					<div class="space-y-4">
						{#each guidelinesData as guideline, idx}
							{@const guidelineKey = `guideline-${idx}`}
							{@const isExpanded = guidelinesExpanded[guidelineKey] !== false}
							<div class="border border-gray-700 rounded-lg bg-gray-800/50 overflow-hidden">
								<button
									type="button"
									onclick={() => guidelinesExpanded[guidelineKey] = !isExpanded}
									class="w-full flex items-center justify-between p-4 text-left hover:bg-gray-800/70 transition-colors"
								>
									<h3 class="text-lg font-semibold text-white flex-1">
										{guideline.finding.finding}
									</h3>
									<svg
										class="w-5 h-5 text-gray-400 transition-transform flex-shrink-0 ml-2 {isExpanded ? 'rotate-180' : ''}"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
									</svg>
								</button>
								
								{#if isExpanded}
									<div class="px-4 pb-4">
										<!-- Diagnostic Overview -->
										{#if guideline.diagnostic_overview}
											<div class="prose prose-invert prose-sm max-w-none mb-4
												prose-headings:text-white prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-2
												prose-p:text-gray-300 prose-p:leading-relaxed prose-p:my-2
												prose-strong:text-white prose-strong:font-semibold
												prose-ul:my-2 prose-ul:pl-5 prose-ul:space-y-1.5 prose-ul:list-disc
												prose-ol:my-2 prose-ol:pl-5 prose-ol:space-y-1.5 prose-ol:list-decimal
												prose-li:text-gray-300 prose-li:leading-relaxed prose-li:pl-1
												prose-code:text-purple-300 prose-code:bg-gray-800/50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
												{@html renderMarkdown(guideline.diagnostic_overview)}
											</div>
										{/if}

										<!-- Classification Systems -->
										{#if guideline.classification_systems && guideline.classification_systems.length > 0}
											<div class="mb-4">
												<h4 class="text-sm font-semibold text-white mb-2">Classification & Grading</h4>
												<div class="space-y-2">
													{#each guideline.classification_systems as system}
														<div class="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
															<div class="font-medium text-purple-300 text-sm mb-1">{system.name}</div>
															<div class="text-xs text-gray-400 mb-1.5">{system.grade_or_category}</div>
															<div class="text-sm text-gray-300">{system.criteria}</div>
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Measurement Protocols -->
										{#if guideline.measurement_protocols && guideline.measurement_protocols.length > 0}
											<div class="mb-4">
												<h4 class="text-sm font-semibold text-white mb-2">Measurement Protocols</h4>
												<div class="space-y-2">
													{#each guideline.measurement_protocols as measure}
														<div class="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
															<div class="font-medium text-blue-300 text-sm mb-1">{measure.parameter}</div>
															<div class="text-sm text-gray-300 mb-2">{measure.technique}</div>
															{#if measure.normal_range}
																<div class="text-xs text-gray-400">Normal: {measure.normal_range}</div>
															{/if}
															{#if measure.threshold}
																<div class="text-xs text-gray-400">Threshold: {measure.threshold}</div>
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Imaging Characteristics -->
										{#if guideline.imaging_characteristics && guideline.imaging_characteristics.length > 0}
											<div class="mb-4">
												<h4 class="text-sm font-semibold text-white mb-2">Key Imaging Features</h4>
												<div class="space-y-2">
													{#each guideline.imaging_characteristics as char}
														<div class="text-sm">
															<span class="font-medium text-green-300">{char.feature}:</span>
															<span class="text-gray-300"> {char.description}</span>
															<span class="text-gray-400 italic"> ({char.significance})</span>
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Differential Diagnoses -->
										{#if guideline.differential_diagnoses && guideline.differential_diagnoses.length > 0}
											<div class="mb-4">
												<h4 class="text-sm font-semibold text-white mb-2">Differential Diagnoses</h4>
												<div class="space-y-2">
													{#each guideline.differential_diagnoses as ddx}
														<div class="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
															<div class="font-medium text-yellow-300 text-sm mb-1">{ddx.diagnosis}</div>
															<div class="text-sm text-gray-300 mb-1">{ddx.imaging_features}</div>
															{#if ddx.supporting_findings}
																<div class="text-xs text-gray-400">Supporting: {ddx.supporting_findings}</div>
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Follow-up Imaging -->
										{#if guideline.follow_up_imaging && guideline.follow_up_imaging.length > 0}
											<div class="mb-4">
												<h4 class="text-sm font-semibold text-white mb-2">Follow-up Imaging</h4>
												<div class="space-y-2">
													{#each guideline.follow_up_imaging as followup}
														<div class="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
															<div class="font-medium text-orange-300 text-sm mb-1">{followup.indication}</div>
															<div class="text-sm text-gray-300 mb-1">
																{followup.modality}, {followup.timing}
															</div>
															{#if followup.technical_specs}
																<div class="text-xs text-gray-400">Technical: {followup.technical_specs}</div>
															{/if}
														</div>
													{/each}
												</div>
											</div>
										{/if}

										<!-- Fallback to guideline_summary if new fields not present -->
										{#if !guideline.diagnostic_overview && guideline.guideline_summary}
											<div class="prose prose-invert prose-sm max-w-none mb-4
												prose-headings:text-white prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-2
												prose-p:text-gray-300 prose-p:leading-relaxed prose-p:my-2
												prose-strong:text-white prose-strong:font-semibold
												prose-ul:my-2 prose-ul:pl-5 prose-ul:space-y-1.5 prose-ul:list-disc
												prose-ol:my-2 prose-ol:pl-5 prose-ol:space-y-1.5 prose-ol:list-decimal
												prose-li:text-gray-300 prose-li:leading-relaxed prose-li:pl-1
												prose-code:text-purple-300 prose-code:bg-gray-800/50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
												{@html renderMarkdown(guideline.guideline_summary)}
											</div>
										{/if}
										
										{#if guideline.sources && guideline.sources.length > 0}
											<div class="mt-3 pt-3 border-t border-gray-700">
												<p class="text-xs font-medium text-gray-400 mb-2">References:</p>
												<ul class="space-y-1">
													{#each guideline.sources.slice(0, 5) as source (source.url || source.title || Math.random())}
														<li>
															{#if source.url}
																<a
																	href={source.url}
																	target="_blank"
																	rel="noopener noreferrer"
																	class="text-xs text-purple-400 hover:text-purple-300 underline truncate block"
																	title={source.title ?? source.url}
																>
																	{source.title ?? source.url}
																</a>
																{#if source.snippet}
																	<p class="text-[11px] text-gray-500 mt-1 leading-snug">
																		{source.snippet}
																	</p>
																{/if}
															{:else if source.title}
																<span class="text-xs text-purple-400">{source.title}</span>
																{#if source.snippet}
																	<p class="text-[11px] text-gray-500 mt-1 leading-snug">
																		{source.snippet}
																	</p>
																{/if}
															{:else}
																<span class="text-xs text-purple-400">Reference</span>
															{/if}
														</li>
													{/each}
												</ul>
											</div>
										{/if}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			
			<!-- Analysis tab content hidden temporarily -->
			{:else if false && activeTab === 'analysis'}
				{#if completenessPending && !completenessAnalysis}
					<div class="text-gray-400 text-center py-8">
						Running completeness analysis...
					</div>
				{:else if !completenessAnalysis}
					<div class="text-gray-400 text-center py-8">
						No analysis available.
					</div>
				{:else}
					<div class="space-y-3">
						<div class="rounded-lg border border-gray-700/60 bg-gray-900/40">
							<button
								type="button"
								class="w-full flex items-center justify-between px-4 py-3 text-left text-white hover:bg-gray-800/60 transition-colors"
								onclick={() => toggleSection('summary')}
								aria-expanded={sectionsExpanded.summary}
							>
								<span class="text-sm font-semibold uppercase tracking-wide">Summary</span>
								<svg
									class="w-4 h-4 text-gray-300 transition-transform transform {sectionsExpanded.summary ? 'rotate-180' : ''}"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							{#if sectionsExpanded.summary}
								<div class="px-4 pb-4">
									{#if summary?.title}
										<p class="text-xs uppercase tracking-wide text-purple-300 font-semibold mb-2">
											{summary.title}
										</p>
									{/if}
									<div class="prose prose-invert max-w-none text-sm text-gray-300">
										{@html renderMarkdown(summary?.details ?? completenessAnalysis.analysis ?? '')}
									</div>
								</div>
							{/if}
						</div>

						<div class="rounded-lg border border-gray-700/60 bg-gray-900/40">
							<button
								type="button"
								class="w-full flex items-center justify-between px-4 py-3 text-left text-white hover:bg-gray-800/60 transition-colors"
								onclick={() => toggleSection('questions')}
								aria-expanded={sectionsExpanded.questions}
							>
								<span class="text-sm font-semibold uppercase tracking-wide">Review Questions</span>
								<svg
									class="w-4 h-4 text-gray-300 transition-transform transform {sectionsExpanded.questions ? 'rotate-180' : ''}"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							{#if sectionsExpanded.questions}
								<div class="px-4 pb-4">
									{#if reviewQuestions.length > 0}
										<ol class="space-y-2 text-sm text-gray-300 list-decimal list-inside">
											{#each reviewQuestions as question, index (question.id || index)}
												<li class="pl-1">
													<span>{question.prompt}</span>
												</li>
											{/each}
										</ol>
									{:else}
										<p class="text-sm text-gray-400">No outstanding review questions identified.</p>
									{/if}
								</div>
							{/if}
						</div>

						<div class="rounded-lg border border-gray-700/60 bg-gray-900/40">
							<button
								type="button"
								class="w-full flex items-center justify-between px-4 py-3 text-left text-white hover:bg-gray-800/60 transition-colors"
								onclick={() => toggleSection('actions')}
								aria-expanded={sectionsExpanded.actions}
							>
								<span class="text-sm font-semibold uppercase tracking-wide">Suggested Actions</span>
								<svg
									class="w-4 h-4 text-gray-300 transition-transform transform {sectionsExpanded.actions ? 'rotate-180' : ''}"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
								</svg>
							</button>
							{#if sectionsExpanded.actions}
								<div class="px-4 pb-4 space-y-3">
									{#if availableSuggestedActions.length === 0}
										<p class="text-sm text-gray-400">No additional actions recommended.</p>
									{:else}
										{#if applyActionsLoading}
											<p class="text-xs text-gray-400">Applying...</p>
										{/if}
										{#if applyActionsError}
											<div class="border border-red-500/30 bg-red-500/10 text-xs text-red-300 rounded-lg px-3 py-2">
												{applyActionsError}
											</div>
										{/if}

										<ul class="space-y-3">
											{#each availableSuggestedActions as action (action.id)}
												{#if hasActionPatch(action)}
													<li class="rounded-lg border border-gray-700/60 bg-gray-900/50 p-3 transition-colors hover:border-purple-600/60">
														<label class="flex items-start gap-3 cursor-pointer">
															<input
																type="checkbox"
																class="mt-1.5 accent-purple-600 focus:ring-purple-500 flex-shrink-0"
																checked={selectedActionIds.includes(action.id)}
																onchange={() => toggleActionSelection(action)}
															/>
															<div class="space-y-2 min-w-0 flex-1">
																<p class="text-sm font-semibold text-white break-words">
																	{action.title || 'Suggested action'}
																</p>
																<p class="text-sm text-gray-300 break-words">{action.details}</p>
																<pre class="bg-gray-950/70 border border-gray-800 rounded-md text-xs text-gray-200 p-3 overflow-x-auto whitespace-pre-wrap break-words max-w-full">
{getActionPatch(action)}
																</pre>
															</div>
														</label>
													</li>
												{:else}
													<li class="rounded-lg border border-gray-700/60 bg-gray-900/50 p-3">
														<div class="space-y-2">
															<p class="text-sm font-semibold text-white break-words">
																{action.title || 'Suggested action'}
															</p>
															<p class="text-sm text-gray-300 break-words">{action.details}</p>
															<p class="text-xs text-gray-500 italic">No automatic patch provided.</p>
														</div>
													</li>
												{/if}
											{/each}
										</ul>

										<button
											type="button"
											class="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:text-gray-400 text-white text-sm font-medium rounded-lg transition-colors"
											onclick={applySelectedActions}
											disabled={!canApplySelectedActions}
										>
											{applyActionsLoading ? 'Applying...' : 'Apply Selected Actions'}
										</button>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/if}
			
			{:else if activeTab === 'comparison'}
				<div class="space-y-4">
					{#if priorReports.length === 0}
						<div class="text-center py-8">
							<p class="text-gray-400 mb-4">Add prior reports to analyse interval changes</p>
							<button class="btn-primary" onclick={() => showAddPriorModal = true}>
								+ Add Prior Report
							</button>
						</div>
					{:else}
						<div class="bg-gray-800/50 rounded-lg p-3 space-y-2">
							<div class="flex items-center justify-between">
								<span class="text-sm text-gray-400">{priorReports.length} prior report(s) loaded</span>
								<button class="btn-sm" onclick={() => showAddPriorModal = true}>+ Add Another</button>
							</div>
							<div class="space-y-2">
								{#each priorReports as prior, idx}
									<div class="flex items-center justify-between bg-gray-900/50 rounded p-2">
										<span class="text-sm text-gray-300">
											{formatDateUK(prior.date)}{prior.scan_type ? ` - ${prior.scan_type}` : ''}
										</span>
										<div class="flex gap-2">
											<button 
												onclick={() => editPriorReport(idx)}
												class="text-blue-400 hover:text-blue-300 text-xs px-2 py-1"
												title="Edit this prior report"
											>
												✏️ Edit
											</button>
											<button 
												onclick={() => removePriorReport(idx)}
												class="text-red-400 hover:text-red-300 text-xs px-2 py-1"
												title="Remove this prior report"
											>
												🗑️ Remove
											</button>
										</div>
									</div>
								{/each}
							</div>
						</div>
						
						{#if !comparisonResult}
							<button class="btn-primary w-full" onclick={runComparison} disabled={comparing}>
								{comparing ? '⏳ Analysing...' : '🔍 Analyse Interval Changes'}
							</button>
						{:else}
							<!-- Summary -->
							<div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 mb-4">
								<h3 class="text-sm font-semibold text-blue-300 mb-2">📊 Summary</h3>
								<p class="text-sm text-gray-300">{comparisonResult.summary}</p>
							</div>
							
							<!-- Clinical Analysis Section -->
							{@const changedFindings = comparisonResult.findings.filter(f => f.status === 'changed')}
							{@const newFindings = comparisonResult.findings.filter(f => f.status === 'new')}
							{@const stableFindings = comparisonResult.findings.filter(f => f.status === 'stable')}
							
							<div class="mb-4">
								<h3 class="text-sm font-semibold text-white mb-3">🔍 Clinical Analysis</h3>
								
								<!-- New Findings (Priority 1 - Most Important) -->
								{#if newFindings.length > 0}
									{@const hasUrgent = newFindings.some(f => 
										f.assessment.toLowerCase().includes('concerning') || 
										f.assessment.toLowerCase().includes('urgent') ||
										f.assessment.toLowerCase().includes('immediate')
									)}
									<details open class="bg-red-500/10 border border-red-500/30 rounded-lg mb-3">
										<summary class="p-3 cursor-pointer text-sm font-medium flex items-center gap-2 list-none">
											<svg class="w-4 h-4 text-red-300 transition-transform duration-200 arrow-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
											</svg>
											<span class="text-red-300">🆕 New Findings</span>
											<span class="text-xs bg-red-500/30 text-red-200 px-2 py-0.5 rounded font-medium">
												{newFindings.length}
											</span>
											{#if hasUrgent}
												<span class="text-xs bg-red-600/50 text-red-100 px-2 py-0.5 rounded font-bold animate-pulse">
													URGENT
												</span>
											{/if}
										</summary>
										<div class="p-3 pt-0 space-y-3">
											{#each newFindings as finding}
												<div class="border-l-2 border-red-500 pl-3 py-2 bg-red-500/5 rounded">
													<!-- Finding Name & Location -->
													<div class="flex items-start justify-between gap-2 mb-1">
														<div class="text-sm font-medium text-white">{finding.name}</div>
														{#if finding.location}
															<div class="text-xs text-red-300/60 shrink-0 bg-red-500/10 px-1.5 py-0.5 rounded">
																{finding.location}
															</div>
														{/if}
													</div>
													
													<!-- Current Measurement (if available) -->
													{#if finding.current_measurement}
														<div class="text-xs mb-2">
															<span class="bg-red-500/20 text-red-200 px-2 py-0.5 rounded">
																Measures: {finding.current_measurement.raw_text}
															</span>
														</div>
													{/if}
													
													<!-- Assessment -->
													<div class="text-sm text-gray-300">{finding.assessment}</div>
												</div>
											{/each}
										</div>
									</details>
								{/if}
								
								<!-- Interval Changes (Priority 2) -->
								{#if changedFindings.length > 0}
									{@const hasSignificant = changedFindings.some(f => 
										f.assessment.toLowerCase().includes('significant') || 
										f.assessment.toLowerCase().includes('concerning') ||
										f.assessment.toLowerCase().includes('progression')
									)}
									<details open class="bg-orange-500/10 border border-orange-500/30 rounded-lg mb-3">
										<summary class="p-3 cursor-pointer text-sm font-medium flex items-center gap-2 list-none">
											<svg class="w-4 h-4 text-orange-300 transition-transform duration-200 arrow-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
											</svg>
											<span class="text-orange-300">📈 Interval Changes</span>
											<span class="text-xs bg-orange-500/30 text-orange-200 px-2 py-0.5 rounded font-medium">
												{changedFindings.length}
											</span>
											{#if hasSignificant}
												<span class="text-xs bg-orange-600/40 text-orange-100 px-2 py-0.5 rounded font-semibold">
													SIGNIFICANT
												</span>
											{/if}
										</summary>
										<div class="p-3 pt-0 space-y-3">
											{#each changedFindings as finding}
												<div class="border-l-2 border-orange-500 pl-3 py-2 bg-orange-500/5 rounded">
													<!-- Finding Name & Location -->
													<div class="flex items-start justify-between gap-2 mb-1">
														<div class="text-sm font-medium text-white">{finding.name}</div>
														{#if finding.location}
															<div class="text-xs text-orange-300/60 shrink-0 bg-orange-500/10 px-1.5 py-0.5 rounded">
																{finding.location}
															</div>
														{/if}
													</div>
													
													<!-- Measurements (Before → After) -->
													{#if finding.prior_measurement || finding.current_measurement}
														<div class="flex items-center gap-2 text-xs mb-2 flex-wrap">
															{#if finding.prior_measurement}
																<span class="bg-gray-800/50 text-gray-400 px-2 py-0.5 rounded">
																	Was: {finding.prior_measurement.raw_text}
																</span>
															{/if}
															{#if finding.prior_measurement && finding.current_measurement}
																<span class="text-orange-400">→</span>
															{/if}
															{#if finding.current_measurement}
																<span class="bg-orange-500/20 text-orange-200 px-2 py-0.5 rounded">
																	Now: {finding.current_measurement.raw_text}
																</span>
															{/if}
														</div>
													{/if}
													
													<!-- Trend (if multiple priors) -->
													{#if finding.trend}
														<div class="text-xs text-gray-400 mb-2 italic border-l-2 border-gray-700 pl-2 py-1 bg-gray-800/30 rounded">
															<span class="text-gray-500 font-semibold">Trend:</span> {finding.trend}
														</div>
													{/if}
													
													<!-- Prior Date (if single prior) -->
													{#if finding.prior_date && !finding.trend}
														<div class="text-xs text-gray-500 mb-1">
															Prior: {finding.prior_date}
														</div>
													{/if}
													
													<!-- Assessment -->
													<div class="text-sm text-gray-300">{finding.assessment}</div>
												</div>
											{/each}
										</div>
									</details>
								{/if}
								
								<!-- Stable Findings (Priority 3 - Least Urgent) -->
								{#if stableFindings.length > 0}
									<details class="bg-green-500/10 border border-green-500/30 rounded-lg mb-3">
										<summary class="p-3 cursor-pointer text-sm font-medium flex items-center gap-2 list-none">
											<svg class="w-4 h-4 text-green-300 transition-transform duration-200 arrow-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
											</svg>
											<span class="text-green-300">✅ Stable</span>
											<span class="text-xs bg-green-500/30 text-green-200 px-2 py-0.5 rounded font-medium">
												{stableFindings.length}
											</span>
										</summary>
										<div class="p-3 pt-0">
											<ul class="text-sm text-gray-300 space-y-1">
												{#each stableFindings as finding}
													<li class="flex items-start gap-2">
														<span class="text-green-500 mt-0.5">•</span>
														<span>{finding.name}</span>
													</li>
												{/each}
											</ul>
										</div>
									</details>
								{/if}
							</div>
							
							<!-- Report Modifications Section -->
							{#if comparisonResult.key_changes?.length > 0}
								<div class="mb-4">
									<h3 class="text-sm font-semibold text-white mb-3">📝 Report Modifications</h3>
									<div class="space-y-3">
										{#each comparisonResult.key_changes as change}
											<div class="bg-gray-800/50 rounded-lg p-3 border border-gray-700">
												<div class="text-xs text-gray-400 mb-2 font-medium">{change.reason}</div>
												<div class="bg-red-500/10 border border-red-500/30 rounded p-2 mb-2">
													<div class="text-xs text-red-400 mb-1">Original:</div>
													<div class="text-sm text-gray-300 line-through">{change.original}</div>
												</div>
												<div class="bg-green-500/10 border border-green-500/30 rounded p-2">
													<div class="text-xs text-green-400 mb-1">Revised:</div>
													<div class="text-sm text-gray-300">{change.revised}</div>
												</div>
											</div>
										{/each}
									</div>
								</div>
							{/if}
							
							<!-- Action Buttons -->
							<div class="border-t border-gray-700 pt-4">
								{#if comparisonResult?.revised_report}
									<button 
										class="btn-secondary w-full mb-2" 
										onclick={() => showRevisedReportPreview = true}
										disabled={applyRevisedReportLoading || revisedReportApplied}
									>
										👁️ Preview Full Revised Report
									</button>
								{/if}
								
								<div class="relative">
									{#if applyRevisedReportLoading}
										<div class="absolute inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-10 rounded-lg">
											<div class="flex items-center gap-3 text-gray-200 text-sm">
												<div class="w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
												<span>Applying revised report...</span>
											</div>
										</div>
									{/if}
									<button 
										class="btn-primary w-full mb-2 disabled:opacity-50 disabled:cursor-not-allowed" 
										onclick={applyRevisedReport}
										disabled={applyRevisedReportLoading || revisedReportApplied}
									>
										{revisedReportApplied ? '✅ Report Applied' : '✅ Apply Revised Report'}
									</button>
								</div>
								<p class="text-xs text-gray-500 text-center mb-3">
									Updates report and creates new version in history
								</p>
								<button class="btn-secondary w-full" onclick={clearComparison} disabled={applyRevisedReportLoading}>
									🔄 Start Over
								</button>
							</div>
						{/if}
					{/if}
				</div>
			
			{:else if activeTab === 'chat'}
				<div class="flex flex-col h-full">
					<!-- Messages -->
					<div class="flex-1 overflow-y-auto mb-4 space-y-4">
						{#if chatMessages.length === 0}
							<div class="text-gray-400 text-center py-8">
								Ask questions about the report or request improvements.
							</div>
						{:else}
							{#each chatMessages as msg, index}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									<div class="max-w-[80%] {msg.role === 'user' ? 'bg-purple-600' : msg.error ? 'bg-red-500/20 border border-red-500/30' : 'bg-gray-800'} rounded-lg p-3">
										<div class="prose prose-invert max-w-none text-sm {msg.error ? 'text-red-300' : 'text-gray-100'}">
											{@html renderMarkdown(msg.content)}
										</div>
										{#if msg.editProposal}
											<div class="mt-3 pt-3 border-t border-gray-700">
												<div class="bg-gray-900/50 rounded p-2 mb-2 border border-gray-700/50">
													<div class="flex items-center justify-between mb-1">
														<p class="text-xs font-medium text-gray-400">Proposed Change:</p>
														<button
															onclick={() => expandedEditProposalIndex = index}
															class="text-xs text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1"
															title="View in expanded modal"
														>
															<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
																<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
															</svg>
															Expand
														</button>
													</div>
													<div class="text-xs text-gray-300 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono bg-black/20 p-2 rounded">
														{msg.editProposal}
													</div>
												</div>
												<button
													onclick={() => {
														updateReportContent(msg.editProposal, 'chat');
														msg.applied = true;
														chatMessages = [...chatMessages]; // Trigger reactivity
													}}
													disabled={msg.applied}
													class="w-full px-3 py-1.5 {msg.applied ? 'bg-green-600/50 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-700'} text-white text-xs font-medium rounded transition-colors flex items-center justify-center gap-2"
												>
													{#if msg.applied}
														<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
															<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
														</svg>
														Applied
													{:else}
														<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
															<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
														</svg>
														Apply Change
													{/if}
												</button>
											</div>
										{/if}
										{#if msg.sources && msg.sources.length > 0}
											<div class="mt-2 pt-2 border-t border-gray-700">
												<p class="text-xs font-medium text-gray-400 mb-1">Sources:</p>
												<ul class="space-y-1">
													{#each msg.sources as source}
														<li>
															<a
																href={source}
																target="_blank"
																rel="noopener noreferrer"
																class="text-xs text-purple-400 hover:text-purple-300 underline truncate block"
															>
																{source}
															</a>
														</li>
													{/each}
												</ul>
											</div>
										{/if}
									</div>
								</div>
							{/each}
						{/if}
						
						{#if chatLoading}
							<div class="flex justify-start">
								<div class="bg-gray-800 rounded-lg p-3">
									<div class="text-sm text-gray-400">Thinking...</div>
								</div>
							</div>
						{/if}
					</div>
					
					<!-- Input -->
					<div class="border-t border-gray-700 pt-4">
						<div class="flex gap-2">
							<textarea
								bind:value={chatInput}
								onkeypress={handleKeyPress}
								placeholder="Ask about the report..."
								class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 resize-none"
								rows="2"
								disabled={chatLoading || !reportId}
							></textarea>
							<button
								onclick={sendChatMessage}
								disabled={!chatInput.trim() || chatLoading || !reportId}
								class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
							>
								Send
							</button>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

<!-- Edit Proposal Modal -->
{#if expandedEditProposalIndex !== null && chatMessages[expandedEditProposalIndex]?.editProposal}
	{@const expandedMsg = chatMessages[expandedEditProposalIndex]}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-[20000]" onclick={() => expandedEditProposalIndex = null}>
		<div class="bg-gray-900 rounded-lg border border-gray-700 w-[90vw] max-w-4xl max-h-[90vh] overflow-hidden flex flex-col" onclick={(e) => e.stopPropagation()}>
			<div class="p-4 border-b border-gray-700 flex items-center justify-between">
				<h3 class="text-lg font-semibold text-white">Proposed Change</h3>
				<button 
					onclick={() => expandedEditProposalIndex = null} 
					class="text-gray-400 hover:text-white transition-colors"
					aria-label="Close modal"
				>
					<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			<div class="flex-1 overflow-y-auto p-4">
				<div class="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
					<pre class="text-sm text-gray-300 whitespace-pre-wrap font-mono bg-black/20 p-4 rounded overflow-x-auto">{expandedMsg.editProposal}</pre>
				</div>
			</div>
			<div class="p-4 border-t border-gray-700 flex gap-3 justify-end">
				<button 
					class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
					onclick={() => expandedEditProposalIndex = null}
				>
					Close
				</button>
				<button
					onclick={() => {
						updateReportContent(expandedMsg.editProposal, 'chat');
						expandedMsg.applied = true;
						chatMessages = [...chatMessages]; // Trigger reactivity
						expandedEditProposalIndex = null;
					}}
					disabled={expandedMsg.applied}
					class="px-4 py-2 {expandedMsg.applied ? 'bg-green-600/50 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-700'} text-white rounded-lg transition-colors flex items-center gap-2"
				>
					{#if expandedMsg.applied}
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
						</svg>
						Applied
					{:else}
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
						</svg>
						Apply Change
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Add Prior Report Modal -->
{#if showAddPriorModal}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-[20000]" onclick={cancelEdit}>
		<div class="bg-gray-900 rounded-lg border border-gray-700 w-[600px] max-h-[80vh] overflow-y-auto" onclick={(e) => e.stopPropagation()}>
			<div class="p-4 border-b border-gray-700 flex items-center justify-between">
				<h3 class="text-lg font-semibold text-white">{editingPriorIndex !== null ? 'Edit Prior Report' : 'Add Prior Report'}</h3>
				<button onclick={cancelEdit} class="text-gray-400 hover:text-white">×</button>
			</div>
			<div class="p-4 space-y-4">
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Study Date *</label>
					<div class="relative">
						<input 
							type="date" 
							bind:value={newPrior.date} 
							bind:this={studyDateInput}
							class="input-dark w-full date-input pr-10" 
							required 
							style="color-scheme: dark;"
						/>
						<button
							type="button"
							onclick={() => {
								if (studyDateInput) {
									studyDateInput.showPicker?.() || studyDateInput.click();
								}
							}}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-white hover:text-gray-200 transition-colors cursor-pointer z-10"
							aria-label="Open calendar"
							tabindex="-1"
						>
							<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
							</svg>
						</button>
					</div>
				</div>
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Scan Type *</label>
					<input 
						type="text" 
						bind:value={newPrior.scan_type} 
						placeholder="e.g., CT Abdomen and Pelvis with IV contrast" 
						class="input-dark w-full" 
						required
					/>
				</div>
				<div>
					<label class="block text-sm font-medium text-gray-300 mb-2">Report Text *</label>
					<textarea bind:value={newPrior.text} placeholder="Paste prior report here..." class="input-dark w-full" rows="12"></textarea>
					<span class="text-xs text-gray-500">{newPrior.text.length} characters</span>
				</div>
			</div>
			<div class="p-4 border-t border-gray-700 flex gap-3 justify-end">
				<button class="btn-secondary" onclick={cancelEdit}>Cancel</button>
				<button class="btn-primary" onclick={addPriorReport} disabled={!newPrior.text.trim() || !newPrior.date || !newPrior.scan_type.trim()}>
					{editingPriorIndex !== null ? 'Update Report' : 'Add Report'}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Revised Report Preview Modal -->
{#if showRevisedReportPreview && comparisonResult?.revised_report}
	<div class="fixed inset-0 bg-black/50 flex items-center justify-center z-[20000]" onclick={() => showRevisedReportPreview = false}>
		<div class="bg-gray-900 rounded-lg border border-gray-700 w-[90vw] max-w-5xl max-h-[90vh] overflow-hidden flex flex-col" onclick={(e) => e.stopPropagation()}>
			<div class="p-4 border-b border-gray-700 flex items-center justify-between">
				<h3 class="text-lg font-semibold text-white">Preview: Revised Report</h3>
				<button 
					onclick={() => showRevisedReportPreview = false} 
					class="text-gray-400 hover:text-white transition-colors"
					aria-label="Close modal"
				>
					<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>
			<div class="flex-1 overflow-y-auto p-6">
				<div class="prose prose-invert max-w-none
					prose-headings:text-white prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-3
					prose-p:text-gray-300 prose-p:leading-relaxed prose-p:my-3
					prose-strong:text-white prose-strong:font-semibold
					prose-ul:my-3 prose-ul:pl-5 prose-ul:space-y-2 prose-ul:list-disc
					prose-ol:my-3 prose-ol:pl-5 prose-ol:space-y-2 prose-ol:list-decimal
					prose-li:text-gray-300 prose-li:leading-relaxed prose-li:pl-1 prose-li:my-1
					prose-code:text-purple-300 prose-code:bg-gray-800/50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded
					prose-pre:bg-transparent prose-pre:text-gray-300 prose-pre:p-0 prose-pre:whitespace-pre-wrap">
					{@html renderMarkdown(comparisonResult.revised_report)}
				</div>
			</div>
			<div class="p-4 border-t border-gray-700 flex gap-3 justify-end">
				<button 
					class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
					onclick={() => showRevisedReportPreview = false}
				>
					Close
				</button>
				<button
					onclick={() => {
						showRevisedReportPreview = false;
						applyRevisedReport();
					}}
					disabled={applyRevisedReportLoading || revisedReportApplied}
					class="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2"
				>
					{#if applyRevisedReportLoading}
						<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
						Applying...
					{:else if revisedReportApplied}
						✅ Report Applied
					{:else}
						✅ Apply This Report
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Rotate arrow icon when details is open */
	details[open] summary .arrow-icon {
		transform: rotate(90deg);
	}
</style>
