<script context="module" lang="ts">
	import type { Finding, GuidelineEntry, SourceLink } from '$lib/guidelines/types';

	interface EnhancementCacheEntry {
		findings: Finding[];
		guidelines: GuidelineEntry[];
		urgency_signals: string[];
		applicable_guidelines: { system: string; context: string; type: string }[];
		timestamp: number;
		error?: string | null;
		chatMessages?: ChatMessage[];
	}

	type ChatMessageLabel = {
		type: 'intelli-fill' | 'audit-fix';
		name: string;
		itemType?: string;
	};

	type ChatMessageAction = {
		title: string;
		details: string;
		patch?: string;
	};

	type ChatMessage = {
		role: 'user' | 'assistant';
		content: string;
		sources?: SourceLink[];
		error?: boolean;
		editProposal?: string;
		actionsApplied?: ChatMessageAction[];
		applied?: boolean;
		label?: ChatMessageLabel;
	};

	const enhancementCache = new Map<string, EnhancementCacheEntry>();
</script>

<script lang="ts">
	import { token } from '$lib/stores/auth';
	import { marked } from 'marked';
	import DiffMatchPatch from 'diff-match-patch';
	import { createEventDispatcher, onMount, tick } from 'svelte';
	import { API_URL } from '$lib/config';
	import GuidelinesPanel from '$lib/review/rail/GuidelinesPanel.svelte';
	import { loadEnhancement, forgetEnhancement } from '$lib/guidelines/enhance';
	import AuditBanner from './AuditBanner.svelte';
	
	// KaTeX for math rendering (optional - will be loaded dynamically)
	let katex: any = null;
	let katexLoaded = false;
	
	// Re-emit panelWide on visibility rising edge so parent reclaims correct width
	let _prevVisible = false;
	$: {
		if (visible && !_prevVisible) {
			dispatch('panelWide', { wide: layoutMode !== 'narrow', mode: layoutMode });
		}
		_prevVisible = visible;
	}

	onMount(() => {
		// Restore layout preference, then sync width with parent
		try {
			const saved = localStorage.getItem('copilotLayout');
			if (saved === 'narrow' || saved === 'dual' || saved === 'tri') {
				layoutMode = saved;
			}
		} catch { /* ignore */ }
		dispatch('panelWide', { wide: layoutMode !== 'narrow', mode: layoutMode });

		// Async KaTeX load (fire and forget — cleanup handled by return below)
		(async () => {
			try {
				katex = (await import('katex')).default;
				await import('katex/dist/katex.css');
				katexLoaded = true;
			} catch (e) {
				console.warn('KaTeX not available - math formulas will render as plain text');
			}
		})();

	});
	
	export let reportId: string | null = null;
	export let reportContent: string = '';
	export let visible: boolean = false;
	export let inFlow: boolean = false;
	export let panelWide: boolean = false;
	/** From parent: max layout allowed given viewport cap (narrow / dual / tri). */
	export let maxLayoutTier: 'narrow' | 'dual' | 'tri' = 'tri';
	export let autoLoad: boolean = false;
	export let historyAvailable: boolean = false;
	export let initialTab: 'guidelines' | 'comparison' | 'chat' | 'qa' | null = null;
	export let initialMessage: string | null = null;
	export let autoSend: boolean = false;
	export let autoSendLabel: { type: string; name: string; itemType?: string } | null = null;
	// Lifted from the audit result so the Guidelines tab can show a QA Reference section.
	// Populated/cleared by +page.svelte via the auditComplete event chain.
	export let auditGuidelineReferences: any[] = [];
	export let auditCriteriaForSidebar: any[] = [];
	/** One-shot: sent once with Fix-with-AI auto message; parent clears on `auditFixContextConsumed` */
	export let auditFixContext: import('$lib/types/auditFixContext').AuditFixContext | null = null;

	/** Lifted audit store snapshot from ReportResponseViewer (via +page) */
	export let auditState: {
		status: string;
		result: any;
		auditId: string | null;
		error: string | null;
		activeCriterion: string | null;
		saveInFlight?: boolean;
	} | null = null;

	const dispatch = createEventDispatcher();

	// Layout mode: narrow = single-panel tab view, dual = QA+GL side by side, tri = QA+GL+Chat inline
	let layoutMode: 'narrow' | 'dual' | 'tri' = 'narrow';
	let activeTab: 'qa' | 'gl' = 'qa';
	let chatSheetOpen = false;

	// Which layout buttons to show — driven by parent viewport cap (see +page.svelte).
	$: availableLayouts = {
		narrow: true,
		dual: maxLayoutTier === 'dual' || maxLayoutTier === 'tri',
		tri: maxLayoutTier === 'tri'
	};

	// Auto-downgrade when viewport no longer supports the current mode.
	$: if (maxLayoutTier === 'narrow' && layoutMode !== 'narrow') {
		setLayoutMode('narrow');
	} else if (maxLayoutTier === 'dual' && layoutMode === 'tri') {
		setLayoutMode('dual');
	}

	function setLayoutMode(mode: 'narrow' | 'dual' | 'tri') {
		layoutMode = mode;
		if (mode !== 'narrow') chatSheetOpen = false;
		dispatch('panelWide', { wide: mode !== 'narrow', mode });
		try { localStorage.setItem('copilotLayout', mode); } catch { /* ignore */ }
	}

	// Zone focus from parent (comparison opens drawer in +page, not here)
	let lastInitialTab: typeof initialTab = null;
	let lastInitialMessage: string | null = null;
	$: if (visible && initialTab && initialTab !== 'comparison') {
		const tabChanged = initialTab !== lastInitialTab;
		const messageChanged = initialTab === 'chat' && !!initialMessage && initialMessage !== lastInitialMessage;
		if (tabChanged) {
			if (initialTab === 'guidelines') {
				activeTab = 'gl';
			} else if (initialTab === 'qa') {
				activeTab = 'qa';
			} else if (initialTab === 'chat') {
				chatSheetOpen = true;
			}
			lastInitialTab = initialTab;
		}
		// For chat: always open the sheet and process new messages, even when tab hasn't changed
		if (initialTab === 'chat' && messageChanged) {
			chatSheetOpen = true;
		}
		if ((tabChanged || messageChanged) && initialTab === 'chat' && initialMessage) {
			lastInitialMessage = initialMessage;
			chatInput = initialMessage;
			if (autoSend) {
				const labelToSend = autoSendLabel as ChatMessageLabel | null;
				setTimeout(() => sendChatMessage(labelToSend ?? undefined), 50);
			} else {
				setTimeout(() => {
					if (chatTextareaRef) {
						chatTextareaRef.style.height = 'auto';
						const maxHeight = Math.floor(window.innerHeight * 0.2);
						const newHeight = Math.min(chatTextareaRef.scrollHeight, maxHeight);
						chatTextareaRef.style.height = `${newHeight}px`;
						chatTextareaRef.style.maxHeight = `${maxHeight}px`;
					}
				}, 0);
			}
			scrollChatToBottom();
		}
	}

	$: if ((chatSheetOpen || layoutMode === 'tri') && chatMessages.length > 0) {
		setTimeout(() => scrollChatToBottom(), 0);
	}

	$: if (!visible) {
		lastInitialTab = null;
		if (initialMessage) chatInput = '';
	}
	let loading = false;
	let error: string | null = null;
	let hasLoaded = false;
	let lastReportId: string | null = null;
	// Mirrors the audit store's guidelineLookupFailed — true when /enhance failed
	// to produce guidelines due to upstream error (prefetch unavailable, synthesis
	// threw, Tavily down). Distinct from "succeeded with zero applicable guidelines".
	// Used by the Guidelines tab to show an error state with Retry vs a plain
	// empty state, and visible to the ReportEnhancementSidebar's local empty-state
	// branch (the AuditBanner reads the store directly via auditState prop).
	let guidelineLookupFailed = false;

	let findings: Finding[] = [];
	let guidelinesData: GuidelineEntry[] = [];
	let urgencySignals: string[] = [];
	let applicableGuidelines: { system: string; context: string; type: string }[] = [];

	let chatMessages: ChatMessage[] = [];
	let chatInput = '';
	let chatTextareaRef: HTMLTextAreaElement | null = null;
	let chatMessagesContainerRef: HTMLDivElement | null = null;
	let chatLoading = false;

	// ── Chat sheet resize ─────────────────────────────────
	let chatSheetHeight = 560;
	let isResizingChat = false;
	let resizeStartY = 0;
	let resizeStartHeight = 0;

	function startChatResize(e: MouseEvent) {
		isResizingChat = true;
		resizeStartY = e.clientY;
		resizeStartHeight = chatSheetHeight;
		e.preventDefault();
	}

	function onWindowMouseMove(e: MouseEvent) {
		if (!isResizingChat) return;
		const delta = resizeStartY - e.clientY;
		chatSheetHeight = Math.max(200, Math.min(
			typeof window !== 'undefined' ? Math.floor(window.innerHeight * 0.88) : 700,
			resizeStartHeight + delta
		));
	}

	function onWindowMouseUp() {
		isResizingChat = false;
	}

	// Edit proposal modal state
	let expandedEditProposalIndex: number | null = null;

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
		urgencySignals = (cloneValue(entry.urgency_signals) as string[]) || [];
		applicableGuidelines = (cloneValue(entry.applicable_guidelines) as { system: string; context: string; type: string }[]) || [];
		error = entry.error ?? null;
		chatMessages = entry.chatMessages ? (cloneValue(entry.chatMessages) as ChatMessage[]) : [];
		hasLoaded = true;
		loading = false;
		setTimeout(() => scrollChatToBottom(), 0);
		return true;
	}

	function saveCacheEntry(id?: string): void {
		const cacheId = id || reportId;
		if (!cacheId) return;
		enhancementCache.set(cacheId, {
			findings: cloneValue(findings) as Finding[],
			guidelines: cloneValue(guidelinesData) as GuidelineEntry[],
			urgency_signals: cloneValue(urgencySignals) as string[],
			applicable_guidelines: cloneValue(applicableGuidelines) as { system: string; context: string; type: string }[],
			timestamp: Date.now(),
			error,
			chatMessages: cloneValue(chatMessages) as ChatMessage[]
		});
	}

	function resetAllSidebarState(): void {
		findings = [];
		guidelinesData = [];
		urgencySignals = [];
		applicableGuidelines = [];
		chatMessages = [];
		chatInput = '';
		chatLoading = false;
		expandedEditProposalIndex = null;
		error = null;
	}
	
	function invalidateCache(): void {
		if (reportId) {
			enhancementCache.delete(reportId);
		}
		resetAllSidebarState();
	}

	const dmp = new DiffMatchPatch();
	
	function renderDiff(oldText: string, newText: string): string {
		if (!oldText || !newText) return '';
		const diffs = dmp.diff_main(oldText, newText);
		dmp.diff_cleanupSemantic(diffs);
		return diffs
			.map(([op, text]) => {
				const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
				if (op === 1) return `<ins class="bg-green-500/30 text-green-200 px-0.5 rounded no-underline">${escaped}</ins>`;
				if (op === -1) return `<del class="bg-red-500/30 text-red-200 px-0.5 rounded line-through">${escaped}</del>`;
				return escaped;
			})
			.join('');
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
		
		// Render markdown to HTML
		let html = marked.parse(processed) as string;
		
		// Render math formulas using KaTeX if available
		if (katexLoaded && katex) {
			// Handle block math: $$...$$
			html = html.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
				try {
					const rendered = katex.renderToString(formula.trim(), { displayMode: true, throwOnError: false });
					// Wrap in a container with overflow handling
					return `<div class="katex-block-container" style="overflow-x: auto; overflow-y: hidden; max-width: 100%; margin: 1rem 0;">${rendered}</div>`;
				} catch (e) {
					return match; // Return original if rendering fails
				}
			});
			
			// Handle inline math: $...$
			html = html.replace(/\$([^$\n]+?)\$/g, (match, formula) => {
				try {
					const rendered = katex.renderToString(formula.trim(), { displayMode: false, throwOnError: false });
					// Wrap inline math in a span with word-break handling
					return `<span class="katex-inline-container" style="display: inline-block; max-width: 100%; overflow-x: auto; word-break: break-word;">${rendered}</span>`;
				} catch (e) {
					return match; // Return original if rendering fails
				}
			});
		}
		
		return html;
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
			forgetEnhancement(reportId);
			hasLoaded = false;
		}

		loading = true;
		error = null;
		const id = reportId;
		try {
			// lib/guidelines/enhance.ts: one request per report (shared with the review rail's Guidelines tab); it
			// also merges Phase 2 audit criteria into the audit store, on success and on failure.
			const data = await loadEnhancement(id);
			if (reportId !== id) return; // switched report meanwhile; its own load runs
			findings = [...data.findings];
			guidelinesData = [...data.guidelines];
			urgencySignals = data.urgencySignals;
			applicableGuidelines = data.applicableGuidelines;
			guidelineLookupFailed = data.lookupFailed;
			error = null;
			saveCacheEntry();
			hasLoaded = true;
		} catch (err: unknown) {
			if (reportId !== id) return;
			// Only show the error if we don't already have data
			const hasData = findings.length > 0 || guidelinesData.length > 0;
			error = hasData ? null : err instanceof Error ? err.message : 'Failed to connect. Please try again.';
			if (error) guidelineLookupFailed = true;
		} finally {
			if (reportId === id) {
				loading = false;
				if (!error && (findings.length > 0 || guidelinesData.length > 0)) hasLoaded = true;
			}
		}
	}

	async function sendChatMessage(label?: ChatMessageLabel): Promise<void> {
		if (!chatInput.trim() || !reportId) return;
		
		const userMessage = chatInput.trim();
		chatInput = '';
		
		// Reset textarea height after clearing input
		if (chatTextareaRef) {
			chatTextareaRef.style.height = 'auto';
			chatTextareaRef.style.maxHeight = '';
		}
		
		chatMessages.push({ role: 'user', content: userMessage, ...(label ? { label } : {}) });
		chatMessages = [...chatMessages];
		scrollChatToBottom(); // Scroll after user message
		
		chatLoading = true;
		
		try {
			const headers = {
				'Content-Type': 'application/json',
				...(($token) ? { 'Authorization': `Bearer ${$token}` } : {})
			};

			const attachAuditFix = label?.type === 'audit-fix' && auditFixContext != null;
			const body: Record<string, unknown> = {
				message: userMessage,
				history: chatMessages.slice(0, -1)
			};
			if (attachAuditFix) {
				body.audit_fix_context = auditFixContext;
			}

			const response = await fetch(`${API_URL}/api/reports/${reportId}/chat`, {
				method: 'POST',
				headers,
				body: JSON.stringify(body)
			});
			
			const data: any = await response.json();
			
			if (data.success) {
				if (attachAuditFix) {
					dispatch('auditFixContextConsumed');
				}
				let content = data.response;
				let editProposal = data.edit_proposal;
				let actionsApplied = data.actions_applied || null;

				chatMessages.push({
					role: 'assistant',
					content: content,
					sources: data.sources || [],
					editProposal,
					actionsApplied
				});
				chatMessages = [...chatMessages];
				scrollChatToBottom(); // Scroll after assistant message
			} else {
				chatMessages.push({
					role: 'assistant',
					content: 'Something went wrong. Please try again.',
					error: true
				});
				chatMessages = [...chatMessages];
				scrollChatToBottom(); // Scroll after error message
			}
		} catch (err) {
			chatMessages.push({
				role: 'assistant',
				content: `Error: ${err instanceof Error ? err.message : String(err)}`,
				error: true
			});
			chatMessages = [...chatMessages];
			scrollChatToBottom(); // Scroll after error message
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
				error = 'Failed to update report. Please try again.';
			}
		} catch (err) {
			error = 'Failed to update report. Please try again.';
		} finally {
			dispatch('reportUpdating', { status: 'end' });
		}
	}

	function autoResizeTextarea(e: Event) {
		const target = e.target as HTMLTextAreaElement;
		target.style.height = 'auto';
		const maxHeight = Math.floor(window.innerHeight * 0.2);
		const newHeight = Math.min(target.scrollHeight, maxHeight);
		target.style.height = `${newHeight}px`;
		target.style.maxHeight = `${maxHeight}px`;
	}

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendChatMessage();
		}
	}
	
	async function scrollChatToBottom() {
		await tick(); // Wait for DOM to update
		if (chatMessagesContainerRef) {
			chatMessagesContainerRef.scrollTop = chatMessagesContainerRef.scrollHeight;
		}
	}
	
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

	// Emit enhancement state updates for dock/cards
	$: {
		dispatch('enhancementState', {
			guidelinesCount: guidelinesData.length,
			isLoading: loading,
			hasError: Boolean(error),
			reportId
		});
	}

	$: auditForBanner = auditState ?? {
		status: 'idle',
		result: null,
		auditId: null,
		error: null,
		activeCriterion: null
	};

	function bridgeAskToChat(text: string) {
		chatInput = `Re: ${text} — `;
		if (layoutMode !== 'tri') chatSheetOpen = true;
		tick().then(() => chatTextareaRef?.focus());
	}

