<script lang="ts">
	import { createEventDispatcher, tick } from 'svelte';
	import { fly, fade } from 'svelte/transition';

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
	}

	interface AuditCriterion {
		criterion: string;
		status: 'pass' | 'flag' | 'warning';
		rationale: string;
		highlighted_spans: string[];
		recommendation?: string;
		flags_identified?: AuditCriterionFlag[];
		suggested_banners?: FlagBannerOption[];
		acknowledged?: boolean;
		acknowledged_at?: string;
		resolution_method?: string;
	}

	interface AuditResult {
		overall_status: 'pass' | 'flag' | 'warning';
		criteria: AuditCriterion[];
		summary: string;
	}

	interface AuditState {
		status: 'idle' | 'loading' | 'complete' | 'stale' | 'error';
		result: AuditResult | null;
		auditId: string | null;
		error: string | null;
		activeCriterion: string | null;
	}

	export let auditState: AuditState;
	export let canReaudit: boolean = false;
	export let showClose: boolean = false;

	const dispatch = createEventDispatcher();

	let expandedCriteria: Set<string> = new Set();
	let criterionRefs: { [key: string]: HTMLElement } = {};

	const criterionLabels: Record<string, string> = {
		anatomical_accuracy: 'Anatomical Accuracy',
		clinical_relevance: 'Clinical Relevance',
		recommendations: 'Recommendations',
		clinical_flagging: 'Clinical Flagging',
		report_completeness: 'Report Completeness',
		language_quality: 'Language Quality',
		// Legacy labels for older stored audits
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
	$: unacknowledgedCount = pendingCriteria.length;
	$: flagCount = flaggedCriteria.filter(c => c.status === 'flag').length;
	$: warningCount = flaggedCriteria.filter(c => c.status === 'warning').length;

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
		dispatch('suggestFix', { criterion: criterion.criterion, rationale: criterion.rationale });
	}

	function handleReaudit() {
		dispatch('reaudit');
	}

	let selectedBannerIndex: number | null = null;
	let bannerInserted = false;

	function handleInsertBanner() {
		if (selectedBannerIndex == null || selectedBannerIndex < 0 || selectedBannerIndex >= suggestedBanners.length) return;
		const banner = suggestedBanners[selectedBannerIndex];
		dispatch('insertBanner', { bannerText: banner.banner_text });
		bannerInserted = true;
	}

	function handleDismissBanner() {
		dispatch('acknowledge', { criterion: 'clinical_flagging', resolutionMethod: 'dismissed' });
	}

	function getStatusDot(status: string): string {
		switch (status) {
			case 'flag': return 'bg-rose-500';
			case 'warning': return 'bg-amber-400';
			default: return 'bg-gray-500';
		}
	}

	function getStatusBorder(status: string): string {
		switch (status) {
			case 'flag': return 'border-l-rose-500/60';
			case 'warning': return 'border-l-amber-400/60';
			default: return 'border-l-gray-600/40';
		}
	}

	function getStatusPill(status: string): string {
		switch (status) {
			case 'flag': return 'bg-rose-500/15 text-rose-300 border-rose-500/25';
			case 'warning': return 'bg-amber-400/15 text-amber-300 border-amber-400/25';
			default: return 'bg-gray-500/15 text-gray-400 border-gray-500/25';
		}
	}

	function flagTypeColor(type: string): string {
		switch (type) {
			case 'critical': return 'text-rose-400';
			case 'urgent': return 'text-orange-400';
			case 'significant': return 'text-amber-400';
			case 'suspected_new_malignancy': return 'text-purple-400';
			case 'known_malignancy_interval': return 'text-blue-400';
			default: return 'text-gray-400';
		}
	}
</script>

