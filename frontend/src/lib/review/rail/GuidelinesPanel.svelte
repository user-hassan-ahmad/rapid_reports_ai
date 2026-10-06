<script lang="ts">
	/**
	 * The guidelines panel (from POST /enhance): classification criteria from the audit, urgent signals and the
	 * guideline cards. Presentational: the host loads the data (lib/guidelines/enhance.ts) and decides what "Ask"
	 * does: the Copilot sidebar bridges it to its chat; the review rail routes it through its command path
	 * (`ask_chat`), so it lands in the rail chat like any item's "Ask in chat".
	 */
	import GuidelinePanel from '../../../routes/components/GuidelinePanel.svelte';
	import type { GuidelineEntry, UrgencyTier } from '$lib/guidelines/types';

	let {
		guidelines = [],
		urgencySignals = [],
		loading = false,
		loaded = false,
		error = null,
		lookupFailed = false,
		auditGuidelineReferences = [],
		auditCriteria = [],
		onRetry,
		onAsk
	}: {
		guidelines?: GuidelineEntry[];
		urgencySignals?: string[];
		loading?: boolean;
		/** Data has arrived (shows the card count). */
		loaded?: boolean;
		error?: string | null;
		lookupFailed?: boolean;
		auditGuidelineReferences?: any[];
		auditCriteria?: any[];
		onRetry?: () => void;
		/** "Ask →" on a card or a classification reference. */
		onAsk?: (text: string) => void;
	} = $props();

	let guidelinesExpanded = $state<Record<string, boolean>>({});

	// ── Urgency accent lookup (deterministic enum → colour) ─────────────────
	const URGENCY_ACCENT: Record<UrgencyTier, string> = {
		urgent:  '#ef4444',
		soon:    '#f59e0b',
		routine: '#3b82f6',
		watch:   '#6366f1',
		none:    'rgba(139,92,246,0.3)',
	};
	const URGENCY_LABEL: Record<UrgencyTier, string> = {
		urgent:  'Urgent',
		soon:    'Soon',
		routine: 'Routine',
		watch:   'Watch',
		none:    '',
	};

	function glAccentColor(g: GuidelineEntry): string {
		return URGENCY_ACCENT[g.urgency_tier ?? 'none'] ?? URGENCY_ACCENT.none;
	}

	/** One-liner follow-up action preview for the collapsed card header */
	function glActionPreview(g: GuidelineEntry): string | null {
		const f = g.follow_up_actions?.[0];
		if (!f) return null;
		const s = [f.modality, f.timing].filter(Boolean).join(' · ');
		return s.length > 52 ? s.slice(0, 49) + '…' : s || null;
	}

	const _MGMT_LEAD_LABEL = 'This patient:';

	/** Bold lead-in for classification management text (case-insensitive prefix match). */
	function splitClassificationManagementLead(raw: string): { lead: string | null; body: string } {
		const m = raw.match(/^\s*this patient:\s*/i);
		if (m?.[0]) {
			let body = raw.slice(m[0].length);
			if (body.length > 0 && !/^\s/.test(body)) {
				body = ` ${body}`;
			}
			return { lead: _MGMT_LEAD_LABEL, body };
		}
		return { lead: null, body: raw };
	}

	type ChipVariant = 'v' | 'c' | 'a' | 'r';

	/**
	 * Single right-aligned grade badge for the collapsed card header.
	 * Shows system + grade from first classification; falls back to first follow-up modality.
	 */
	function glGradeBadge(g: GuidelineEntry): { text: string; variant: ChipVariant } | null {
		const c = g.classifications?.[0];
		if (c) {
			const text = `${c.system} ${c.grade}`.trim();
			return { text: text.length > 18 ? text.slice(0, 16) + '…' : text, variant: 'v' };
		}
		const fu = g.follow_up_actions?.[0];
		if (fu?.modality) {
			const text = fu.modality.length > 16 ? fu.modality.slice(0, 14) + '…' : fu.modality;
			return { text, variant: 'c' };
		}
		return null;
	}

	/** Progressive detail toggle per card */
	let guidelinesDetailExpanded = $state<Record<string, boolean>>({});

	/** Show-more toggle for sources per card */
	let sourcesExpanded = $state<Record<string, boolean>>({});

	function sourceDomain(url: string | undefined | null): string {
		if (!url) return '';
		try {
			return new URL(url).hostname.replace(/^www\./, '');
		} catch {
			return '';
		}
	}