</script>

<svelte:window onmousemove={onWindowMouseMove} onmouseup={onWindowMouseUp} />

{#if visible}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="copilot-sb h-full min-h-0 flex flex-col shadow-2xl shadow-purple-500/10 transition-all duration-300 ease-in-out {!inFlow
			? 'fixed right-0 top-0 z-[10000] bg-[rgba(6,6,10,0.99)] backdrop-blur-2xl border-l border-white/[0.13] rounded-l-2xl overflow-hidden'
			: 'w-full'}"
		style={!inFlow ? `width:${layoutMode==='tri'?'940px':layoutMode==='dual'?'700px':'420px'}` : ''}
	>
		<!-- ══ HEADER ══ -->
		<div class="copilot-header shrink-0 {(auditForBanner?.status === 'loading' || loading) ? 'header-loading' : (hasLoaded && !loading) ? 'header-loaded' : ''}">
			{#if auditForBanner?.status === 'loading' || loading}
				<div class="header-shimmer" aria-hidden="true"></div>
			{/if}
			<div class="flex items-center justify-between gap-2 relative z-[1]">
				<div class="flex items-center gap-2 min-w-0">
					<div class="pilot-icon" aria-hidden="true">
						<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
							<path d="M13 10V3L4 14h7v7l9-11h-7z" />
						</svg>
					</div>
					<span class="brand-name">Copilot</span>
					{#if auditForBanner?.result}
						{@const _flags = auditForBanner.result.criteria?.filter((c: { status: string; acknowledged?: boolean }) => c.status === 'flag' && !c.acknowledged).length ?? 0}
						{@const _warns = auditForBanner.result.criteria?.filter((c: { status: string; acknowledged?: boolean }) => c.status === 'warning' && !c.acknowledged).length ?? 0}
						{@const reviewCount = _flags + _warns}
						{#if reviewCount > 0}
							<div class="status-pill status-alert">
								<span class="status-dot dot-alert"></span>
								<span class="status-text">{reviewCount} item{reviewCount === 1 ? '' : 's'} need review</span>
							</div>
						{:else}
							<div class="status-pill status-clear">
								<span class="status-dot dot-clear"></span>
								<span class="status-text">All clear</span>
							</div>
						{/if}
					{:else if auditForBanner?.status === 'loading'}
						<div class="status-pill status-neutral">
							<span class="w-2 h-2 rounded-full bg-purple-400 animate-pulse shrink-0"></span>
							<span class="status-text">Analysing…</span>
						</div>
					{/if}
				</div>
				<div class="hdr-right flex items-center gap-1 shrink-0">
					{#if maxLayoutTier !== 'narrow'}
						<button
							type="button"
							onclick={() => { const next = layoutMode === 'narrow' ? (availableLayouts.dual ? 'dual' : 'narrow') : layoutMode === 'dual' ? (availableLayouts.tri ? 'tri' : 'narrow') : 'narrow'; setLayoutMode(next); }}
							class="btn-icon-copilot"
							class:btn-icon-copilot-active={layoutMode !== 'narrow'}
							title="Cycle layout"
						>
							{#if layoutMode === 'narrow'}
								<svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7"/></svg>
							{:else}
								<svg width="13" height="13" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"/></svg>
							{/if}
						</button>
					{/if}
					<button type="button" onclick={() => dispatch('close')} class="btn-icon-copilot" aria-label="Close sidebar">
						<svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
					</button>
				</div>
			</div>
		</div>

		<!-- ══ TAB BAR (narrow only) ══ -->
		{#if layoutMode === 'narrow'}
			{@const _tabFlags = auditForBanner?.result?.criteria?.filter((c: { status: string; acknowledged?: boolean }) => c.status === 'flag' && !c.acknowledged).length ?? 0}
			{@const _tabWarns = auditForBanner?.result?.criteria?.filter((c: { status: string; acknowledged?: boolean }) => c.status === 'warning' && !c.acknowledged).length ?? 0}
			<div class="tab-bar-copilot shrink-0">
				<button type="button" onclick={() => (activeTab = 'qa')} class="tab-copilot {activeTab === 'qa' ? 'tab-copilot-active' : ''}">
					{#if _tabFlags > 0}
						<span class="tab-ind ti-alert"></span>
					{:else if _tabWarns > 0}
						<span class="tab-ind" style="background:#f59e0b;box-shadow:0 0 5px rgba(245,158,11,0.5)"></span>
					{:else if auditForBanner?.status === 'loading'}
						<span class="tab-ind" style="background:#a78bfa" class:animate-pulse={true}></span>
					{:else}
						<span class="tab-ind ti-neutral"></span>
					{/if}
					QA Audit
				</button>
				<button type="button" onclick={() => (activeTab = 'gl')} class="tab-copilot {activeTab === 'gl' ? 'tab-copilot-active' : ''}">
					{#if loading}
						<span class="tab-ind" style="background:#a78bfa" class:animate-pulse={true}></span>
					{:else if guidelinesData.length > 0 || auditGuidelineReferences.length > 0}
						<span class="tab-ind ti-ok"></span>
					{:else}
						<span class="tab-ind ti-neutral"></span>
					{/if}
					Guidelines
				</button>
			</div>
		{/if}

		<!-- ══ CONTENT AREA ══ -->
		<div class="flex-1 min-h-0 overflow-hidden" style="display:flex; flex-direction:{layoutMode !== 'narrow' ? 'row' : 'column'};">

			<!-- ── QA PANEL ── -->
			<div
				class="qa-panel"
				style="display:{layoutMode === 'narrow' && activeTab !== 'qa' ? 'none' : 'flex'}; flex-direction:column; flex:{layoutMode !== 'narrow' ? '0 0 280px' : '1'}; min-width:{layoutMode !== 'narrow' ? '240px' : '0'}; overflow:hidden; {layoutMode !== 'narrow' ? 'border-right:1px solid rgba(255,255,255,0.06);' : 'overflow-y:auto;'}"
			>
				{#if layoutMode !== 'narrow'}
					<div class="panel-header shrink-0 flex items-center justify-between px-3 py-2 border-b border-white/[0.06]">
						<div class="flex items-center gap-1.5">
							{#if auditForBanner?.status === 'loading'}
								<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>
							{:else}
								{@const _hasIssues = (auditForBanner?.result?.criteria?.filter((c: { status: string; acknowledged?: boolean }) => (c.status === 'flag' || c.status === 'warning') && !c.acknowledged).length ?? 0) > 0}
								<span class="w-1.5 h-1.5 rounded-full {_hasIssues ? 'bg-rose-500' : 'bg-gray-600'}"></span>
							{/if}
							<span class="text-[9px] font-bold uppercase tracking-[0.12em] text-gray-500">QA Audit</span>
						</div>
						<button
							type="button"
							onclick={() => dispatch('auditReaudit')}
							class="text-[9px] font-medium text-gray-500 hover:text-gray-300 px-2 py-0.5 rounded border border-white/[0.07] hover:border-white/20 transition-colors"
						>Re-audit</button>
					</div>
				{/if}
				<div class="qa-inner-scroll {layoutMode !== 'narrow' ? 'flex-1 overflow-y-auto p-2.5' : 'px-3 py-2'}">
					{#if !auditForBanner || auditForBanner.status === 'idle'}
						<p class="text-xs text-gray-600 py-6 text-center">Audit will run automatically.</p>
					{:else if auditForBanner.status === 'loading'}
						<p class="text-xs text-gray-500 py-6 text-center">Analysing report…</p>
					{:else}
						<AuditBanner
							auditState={auditForBanner as any}
							canReaudit={['complete', 'stale', 'error'].includes(auditForBanner.status) && !auditState?.saveInFlight && (auditForBanner as any)?.phase2Complete === true}
							showClose={false}
							on:acknowledge={(e) => dispatch('auditAcknowledge', e.detail)}
							on:restore={(e) => dispatch('auditRestore', e.detail)}
							on:suggestFix={(e) => dispatch('auditSuggestFix', e.detail)}
							on:applyFix={(e) => dispatch('auditApplyFix', e.detail)}
							on:insertBanner={(e) => dispatch('auditInsertBanner', e.detail)}
							on:reaudit={() => dispatch('auditReaudit')}
							on:retryGuidelines={() => loadEnhancements(true)}
							on:openSidebar={(e) => { if (e.detail?.tab === 'guidelines') activeTab = 'gl'; }}
						/>
					{/if}
				</div>
			</div>

			<!-- ── GUIDELINES PANEL ── -->
			<div
				style="display:{layoutMode === 'narrow' && activeTab !== 'gl' ? 'none' : 'flex'}; flex-direction:column; flex:1; min-width:{layoutMode !== 'narrow' ? '260px' : '0'}; overflow:hidden; {layoutMode === 'narrow' ? 'overflow-y:auto;' : ''}{layoutMode !== 'narrow' ? 'border-left:1px solid rgba(255,255,255,0.06);' : ''}"
			>
				{#if layoutMode !== 'narrow'}
					<div class="panel-header shrink-0 flex items-center gap-1.5 px-3 py-2 border-b border-white/[0.06]">
						{#if loading}
							<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>
						{:else if guidelinesData.length > 0 || auditGuidelineReferences.length > 0}
							<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
						{:else}
							<span class="w-1.5 h-1.5 rounded-full bg-gray-600"></span>
						{/if}
						<span class="text-[9px] font-bold uppercase tracking-[0.12em] text-gray-500">Guidelines</span>
					</div>
				{/if}
				<div class="{layoutMode !== 'narrow' ? 'flex-1 overflow-y-auto' : ''} px-3 py-2">
					{#key reportId}
						<GuidelinesPanel
							guidelines={guidelinesData}
							{urgencySignals}
							{loading}
							loaded={hasLoaded}
							{error}
							lookupFailed={guidelineLookupFailed}
							{auditGuidelineReferences}
							auditCriteria={auditCriteriaForSidebar}
							onRetry={() => loadEnhancements(true)}
							onAsk={bridgeAskToChat}
						/>
					{/key}
				</div>
			</div>

			<!-- ── CHAT PANEL (tri mode — inline) ── -->
			{#if layoutMode === 'tri'}
				<div style="display:flex; flex-direction:column; flex:0 0 240px; min-width:200px; overflow:hidden; border-left:1px solid rgba(255,255,255,0.06);">
					<div class="panel-header shrink-0 flex items-center gap-1.5 px-3 py-2 border-b border-white/[0.06]">
						<svg class="w-3 h-3 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>
						<span class="text-[9px] font-bold uppercase tracking-[0.12em] text-gray-500">Ask Copilot</span>
					</div>
				<div bind:this={chatMessagesContainerRef} class="flex-1 overflow-y-auto px-3 py-3 space-y-2.5 min-h-0 chat-msgs-area">
					{#if chatMessages.length === 0}
						<div class="flex flex-col items-center gap-2 py-6 text-center">
							<div class="w-7 h-7 rounded-lg bg-purple-600/15 border border-purple-500/20 flex items-center justify-center">
								<svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
							</div>
							<p class="text-[11px] text-gray-500 leading-relaxed">Ask about the report</p>
						</div>
					{:else}
						{#each chatMessages as msg, index}
							<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
								<div class="max-w-[87%] {msg.role === 'user' ? (msg.label ? 'chat-bubble-label' : 'chat-bubble-user') : msg.error ? 'chat-bubble-error' : 'chat-bubble-assistant'} rounded-xl p-2.5">
										{#if msg.label}
											{@const isAudit = msg.label.type === 'audit-fix'}
											<div class="flex items-center gap-1.5">
												<div class="flex items-center gap-1 px-1.5 py-0.5 rounded {isAudit ? 'bg-amber-500/15 border border-amber-500/25' : 'bg-purple-500/15 border border-purple-500/25'}">
													<span class="text-[9px] font-semibold {isAudit ? 'text-amber-400' : 'text-purple-400'} uppercase tracking-wide">{isAudit ? 'Audit Fix' : 'Intelli-Fill'}</span>
												</div>
												<span class="text-[10px] font-mono {isAudit ? 'text-amber-300' : 'text-purple-300'} truncate max-w-[120px]" title={msg.label.name}>{msg.label.name}</span>
											</div>
										{:else}
											<div class="prose prose-invert max-w-none prose-p:leading-relaxed {msg.error ? 'text-red-300' : 'text-gray-100'}">
												{@html renderMarkdown(msg.content)}
											</div>
										{/if}
										{#if msg.editProposal}
											<div class="mt-2 pt-2 border-t border-white/10 space-y-1.5">
												<div class="bg-black/50 rounded p-1.5 border border-white/10">
													<div class="flex items-center justify-between mb-1">
														<p class="text-[10px] font-medium text-gray-400">Preview</p>
														<button onclick={() => expandedEditProposalIndex = index} class="text-[10px] text-purple-400 hover:text-purple-300">Expand</button>
													</div>
													<div class="text-[10px] text-gray-300 max-h-32 overflow-y-auto font-mono bg-black/20 p-1.5 rounded whitespace-pre-wrap">
														{#if reportContent}{@html renderDiff(reportContent, msg.editProposal)}{:else}{msg.editProposal}{/if}
													</div>
												</div>
												<button onclick={() => { if (msg.editProposal) { updateReportContent(msg.editProposal, 'chat'); msg.applied = true; } chatMessages = [...chatMessages]; }} disabled={msg.applied || !reportId} class="w-full px-2 py-1 {msg.applied ? 'bg-green-600/50 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-700'} text-white text-[10px] font-medium rounded transition-colors">
													{msg.applied ? 'Applied' : 'Apply Change'}
												</button>
											</div>
										{/if}
										{#if msg.sources && msg.sources.length > 0}
											<div class="mt-1.5 pt-1.5 border-t border-white/10">
												<p class="text-[9px] font-medium text-gray-400 mb-1">Sources</p>
												<ul class="space-y-1">
													{#each msg.sources as source}
														<li class="src-ref-item text-[10px]">
															<a href={source.url} target="_blank" rel="noopener noreferrer" class="text-purple-400 hover:text-purple-300 truncate block">{source.title?.trim() || source.domain || source.url}</a>
															{#if source.snippet?.trim()}<div class="src-snippet">{source.snippet}</div>{/if}
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
							<div class="chat-bubble-assistant rounded-xl px-3 py-2 flex items-center gap-1.5">
								<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>
								<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" style="animation-delay:0.2s"></span>
								<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" style="animation-delay:0.4s"></span>
							</div>
						</div>
					{/if}
				</div>
				<div class="shrink-0 border-t border-white/[0.07] p-2.5 bg-black/20">
					<div class="flex gap-2 items-end">
						<textarea
							bind:value={chatInput}
							bind:this={chatTextareaRef}
							onkeydown={handleKeyDown}
							placeholder="Ask…"
							class="flex-1 bg-white/[0.04] border border-white/[0.1] rounded-xl px-2.5 py-1.5 text-[11.5px] text-white placeholder-gray-600 resize-none focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-colors"
							rows="2"
							disabled={chatLoading || !reportId}
							oninput={autoResizeTextarea}
						></textarea>
					<button type="button" onclick={() => sendChatMessage()} disabled={!chatInput.trim() || chatLoading || !reportId} aria-label="Send message" class="w-7 h-7 flex-shrink-0 rounded-lg bg-gradient-to-br from-purple-600 to-purple-500 hover:from-purple-500 hover:to-purple-400 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-all flex items-center justify-center shadow-lg shadow-purple-500/25 mb-0.5">
						<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
					</button>
				</div>
			</div>
		</div>
	{/if}

		</div><!-- end content area -->

		<!-- ══ CHAT DOCK + SHEET (narrow & dual) ══ -->
		{#if layoutMode !== 'tri'}
			<div class="shrink-0 border-t border-white/[0.1] relative bg-gradient-to-t from-black/30 to-transparent">
				<!-- Pill row (always visible when sheet is closed) -->
				{#if !chatSheetOpen}
					<button
						type="button"
						onclick={() => { chatSheetOpen = true; }}
						class="chat-dock-pill w-full flex items-center gap-2.5 px-3.5 py-2.5"
					>
						<div class="chat-dock-icon">
							<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>
						</div>
						<span class="flex-1 text-left truncate chat-dock-text">
							{#if chatMessages.length > 0}
								{chatMessages[chatMessages.length - 1].content.slice(0, 55)}{chatMessages[chatMessages.length - 1].content.length > 55 ? '…' : ''}
							{:else}
								Ask Copilot about this report…
							{/if}
						</span>
						{#if chatMessages.length > 0}
							<span class="chat-dock-count">{chatMessages.length}</span>
						{/if}
						<svg class="w-3 h-3 shrink-0 text-purple-400/60 -rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
					</button>
				{/if}

				<!-- Slide-up chat sheet -->
				{#if chatSheetOpen}
					<div class="chat-sheet absolute bottom-0 left-0 right-0 flex flex-col z-10" style="height: {chatSheetHeight}px; max-height: 88vh;">
						<!-- Drag-to-resize handle -->
						<!-- svelte-ignore a11y-no-static-element-interactions a11y-no-noninteractive-element-interactions -->
						<div
							class="chat-resize-handle shrink-0"
							class:dragging={isResizingChat}
							onmousedown={startChatResize}
							title="Drag to resize"
							role="separator"
							aria-orientation="horizontal"
						>
							<div class="chat-resize-grip"></div>
						</div>
						<div class="chat-sheet-header shrink-0 flex items-center justify-between px-3.5 py-2 border-b border-white/[0.08]">
							<div class="flex items-center gap-2">
								<div class="w-5 h-5 rounded-md bg-purple-600/30 border border-purple-500/30 flex items-center justify-center">
									<svg class="w-3 h-3 text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>
								</div>
								<span class="text-xs font-semibold text-gray-200 tracking-wide">Ask Copilot</span>
							</div>
							<button type="button" onclick={() => { chatSheetOpen = false; }} aria-label="Close chat" class="p-1 text-gray-500 hover:text-gray-300 transition-colors rounded-md hover:bg-white/[0.06]">
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
							</button>
						</div>
						<div bind:this={chatMessagesContainerRef} class="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0 chat-msgs-area">
							{#if chatMessages.length === 0}
								<div class="flex flex-col items-center gap-2 py-6 text-center">
									<div class="w-8 h-8 rounded-xl bg-purple-600/15 border border-purple-500/20 flex items-center justify-center">
										<svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
									</div>
									<p class="text-xs text-gray-500 max-w-[180px] leading-relaxed">Ask questions about the report or request edits</p>
								</div>
							{:else}
								{#each chatMessages as msg, index}
									<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
										<div class="max-w-[82%] {msg.role === 'user' ? (msg.label ? 'chat-bubble-label' : 'chat-bubble-user') : msg.error ? 'chat-bubble-error' : 'chat-bubble-assistant'} rounded-xl p-3">
											{#if msg.label}
												{@const isAudit = msg.label.type === 'audit-fix'}
												<div class="flex items-center gap-2">
													<div class="flex items-center gap-1.5 px-2 py-1 rounded-md {isAudit ? 'bg-amber-500/15 border border-amber-500/25' : 'bg-purple-500/15 border border-purple-500/25'}">
														{#if isAudit}
															<svg class="w-3 h-3 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
															<span class="text-[10px] font-semibold text-amber-400 uppercase tracking-wide">Audit Fix</span>
														{:else}
															<svg class="w-3 h-3 text-purple-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
															<span class="text-[10px] font-semibold text-purple-400 uppercase tracking-wide">Intelli-Fill</span>
														{/if}
													</div>
													<span class="text-xs font-mono {isAudit ? 'text-amber-300' : 'text-purple-300'} truncate max-w-[160px]" title={msg.label.name}>{msg.label.name}</span>
												</div>
											{:else}
												<div class="prose prose-invert max-w-none prose-p:leading-relaxed {msg.error ? 'text-red-300' : 'text-gray-100'}">
													{@html renderMarkdown(msg.content)}
												</div>
											{/if}
											{#if msg.editProposal}
												<div class="mt-3 pt-3 border-t border-white/10 space-y-2">
													{#if msg.actionsApplied && msg.actionsApplied.length > 0}
														<div class="bg-black/40 rounded p-2 border border-white/10">
															<p class="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Reasoning & changes</p>
															{#each msg.actionsApplied as action}
																<div class="text-xs text-gray-300 mb-2 last:mb-0">
																	<span class="font-medium text-purple-300">{action.title}</span>
																	{#if action.details}<p class="text-gray-400 mt-0.5">{action.details}</p>{/if}
																</div>
															{/each}
														</div>
													{/if}
													<div class="bg-black/50 rounded p-2 border border-white/10">
														<div class="flex items-center justify-between mb-1">
															<p class="text-xs font-medium text-gray-400">Preview</p>
															<button onclick={() => expandedEditProposalIndex = index} class="text-xs text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1">
																<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"/></svg>
																Expand
															</button>
														</div>
														<div class="text-xs text-gray-300 max-h-48 overflow-y-auto font-mono bg-black/20 p-2 rounded whitespace-pre-wrap">
															{#if reportContent}{@html renderDiff(reportContent, msg.editProposal)}{:else}{msg.editProposal}{/if}
														</div>
													</div>
													<button
														onclick={() => { if (msg.editProposal) { updateReportContent(msg.editProposal, 'chat'); msg.applied = true; } chatMessages = [...chatMessages]; }}
														disabled={msg.applied || !reportId}
														class="w-full px-3 py-1.5 {msg.applied ? 'bg-green-600/50 cursor-not-allowed' : !reportId ? 'bg-gray-600 cursor-not-allowed' : 'bg-purple-600 hover:bg-purple-700'} text-white text-xs font-medium rounded transition-colors flex items-center justify-center gap-2"
													>
														<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
														{msg.applied ? 'Applied' : 'Apply Change'}
													</button>
												</div>
											{/if}
											{#if msg.sources && msg.sources.length > 0}
												<div class="mt-2 pt-2 border-t border-white/10">
													<p class="text-xs font-medium text-gray-400 mb-1">Sources consulted</p>
													<ul class="space-y-1.5">
														{#each msg.sources as source}
															<li class="src-ref-item text-xs flex gap-1.5 items-start">
																<div class="min-w-0 flex-1">
																	<a href={source.url} target="_blank" rel="noopener noreferrer" class="text-purple-400 hover:text-purple-300 font-medium block truncate leading-snug">{source.title?.trim() || source.domain || source.url}</a>
																	{#if source.snippet?.trim()}<div class="src-snippet">{source.snippet}</div>{/if}
																</div>
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
								<div class="chat-bubble-assistant rounded-xl px-3 py-2 flex items-center gap-1.5">
									<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse"></span>
									<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" style="animation-delay:0.2s"></span>
									<span class="w-1.5 h-1.5 rounded-full bg-purple-400 animate-pulse" style="animation-delay:0.4s"></span>
								</div>
							</div>
						{/if}
					</div>
					<div class="shrink-0 border-t border-white/[0.07] p-2.5 bg-black/20">
						<div class="flex gap-2 items-end">
							<textarea
								bind:value={chatInput}
								bind:this={chatTextareaRef}
								onkeydown={handleKeyDown}
								placeholder="Ask about the report…"
									class="flex-1 bg-white/[0.04] border border-white/[0.1] rounded-xl px-3 py-2 text-[12.5px] text-white placeholder-gray-600 resize-none focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/30 transition-colors"
									rows="2"
									disabled={chatLoading || !reportId}
									oninput={autoResizeTextarea}
								></textarea>
							<button type="button" onclick={() => sendChatMessage()} disabled={!chatInput.trim() || chatLoading || !reportId} aria-label="Send message" class="w-8 h-8 flex-shrink-0 rounded-xl bg-gradient-to-br from-purple-600 to-purple-500 hover:from-purple-500 hover:to-purple-400 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-all flex items-center justify-center shadow-lg shadow-purple-500/30 mb-0.5">
								<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>
							</button>
						</div>
					</div>
				</div>
			{/if}
		</div>
	{/if}

		<!-- ══ LAYOUT SWITCHER (hidden when only narrow fits viewport cap) ══ -->
		{#if maxLayoutTier !== 'narrow'}
			<div class="shrink-0 flex items-center justify-center gap-1 py-1.5 border-t border-white/[0.05] bg-black/20">
				{#each (['narrow', 'dual', 'tri'] as const) as mode}
					{#if availableLayouts[mode]}
						<button
							type="button"
							onclick={() => setLayoutMode(mode)}
							class="layout-btn {layoutMode === mode ? 'layout-btn-active' : ''}"
						>
						{#if mode === 'narrow'}
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2" stroke-width="1.5"/></svg>
						{:else if mode === 'dual'}
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="3" y="4" width="8" height="16" rx="1.5" stroke-width="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5" stroke-width="1.5"/></svg>
						{:else}
							<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><rect x="2" y="4" width="6" height="16" rx="1.5" stroke-width="1.5"/><rect x="9" y="4" width="6" height="16" rx="1.5" stroke-width="1.5"/><rect x="16" y="4" width="6" height="16" rx="1.5" stroke-width="1.5"/></svg>
						{/if}
						{mode === 'narrow' ? 'Narrow' : mode === 'dual' ? 'Dual' : 'Tri'}
					</button>
					{/if}
				{/each}
			</div>
		{/if}

	</div>
{/if}

<!-- Edit Proposal Modal -->
{#if expandedEditProposalIndex !== null && chatMessages[expandedEditProposalIndex]?.editProposal}
	{@const expandedMsg = chatMessages[expandedEditProposalIndex]}
	<div class="fixed inset-0 bg-black/60 backdrop-blur-md flex items-center justify-center z-[20000]" onclick={() => expandedEditProposalIndex = null}>
		<div class="bg-black/80 backdrop-blur-2xl rounded-2xl border border-white/10 shadow-2xl shadow-purple-500/20 w-[90vw] max-w-4xl max-h-[90vh] overflow-hidden flex flex-col" onclick={(e) => e.stopPropagation()}>
			<div class="p-4 border-b border-white/10 flex items-center justify-between">
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
			<div class="flex-1 overflow-y-auto p-4 space-y-4">
				{#if expandedMsg.actionsApplied && expandedMsg.actionsApplied.length > 0}
					<div class="rounded-lg p-4 border border-white/10 bg-black/40">
						<h4 class="text-sm font-semibold text-gray-300 mb-3">Reasoning & changes</h4>
						{#each expandedMsg.actionsApplied as action}
							<div class="text-sm text-gray-300 mb-3 last:mb-0">
								<span class="font-medium text-purple-300">{action.title}</span>
								{#if action.details}<p class="text-gray-400 mt-1">{action.details}</p>{/if}
							</div>
						{/each}
					</div>
				{/if}
				<div class="rounded-lg p-4 border border-white/10">
					<h4 class="text-sm font-semibold text-gray-300 mb-2">Preview</h4>
					<div class="text-sm text-gray-300 font-mono bg-black/20 p-4 rounded overflow-x-auto overflow-y-auto max-h-[50vh] prose prose-invert max-w-none whitespace-pre-wrap">
						{#if expandedMsg.editProposal}
							{#if reportContent}
								{@html renderDiff(reportContent, expandedMsg.editProposal)}
							{:else}
								{expandedMsg.editProposal}
							{/if}
						{/if}
					</div>
				</div>
			</div>
			<div class="p-4 border-t border-white/10 flex gap-3 justify-end">
				<button 
					class="px-4 py-2 bg-white/10 backdrop-blur-xl hover:bg-white/20 border border-white/10 text-white rounded-lg transition-all duration-200"
					onclick={() => expandedEditProposalIndex = null}
				>
					Close
				</button>
				<button
					onclick={() => {
						if (expandedMsg.editProposal) {
							updateReportContent(expandedMsg.editProposal, 'chat');
							expandedMsg.applied = true;
							chatMessages = [...chatMessages]; // Trigger reactivity
							expandedEditProposalIndex = null;
						}
					}}
					disabled={expandedMsg.applied || !reportId || !expandedMsg.editProposal}
					title={!reportId ? 'No report loaded' : expandedMsg.applied ? 'Already applied' : 'Apply this change to the report'}
					class="px-4 py-2 {expandedMsg.applied ? 'bg-green-600/50 cursor-not-allowed' : 'bg-gradient-to-r from-purple-600 to-purple-500 hover:from-purple-500 hover:to-purple-400 shadow-lg shadow-purple-500/50'} text-white rounded-lg transition-all duration-200 flex items-center gap-2"
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

<style>
	/* ── Typography ─────────────────────────────────────── */
	:global(.copilot-sb),
	:global(.copilot-sb) * {
		font-family: 'DM Sans', 'IBM Plex Sans', system-ui, sans-serif;
	}
	:global(.copilot-sb) code,
	:global(.copilot-sb) pre,
	:global(.copilot-sb) .font-mono {
		font-family: 'DM Mono', 'IBM Plex Mono', monospace;
	}

	/* Compact QA in wide-column mode */
	.qa-panel :global(.audit-card) {
		padding: 10px;
		gap: 8px;
		margin-bottom: 8px;
		flex-wrap: wrap;
	}
	.qa-panel :global(.score-ring) {
		width: 40px;
		height: 40px;
	}
	.qa-panel :global(.score-ring::before) {
		inset: 4px;
	}
	.qa-panel :global(.score-num) {
		font-size: 12px;
	}
	.qa-panel :global(.audit-title) {
		font-size: 11.5px;
	}
	.qa-panel :global(.audit-sub) {
		font-size: 9.5px;
	}
	.qa-panel :global(.reaudit-btn) {
		font-size: 9px;
		padding: 3px 8px;
	}
	.qa-panel :global(.urgency-pill) {
		padding: 7px 10px;
		font-size: 10px;
		margin-bottom: 8px;
	}
	.qa-panel :global(.criterion-row) {
		padding: 7px 9px;
		gap: 7px;
	}
	.qa-panel :global(.c-name) {
		font-size: 10.5px;
	}
	.qa-panel :global(.c-detail) {
		display: none;
	}
	.qa-panel :global(.fix-btn) {
		font-size: 8px;
		padding: 2px 6px;
	}
	.qa-panel :global(.c-dot) {
		width: 6px;
		height: 6px;
		margin-top: 4px;
	}
	.qa-panel :global(.divider) {
		margin: 8px 0 6px;
	}
	.qa-panel :global(.div-text) {
		font-size: 8px;
	}

	/* ── Header (prototype) ─────────────────────────── */
	.copilot-header {
		padding: 10px 12px 9px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.07);
		background: linear-gradient(to bottom, rgba(0, 0, 0, 0.35), transparent);
		position: relative;
		overflow: hidden;
		transition: background 0.4s ease, border-color 0.4s ease;
	}
	.header-loading {
		border-bottom-color: rgba(139, 92, 246, 0.2);
	}
	.header-loaded {
		background: linear-gradient(to bottom, rgba(88, 28, 235, 0.08), rgba(88, 28, 235, 0.03));
		border-bottom-color: rgba(139, 92, 246, 0.18);
	}

	/* Shimmer sweep animation */
	.header-shimmer {
		position: absolute;
		inset: 0;
		pointer-events: none;
		background: linear-gradient(
			105deg,
			transparent 30%,
			rgba(139, 92, 246, 0.12) 48%,
			rgba(167, 139, 250, 0.22) 52%,
			rgba(139, 92, 246, 0.08) 56%,
			transparent 70%
		);
		background-size: 200% 100%;
		animation: header-shimmer-sweep 1.8s ease-in-out infinite;
	}
	@keyframes header-shimmer-sweep {
		0%   { background-position: 200% 0; opacity: 0.6; }
		50%  { opacity: 1; }
		100% { background-position: -200% 0; opacity: 0.6; }
	}
	.pilot-icon {
		width: 28px;
		height: 28px;
		border-radius: 8px;
		flex-shrink: 0;
		background: linear-gradient(135deg, #5b21b6, #8b5cf6);
		display: flex;
		align-items: center;
		justify-content: center;
		box-shadow: 0 0 16px rgba(139, 92, 246, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.12);
	}
	.pilot-icon svg {
		width: 14px;
		height: 14px;
	}
	.brand-name {
		font-size: 14px;
		font-weight: 700;
		color: #fff;
		letter-spacing: -0.01em;
	}
	.hdr-right {
		gap: 4px;
	}
	.btn-ghost-copilot {
		height: 26px;
		padding: 0 9px;
		border-radius: 6px;
		border: 1px solid rgba(255, 255, 255, 0.09);
		background: transparent;
		color: #71717a;
		font-size: 10.5px;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.15s;
		font-family: inherit;
		white-space: nowrap;
	}
	.btn-ghost-copilot:hover {
		background: rgba(255, 255, 255, 0.06);
		color: #fff;
		border-color: rgba(255, 255, 255, 0.13);
	}
	.btn-icon-copilot {
		width: 26px;
		height: 26px;
		border-radius: 6px;
		border: 1px solid rgba(255, 255, 255, 0.09);
		background: transparent;
		color: #71717a;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all 0.15s;
		flex-shrink: 0;
	}
	.btn-icon-copilot:hover {
		background: rgba(255, 255, 255, 0.06);
		color: #fff;
	}
	.btn-icon-copilot-active {
		background: rgba(139, 92, 246, 0.15);
		border-color: rgba(139, 92, 246, 0.35);
		color: #a78bfa;
	}
	/* Compact status pill at narrow panel widths to avoid header crowding */
	@media (max-width: 460px) {
		.status-pill .status-text {
			display: none;
		}
		.status-pill {
			padding: 4px 5px;
		}
	}

	/* ── Tabs (prototype) ─────────────────────────── */
	.tab-bar-copilot {
		display: flex;
		padding: 0 14px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.07);
	}
	.tab-copilot {
		flex: 1;
		padding: 10px 8px 9px;
		border: none;
		background: transparent;
		font-size: 12.5px;
		font-weight: 600;
		color: #52525b;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 5px;
		border-bottom: 2px solid transparent;
		margin-bottom: -1px;
		transition: color 0.15s, border-color 0.15s;
		font-family: inherit;
	}
	.tab-copilot:not(.tab-copilot-active):hover {
		color: #a1a1aa;
		background: rgba(255, 255, 255, 0.03);
	}
	.tab-copilot-active {
		color: #fff;
		border-bottom-color: #8b5cf6;
	}
	.tab-ind {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.tab-ind.ti-alert {
		background: #f43f5e;
		box-shadow: 0 0 5px rgba(244, 63, 94, 0.7);
	}
	.tab-ind.ti-ok {
		background: #10b981;
	}
	.tab-ind.ti-neutral {
		background: #3f3f46;
	}

	/* ── Status pill ────────────────────────────────── */
	.status-pill {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 8px;
		border-radius: 8px;
		font-size: 11px;
		font-weight: 600;
		border: 1px solid;
		flex-shrink: 0;
	}
	.status-alert { background: rgba(244,63,94,0.08); border-color: rgba(244,63,94,0.2); color: #fda4af; }
	.status-clear { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.2); color: #6ee7b7; }
	.status-neutral{ background: rgba(167,139,250,0.08); border-color: rgba(167,139,250,0.2); color: #c4b5fd; }
	.status-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
	.dot-alert { background: #f43f5e; box-shadow: 0 0 6px rgba(244,63,94,0.7); animation: pulse-dot 1.8s ease-in-out infinite; }
	.dot-clear { background: #34d399; }
	.status-text { white-space: nowrap; }
	@keyframes pulse-dot { 0%,100%{ opacity:1; } 50%{ opacity:0.5; } }

	/* ── Chat sheet ─────────────────────────────────── */
	.chat-sheet {
		animation: slide-up 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
		background: rgba(8, 6, 18, 0.97);
		backdrop-filter: blur(20px);
		-webkit-backdrop-filter: blur(20px);
		border-top: 1px solid rgba(139, 92, 246, 0.22);
		box-shadow: 0 -20px 60px rgba(0, 0, 0, 0.7), 0 -1px 0 rgba(139, 92, 246, 0.15);
	}
	.chat-sheet-header {
		background: linear-gradient(to bottom, rgba(88, 28, 235, 0.08), transparent);
	}
	@keyframes slide-up { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

	/* ── Resize handle ───────────────────────────────── */
	.chat-resize-handle {
		height: 14px;
		cursor: ns-resize;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(139, 92, 246, 0.04);
		transition: background 0.15s;
		flex-shrink: 0;
	}
	.chat-resize-handle:hover,
	.chat-resize-handle.dragging {
		background: rgba(139, 92, 246, 0.12);
	}
	.chat-resize-grip {
		width: 32px;
		height: 3px;
		border-radius: 2px;
		background: rgba(255, 255, 255, 0.12);
		transition: background 0.15s, width 0.15s;
	}
	.chat-resize-handle:hover .chat-resize-grip,
	.chat-resize-handle.dragging .chat-resize-grip {
		background: rgba(139, 92, 246, 0.55);
		width: 44px;
	}

	/* ── Chat dock pill ─────────────────────────────── */
	.chat-dock-pill {
		background: rgba(139, 92, 246, 0.05);
		border: none;
		cursor: pointer;
		transition: background 0.15s;
		color: inherit;
		font-family: inherit;
	}
	.chat-dock-pill:hover {
		background: rgba(139, 92, 246, 0.1);
	}
	.chat-dock-icon {
		width: 26px; height: 26px;
		border-radius: 8px;
		background: linear-gradient(135deg, rgba(88, 28, 235, 0.4), rgba(139, 92, 246, 0.35));
		border: 1px solid rgba(139, 92, 246, 0.3);
		display: flex; align-items: center; justify-content: center;
		flex-shrink: 0;
		color: #c4b5fd;
		box-shadow: 0 0 10px rgba(139, 92, 246, 0.2);
	}
	.chat-dock-text {
		font-size: 12px;
		font-weight: 500;
		color: #a1a1aa;
	}
	.chat-dock-count {
		font-size: 10px;
		font-weight: 700;
		color: #a78bfa;
		background: rgba(139, 92, 246, 0.15);
		border: 1px solid rgba(139, 92, 246, 0.25);
		padding: 1px 6px;
		border-radius: 20px;
		flex-shrink: 0;
	}
	.chat-msgs-area {
		scrollbar-width: thin;
		scrollbar-color: rgba(139, 92, 246, 0.15) transparent;
	}
	.chat-msgs-area::-webkit-scrollbar { width: 3px; }
	.chat-msgs-area::-webkit-scrollbar-thumb { background: rgba(139, 92, 246, 0.15); border-radius: 2px; }

	/* ── Chat bubbles ─────────────────────────────────── */
	.chat-bubble-user {
		background: linear-gradient(135deg, #5b21b6, #7c3aed);
		color: white;
		box-shadow: 0 4px 16px rgba(109, 40, 217, 0.35), 0 0 0 1px rgba(139, 92, 246, 0.3);
	}
	.chat-bubble-assistant {
		background: rgba(255, 255, 255, 0.05);
		border: 1px solid rgba(255, 255, 255, 0.08);
		color: #d4d4d8;
	}
	.chat-bubble-label {
		background: rgba(255, 255, 255, 0.04);
		border: 1px solid rgba(255, 255, 255, 0.09);
	}
	.chat-bubble-error {
		background: rgba(239, 68, 68, 0.12);
		border: 1px solid rgba(239, 68, 68, 0.25);
		color: #fca5a5;
	}

	/* ── Layout switcher ────────────────────────────── */
	.layout-btn {
		display: flex; align-items: center; gap: 4px;
		padding: 4px 10px; border-radius: 6px;
		font-size: 10px; font-weight: 600; color: #6b7280;
		background: none; border: 1px solid transparent;
		cursor: pointer; transition: all 0.15s;
	}
	.layout-btn:hover { color: #d1d5db; background: rgba(255,255,255,0.05); }
	.layout-btn-active { color: #e9d5ff; background: rgba(168,85,247,0.12); border-color: rgba(168,85,247,0.25); }

	/* Rotate arrow icon when details is open */
	details[open] summary .arrow-icon {
		transform: rotate(90deg);
	}
	
	/* KaTeX math rendering styles */
	:global(.katex-block-container) {
		overflow-x: auto;
		overflow-y: hidden;
		max-width: 100%;
		margin: 1rem 0;
		padding: 0.5rem 0;
	}
	
	:global(.katex-block-container .katex) {
		display: block;
		white-space: nowrap;
	}
	
	:global(.katex-inline-container) {
		display: inline-block;
		max-width: 100%;
		overflow-x: auto;
		word-break: break-word;
		vertical-align: middle;
	}
	
	:global(.katex-inline-container .katex) {
		display: inline-block;
		white-space: nowrap;
	}
	
	/* Ensure prose containers handle KaTeX properly */
	:global(.prose .katex-block-container) {
		margin: 1rem 0;
	}
	
	:global(.prose .katex-inline-container) {
		margin: 0 0.2em;
	}

	.src-ref-item .src-snippet {
		max-height: 0;
		overflow: hidden;
		opacity: 0;
		font-size: 0.68rem;
		line-height: 1.45;
		color: rgb(107, 114, 128);
		margin-top: 0;
		transition: max-height 0.22s ease, opacity 0.18s ease, margin-top 0.18s ease;
	}
	.src-ref-item:hover .src-snippet {
		max-height: 6rem;
		opacity: 1;
		margin-top: 2px;
	}

	/* ── Chat bubble markdown overrides ─────────────── */
	/* Scale headings down — prose defaults are too large for sidebar context */
	:global(.chat-bubble-assistant h1),
	:global(.chat-bubble-assistant h2),
	:global(.chat-bubble-assistant h3),
	:global(.chat-bubble-assistant h4),
	:global(.chat-bubble-user h1),
	:global(.chat-bubble-user h2),
	:global(.chat-bubble-user h3),
	:global(.chat-bubble-user h4) {
		font-size: 13px !important;
		font-weight: 700;
		line-height: 1.4;
		margin-top: 10px;
		margin-bottom: 4px;
		color: #e4e4e7;
	}
	:global(.chat-bubble-assistant h1:first-child),
	:global(.chat-bubble-assistant h2:first-child),
	:global(.chat-bubble-assistant h3:first-child) {
		margin-top: 0;
	}
	:global(.chat-bubble-assistant p),
	:global(.chat-bubble-user p) {
		font-size: 13px;
		line-height: 1.6;
		margin-bottom: 6px;
		color: #d4d4d8;
	}
	:global(.chat-bubble-user p) { color: #f3f4f6; }
	:global(.chat-bubble-assistant p:last-child),
	:global(.chat-bubble-user p:last-child) { margin-bottom: 0; }
	:global(.chat-bubble-assistant ul),
	:global(.chat-bubble-assistant ol) {
		padding-left: 16px;
		margin: 5px 0 6px;
		font-size: 13px;
	}
	:global(.chat-bubble-assistant li) {
		margin-bottom: 3px;
		line-height: 1.55;
		color: #c4c4cc;
	}
	:global(.chat-bubble-assistant strong) {
		font-weight: 650;
		color: #e9e9ef;
	}
	:global(.chat-bubble-user strong) {
		font-weight: 650;
		color: #ffffff;
	}
	:global(.chat-bubble-assistant code) {
		font-size: 11.5px;
		background: rgba(255, 255, 255, 0.08);
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 4px;
		padding: 1px 5px;
		font-family: 'DM Mono', monospace;
		color: #c4b5fd;
	}
	:global(.chat-bubble-assistant pre) {
		background: rgba(0, 0, 0, 0.35);
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 8px;
		padding: 10px 12px;
		overflow-x: auto;
		margin: 6px 0;
		font-size: 11.5px;
		line-height: 1.55;
	}
	:global(.chat-bubble-assistant pre code) {
		background: none;
		border: none;
		padding: 0;
		color: #d4d4d8;
	}
	:global(.chat-bubble-assistant blockquote) {
		border-left: 2px solid rgba(139, 92, 246, 0.5);
		padding-left: 10px;
		margin: 6px 0;
		color: #a1a1aa;
		font-style: italic;
		font-size: 12.5px;
	}
	:global(.chat-bubble-assistant hr) {
		border: none;
		border-top: 1px solid rgba(255, 255, 255, 0.08);
		margin: 8px 0;
	}
</style>
