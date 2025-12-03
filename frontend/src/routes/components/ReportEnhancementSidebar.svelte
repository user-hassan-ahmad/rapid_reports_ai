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
	};
	
	const enhancementCache = new Map<string, EnhancementCacheEntry>();
</script>

<script lang="ts">
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import { onDestroy } from 'svelte';
	import pilotIcon from '$lib/assets/pilot.png';
	import { API_URL } from '$lib/config';
	
	export let reportId: string | null = null;
	export let reportContent: string = '';
	export let visible: boolean = false;
	export let autoLoad: boolean = false;
	export let historyAvailable: boolean = false;
	export let reportVersion: number = 0; // Increment this to force reload
	
	let activeTab: 'guidelines' | 'analysis' | 'chat' = 'guidelines';
	let loading = false;
	let error: string | null = null;
	let hasLoaded = false;
	let lastReportId: string | null = null;
	
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
	
	function saveCacheEntry(): void {
		if (!reportId) return;
		enhancementCache.set(reportId, {
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
	
	function invalidateCache(): void {
		if (reportId) {
			enhancementCache.delete(reportId);
		}
	completenessPending = false;
	completenessAnalysis = null;
	stopCompletenessPoll();
	resetActionSelections();
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
			console.error('pollCompleteness: HTTP error', response.status);
			return;
		}
		const data = await response.json();
		if (reportId !== currentReport) {
			return;
		}
		if (!data.success) {
			console.error('pollCompleteness: API returned error', data.error);
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
		console.error('pollCompleteness: Exception', err);
	}
}

function startCompletenessPoll() {
	if (completenessPollTimer || !reportId) return;
	pollCompleteness();
	completenessPollTimer = setInterval(pollCompleteness, COMPLETENESS_POLL_INTERVAL);
	}
	
function renderMarkdown(md: string) {
		if (!md) return '';
		
		// Preprocess: Fix inline bullet points (• or -) that should be list items
		// Convert "• Item1 • Item2" or ". • Item" to proper markdown lists
		let processed = md;
		
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
			console.error('loadEnhancements: No reportId available');
			return;
		}
		
		if (!force) {
			const cached = enhancementCache.get(reportId);
			if (cached) {
				console.log('loadEnhancements: Using cached data for reportId:', reportId);
				applyCacheEntry(cached);
				return;
			}
		} else {
			invalidateCache();
			hasLoaded = false;
		}
		
		console.log('loadEnhancements: Starting for reportId:', reportId);
		loading = true;
		error = null;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};
			
			console.log('loadEnhancements: Calling API...', `${API_URL}/api/reports/${reportId}/enhance`);
			
			// Add a longer timeout for this API call (enhancement can take 30-60 seconds)
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minutes
			
			let response: Response;
			try {
				response = await fetch(`${API_URL}/api/reports/${reportId}/enhance`, {
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
					console.error('loadEnhancements: Request timeout');
					loading = false;
					return;
				} else {
					throw fetchErr;
				}
			}
			
			console.log('loadEnhancements: Response status:', response.status);
			
			if (!response.ok) {
				const errorText = await response.text();
				console.error('loadEnhancements: HTTP error:', response.status, errorText);
				error = `HTTP ${response.status}: ${errorText}`;
				loading = false;
				return;
			}
			
			let data: any;
			try {
				data = await response.json();
				console.log('loadEnhancements: Response data:', data);
			} catch (jsonErr) {
				// If connection reset happens after response starts, we might have partial data
				// Try to continue if we have status 200
				if (response.status === 200) {
					console.warn('loadEnhancements: JSON parse error but status 200:', jsonErr);
					const text = await response.text().catch(() => '');
					console.warn('loadEnhancements: Response text:', text.substring(0, 200));
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
				console.log('loadEnhancements: Success - findings:', findings.length, 'guidelines:', guidelinesData.length, 'completeness:', !!completenessAnalysis, 'pending:', completenessPending);
				if (completenessPending) {
					startCompletenessPoll();
				} else {
					stopCompletenessPoll();
				}
				resetActionSelections();
				saveCacheEntry();
				hasLoaded = true;
			} else if (data && !data.success) {
				error = data.error || 'Failed to load enhancements';
				console.error('loadEnhancements: API returned error:', error);
				if (data.traceback) {
					console.error('Backend traceback:', data.traceback);
				}
				completenessPending = false;
				stopCompletenessPoll();
			} else {
				error = 'No data received from server';
				console.error('loadEnhancements: No data in response');
				completenessPending = false;
				stopCompletenessPoll();
			}
		} catch (err: unknown) {
			// Only set error if we don't already have successful data
			const hasData = findings.length > 0 || guidelinesData.length > 0;
			
			if (err instanceof TypeError && err.message.includes('fetch')) {
				// Network error - but check if we already got the data
				console.error('loadEnhancements: Network error:', err);
				if (!hasData) {
					error = `Network error: ${err.message}. The connection may have been reset, but data was received.`;
				} else {
					console.log('loadEnhancements: Network error but data already loaded, ignoring error');
					error = null; // Clear error if we have data
				}
			} else {
				const errMsg = err instanceof Error ? err.message : String(err);
				if (!hasData) {
					error = `Failed to connect: ${errMsg}`;
				} else {
					console.log('loadEnhancements: Error after data received, ignoring:', errMsg);
					error = null; // Clear error if we have data
				}
				console.error('loadEnhancements: Exception:', err);
			}
			if (!hasData) {
				completenessPending = false;
				stopCompletenessPoll();
			}
		} finally {
			loading = false;
			console.log('loadEnhancements: Finished, loading:', loading, 'findings:', findings.length, 'guidelines:', guidelinesData.length, 'error:', error);
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
				chatMessages.push({
					role: 'assistant',
					content: data.response,
					sources: data.sources || []
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
	
	async function updateReportContent(newContent: string) {
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
				body: JSON.stringify({ content: newContent })
			});
			
			const data = await response.json();
			
			if (data.success) {
				invalidateCache();
				hasLoaded = false;
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
	
onDestroy(() => {
	stopCompletenessPoll();
});

	// Debug logging
	$: {
		console.log('ReportEnhancementSidebar - visible:', visible, 'reportId:', reportId);
	}
	
	// Track last report version to detect changes
	let lastReportVersion = -1;
	
	// Reset hasLoaded when reportVersion changes (form resubmitted)
	$: if (reportVersion !== lastReportVersion) {
		console.log('ReportEnhancementSidebar: reportVersion changed from', lastReportVersion, 'to', reportVersion);
		if (reportId) {
			hasLoaded = false; // Force reload on version change
			invalidateCache(); // Clear cache for current report to force fresh data
		}
		lastReportVersion = reportVersion;
	}
	
	// Apply cache when report changes
	$: if (reportId !== lastReportId) {
		if (!reportId) {
			findings = [];
			guidelinesData = [];
			completenessAnalysis = null;
			chatMessages = [];
			chatInput = '';
			chatLoading = false;
			error = null;
			completenessPending = false;
			appliedActionIds = [];
			stopCompletenessPoll();
			resetActionSelections();
		} else {
			// Switching to a different report - save current state first
			if (lastReportId) {
				saveCacheEntry();
			}
			lastReportId = reportId;
			
			// Try to load cached data for the new report
			if (applyCacheEntry(enhancementCache.get(reportId))) {
				console.log('ReportEnhancementSidebar: Applied cached data for reportId:', reportId);
			} else {
				// No cache found, reset to empty state
				findings = [];
				guidelinesData = [];
				completenessAnalysis = null;
				chatMessages = [];
				chatInput = '';
				error = null;
				completenessPending = false;
				appliedActionIds = [];
				stopCompletenessPoll();
				resetActionSelections();
			}
			
			// Always reset hasLoaded for new reports to force refresh
			hasLoaded = false;
		}
		lastReportId = reportId;
	}
	
	// Load enhancements when sidebar becomes visible
	$: if ((visible || autoLoad) && reportId && !loading && !hasLoaded) {
		console.log(
			'ReportEnhancementSidebar: Triggering loadEnhancements - visible:',
			visible,
			'autoLoad:',
			autoLoad,
			'reportId:',
			reportId
		);
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
</script>

{#if visible}
	<div class="fixed right-0 top-0 h-full w-96 bg-gray-900 border-l border-gray-700 shadow-2xl z-[10000] flex flex-col">
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
				<button
					onclick={() => activeTab = 'analysis'}
					class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {activeTab === 'analysis' ? 'bg-purple-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}"
				>
					Analysis
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
			
			{:else if activeTab === 'analysis'}
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
			
			{:else if activeTab === 'chat'}
				<div class="flex flex-col h-full">
					<!-- Messages -->
					<div class="flex-1 overflow-y-auto mb-4 space-y-4">
						{#if chatMessages.length === 0}
							<div class="text-gray-400 text-center py-8">
								Ask questions about the report or request improvements.
							</div>
						{:else}
							{#each chatMessages as msg}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									<div class="max-w-[80%] {msg.role === 'user' ? 'bg-purple-600' : msg.error ? 'bg-red-500/20 border border-red-500/30' : 'bg-gray-800'} rounded-lg p-3">
										<div class="prose prose-invert max-w-none text-sm {msg.error ? 'text-red-300' : 'text-gray-100'}">
											{@html renderMarkdown(msg.content)}
										</div>
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

