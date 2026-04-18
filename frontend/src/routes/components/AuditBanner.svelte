<script lang="ts">
	import { createEventDispatcher, tick } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { buildAuditFixContext } from '$lib/types/auditFixContext';
	interface AuditCriterionFlag {
		type: string;
		present: boolean;
		adequately_supported: boolean;
		detail: string;
	}

	interface FlagBannerOption {
		category: string;
		label: string;
		banner_text: string;
		rationale: string;
		clinical_context?: string;
	}

	interface AuditCriterion {
		criterion: string;
		status: 'pass' | 'flag' | 'warning';
		rationale: string;
		highlighted_spans: string[];
		recommendation?: string;
		suggested_replacement?: string | null;
		suggested_sentence?: string | null;
		criterion_line?: string | null;
		flags_identified?: AuditCriterionFlag[];
		suggested_banners?: FlagBannerOption[];
		acknowledged?: boolean;
		acknowledged_at?: string;
		resolution_method?: string;
		discrepancies?: Array<{ input_text: string; report_text?: string; type: string; severity: string }>;
		systems_unaddressed?: string[];
		characterisation_gaps?: Array<{ finding: string; missing_features: string[]; guideline_basis: string; severity: string }>;
	}

	interface GuidelineReference {
		system: string;
		context: string;
		type: string;
		source_url?: string | null;
		criteria_summary?: string | null;
		criteria_summary_truncated?: boolean;
		injected: boolean;
	}

	interface AuditResult {
		overall_status: 'pass' | 'flag' | 'warning';
		criteria: AuditCriterion[];
		summary: string;
		guideline_references?: GuidelineReference[];
	}

	interface AuditState {
		status: 'idle' | 'loading' | 'complete' | 'stale' | 'error';
		result: AuditResult | null;
		auditId: string | null;
		error: string | null;
		activeCriterion: string | null;
		phase2Complete?: boolean;
		guidelineLookupFailed?: boolean;
		guidelineCardsCount?: number;
	}

	export let auditState: AuditState;
	export let canReaudit: boolean = false;
	export let showClose: boolean = false;

	const dispatch = createEventDispatcher();

	let expandedCriteria: Set<string> = new Set();
	let criterionRefs: { [key: string]: HTMLElement } = {};
	let retryingGuidelines = false;

	function handleRetryGuidelines() {
		if (retryingGuidelines) return;
		retryingGuidelines = true;
		dispatch('retryGuidelines');
	}

	// Auto-clear the local retrying flag when the store settles — either the
	// retry succeeded (guidelineLookupFailed flips to false) or failed again
	// (stays true but mergePhase2 fires anew). The phase2Complete pulse isn't
	// observable here; rely on a bounded clear via status change or
	// guidelineLookupFailed flip.
	$: if (retryingGuidelines && auditState?.guidelineLookupFailed === false) {
		retryingGuidelines = false;
	}

	const criterionLabels: Record<string, string> = {
		anatomical_accuracy: 'Anatomical Accuracy',
		clinical_relevance: 'Clinical Relevance',
		recommendations: 'Recommendations',
		clinical_flagging: 'Clinical Flagging',
		report_completeness: 'Report Completeness',
		diagnostic_fidelity: 'Diagnostic Fidelity',
		input_fidelity: 'Input Fidelity',
		scan_coverage: 'Scan Coverage',
		characterisation_gap: 'Characterisation Depth',
		language_quality: 'Language Quality',
		laterality: 'Laterality',
		clinical_question: 'Clinical Question',
		actionability: 'Actionability',
		incidental_findings: 'Incidental Findings',
		descriptor_misregistration: 'Descriptor Accuracy',
		systematic_coverage: 'Systematic Coverage',
		comparative_analysis: 'Comparative Analysis',
		confidence_calibration: 'Confidence Calibration'
	};

	const flagTypeLabels: Record<string, string> = {
		critical: 'Critical',
		urgent: 'Urgent',
		significant: 'Significant',
		// Legacy values from older stored audits (pre-3-tier migration)
		malignancy_suspected: 'Suspected New Malignancy',
		malignancy_interval: 'Known Malignancy — Interval',
		suspected_new_malignancy: 'Suspected New Malignancy',
		known_malignancy_interval: 'Known Malignancy — Interval'
	};

	$: flaggedCriteria = auditState.result?.criteria.filter(c => c.status !== 'pass') || [];
	$: pendingCriteria = flaggedCriteria.filter(c => !c.acknowledged);
	$: reviewedCriteria = flaggedCriteria.filter(c => c.acknowledged && c.resolution_method !== 'ai_assisted');
	$: completedCriteria = flaggedCriteria.filter(c => c.acknowledged && c.resolution_method === 'ai_assisted');
	$: clinicalFlaggingCriterion = auditState.result?.criteria?.find((c) => c.criterion === 'clinical_flagging');
	$: suggestedBanners = (clinicalFlaggingCriterion?.suggested_banners || []).filter((b) => b && b.banner_text);
	// When showing the banner panel, exclude clinical_flagging from the criteria list to avoid duplication
	$: pendingCriteriaForList = suggestedBanners.length > 0
		? pendingCriteria.filter((c) => c.criterion !== 'clinical_flagging')
		: pendingCriteria;
	$: flagCount = flaggedCriteria.filter(c => c.status === 'flag').length;
	$: warningCount = flaggedCriteria.filter(c => c.status === 'warning').length;
	$: guidelineReferences = auditState.result?.guideline_references ?? [];

	$: allCriteria = auditState.result?.criteria ?? [];
	$: passedCount = allCriteria.filter((c) => c.status === 'pass' || c.acknowledged).length;
	$: totalCount = allCriteria.length;
	// Severity-weighted score: pass/acknowledged = full credit, unacknowledged
	// warning = partial credit (0.7 — a concern worth attention but not
	// gate-blocking), unacknowledged flag = no credit (needs fixing before
	// sign-off). Equal-weight pass/fail conflated warnings with flags despite
	// very different clinical stakes.
	$: score = (() => {
		if (totalCount === 0) return 0;
		const WARNING_WEIGHT = 0.7;
		const weightedSum = allCriteria.reduce((sum, c) => {
			if (c.status === 'pass' || c.acknowledged) return sum + 1;
			if (c.status === 'warning') return sum + WARNING_WEIGHT;
			return sum; // flag → 0
		}, 0);
		return Math.round((weightedSum / totalCount) * 100);
	})();
	/** Ring accent: rose &lt;70, amber 70–89, emerald ≥90 */
	$: scoreTier = score < 70 ? 'rose' : score < 90 ? 'amber' : 'emerald';
	$: passedCriteriaList = allCriteria.filter((c) => c.status === 'pass');
	$: urgencyLine = (() => {
		const cf = clinicalFlaggingCriterion;
		if (!cf || cf.acknowledged) return '';
		return (
			cf.criterion_line?.trim() ||
			suggestedBanners[0]?.label ||
			suggestedBanners[0]?.banner_text ||
			''
		);
	})();

	function scoreRingCssVars(tier: string, pct: number): string {
		const track = 'rgba(255,255,255,0.04)';
		let arc = '#f43f5e';
		let num = '#fb7185';
		if (tier === 'amber') {
			arc = '#f59e0b';
			num = '#fbbf24';
		} else if (tier === 'emerald') {
			arc = '#10b981';
			num = '#34d399';
		}
		return `--audit-ring-pct:${pct}%;--audit-ring-arc:${arc};--audit-ring-track:${track};--audit-score-num:${num}`;
	}

	function criterionPreviewLine(c: AuditCriterion): string {
		if (c.criterion === 'diagnostic_fidelity') {
			const df = parseDiagnosticFidelityRationale(c.rationale);
			if (df?.length) {
				const worst = df.find((r) => r.status === 'flag') || df.find((r) => r.status === 'warning') || df[0];
				return `${worst.sub}: ${worst.body}`.slice(0, 200);
			}
		}
		return (c.criterion_line || c.rationale || '').trim();
	}

	// GuidelinePanel has moved to the Copilot Guidelines tab. Global strip + openSidebar navigate
	// to the sidebar QA Reference section instead of scrolling within this panel.
	function openGuidelineInSidebar() {
		dispatch('openSidebar', { tab: 'guidelines' });
	}

	// Auto-scroll to active criterion
	$: if (auditState.activeCriterion && criterionRefs[auditState.activeCriterion]) {
		highlightCriterion(auditState.activeCriterion);
	}

	async function highlightCriterion(criterion: string) {
		await tick();
		const el = criterionRefs[criterion];
		if (!el) return;
		el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		// Auto-expand the criterion card
		if (!expandedCriteria.has(criterion)) {
			expandedCriteria = new Set([...expandedCriteria, criterion]);
		}
		el.classList.add('criterion-active-pulse');
		setTimeout(() => el.classList.remove('criterion-active-pulse'), 1200);
	}

	function toggleCriterion(criterion: string) {
		const next = new Set(expandedCriteria);
		if (next.has(criterion)) next.delete(criterion);
		else next.add(criterion);
		expandedCriteria = next;
	}

	function handleAcknowledge(criterion: string, method: 'manual' | 'dismissed') {
		dispatch('acknowledge', { criterion, resolutionMethod: method });
	}

	function handleRestore(criterion: string) {
		dispatch('restore', { criterion });
	}

	function handleSuggestFix(criterion: AuditCriterion) {
		const auditFixContext = buildAuditFixContext(
			auditState.auditId,
			criterion,
			auditState.result?.guideline_references
		);
		dispatch('suggestFix', {
			criterion: criterion.criterion,
			rationale: criterion.rationale,
			auditFixContext
		});
	}

	function handleApplyFix(criterion: AuditCriterion) {
		const original = criterion.highlighted_spans?.[0] ?? null;
		const replacement = criterion.suggested_replacement ?? null;
		const sentence = criterion.suggested_sentence ?? null;
		dispatch('applyFix', {
			criterion: criterion.criterion,
			original,
			replacement,
			sentence,
			source: 'audit_suggested_replacement'
		});
	}

	function handleReaudit() {
		dispatch('reaudit');
	}

	let selectedBannerIndex: number | null = null;
	let bannerInserted = false;
	/** Collapsible clinical-flagging + banner picker (starts collapsed) */
	let flaggingBannerExpanded = false;

	const contextMeta: Record<string, { icon: string; accent: string; badge: string }> = {
		malignancy_new:       { icon: '🔬', accent: 'rgba(239,68,68,0.25)',  badge: 'New malignancy' },
		malignancy_interval:  { icon: '📊', accent: 'rgba(245,158,11,0.25)', badge: 'Interval change' },
		vascular_emergency:   { icon: '🫀', accent: 'rgba(239,68,68,0.3)',   badge: 'Vascular emergency' },
		thromboembolism:      { icon: '🩸', accent: 'rgba(239,68,68,0.25)',  badge: 'Thromboembolism' },
		infection_sepsis:     { icon: '🦠', accent: 'rgba(245,158,11,0.25)', badge: 'Infection / sepsis' },
		bowel_obstruction:    { icon: '⚠️', accent: 'rgba(245,158,11,0.2)', badge: 'Bowel obstruction' },
		cord_compression:     { icon: '⚡', accent: 'rgba(239,68,68,0.3)',   badge: 'Cord compression' },
		haemorrhage_active:   { icon: '🩸', accent: 'rgba(239,68,68,0.3)',   badge: 'Active haemorrhage' },
		fracture_unstable:    { icon: '🦴', accent: 'rgba(245,158,11,0.2)', badge: 'Unstable fracture' },
		organ_ischaemia:      { icon: '⚡', accent: 'rgba(239,68,68,0.25)',  badge: 'Organ ischaemia' },
	};
	function getContextMeta(ctx?: string) {
		if (!ctx) return null;
		return contextMeta[ctx] ?? { icon: '📋', accent: 'rgba(148,163,184,0.15)', badge: ctx.replace(/_/g, ' ') };
	}

	$: if (!suggestedBanners.length || clinicalFlaggingCriterion?.acknowledged) {
		flaggingBannerExpanded = false;
	}

	function handleInsertBanner() {
		if (selectedBannerIndex == null || selectedBannerIndex < 0 || selectedBannerIndex >= suggestedBanners.length) return;
		const banner = suggestedBanners[selectedBannerIndex];
		dispatch('insertBanner', { bannerText: banner.banner_text });
		bannerInserted = true;
		flaggingBannerExpanded = true;
	}

	function handleDismissBanner() {
		dispatch('acknowledge', { criterion: 'clinical_flagging', resolutionMethod: 'dismissed' });
	}

	function toggleFlaggingBanner() {
		flaggingBannerExpanded = !flaggingBannerExpanded;
	}

	function flagTypeColor(type: string): string {
		switch (type) {
			case 'critical': return 'text-rose-400';
			case 'urgent': return 'text-orange-400';
			case 'significant': return 'text-amber-400';
			// Legacy sub-flag types (pre-3-tier migration) — keep for old stored audits
			case 'malignancy_suspected':
			case 'suspected_new_malignancy': return 'text-purple-400';
			case 'malignancy_interval':
			case 'known_malignancy_interval': return 'text-blue-400';
			default: return 'text-gray-400';
		}
	}

	interface DiagnosticFidelityRow {
		letter: string;
		sub: string;
		status: string;
		body: string;
	}

	function parseDiagnosticFidelityRationale(text: string): DiagnosticFidelityRow[] | null {
		const pattern =
			/\(([ab])\)\s*(Certainty|Consistency):\s*(PASS|WARNING|FLAG)\s*[—\-]\s*([^(]+?)(?=\s*\([ab]\)|$)/gi;
		const matches = [...text.matchAll(pattern)];
		if (matches.length < 2) return null;
		return matches.map((m) => ({
			letter: m[1].toLowerCase(),
			sub: m[2],
			status: m[3].toLowerCase(),
			body: m[4].trim()
		}));
	}
</script>

<div class="audit-panel flex flex-col h-full">

	<!-- ── Scrollable Body ──────────────────────────────────────────── -->
	<div class="flex-1 overflow-y-auto overflow-x-hidden min-h-0 px-3.5 py-3 space-y-3 custom-scrollbar audit-scroll">

		<!-- Loading -->
		{#if auditState.status === 'loading'}
			<div class="flex flex-col items-center justify-center py-12 gap-4">
				<div class="relative">
					<div class="w-10 h-10 border-2 border-purple-500/30 rounded-full"></div>
					<div class="absolute inset-0 w-10 h-10 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
				</div>
				<div class="text-center">
					<p class="text-sm text-gray-300 font-medium">Auditing report</p>
					<p class="text-xs text-gray-500 mt-0.5">Evaluating quality criteria…</p>
				</div>
				<!-- Skeleton criteria -->
				<div class="w-full space-y-3 mt-3">
					{#each [1,2,3] as i}
						<div class="h-16 rounded-lg bg-white/[0.03] border border-white/[0.04] animate-pulse" style="animation-delay: {i * 0.1}s"></div>
					{/each}
				</div>
			</div>

		<!-- Error -->
		{:else if auditState.status === 'error'}
			<div class="flex flex-col items-center justify-center py-8 gap-3">
				<div class="w-10 h-10 rounded-full bg-rose-500/10 flex items-center justify-center border border-rose-500/20">
					<svg class="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
				</div>
				<div class="text-center">
					<p class="text-sm text-rose-300 font-medium">Audit failed</p>
					<p class="text-xs text-gray-500 mt-0.5 px-4">{auditState.error || 'Unexpected error'}</p>
				</div>
				{#if canReaudit}
					<button
						class="px-3 py-1.5 text-xs font-semibold text-rose-300 bg-rose-500/15 hover:bg-rose-500/25 rounded-md border border-rose-500/25 transition"
						on:click={handleReaudit}
					>Retry audit</button>
				{/if}
			</div>

		<!-- Complete / stale: score card, urgency, issues, passed -->
		{:else if auditState.status === 'complete' || auditState.status === 'stale'}
			{#if auditState.status === 'stale'}
				<div class="stale-strip" transition:fade={{ duration: 150 }}>
					<div class="stale-strip-inner">
						<svg class="stale-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
						</svg>
						<span class="stale-text">Outdated — unsaved changes</span>
					</div>
					{#if canReaudit}
						<button type="button" class="stale-rerun" on:click={handleReaudit}>Re-run</button>
					{/if}
				</div>
			{/if}

			{#if showClose}
				<div class="flex justify-end">
					<button
						type="button"
						class="audit-close-ghost"
						on:click={() => dispatch('close')}
						aria-label="Close QA panel"
					>
						<svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>
			{/if}

			{#if guidelineReferences.length > 0}
				<div class="guideline-strip">
					<span class="guideline-strip-label">Guidelines</span>
					{#each guidelineReferences as ref, gi (ref.system + '-' + gi)}
						<button
							type="button"
							class="guideline-strip-chip {ref.type === 'uk_pathway' ? 'guideline-strip-chip--cyan' : ''}"
							title="View {ref.system} criteria in Guidelines"
							on:click={openGuidelineInSidebar}
						>
							{ref.system} ↗
						</button>
					{/each}
				</div>
			{/if}

			<!-- Score summary card -->
			<div class="audit-card" class:audit-card--ok={flaggedCriteria.length === 0}>
				<div class="score-ring" style={scoreRingCssVars(scoreTier, score)}>
					<span class="score-num">{score}</span>
				</div>
				<div class="audit-info">
					<div class="audit-title">{flaggedCriteria.length === 0 ? 'All clear' : 'Attention required'}</div>
					<div class="audit-sub">
						{flagCount} flag{flagCount === 1 ? '' : 's'} · {warningCount} warning{warningCount === 1 ? '' : 's'} · {passedCount} passed
					</div>
				</div>
				{#if canReaudit}
					<button type="button" class="reaudit-btn" on:click={handleReaudit}>Re-audit</button>
				{/if}
			</div>

			{#if suggestedBanners.length > 0 && !clinicalFlaggingCriterion?.acknowledged}
				<div class="flagging-accordion" class:flagging-accordion--open={flaggingBannerExpanded}>
					<button
						type="button"
						class="flagging-accordion-trigger"
						class:flagging-accordion-trigger--open={flaggingBannerExpanded}
						aria-expanded={flaggingBannerExpanded}
						aria-controls="flagging-banner-panel"
						id="flagging-banner-trigger"
						on:click={toggleFlaggingBanner}
					>
					<span class="u-icon" aria-hidden="true">{getContextMeta(suggestedBanners[0]?.clinical_context)?.icon ?? '⚡'}</span>
					<span class="flagging-trigger-meta">
						<span class="flagging-trigger-title">{urgencyLine || 'Clinical flagging'}</span>
						<span class="flagging-trigger-sub"
							>Clinical flagging suggested · {flaggingBannerExpanded ? 'Hide options' : 'Add communication banner'}</span
						>
					</span>
						<svg
							class="flagging-trigger-chevron"
							class:flagging-trigger-chevron--open={flaggingBannerExpanded}
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							aria-hidden="true"
						>
							<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
						</svg>
					</button>
					<div
						id="flagging-banner-panel"
						role="region"
						aria-labelledby="flagging-banner-trigger"
						class="flagging-accordion-panel"
						class:flagging-accordion-panel--open={flaggingBannerExpanded}
					>
						<div class="flagging-accordion-inner">
							<div class="flagging-banner-body">
								{#if bannerInserted}
									<div class="flagging-banner-success">
										<svg class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
										</svg>
										<span class="text-[10px] font-medium text-emerald-400">Banner added to report</span>
									</div>
								{:else}
									<div class="flagging-banner-options">
										{#each suggestedBanners as banner, i}
											<label
												class="flagging-banner-option {selectedBannerIndex === i ? 'flagging-banner-option--selected' : ''}"
											>
												<input
													type="radio"
													name="banner-option"
													checked={selectedBannerIndex === i}
													on:change={() => (selectedBannerIndex = i)}
													class="sr-only"
												/>
											<div class="flagging-banner-option-inner" style={banner.clinical_context && getContextMeta(banner.clinical_context) ? `border-left: 2px solid ${getContextMeta(banner.clinical_context)?.accent?.replace(/[\d.]+\)$/, '0.6)')}` : ''}>
												<div class="flagging-banner-option-row">
													<span class="flagging-banner-option-label">{banner.label}</span>
													{#if banner.clinical_context}
														{@const meta = getContextMeta(banner.clinical_context)}
														{#if meta}
															<span class="flagging-context-badge" style="background:{meta.accent}">{meta.icon} {meta.badge}</span>
														{/if}
													{/if}
													{#if selectedBannerIndex === i && banner.rationale}
														<span class="flagging-banner-option-why">{banner.rationale}</span>
													{/if}
												</div>
												<p class="flagging-banner-option-text" title={banner.banner_text}>{banner.banner_text}</p>
											</div>
											</label>
										{/each}
									</div>
									<div class="flagging-banner-actions">
										<button
											type="button"
											class="flagging-btn flagging-btn-primary"
											disabled={selectedBannerIndex == null}
											on:click={handleInsertBanner}
										>
											<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
											</svg>
											Insert selected banner
										</button>
										<button
											type="button"
											class="flagging-btn flagging-btn-secondary"
											on:click={handleDismissBanner}
											title="Dismiss without adding banner"
										>
											Dismiss
										</button>
									</div>
								{/if}
							</div>
						</div>
					</div>
				</div>
			{:else if urgencyLine}
				<div class="urgency-pill">
					<span class="u-icon" aria-hidden="true">⚡</span>
					<span class="u-text">{urgencyLine}</span>
				</div>
			{/if}

			{#if auditState.result && auditState.result.criteria && auditState.result.criteria.length < 9 && auditState.status === 'complete' && !auditState.phase2Complete}
				<div class="flex items-center gap-2 p-2.5 rounded-md bg-blue-500/5 border border-blue-500/10 mb-3">
					<div class="w-3 h-3 rounded-full border-2 border-blue-400/50 border-t-transparent animate-spin flex-shrink-0"></div>
					<p class="text-[10px] text-blue-400/80">{9 - auditState.result.criteria.length} additional criteria evaluating…</p>
				</div>
			{/if}

			{#if auditState.guidelineLookupFailed && auditState.phase2Complete}
				<div class="flex items-center gap-2 p-2.5 rounded-md bg-amber-500/[0.06] border border-amber-500/20 mb-3">
					{#if retryingGuidelines}
						<div class="w-3 h-3 rounded-full border-2 border-amber-400/50 border-t-transparent animate-spin flex-shrink-0"></div>
						<p class="text-[10px] text-amber-300/90 flex-1">Retrying guideline lookup…</p>
					{:else}
						<svg class="w-3 h-3 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M4.93 4.93l14.14 14.14" /></svg>
						<p class="text-[10px] text-amber-300/90 flex-1">Guideline lookup unavailable — assessed against standard reporting practice.</p>
						<button
							type="button"
							class="px-2 py-0.5 rounded text-[10px] font-medium text-amber-200 bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 transition-colors shrink-0"
							on:click={handleRetryGuidelines}
						>Retry</button>
					{/if}
				</div>
			{:else if auditState.phase2Complete && (auditState.guidelineCardsCount ?? 0) === 0}
				<div class="flex items-center gap-2 p-2 rounded-md bg-white/[0.02] border border-white/[0.06] mb-3">
					<svg class="w-3 h-3 text-gray-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
					<p class="text-[10px] text-gray-500/90">No specific guidelines applied — assessed against standard reporting practice.</p>
				</div>
			{/if}

			{#if flaggedCriteria.length === 0}
				<p class="all-clear-hint">No issues found across quality criteria.</p>
			{:else}

			<!-- Pending (unreviewed) criteria -->
			{#each pendingCriteriaForList as criterion (criterion.criterion)}
				{@const isExpanded = expandedCriteria.has(criterion.criterion)}
				<div
					bind:this={criterionRefs[criterion.criterion]}
					class="criterion criterion-wrap {auditState.status === 'stale' ? 'criterion-stale' : ''}"
				>
					<div
						class="criterion-row"
						role="button"
						tabindex="0"
						on:click={() => toggleCriterion(criterion.criterion)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								toggleCriterion(criterion.criterion);
							}
						}}
					>
						<div class="c-dot {criterion.status === 'flag' ? 'dot-flag' : 'dot-warn'}"></div>
						<div class="c-body">
							<div class="c-name">{criterionLabels[criterion.criterion] || criterion.criterion}</div>
							<div class="c-detail">{criterionPreviewLine(criterion)}</div>
						</div>
						<button
							type="button"
							class="fix-btn"
							on:click|stopPropagation={() => handleSuggestFix(criterion)}
						>Fix →</button>
						<svg
							class="criterion-chevron"
							class:criterion-chevron-open={isExpanded}
							fill="none" stroke="currentColor" viewBox="0 0 24 24"
							width="14"
							height="14"
						>
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</div>

					{#if isExpanded}
						<div class="px-3.5 pb-4 pt-3 space-y-4 border-t border-white/[0.05]" transition:fly={{ y: -4, duration: 150 }}>
							{#if criterion.criterion === 'diagnostic_fidelity'}
								{@const dfRows = parseDiagnosticFidelityRationale(criterion.rationale)}
								{#if dfRows}
									<div class="space-y-3">
										{#each dfRows as row}
											<div
												class="pl-2.5 py-1 border-l-2
												{row.status === 'flag'
													? 'border-l-rose-500/50'
													: row.status === 'warning'
														? 'border-l-amber-400/50'
														: 'border-l-emerald-500/30'}"
											>
												<div class="flex items-baseline gap-2 flex-wrap">
													<span class="text-[9px] font-semibold tracking-wider text-gray-500">
														({row.letter}) <span class="capitalize">{row.sub.toLowerCase()}</span>
													</span>
													<span
														class="text-[9px] font-bold tracking-wide
														{row.status === 'flag'
															? 'text-rose-400'
															: row.status === 'warning'
																? 'text-amber-400'
																: 'text-emerald-500/70'}"
													>
														{row.status.toUpperCase()}
													</span>
												</div>
												<p class="text-[11px] text-gray-400 leading-relaxed mt-1.5">{row.body}</p>
											</div>
										{/each}
									</div>
								{:else}
									<p class="text-[11px] text-gray-400 leading-relaxed">{criterion.rationale}</p>
								{/if}
							{:else}
								<p class="text-[11px] text-gray-400 leading-relaxed">{criterion.rationale}</p>
							{/if}

							{#if criterion.criterion_line}
								<p
									class="text-[11px] text-cyan-300/80 leading-relaxed border-l-2 border-cyan-500/40 pl-2"
								>
									{criterion.criterion_line}
								</p>
							{:else if criterion.recommendation}
								<div class="flex gap-2.5 p-3 rounded-md bg-white/[0.03] border border-white/[0.05]">
									<svg class="w-3 h-3 text-purple-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
									<p class="text-[10px] text-gray-400 leading-relaxed">{criterion.recommendation}</p>
								</div>
							{/if}

							{#if criterion.criterion === 'clinical_flagging' && criterion.flags_identified && criterion.flags_identified.length > 0}
								<div class="space-y-2 pt-1">
									<p class="text-[9px] text-gray-600 uppercase tracking-wider font-semibold">Clinical flags</p>
									{#each criterion.flags_identified as flag}
										{#if flag.present}
											<div class="flex items-start gap-2.5 p-2.5 rounded-md bg-white/[0.02] border border-white/[0.04]">
												<div class="w-1 h-1 rounded-full {flagTypeColor(flag.type).replace('text-', 'bg-')} mt-1.5 flex-shrink-0"></div>
												<div class="min-w-0">
													<span class="text-[10px] font-semibold {flagTypeColor(flag.type)}">{flagTypeLabels[flag.type] || flag.type}</span>
													{#if !flag.adequately_supported}
														<span class="ml-1 text-[9px] text-amber-400/70">(language insufficient)</span>
													{/if}
													{#if flag.detail}
														<p class="text-[10px] text-gray-500 mt-1 leading-relaxed">{flag.detail}</p>
													{/if}
												</div>
											</div>
										{/if}
									{/each}
								</div>
							{/if}

							{#if criterion.criterion === 'input_fidelity' && criterion.discrepancies && criterion.discrepancies.length > 0}
								<div class="space-y-2 pt-1">
									<p class="text-[9px] text-gray-600 uppercase tracking-wider font-semibold">Discrepancies</p>
									{#each criterion.discrepancies as disc}
										<div class="p-2.5 rounded-md bg-white/[0.02] border border-white/[0.04]">
											<div class="flex items-center gap-2 mb-1">
												<span class="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded {disc.severity === 'significant' ? 'bg-red-500/15 text-red-400' : 'bg-amber-500/15 text-amber-400'}">{disc.type.replace('_', ' ')}</span>
												<span class="text-[9px] text-gray-600">{disc.severity}</span>
											</div>
											<p class="text-[10px] text-gray-400"><span class="text-gray-500">Input:</span> {disc.input_text}</p>
											{#if disc.report_text}
												<p class="text-[10px] text-gray-400 mt-0.5"><span class="text-gray-500">Report:</span> {disc.report_text}</p>
											{/if}
										</div>
									{/each}
								</div>
							{/if}

							{#if criterion.criterion === 'scan_coverage' && criterion.systems_unaddressed && criterion.systems_unaddressed.length > 0}
								<div class="pt-1">
									<p class="text-[9px] text-gray-600 uppercase tracking-wider font-semibold mb-1.5">Systems unaddressed</p>
									<div class="flex flex-wrap gap-1.5">
										{#each criterion.systems_unaddressed as sys}
											<span class="text-[9px] px-2 py-1 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">{sys}</span>
										{/each}
									</div>
								</div>
							{/if}

							{#if criterion.criterion === 'characterisation_gap' && criterion.characterisation_gaps && criterion.characterisation_gaps.length > 0}
								<div class="space-y-2 pt-1">
									<p class="text-[9px] text-gray-600 uppercase tracking-wider font-semibold">Characterisation gaps</p>
									{#each criterion.characterisation_gaps as gap}
										<div class="p-2.5 rounded-md bg-white/[0.02] border border-white/[0.04]">
											<p class="text-[10px] font-medium text-gray-300 mb-1">{gap.finding}</p>
											<div class="flex flex-wrap gap-1 mb-1.5">
												{#each gap.missing_features as feat}
													<span class="text-[9px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/15">{feat}</span>
												{/each}
											</div>
											<p class="text-[9px] text-gray-600">Basis: {gap.guideline_basis}</p>
										</div>
									{/each}
								</div>
							{/if}

					<div class="flex flex-col gap-1.5 pt-2 border-t border-white/[0.04] mt-1">
						{#if criterion.suggested_replacement || criterion.suggested_sentence}
							<!-- Apply fix: full-width primary row -->
							<button
								class="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-md bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 hover:border-blue-500/40 text-blue-400 transition-all"
								on:click|stopPropagation={() => handleApplyFix(criterion)}
								title="Apply suggested fix to report"
							>
								<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
								</svg>
								<span class="text-[10px] font-semibold whitespace-nowrap">Apply fix</span>
							</button>
							<!-- Secondary row: Reviewed + Fix with AI -->
							<div class="flex items-center gap-1.5">
								<button
									class="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 hover:border-emerald-500/40 text-emerald-400 transition-all"
									on:click|stopPropagation={() => handleAcknowledge(criterion.criterion, 'manual')}
									title="Mark as reviewed"
								>
									<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
									</svg>
									<span class="text-[10px] font-semibold whitespace-nowrap">Reviewed</span>
								</button>
								<button
									class="flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-md bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] hover:border-white/[0.12] text-gray-500 hover:text-gray-300 transition-all"
									on:click|stopPropagation={() => handleSuggestFix(criterion)}
									title="Fix with AI in chat"
								>
									<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
									</svg>
									<span class="text-[10px] text-gray-500 whitespace-nowrap">AI</span>
								</button>
							</div>
						{:else}
							<!-- No instant fix available: single row -->
							<div class="flex items-center gap-1.5">
								<button
									class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 hover:border-emerald-500/40 text-emerald-400 transition-all"
									on:click|stopPropagation={() => handleAcknowledge(criterion.criterion, 'manual')}
									title="Mark as reviewed"
								>
									<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
									</svg>
									<span class="text-[10px] font-semibold">Reviewed</span>
								</button>
								<button
									class="flex-1 flex items-center justify-center gap-1.5 px-2 py-2 rounded-md bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 hover:border-purple-500/40 text-purple-400 transition-all"
									on:click|stopPropagation={() => handleSuggestFix(criterion)}
									title="Fix with AI in chat"
								>
									<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
									</svg>
									<span class="text-[10px] font-semibold">Fix with AI</span>
								</button>
							</div>
						{/if}
					</div>
						</div>
					{/if}
				</div>
			{/each}
			{/if}

			<!-- Passed criteria (prototype PASSED divider) -->
			{#if passedCriteriaList.length > 0}
				<div class="divider">
					<div class="div-line"></div>
					<span class="div-text">Passed</span>
					<div class="div-line"></div>
				</div>
			{#each passedCriteriaList as pc (pc.criterion)}
				{@const isPassExpanded = expandedCriteria.has(pc.criterion)}
				<div class="criterion-wrap criterion-passed-wrap">
					<!-- svelte-ignore a11y-no-static-element-interactions -->
					<div
						class="criterion-row criterion-passed-row"
						role="button"
						tabindex="0"
						on:click={() => toggleCriterion(pc.criterion)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								toggleCriterion(pc.criterion);
							}
						}}
					>
						<div class="c-dot dot-pass"></div>
						<div class="c-body">
							<div class="c-name c-name-passed">{criterionLabels[pc.criterion] || pc.criterion}</div>
						</div>
						<svg
							class="criterion-chevron criterion-chevron-pass"
							class:criterion-chevron-open={isPassExpanded}
							fill="none" stroke="currentColor" viewBox="0 0 24 24"
							width="12" height="12"
							aria-hidden="true"
						>
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</div>
					{#if isPassExpanded && pc.rationale}
						<div class="pass-expand-body" transition:fly={{ y: -4, duration: 150 }}>
							<p class="pass-expand-text">{pc.rationale}</p>
						</div>
					{/if}
				</div>
			{/each}
			{/if}

			<!-- Completed section (Fix was clicked) -->
			{#if completedCriteria.length > 0}
				<div class="mt-4" transition:fade={{ duration: 200 }}>
					<div class="flex items-center gap-2 mb-3">
						<div class="flex-1 h-px bg-white/[0.06]"></div>
						<span class="text-[9px] uppercase tracking-widest font-semibold text-purple-500/80">Completed</span>
						<div class="flex-1 h-px bg-white/[0.06]"></div>
					</div>
					<div class="space-y-2">
						{#each completedCriteria as criterion (criterion.criterion)}
							<div
								bind:this={criterionRefs[criterion.criterion]}
								class="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-purple-500/[0.06] border border-purple-500/20 opacity-80 hover:opacity-100 transition-opacity duration-200"
							>
								<svg class="w-3 h-3 text-purple-400/80 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
								</svg>
								<span class="text-[10px] text-purple-300/90 flex-1 truncate">
									{criterionLabels[criterion.criterion] || criterion.criterion}
								</span>
								<button
									class="flex-shrink-0 p-1 rounded text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] transition-all"
									on:click|stopPropagation={() => handleRestore(criterion.criterion)}
									title="Restore to pending"
								>
									<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
									</svg>
								</button>
							</div>
						{/each}
					</div>
				</div>
			{/if}
			<!-- Reviewed section (manual/dismissed) -->
			{#if reviewedCriteria.length > 0}
				<div class="mt-4" transition:fade={{ duration: 200 }}>
					<div class="flex items-center gap-2 mb-3">
						<div class="flex-1 h-px bg-white/[0.06]"></div>
						<span class="text-[9px] uppercase tracking-widest font-semibold text-gray-600">Reviewed</span>
						<div class="flex-1 h-px bg-white/[0.06]"></div>
					</div>
					<div class="space-y-2">
						{#each reviewedCriteria as criterion (criterion.criterion)}
							<div
								bind:this={criterionRefs[criterion.criterion]}
								class="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-white/[0.01] border border-white/[0.04] opacity-60 hover:opacity-80 transition-opacity duration-200"
							>
								<svg class="w-3 h-3 text-emerald-500/60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
								</svg>
								<span class="text-[10px] text-gray-500 flex-1 truncate">
									{criterionLabels[criterion.criterion] || criterion.criterion}
								</span>
								<button
									class="flex-shrink-0 p-1 rounded text-gray-600 hover:text-gray-300 hover:bg-white/[0.06] transition-all"
									on:click|stopPropagation={() => handleRestore(criterion.criterion)}
									title="Restore to pending"
								>
									<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
									</svg>
								</button>
							</div>
						{/each}
					</div>
				</div>
			{/if}

		<!-- GUIDELINE PANEL TEMPORARILY COMMENTED — Guideline Panel Consolidation
		     Reference guidelines have moved to the Copilot Guidelines tab (QA Reference section).
		     See ReportEnhancementSidebar QA Reference section (step 3 of consolidation).
		     Safe to delete once step 3 verified in staging — 2026-03-31
		<GuidelinePanel references={guidelineReferences} /> -->
	{/if}
	</div>

	<!-- ── Footer (governance note only — Re-audit is on the score card) ── -->
	{#if auditState.status === 'complete' || auditState.status === 'stale'}
		<div class="audit-footer-note">
			Flags are logged for governance review
		</div>
	{/if}
</div>

<style>
	.audit-panel {
		--bg: #060608;
		--surface: #0d0d12;
		--surface2: #13131b;
		--border: rgba(255, 255, 255, 0.07);
		--border2: rgba(255, 255, 255, 0.13);
		--purple: #8b5cf6;
		--text: #e2e2e8;
		--text-dim: #71717a;
		--text-muted: #3f3f46;
		--rose: #f43f5e;
		--amber: #f59e0b;
		--emerald: #10b981;
		background: var(--bg);
		font-family: 'DM Sans', system-ui, sans-serif;
		color: var(--text);
	}

	.audit-scroll {
		scrollbar-width: thin;
		scrollbar-color: rgba(255, 255, 255, 0.07) transparent;
	}
	.audit-scroll::-webkit-scrollbar {
		width: 3px;
	}
	.audit-scroll::-webkit-scrollbar-thumb {
		background: rgba(255, 255, 255, 0.07);
		border-radius: 2px;
	}

	.stale-strip {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 8px 10px;
		border-radius: 9px;
		background: rgba(245, 158, 11, 0.08);
		border: 1px solid rgba(245, 158, 11, 0.2);
		margin-bottom: 4px;
	}
	.stale-strip-inner {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.stale-icon {
		width: 14px;
		height: 14px;
		color: #fbbf24;
		flex-shrink: 0;
	}
	.stale-text {
		font-size: 10px;
		color: rgba(253, 224, 71, 0.85);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.stale-rerun {
		font-size: 10px;
		font-weight: 600;
		color: #fcd34d;
		background: none;
		border: none;
		cursor: pointer;
		flex-shrink: 0;
		font-family: inherit;
	}
	.stale-rerun:hover {
		color: #fde68a;
	}

	.audit-close-ghost {
		padding: 6px;
		border-radius: 7px;
		border: 1px solid var(--border);
		background: transparent;
		color: var(--text-dim);
		cursor: pointer;
	}
	.audit-close-ghost:hover {
		background: rgba(255, 255, 255, 0.06);
		color: #fff;
	}

	.guideline-strip {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		padding: 4px 0 8px;
	}
	.guideline-strip-label {
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-muted);
	}
	.guideline-strip-chip {
		padding: 2px 8px;
		border-radius: 6px;
		font-size: 10px;
		font-weight: 600;
		border: 1px solid var(--border);
		background: rgba(255, 255, 255, 0.04);
		color: var(--text-dim);
		cursor: pointer;
		font-family: inherit;
		transition: background 0.15s, color 0.15s;
	}
	.guideline-strip-chip:hover {
		background: rgba(255, 255, 255, 0.07);
		color: var(--text);
	}
	.guideline-strip-chip--cyan {
		background: rgba(6, 182, 212, 0.1);
		border-color: rgba(6, 182, 212, 0.2);
		color: #67e8f9;
	}

	.audit-card {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 14px;
		border-radius: 12px;
		background: rgba(244, 63, 94, 0.05);
		border: 1px solid rgba(244, 63, 94, 0.13);
		margin-bottom: 12px;
		flex-wrap: wrap;
	}
	.audit-card--ok {
		background: rgba(16, 185, 129, 0.06);
		border-color: rgba(16, 185, 129, 0.18);
	}

	.score-ring {
		width: 46px;
		height: 46px;
		border-radius: 50%;
		flex-shrink: 0;
		background: conic-gradient(
			var(--audit-ring-arc) 0% var(--audit-ring-pct),
			var(--audit-ring-track) var(--audit-ring-pct) 100%
		);
		display: flex;
		align-items: center;
		justify-content: center;
		position: relative;
	}
	.score-ring::before {
		content: '';
		position: absolute;
		inset: 5px;
		border-radius: 50%;
		background: rgba(6, 6, 10, 0.98);
	}
	.score-num {
		position: relative;
		z-index: 1;
		font-size: 13px;
		font-weight: 800;
		color: var(--audit-score-num, #fb7185);
		font-family: 'DM Mono', monospace;
	}

	.audit-info {
		flex: 1;
		min-width: 0;
	}
	.audit-title {
		font-size: 12.5px;
		font-weight: 600;
		color: #fff;
		margin-bottom: 2px;
	}
	.audit-sub {
		font-size: 10.5px;
		color: var(--text-dim);
	}

	.reaudit-btn {
		padding: 4px 10px;
		border-radius: 7px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(255, 255, 255, 0.04);
		color: var(--text-dim);
		font-size: 10px;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.15s;
		font-family: inherit;
		align-self: flex-start;
	}
	.reaudit-btn:hover {
		background: rgba(255, 255, 255, 0.08);
		color: #fff;
	}

	.urgency-pill {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 8px 11px;
		border-radius: 9px;
		background: rgba(245, 158, 11, 0.07);
		border: 1px solid rgba(245, 158, 11, 0.18);
		margin-bottom: 12px;
	}
	.u-icon {
		font-size: 12px;
	}
	.u-text {
		font-size: 11px;
		font-weight: 500;
		color: #fbbf24;
		line-height: 1.35;
	}

	/* Clinical flagging: urgency header + animated banner picker */
	.flagging-accordion {
		margin-bottom: 12px;
		border-radius: 10px;
		border: 1px solid rgba(245, 158, 11, 0.22);
		background: rgba(245, 158, 11, 0.05);
		overflow: hidden;
		transition: border-color 0.2s ease, box-shadow 0.2s ease;
	}
	.flagging-accordion--open {
		border-color: rgba(245, 158, 11, 0.32);
		box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.06);
	}

	.flagging-accordion-trigger {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 10px 12px;
		border: none;
		background: transparent;
		cursor: pointer;
		text-align: left;
		font-family: inherit;
		color: inherit;
		transition: background 0.15s ease;
	}
	.flagging-accordion-trigger:hover {
		background: rgba(245, 158, 11, 0.06);
	}
	.flagging-accordion-trigger--open {
		background: rgba(245, 158, 11, 0.08);
		border-bottom: 1px solid rgba(245, 158, 11, 0.15);
	}

	.flagging-trigger-meta {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.flagging-trigger-title {
		font-size: 11px;
		font-weight: 600;
		color: #fbbf24;
		line-height: 1.35;
	}
	.flagging-trigger-sub {
		font-size: 9px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: rgba(251, 191, 36, 0.55);
	}

	.flagging-trigger-chevron {
		flex-shrink: 0;
		color: rgba(251, 191, 36, 0.65);
		transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
		margin-top: 2px;
	}
	.flagging-trigger-chevron--open {
		transform: rotate(180deg);
	}

	.flagging-accordion-panel {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.38s cubic-bezier(0.4, 0, 0.2, 1);
	}
	.flagging-accordion-panel--open {
		grid-template-rows: 1fr;
	}

	.flagging-accordion-inner {
		overflow: hidden;
		min-height: 0;
	}

	.flagging-banner-body {
		padding: 8px 12px 10px;
		border-top: 1px solid rgba(245, 158, 11, 0.1);
		background: rgba(6, 6, 10, 0.3);
	}

	.flagging-banner-success {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 7px 10px;
		border-radius: 7px;
		background: rgba(16, 185, 129, 0.08);
		border: 1px solid rgba(16, 185, 129, 0.18);
	}

	.flagging-banner-options {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.flagging-banner-option {
		display: block;
		cursor: pointer;
		border-radius: 7px;
		border: 1px solid rgba(255, 255, 255, 0.05);
		background: rgba(255, 255, 255, 0.02);
		transition: background 0.15s, border-color 0.15s;
	}
	.flagging-banner-option:hover {
		background: rgba(255, 255, 255, 0.04);
		border-color: rgba(255, 255, 255, 0.09);
	}
	.flagging-banner-option--selected {
		background: rgba(245, 158, 11, 0.08);
		border-color: rgba(245, 158, 11, 0.28);
	}
	.flagging-banner-option-inner {
		padding: 7px 10px;
	}
	.flagging-banner-option-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 4px;
		min-width: 0;
	}
	.flagging-banner-option-label {
		font-size: 10px;
		font-weight: 600;
		color: rgba(253, 224, 71, 0.9);
		white-space: normal;
		word-break: break-word;
		line-height: 1.4;
	}
	.flagging-context-badge {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 8.5px;
		font-weight: 500;
		padding: 1px 6px;
		border-radius: 3px;
		color: rgba(255, 255, 255, 0.75);
		white-space: nowrap;
		width: fit-content;
		line-height: 1.5;
		letter-spacing: 0.01em;
	}
	.flagging-banner-option-text {
		font-size: 9px;
		font-family: 'DM Mono', ui-monospace, monospace;
		color: rgba(161, 161, 170, 0.7);
		line-height: 1.35;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}
	.flagging-banner-option--selected .flagging-banner-option-text {
		white-space: normal;
		overflow: visible;
		text-overflow: unset;
	}
	.flagging-banner-option-why {
		font-size: 9px;
		color: rgba(161, 161, 170, 0.6);
		line-height: 1.4;
	}

	.flagging-banner-actions {
		display: flex;
		gap: 6px;
		margin-top: 8px;
		flex-wrap: wrap;
	}
	.flagging-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 5px;
		padding: 5px 10px;
		border-radius: 7px;
		font-size: 9.5px;
		font-weight: 600;
		font-family: inherit;
		cursor: pointer;
		transition: opacity 0.15s, background 0.15s, border-color 0.15s;
		border: 1px solid transparent;
	}
	.flagging-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.flagging-btn-primary {
		flex: 1;
		min-width: 120px;
		background: rgba(245, 158, 11, 0.14);
		border-color: rgba(245, 158, 11, 0.28);
		color: #fcd34d;
	}
	.flagging-btn-primary:hover:not(:disabled) {
		background: rgba(245, 158, 11, 0.28);
	}
	.flagging-btn-secondary {
		background: rgba(255, 255, 255, 0.05);
		border-color: rgba(255, 255, 255, 0.1);
		color: var(--text-dim);
	}
	.flagging-btn-secondary:hover {
		background: rgba(255, 255, 255, 0.08);
		color: var(--text);
	}

	.all-clear-hint {
		font-size: 11px;
		color: var(--text-dim);
		text-align: center;
		padding: 8px 0 4px;
	}

	.criterion-wrap {
		display: flex;
		flex-direction: column;
		margin-bottom: 6px;
		border-radius: 10px;
		border: 1px solid var(--border);
		background: var(--surface);
		overflow: hidden;
		transition: border-color 0.15s, background 0.15s;
	}
	.criterion-wrap:hover {
		border-color: var(--border2);
		background: var(--surface2);
	}
	.criterion-stale {
		filter: saturate(0.92);
	}

	.criterion-row {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 10px 12px;
		cursor: pointer;
		user-select: none;
		text-align: left;
		width: 100%;
		box-sizing: border-box;
		background: none;
		border: none;
		color: inherit;
		font-family: inherit;
	}
	.c-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		margin-top: 5px;
		flex-shrink: 0;
	}
	.dot-flag {
		background: var(--rose);
		box-shadow: 0 0 7px rgba(244, 63, 94, 0.6);
	}
	.dot-warn {
		background: var(--amber);
		box-shadow: 0 0 7px rgba(245, 158, 11, 0.5);
	}
	.dot-pass {
		background: var(--emerald);
	}
	.c-body {
		flex: 1;
		min-width: 0;
	}
	.c-name {
		font-size: 11.5px;
		font-weight: 600;
		color: var(--text);
		margin-bottom: 2px;
	}
	.c-detail {
		font-size: 10.5px;
		color: var(--text-dim);
		line-height: 1.5;
		display: -webkit-box;
		line-clamp: 2;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.fix-btn {
		padding: 3px 9px;
		border-radius: 6px;
		border: 1px solid rgba(139, 92, 246, 0.28);
		background: rgba(139, 92, 246, 0.1);
		color: #c4b5fd;
		font-size: 9.5px;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
		flex-shrink: 0;
		transition: all 0.15s;
		font-family: inherit;
		margin-top: 2px;
	}
	.fix-btn:hover {
		background: rgba(139, 92, 246, 0.22);
		color: #fff;
	}

	.criterion-chevron {
		flex-shrink: 0;
		margin-top: 4px;
		color: var(--text-muted);
		transition: transform 0.2s;
	}
	.criterion-chevron-open {
		transform: rotate(180deg);
	}

	/* Passed criteria — expandable to show rationale */
	.criterion-passed-wrap {
		opacity: 0.5;
		transition: opacity 0.15s, border-color 0.15s, background 0.15s;
	}
	.criterion-passed-wrap:hover {
		opacity: 0.8;
		border-color: rgba(16, 185, 129, 0.18);
		background: rgba(16, 185, 129, 0.03);
	}
	.criterion-passed-row {
		padding: 8px 10px;
	}
	.c-name-passed {
		color: var(--text-dim);
		font-weight: 500;
	}
	.criterion-chevron-pass {
		margin-top: 2px;
		opacity: 0.5;
	}
	.pass-expand-body {
		padding: 8px 12px 10px;
		border-top: 1px solid rgba(16, 185, 129, 0.08);
		background: rgba(16, 185, 129, 0.025);
	}
	.pass-expand-text {
		font-size: 10.5px;
		color: #71717a;
		line-height: 1.55;
	}

	.divider {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 12px 0 8px;
	}
	.div-line {
		flex: 1;
		height: 1px;
		background: var(--border);
	}
	.div-text {
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--text-muted);
	}

	.audit-footer-note {
		flex-shrink: 0;
		padding: 10px 14px 12px;
		border-top: 1px solid var(--border);
		font-size: 9px;
		color: var(--text-muted);
		text-align: center;
		line-height: 1.4;
	}

	:global(.criterion-active-pulse) {
		animation: criterionPulse 1.2s ease-out forwards;
	}

	@keyframes criterionPulse {
		0% {
			box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.35);
		}
		40% {
			box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.15);
		}
		100% {
			box-shadow: 0 0 0 0 rgba(139, 92, 246, 0);
		}
	}
</style>