<div class="audit-panel flex flex-col h-full">

	<!-- ── Panel Header ─────────────────────────────────────────────── -->
	<div class="flex-shrink-0 px-4 py-3 border-b border-white/[0.06]">
		<div class="flex items-center justify-between mb-2">
			<div class="flex items-center gap-2">
				<div class="w-6 h-6 rounded-md bg-purple-500/20 flex items-center justify-center">
					<svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
					</svg>
				</div>
				<span class="text-xs font-semibold text-white/80 uppercase tracking-wider">Report QA</span>
			</div>

		<div class="flex items-center gap-1.5">
			{#if auditState.status === 'loading'}
				<div class="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
				<span class="text-[10px] text-gray-500">Analysing…</span>
			{:else if auditState.status === 'complete' || auditState.status === 'stale'}
				{#if flagCount > 0}
					<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-500/15 text-rose-300 border border-rose-500/25">
						{flagCount} flag{flagCount > 1 ? 's' : ''}
					</span>
				{/if}
				{#if warningCount > 0}
					<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-400/15 text-amber-300 border border-amber-400/25">
						{warningCount} warn{warningCount > 1 ? 's' : ''}
					</span>
				{/if}
				{#if flagCount === 0 && warningCount === 0}
					<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
						Clear
					</span>
				{/if}
			{/if}
			{#if showClose}
				<button
					type="button"
					class="ml-1 p-1 rounded-md text-gray-500 hover:text-white hover:bg-white/10 transition-colors"
					on:click={() => dispatch('close')}
					aria-label="Close QA panel"
				>
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			{/if}
		</div>
	</div>

		<!-- Stale notice -->
		{#if auditState.status === 'stale'}
			<div class="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md bg-amber-500/10 border border-amber-500/20 mt-1" transition:fade={{ duration: 150 }}>
				<div class="flex items-center gap-1.5 min-w-0">
					<svg class="w-3 h-3 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
					</svg>
					<span class="text-[10px] text-amber-300/80 truncate">Outdated — unsaved changes</span>
				</div>
				{#if canReaudit}
					<button
						class="text-[10px] font-semibold text-amber-300 hover:text-amber-200 flex-shrink-0 transition-colors"
						on:click={handleReaudit}
					>Re-run</button>
				{/if}
			</div>
		{/if}
	</div>

	<!-- ── Scrollable Body ──────────────────────────────────────────── -->
	<div class="flex-1 overflow-y-auto overflow-x-hidden min-h-0 px-3 py-3 space-y-2 custom-scrollbar">

		<!-- Loading -->
		{#if auditState.status === 'loading'}
			<div class="flex flex-col items-center justify-center py-12 gap-4">
				<div class="relative">
					<div class="w-10 h-10 border-2 border-purple-500/30 rounded-full"></div>
					<div class="absolute inset-0 w-10 h-10 border-2 border-purple-400 border-t-transparent rounded-full animate-spin"></div>
				</div>
				<div class="text-center">
					<p class="text-sm text-gray-300 font-medium">Auditing report</p>
					<p class="text-xs text-gray-500 mt-0.5">Evaluating 6 quality criteria…</p>
				</div>
				<!-- Skeleton criteria -->
				<div class="w-full space-y-2 mt-2">
					{#each [1,2,3] as i}
						<div class="h-14 rounded-lg bg-white/[0.03] border border-white/[0.04] animate-pulse" style="animation-delay: {i * 0.1}s"></div>
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

		<!-- All clear -->
		{:else if (auditState.status === 'complete' || auditState.status === 'stale') && flaggedCriteria.length === 0}
			<div class="flex flex-col items-center justify-center py-10 gap-3">
				<div class="w-10 h-10 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
					<svg class="w-5 h-5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
				</div>
				<div class="text-center">
					<p class="text-sm text-emerald-400 font-semibold">All clear</p>
					<p class="text-xs text-gray-500 mt-0.5">No issues found across 6 criteria</p>
				</div>
			</div>

		<!-- Criteria list (with optional Flag Banner Panel) -->
		{:else if auditState.status === 'complete' || auditState.status === 'stale'}

			<!-- Flag Banner Panel - when clinical_flagging has suggested banners -->
			{#if suggestedBanners.length > 0 && !clinicalFlaggingCriterion?.acknowledged}
				<div class="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 mb-3 space-y-2.5">
					<div class="flex items-center gap-2">
						<svg class="w-4 h-4 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
						</svg>
						<span class="text-[10px] font-semibold text-amber-300 uppercase tracking-wider">Clinical Flagging Suggested</span>
					</div>
					<p class="text-[10px] text-gray-400 leading-relaxed">This report may warrant a communication banner. Select one to add to the end of the report:</p>
					{#if bannerInserted}
						<div class="flex items-center gap-2 p-2 rounded-md bg-emerald-500/10 border border-emerald-500/20">
							<svg class="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
							</svg>
							<span class="text-[10px] font-medium text-emerald-400">Banner added to report</span>
						</div>
					{:else}
						<div class="space-y-1.5">
							{#each suggestedBanners as banner, i}
								<label
									class="flex items-start gap-2 p-2 rounded-md cursor-pointer transition-colors {selectedBannerIndex === i ? 'bg-amber-500/15 border border-amber-500/30' : 'bg-white/[0.03] border border-white/[0.05] hover:bg-white/[0.05]'}"
								>
									<input
										type="radio"
										name="banner-option"
										checked={selectedBannerIndex === i}
										on:change={() => (selectedBannerIndex = i)}
										class="sr-only"
									/>
									<div class="flex-1 min-w-0">
										<span class="text-[10px] font-semibold text-amber-300/90">{banner.label}</span>
										<p class="text-[9px] text-gray-500 mt-0.5 font-mono truncate" title={banner.banner_text}>{banner.banner_text}</p>
										{#if banner.rationale}
											<p class="text-[9px] text-gray-500 mt-0.5 leading-relaxed">Why: {banner.rationale}</p>
										{/if}
									</div>
								</label>
							{/each}
						</div>
						<div class="flex gap-1.5">
							<button
								type="button"
								class="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-300 text-[10px] font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
								disabled={selectedBannerIndex == null}
								on:click={handleInsertBanner}
							>
								<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
								</svg>
								Insert Selected Banner
							</button>
							<button
								type="button"
								class="flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md bg-white/[0.05] hover:bg-white/[0.08] border border-white/[0.08] text-gray-400 hover:text-gray-300 text-[10px] font-semibold transition-colors"
								on:click={handleDismissBanner}
								title="Dismiss without adding banner"
							>
								Dismiss
							</button>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Pending (unreviewed) criteria -->
			{#each pendingCriteriaForList as criterion (criterion.criterion)}
				{@const isExpanded = expandedCriteria.has(criterion.criterion)}
				<div
					bind:this={criterionRefs[criterion.criterion]}
					class="criterion-card rounded-lg border border-white/[0.06] border-l-2 {getStatusBorder(criterion.status)} bg-white/[0.025] transition-all duration-200 overflow-hidden
						{auditState.status === 'stale' ? 'saturate-50' : ''}"
				>
					<button
						class="w-full flex items-start gap-2.5 px-3 py-2.5 text-left hover:bg-white/[0.03] transition-colors"
						on:click={() => toggleCriterion(criterion.criterion)}
					>
						<div class="flex-shrink-0 mt-0.5">
							<div class="w-1.5 h-1.5 rounded-full {getStatusDot(criterion.status)} mt-1"></div>
						</div>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-1.5 mb-0.5">
								<span class="text-[10px] font-semibold uppercase tracking-wider {getStatusPill(criterion.status)} px-1.5 py-0.5 rounded border">
									{criterionLabels[criterion.criterion] || criterion.criterion}
								</span>
							</div>
							<p class="text-[11px] text-gray-300 leading-relaxed line-clamp-2">
								{criterion.rationale}
							</p>
						</div>
						<svg
							class="w-3.5 h-3.5 text-gray-600 flex-shrink-0 mt-1 transition-transform duration-200"
							class:rotate-180={isExpanded}
							fill="none" stroke="currentColor" viewBox="0 0 24 24"
						>
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
						</svg>
					</button>

					{#if isExpanded}
						<div class="px-3 pb-3 space-y-2.5 border-t border-white/[0.05]" transition:fly={{ y: -4, duration: 150 }}>
							<p class="text-[11px] text-gray-400 leading-relaxed pt-2">{criterion.rationale}</p>

							{#if criterion.recommendation}
								<div class="flex gap-2 p-2 rounded-md bg-white/[0.03] border border-white/[0.05]">
									<svg class="w-3 h-3 text-purple-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
									</svg>
									<p class="text-[10px] text-gray-400 leading-relaxed">{criterion.recommendation}</p>
								</div>
							{/if}

							{#if criterion.criterion === 'clinical_flagging' && criterion.flags_identified && criterion.flags_identified.length > 0}
								<div class="space-y-1 pt-0.5">
									<p class="text-[9px] text-gray-600 uppercase tracking-wider font-semibold">Clinical flags</p>
									{#each criterion.flags_identified as flag}
										{#if flag.present}
											<div class="flex items-start gap-2 p-1.5 rounded-md bg-white/[0.02] border border-white/[0.04]">
												<div class="w-1 h-1 rounded-full {flagTypeColor(flag.type).replace('text-', 'bg-')} mt-1.5 flex-shrink-0"></div>
												<div class="min-w-0">
													<span class="text-[10px] font-semibold {flagTypeColor(flag.type)}">{flagTypeLabels[flag.type] || flag.type}</span>
													{#if !flag.adequately_supported}
														<span class="ml-1 text-[9px] text-amber-400/70">(language insufficient)</span>
													{/if}
													{#if flag.detail}
														<p class="text-[10px] text-gray-500 mt-0.5 leading-relaxed">{flag.detail}</p>
													{/if}
												</div>
											</div>
										{/if}
									{/each}
								</div>
							{/if}

						<div class="flex items-center gap-1.5 pt-1">
							<button
								class="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/20 hover:border-emerald-500/40 text-emerald-400 transition-all"
								on:click|stopPropagation={() => handleAcknowledge(criterion.criterion, 'manual')}
								title="Mark as reviewed"
							>
								<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
								</svg>
								<span class="text-[10px] font-semibold">Reviewed</span>
							</button>
							<button
								class="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 hover:border-purple-500/40 text-purple-400 transition-all"
								on:click|stopPropagation={() => handleSuggestFix(criterion)}
								title="Ask AI to fix"
							>
								<svg class="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
								</svg>
								<span class="text-[10px] font-semibold">Fix</span>
							</button>
						</div>
						</div>
					{/if}
				</div>
			{/each}

			<!-- Completed section (Fix was clicked) -->
			{#if completedCriteria.length > 0}
				<div class="mt-3" transition:fade={{ duration: 200 }}>
					<div class="flex items-center gap-2 mb-2">
						<div class="flex-1 h-px bg-white/[0.06]"></div>
						<span class="text-[9px] uppercase tracking-widest font-semibold text-purple-500/80">Completed</span>
						<div class="flex-1 h-px bg-white/[0.06]"></div>
					</div>
					<div class="space-y-1">
						{#each completedCriteria as criterion (criterion.criterion)}
							<div
								bind:this={criterionRefs[criterion.criterion]}
								class="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-purple-500/[0.06] border border-purple-500/20 opacity-80 hover:opacity-100 transition-opacity duration-200"
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
				<div class="mt-3" transition:fade={{ duration: 200 }}>
					<div class="flex items-center gap-2 mb-2">
						<div class="flex-1 h-px bg-white/[0.06]"></div>
						<span class="text-[9px] uppercase tracking-widest font-semibold text-gray-600">Reviewed</span>
						<div class="flex-1 h-px bg-white/[0.06]"></div>
					</div>
					<div class="space-y-1">
						{#each reviewedCriteria as criterion (criterion.criterion)}
							<div
								bind:this={criterionRefs[criterion.criterion]}
								class="flex items-center gap-2.5 px-3 py-2 rounded-lg bg-white/[0.01] border border-white/[0.04] opacity-60 hover:opacity-80 transition-opacity duration-200"
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
		{/if}
	</div>

	<!-- ── Footer ──────────────────────────────────────────────────── -->
	{#if (auditState.status === 'complete' || auditState.status === 'stale') && canReaudit}
		<div class="flex-shrink-0 px-3 pb-3 pt-2 border-t border-white/[0.04]">
			<button
				class="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/10 text-gray-500 hover:text-gray-300 transition-all text-xs font-medium"
				on:click={handleReaudit}
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
				</svg>
				Re-audit report
			</button>
			<p class="text-[9px] text-gray-700 text-center mt-2 leading-relaxed">
				Flags are logged for governance review
			</p>
		</div>
	{/if}
</div>

<style>
	.audit-panel {
		background: rgb(10, 10, 18);
	}

	.custom-scrollbar {
		scrollbar-width: thin;
		scrollbar-color: rgba(255,255,255,0.08) transparent;
	}

	.custom-scrollbar::-webkit-scrollbar {
		width: 3px;
	}

	.custom-scrollbar::-webkit-scrollbar-track {
		background: transparent;
	}

	.custom-scrollbar::-webkit-scrollbar-thumb {
		background: rgba(255,255,255,0.08);
		border-radius: 2px;
	}

	:global(.criterion-active-pulse) {
		animation: criterionPulse 1.2s ease-out forwards;
	}

	@keyframes criterionPulse {
		0%   { box-shadow: 0 0 0 0 rgba(168, 85, 247, 0.4); }
		40%  { box-shadow: 0 0 0 4px rgba(168, 85, 247, 0.2); }
		100% { box-shadow: 0 0 0 0 rgba(168, 85, 247, 0); }
	}
</style>