</script>

<div class="gl-panel" data-testid="guidelines-panel">
{#if loading}
	<div class="space-y-3 py-2">
		{#each [1, 2, 3] as _}
			<div class="rounded-xl border border-white/[0.06] p-3 animate-pulse space-y-2">
				<div class="h-3 bg-white/[0.07] rounded w-3/4"></div>
				<div class="h-2.5 bg-white/[0.05] rounded w-1/2"></div>
			</div>
		{/each}
	</div>
{:else if error}
	<div class="border border-red-500/30 bg-red-500/10 rounded-lg p-3 mt-2">
		<p class="text-red-400 font-medium text-xs mb-1">Error loading guidelines</p>
		<p class="text-red-300 text-xs">{error}</p>
		<button type="button" onclick={() => onRetry?.()} class="mt-2 px-3 py-1 bg-red-600 hover:bg-red-700 text-white text-xs rounded">Retry</button>
	</div>
{:else}
{#if auditGuidelineReferences.length > 0}
	<div class="gl-audit-block">
		<div class="gl-inline-label">
			<span class="gl-inline-label-ico">📋</span>
			<span class="gl-inline-label-txt">Classification criteria</span>
		</div>
		<GuidelinePanel
			references={auditGuidelineReferences}
			auditCriteria={auditCriteria}
			compact={true}
			onAskAbout={onAsk}
		/>
	</div>
{/if}
{#if auditGuidelineReferences.length > 0 && guidelines.length > 0}
	<div class="gl-sep"></div>
{/if}

{#if urgencySignals.length > 0}
<div class="gl-urgency-block">
	<div class="gl-urgency-header">
		<div class="gl-urgency-icon" aria-hidden="true">
			<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
		</div>
		<div>
			<p class="gl-urgency-title">Urgent findings detected</p>
			<p class="gl-urgency-sub">AI-identified findings requiring guideline review</p>
		</div>
	</div>
	<div class="gl-urgency-chips">
		{#each urgencySignals as sig}
			<span class="gl-urgency-chip">{sig}</span>
		{/each}
	</div>
</div>
{/if}

{#if guidelines.length > 0}
	<div class="gl-inline-label gl-inline-label--muted">
		<span class="gl-inline-label-txt">Supporting information</span>
		{#if loaded}
			<span class="gl-count-badge">{guidelines.length}</span>
		{/if}
	</div>
	<div class="gl-card-stack">
		{#each guidelines as guideline, idx}
			{@const guidelineKey = `guideline-${idx}`}
			{@const isExpanded = guidelinesExpanded[guidelineKey] === true}
			{@const isDetailOpen = guidelinesDetailExpanded[guidelineKey] === true}
			{@const gradeBadge = glGradeBadge(guideline)}
			{@const actionPreview = glActionPreview(guideline)}
			{@const accentColor = glAccentColor(guideline)}
			{@const hasDetail = !!(guideline.clinical_summary || (guideline.differentials?.length ?? 0) > 0)}
		{@const detailAutoOpen = (guideline.differentials?.length ?? 0) > 0}
			<div class="gl-card" style="--gl-accent: {accentColor}; --gl-action-color: {accentColor}">
				<!-- svelte-ignore a11y-no-static-element-interactions a11y-click-events-have-key-events -->
				<div
					class="gl-head {isExpanded ? 'gl-head--open' : ''}"
					role="button"
					tabindex="0"
					onclick={() => (guidelinesExpanded = { ...guidelinesExpanded, [guidelineKey]: !isExpanded })}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							guidelinesExpanded = { ...guidelinesExpanded, [guidelineKey]: !isExpanded };
						}
					}}
				>
					<div class="gl-meta">
						<!-- Row 1: title + right-aligned grade badge -->
					<div class="gl-title-row">
						<span class="gl-title">{guideline.finding_short_label || guideline.finding}</span>
							{#if gradeBadge}
								<span class="gl-grade-badge ch-{gradeBadge.variant}">{gradeBadge.text}</span>
							{/if}
						</div>
						<!-- Row 2: colored action hint (collapsed only) -->
						{#if !isExpanded && actionPreview}
							<div class="gl-action-hint">→ {actionPreview}</div>
						{/if}
					</div>
					<!-- Controls: ask + chevron (right-aligned, top-aligned) -->
					<div class="gl-controls">
						<button
							type="button"
							class="gl-ask-btn"
							onclick={(e) => {
								e.stopPropagation();
								onAsk?.(guideline.finding);
							}}
						>Ask →</button>
						<svg class="gl-chevron {isExpanded ? 'open' : ''}" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/></svg>
					</div>
				</div>

			{#if isExpanded}
				{@const urgencyLabel = URGENCY_LABEL[guideline.urgency_tier ?? 'none']}
				{@const sourcesKey = `sources-${idx}`}
				{@const sourcesOpen = sourcesExpanded[sourcesKey] === true}
				<div class="gl-body">

					<!-- ① Urgency tier badge -->
					{#if urgencyLabel}
						<div class="gl-urgency-tier-row">
							<span class="gl-urgency-tier-badge" style="color:{accentColor}; border-color:{accentColor}33; background:{accentColor}12">{urgencyLabel}</span>
						</div>
					{/if}

					<!-- ② Follow-up actions — most actionable info first -->
					{#if guideline.follow_up_actions && guideline.follow_up_actions.length > 0}
						<div class="gl-fu-block">
							<div class="gl-micro-label">
								<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
								Follow-up
							</div>
							{#each guideline.follow_up_actions as fu}
								{@const fuAccent = URGENCY_ACCENT[fu.urgency ?? 'none'] ?? accentColor}
								<div class="gl-fu-row">
									<span class="gl-fu-tag">{fu.modality}</span>
									{#if fu.timing}<span class="gl-fu-timing" style="color: {fuAccent}">{fu.timing}</span>{/if}
									{#if fu.indication}<p class="gl-fu-note">{fu.indication}</p>{/if}
									{#if fu.guideline_source}<span class="gl-fu-source">{fu.guideline_source}</span>{/if}
								</div>
							{/each}
						</div>
					{/if}

					<!-- ③ Classifications — system, authority, year, grade, criteria, management -->
					{#if guideline.classifications && guideline.classifications.length > 0}
						<div class="gl-class-block">
							{#each guideline.classifications as cls}
								<div class="gl-class-item">
									<div class="gl-class-header-row">
										<span class="gl-class-sys">{cls.system}{#if cls.year}&nbsp;<span class="gl-class-year">({cls.year})</span>{/if}</span>
										{#if cls.authority}<span class="gl-authority-chip">{cls.authority}</span>{/if}
										{#if cls.grade}<span class="gl-class-grade">{cls.grade}</span>{/if}
									</div>
									{#if cls.criteria}<p class="gl-class-note">{cls.criteria}</p>{/if}
									{#if cls.management}
										{@const _mgmt = splitClassificationManagementLead(cls.management)}
										<p class="gl-class-mgmt">
											{#if _mgmt.lead}<strong class="gl-class-mgmt-lead">{_mgmt.lead}</strong>{/if}{_mgmt.body}
										</p>
									{/if}
								</div>
							{/each}
						</div>
					{/if}

					<!-- ④ Actionable thresholds -->
					{#if guideline.thresholds && guideline.thresholds.length > 0}
						<div class="gl-threshold-block">
							<div class="gl-micro-label">
								<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="2" y1="12" x2="22" y2="12"/><polyline points="6 9 2 12 6 15"/><polyline points="18 9 22 12 18 15"/></svg>
								Thresholds
							</div>
							{#each guideline.thresholds as t}
								<div class="gl-threshold-row">
									<span class="gl-threshold-param">{t.parameter}</span>
									<span class="gl-threshold-chip">{t.threshold}</span>
									<span class="gl-dr-val">{t.significance}</span>
								</div>
								{#if t.context || t.measurement_tip}
									<p class="gl-threshold-ctx">{t.context || t.measurement_tip}</p>
								{/if}
							{/each}
						</div>
					{/if}

					<!-- ⑤ Imaging flags — promoted out of detail toggle -->
					{#if guideline.imaging_flags && guideline.imaging_flags.length > 0}
						<div class="gl-detail-section">
							<div class="gl-micro-label">
								<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
								Key Imaging Features
							</div>
							<div class="gl-flags-row">
								{#each guideline.imaging_flags as flag}
									<span class="gl-flag-chip">{flag}</span>
								{/each}
							</div>
						</div>
					{/if}

					<!-- ⑥ Progressive detail toggle (differentials + clinical summary) -->
					{#if hasDetail}
						<button
							type="button"
							class="gl-detail-toggle"
							onclick={(e) => {
								e.stopPropagation();
								const next = !isDetailOpen;
								guidelinesDetailExpanded = { ...guidelinesDetailExpanded, [guidelineKey]: next };
							}}
						>
							<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="gl-detail-chevron {(isDetailOpen || (detailAutoOpen && guidelinesDetailExpanded[guidelineKey] === undefined) ? 'open' : isDetailOpen ? 'open' : '')}" aria-hidden="true"><path d="M19 9l-7 7-7-7"/></svg>
							{(isDetailOpen || (detailAutoOpen && guidelinesDetailExpanded[guidelineKey] === undefined)) ? 'Less detail' : 'Differentials & overview'}
						</button>

						{#if isDetailOpen || (detailAutoOpen && guidelinesDetailExpanded[guidelineKey] === undefined)}
							<!-- Differentials -->
							{#if guideline.differentials && guideline.differentials.length > 0}
								<div class="gl-detail-section">
									<div class="gl-micro-label">
										<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>
										Differentials
									</div>
									{#each guideline.differentials as ddx}
										<div class="gl-ddx-item">
											<div class="gl-ddx-header">
												<span class="gl-ddx-name">{ddx.diagnosis}</span>
												{#if ddx.likelihood}<span class="gl-ddx-likelihood gl-ddx-likelihood--{ddx.likelihood.replace(' ', '-')}">{ddx.likelihood}</span>{/if}
											</div>
											<span class="gl-ddx-desc">{ddx.key_features}</span>
											{#if ddx.excluders}<p class="gl-dr-note">Excluded by: {ddx.excluders}</p>{/if}
										</div>
									{/each}
								</div>
							{/if}

							<!-- Overview -->
							{#if guideline.clinical_summary}
								<div class="gl-detail-section">
									<div class="gl-micro-label">
										<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
										Overview
									</div>
									<p class="gl-prose">{guideline.clinical_summary}</p>
								</div>
							{/if}
						{/if}
					{/if}

					<!-- ⑦ Sources: authority chip + guideline refs + links (5 inline, show-more for rest) -->
					<div class="gl-sources">
						{#if guideline.uk_authority}
							<span class="gl-authority-chip gl-authority-chip--source">{guideline.uk_authority}</span>
						{/if}
						{#if guideline.guideline_refs && guideline.guideline_refs.length > 0}
							{#each guideline.guideline_refs as ref}
								<span class="gl-source-link gl-source-static">{ref}</span>
							{/each}
						{/if}
						{#if guideline.sources && guideline.sources.length > 0}
							{@const srcLimit = sourcesOpen ? guideline.sources.length : 5}
							{#each guideline.sources.slice(0, srcLimit) as source (source.url || source.title || Math.random())}
								{#if source.url}
									<a href={source.url} target="_blank" rel="noopener noreferrer" class="gl-source-link" title={source.title ?? source.url}>
										<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
										{source.domain || sourceDomain(source.url) || source.title || 'Reference'}
									</a>
								{:else if source.title}
									<span class="gl-source-link gl-source-static">{source.title}</span>
								{/if}
							{/each}
							{#if guideline.sources.length > 5}
								<button
									type="button"
									class="gl-source-link gl-source-more"
									onclick={(e) => { e.stopPropagation(); sourcesExpanded = { ...sourcesExpanded, [sourcesKey]: !sourcesOpen }; }}
								>
									{sourcesOpen ? 'Show less' : `+${guideline.sources.length - 5} more`}
								</button>
							{/if}
						{/if}
					</div>
				</div>
			{/if}
			</div>
		{/each}
	</div>
	{/if}
	{#if !loading && auditGuidelineReferences.length === 0 && guidelines.length === 0}
		{#if lookupFailed}
			<div class="mx-4 my-6 p-4 rounded-lg bg-amber-500/[0.06] border border-amber-500/25 space-y-3">
				<div class="flex items-start gap-2">
					<svg class="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M4.93 4.93l14.14 14.14" />
					</svg>
					<div class="flex-1 min-w-0">
						<p class="text-xs text-amber-200 font-medium">Guideline lookup unavailable</p>
						<p class="text-[11px] text-amber-200/70 mt-1 leading-relaxed">
							Retrieval failed — no guideline evidence could be fetched for this report.
						</p>
					</div>
				</div>
				<button
					type="button"
					class="w-full px-3 py-1.5 rounded-md text-xs font-medium text-amber-200 bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 transition-colors"
					onclick={() => onRetry?.()}
				>Retry</button>
			</div>
		{:else}
			<div class="text-gray-500 text-xs text-center py-8">No guidelines applicable to this report.</div>
		{/if}
	{/if}
{/if}
</div>

<style>
	.gl-panel {
		font-family: 'DM Sans', 'IBM Plex Sans', system-ui, sans-serif;
	}
	/* Count badge on section labels */
	.gl-count-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		border-radius: 20px;
		font-size: 9px;
		font-weight: 700;
		background: rgba(16, 185, 129, 0.1);
		border: 1px solid rgba(16, 185, 129, 0.18);
		color: #34d399;
		margin-left: 4px;
	}
	.gl-sep {
		margin: 16px 0;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}
	.gl-audit-block {
		margin-bottom: 4px;
	}
	.gl-inline-label {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 8px;
	}
	.gl-inline-label--muted {
		opacity: 0.85;
	}
	.gl-inline-label-ico {
		font-size: 13px;
	}
	.gl-inline-label-txt {
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: #71717a;
	}
	/* ═══ Guideline cards ════════════════════════════ */
	.gl-card-stack { display: flex; flex-direction: column; gap: 6px; }

	.gl-card {
		border-radius: 10px;
		border: 1px solid rgba(255,255,255,0.08);
		background: #0d0d14;
		overflow: hidden;
		transition: border-color 0.18s, background 0.18s;
		position: relative;
	}
	/* Left accent strip — solid, always visible */
	.gl-card::before {
		content: '';
		position: absolute;
		left: 0; top: 0; bottom: 0;
		width: 3px;
		background: var(--gl-accent, #8b5cf6);
		border-radius: 10px 0 0 10px;
	}
	.gl-card:hover {
		border-color: rgba(255,255,255,0.13);
		background: #101018;
	}

	/* ── Collapsed head ── */
	.gl-head {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		padding: 10px 11px 10px 15px;
		cursor: pointer;
		user-select: none;
	}
	.gl-head--open { padding-bottom: 9px; }

	.gl-meta { flex: 1; min-width: 0; }

	/* Row 1: title + grade badge */
	.gl-title-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 8px;
	}
	.gl-title {
		flex: 1;
		min-width: 0;
		font-size: 13px;
		font-weight: 600;
		color: #e8e8ec;
		line-height: 1.3;
		letter-spacing: -0.008em;
	}
	/* Grade badge — right-aligned, theme-consistent */
	.gl-grade-badge {
		flex-shrink: 0;
		font-size: 9px;
		font-weight: 700;
		padding: 2px 7px;
		border-radius: 20px;
		letter-spacing: 0.02em;
		white-space: nowrap;
		margin-top: 2px;
	}
	.ch-v { background: rgba(139,92,246,0.12); color: #c4b5fd; border: 1px solid rgba(139,92,246,0.25); }
	.ch-c { background: rgba(6,182,212,0.1);   color: #67e8f9; border: 1px solid rgba(6,182,212,0.22); }
	.ch-a { background: rgba(245,158,11,0.1);  color: #fcd34d; border: 1px solid rgba(245,158,11,0.22); }
	.ch-r { background: rgba(244,63,94,0.1);   color: #fda4af; border: 1px solid rgba(244,63,94,0.22); }

	/* Row 2: colored action hint (collapsed only) — no extra opacity dimming */
	.gl-action-hint {
		margin-top: 4px;
		font-size: 10.5px;
		font-weight: 500;
		line-height: 1.35;
		color: var(--gl-action-color, #a78bfa);
	}

	/* Controls: ask + chevron */
	.gl-controls {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-shrink: 0;
		padding-top: 2px;
	}
	.gl-ask-btn {
		padding: 3px 8px;
		border-radius: 6px;
		border: 1px solid rgba(139,92,246,0.28);
		background: rgba(139,92,246,0.09);
		color: #a78bfa;
		font-size: 9.5px;
		font-weight: 600;
		cursor: pointer;
		white-space: nowrap;
		font-family: inherit;
		transition: all 0.15s;
	}
	.gl-ask-btn:hover { background: rgba(139,92,246,0.2); color: #ddd6fe; }
	.gl-chevron { transition: transform 0.2s; color: #52525b; flex-shrink: 0; }
	.gl-chevron.open { transform: rotate(180deg); color: #a1a1aa; }

	/* ── Expanded body ── */
	.gl-body {
		border-top: 1px solid rgba(255,255,255,0.06);
		padding: 10px 12px 12px 15px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
	}

	/* Urgency tier text badge */
	.gl-urgency-tier-row {
		display: flex;
		align-items: center;
	}
	.gl-urgency-tier-badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 4px;
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		border: 1px solid;
	}

	/* Shared micro-label (eyebrow above each section) */
	.gl-micro-label {
		display: flex;
		align-items: center;
		gap: 5px;
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.09em;
		color: #71717a;
		margin-bottom: 6px;
	}
	.gl-micro-label svg { flex-shrink: 0; opacity: 0.7; }

	/* Follow-up block — theme-consistent purple tint, no color-mix() */
	.gl-fu-block {
		padding: 9px 11px;
		border-radius: 8px;
		background: rgba(139,92,246,0.06);
		border: 1px solid rgba(139,92,246,0.18);
	}
	.gl-fu-row {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0 8px;
		padding: 3px 0;
	}
	.gl-fu-row + .gl-fu-row {
		margin-top: 5px;
		padding-top: 5px;
		border-top: 1px solid rgba(255,255,255,0.05);
	}
	.gl-fu-tag {
		font-size: 12.5px;
		font-weight: 600;
		color: #e4e4e7;
	}
	.gl-fu-timing {
		font-size: 11.5px;
		color: #a78bfa;
		font-weight: 500;
	}
	.gl-fu-note {
		width: 100%;
		font-size: 11px;
		color: #71717a;
		line-height: 1.45;
		margin-top: 3px;
	}

	/* Classification year */
	.gl-class-year {
		font-weight: 400;
		color: #52525b;
		font-size: 9px;
	}

	/* Classification block */
	.gl-class-block {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.gl-class-item {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
	}
	.gl-class-sys {
		font-size: 10px;
		font-weight: 600;
		color: #a1a1aa;
		letter-spacing: 0.04em;
	}
	.gl-class-grade {
		font-size: 10.5px;
		font-weight: 700;
		color: #c4b5fd;
		background: rgba(139,92,246,0.12);
		border: 1px solid rgba(139,92,246,0.25);
		padding: 1px 7px;
		border-radius: 20px;
	}
	.gl-class-note {
		width: 100%;
		font-size: 10.5px;
		color: #71717a;
		line-height: 1.45;
		margin-top: 1px;
	}

	/* Detail toggle — visible but unobtrusive */
	.gl-detail-toggle {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 10px;
		font-weight: 600;
		color: #71717a;
		background: none;
		border: none;
		cursor: pointer;
		padding: 2px 0;
		font-family: inherit;
		transition: color 0.15s;
		align-self: flex-start;
	}
	.gl-detail-toggle:hover { color: #c4b5fd; }
	.gl-detail-chevron { transition: transform 0.18s; }
	.gl-detail-chevron.open { transform: rotate(180deg); }

	/* Detail sections */
	.gl-detail-section {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.gl-detail-row {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 3px 6px;
		padding: 5px 0;
		border-bottom: 1px solid rgba(255,255,255,0.05);
	}
	.gl-detail-row:last-child { border-bottom: none; }
	.gl-dr-key {
		font-size: 11px;
		font-weight: 600;
		color: #d4d4d8;
		min-width: 0;
		flex: 1 1 100%;
		overflow-wrap: break-word;
		word-break: normal;
	}
	.gl-dr-val {
		font-size: 11px;
		color: #b4b4be;
		line-height: 1.5;
		min-width: 0;
		flex: 1 1 100%;
		overflow-wrap: break-word;
		word-break: normal;
		border-left: 2px solid rgba(139, 92, 246, 0.35);
		padding-left: 8px;
		margin-top: 1px;
	}
	.gl-dr-note {
		font-size: 10px;
		color: #71717a;
		width: 100%;
		line-height: 1.45;
		font-style: italic;
		margin-top: 1px;
	}

	/* Differentials — purple accent, not amber */
	.gl-ddx-item {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 4px 6px;
		padding: 5px 0;
		border-bottom: 1px solid rgba(255,255,255,0.05);
	}
	.gl-ddx-item:last-child { border-bottom: none; }
	.gl-ddx-name {
		font-size: 11px;
		font-weight: 600;
		color: #c4b5fd;
		flex-shrink: 0;
	}
	.gl-ddx-desc {
		font-size: 10.5px;
		color: #a1a1aa;
		line-height: 1.45;
	}

	/* Overview prose */
	.gl-prose { font-size: 11.5px; color: #a1a1aa; line-height: 1.6; }
	:global(.gl-prose p) { margin: 0 0 5px; }
	:global(.gl-prose strong) { color: #e4e4e7; font-weight: 600; }
	:global(.gl-prose ul) { padding-left: 14px; margin: 3px 0; }
	:global(.gl-prose li) { margin-bottom: 3px; }

	/* Sources — low-key, legible on hover */
	.gl-sources {
		padding-top: 8px;
		border-top: 1px solid rgba(255,255,255,0.06);
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.gl-source-link {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 9.5px;
		color: #71717a;
		text-decoration: none;
		padding: 2px 7px;
		border-radius: 20px;
		background: rgba(255,255,255,0.03);
		border: 1px solid rgba(255,255,255,0.08);
		transition: all 0.15s;
	}
	.gl-source-link:hover { color: #c4b5fd; background: rgba(139,92,246,0.1); border-color: rgba(139,92,246,0.25); }
	.gl-source-static { cursor: default; }
	.gl-source-static:hover { color: #71717a; background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.08); }
	.gl-source-more {
		cursor: pointer;
		font-family: inherit;
		color: #6366f1;
		background: rgba(99,102,241,0.07);
		border-color: rgba(99,102,241,0.2);
	}
	.gl-source-more:hover { color: #a5b4fc; background: rgba(99,102,241,0.15); border-color: rgba(99,102,241,0.35); }

	/* ── Urgency signals block ──────────────────────── */
	.gl-urgency-block {
		margin-bottom: 12px;
		border-radius: 10px;
		border: 1px solid rgba(245, 158, 11, 0.22);
		background: rgba(20, 14, 4, 0.7);
		overflow: hidden;
		/* Left accent strip */
		position: relative;
	}
	.gl-urgency-block::before {
		content: '';
		position: absolute;
		left: 0; top: 0; bottom: 0;
		width: 3px;
		background: linear-gradient(to bottom, #f59e0b, #d97706);
		border-radius: 10px 0 0 10px;
	}
	.gl-urgency-header {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		padding: 9px 12px 8px 14px;
		border-bottom: 1px solid rgba(245, 158, 11, 0.12);
	}
	.gl-urgency-icon {
		width: 22px;
		height: 22px;
		border-radius: 6px;
		background: rgba(245, 158, 11, 0.15);
		border: 1px solid rgba(245, 158, 11, 0.25);
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		color: #f59e0b;
		margin-top: 1px;
	}
	.gl-urgency-title {
		font-size: 11.5px;
		font-weight: 700;
		color: #fbbf24;
		margin: 0 0 1px;
		line-height: 1.3;
	}
	.gl-urgency-sub {
		font-size: 9.5px;
		font-weight: 500;
		color: #92400e;
		color: rgba(251, 191, 36, 0.45);
		margin: 0;
		line-height: 1.3;
	}
	.gl-urgency-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		padding: 8px 12px 10px 14px;
	}
	.gl-urgency-chip {
		display: inline-block;
		font-size: 10.5px;
		font-weight: 600;
		line-height: 1.4;
		color: #fde68a;
		background: rgba(245, 158, 11, 0.1);
		border: 1px solid rgba(245, 158, 11, 0.2);
		border-radius: 6px;
		padding: 3px 9px;
		white-space: normal;
		word-break: break-word;
	}

	/* ── Follow-up source attribution ───────────────── */
	.gl-fu-source {
		font-size: 9.5px;
		color: #52525b;
		font-style: italic;
		margin-top: 2px;
	}

	/* ── Classification management line ─────────────── */
	.gl-class-header-row {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-wrap: wrap;
	}
	.gl-class-mgmt {
		margin: 3px 0 0 0;
		font-size: 10.5px;
		line-height: 1.5;
		color: #c4b5fd;
		font-weight: 400;
	}
	.gl-class-mgmt-lead {
		font-weight: 600;
		color: inherit;
	}

	/* ── Authority chip ──────────────────────────────── */
	.gl-authority-chip {
		display: inline-flex;
		align-items: center;
		padding: 1px 5px;
		border-radius: 4px;
		font-size: 9px;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		background: rgba(99,102,241,0.12);
		border: 1px solid rgba(99,102,241,0.25);
		color: #818cf8;
		white-space: nowrap;
	}
	.gl-authority-chip--source {
		font-size: 9.5px;
		padding: 2px 7px;
	}

	/* ── Threshold block ─────────────────────────────── */
	.gl-threshold-block {
		padding: 8px 10px;
		background: rgba(255,255,255,0.02);
		border: 1px solid rgba(255,255,255,0.06);
		border-radius: 6px;
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.gl-threshold-row {
		display: flex;
		align-items: flex-start;
		gap: 6px 8px;
		flex-wrap: wrap;
		min-width: 0;
	}
	.gl-threshold-param {
		font-size: 9.5px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #71717a;
		min-width: 0;
		flex: 1 1 100%;
		overflow-wrap: break-word;
		word-break: normal;
	}
	.gl-threshold-chip {
		display: block;
		width: 100%;
		max-width: 100%;
		box-sizing: border-box;
		padding: 7px 10px;
		border-radius: 5px;
		font-size: 11px;
		font-weight: 700;
		font-family: ui-monospace, 'SF Mono', monospace;
		line-height: 1.4;
		text-align: center;
		background: rgba(139, 92, 246, 0.15);
		border: 1px solid rgba(139, 92, 246, 0.3);
		color: #c4b5fd;
		white-space: normal;
		word-break: break-word;
		overflow-wrap: break-word;
		min-width: 0;
		flex: 1 1 100%;
	}
	.gl-threshold-ctx {
		font-size: 9.5px;
		color: #52525b;
		font-style: italic;
		line-height: 1.4;
		margin: -2px 0 4px;
		padding-left: 2px;
	}

	/* ── DDx likelihood badge ────────────────────────── */
	.gl-ddx-header {
		display: flex;
		align-items: center;
		gap: 5px;
		flex-wrap: wrap;
	}
	.gl-ddx-likelihood {
		display: inline-flex;
		align-items: center;
		padding: 1px 5px;
		border-radius: 4px;
		font-size: 9px;
		font-weight: 600;
		text-transform: lowercase;
		white-space: nowrap;
	}
	.gl-ddx-likelihood--common { background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); color: #6ee7b7; }
	.gl-ddx-likelihood--less-common { background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); color: #fbbf24; }
	.gl-ddx-likelihood--rare { background: rgba(244,63,94,0.08); border: 1px solid rgba(244,63,94,0.18); color: #fda4af; }

	/* ── Imaging flags tag cloud ─────────────────────── */
	.gl-flags-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 3px;
	}
	.gl-flag-chip {
		display: inline-flex;
		align-items: center;
		padding: 2px 7px;
		border-radius: 4px;
		font-size: 10px;
		background: rgba(255,255,255,0.04);
		border: 1px solid rgba(255,255,255,0.09);
		color: #a1a1aa;
		white-space: nowrap;
	}

</style>
