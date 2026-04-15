/**
 * Shared Audit Store — keyed by reportId to prevent cross-tab contamination.
 *
 * Replaces the per-instance writable in ReportResponseViewer. Any component
 * can subscribe via getAuditState(reportId) or call auditActions.* directly.
 * Phase 2 merge (from /enhance) bypasses the 3-hop event chain entirely.
 */

import { writable, derived, type Readable } from 'svelte/store';

export interface AuditCriterionItem {
	criterion: string;
	status: 'pass' | 'flag' | 'warning';
	rationale: string;
	highlighted_spans?: string[];
	recommendation?: string;
	suggested_replacement?: string | null;
	suggested_sentence?: string | null;
	criterion_line?: string | null;
	flags_identified?: any[];
	suggested_banners?: any[];
	acknowledged?: boolean;
	resolution_method?: string;
	discrepancies?: any[];
	systems_unaddressed?: string[];
	characterisation_gaps?: any[];
}

export interface AuditResult {
	overall_status: 'pass' | 'flag' | 'warning';
	criteria: AuditCriterionItem[];
	summary: string;
	guideline_references?: any[];
}

export interface AuditStoreState {
	status: 'idle' | 'loading' | 'complete' | 'stale' | 'error';
	result: AuditResult | null;
	auditId: string | null;
	error: string | null;
	activeCriterion: string | null;
	/** Phase 2 criteria cached separately so re-audit (Phase 1 only) can re-merge them. */
	_phase2Cache: AuditCriterionItem[] | null;
	/**
	 * True once Phase 2 (the guideline-compliance pass inside /enhance) has settled,
	 * whether it produced criteria or not. The UI uses this to clear the
	 * "N additional criteria evaluating…" spinner — inferring from criteria.length
	 * breaks on normal studies where Phase 2 legitimately returns zero criteria.
	 */
	phase2Complete: boolean;
	/**
	 * True when /enhance failed to produce synthesis evidence (prefetch failure or S4
	 * synthesis error). Phase 2 still ran unanchored, so criteria are present, but the
	 * UI surfaces a degraded-state banner with a Retry affordance. False in both the
	 * happy path and the zero-guideline-success path — those are distinguished by
	 * guidelineCardsCount instead.
	 */
	guidelineLookupFailed: boolean;
	/**
	 * Number of guideline synthesis cards that came through on the latest /enhance call.
	 * Distinguishes grounded (> 0) from unanchored-but-not-failed (0) — the latter being
	 * the legitimate "no applicable guideline for this case" outcome, which deserves a
	 * subtle info line rather than silence so the user knows Phase 2 wasn't anchored to
	 * specific guidelines.
	 */
	guidelineCardsCount: number;
}

const DEFAULT_STATE: AuditStoreState = {
	status: 'idle',
	result: null,
	auditId: null,
	error: null,
	activeCriterion: null,
	_phase2Cache: null,
	phase2Complete: false,
	guidelineLookupFailed: false,
	guidelineCardsCount: 0,
};

const _states = writable<Record<string, AuditStoreState>>({});

// Dev-only: expose the store on window so you can inspect state from the
// browser console without fighting the $lib alias. Usage:
//   __auditStore()                 → full state snapshot
//   __auditStore('<reportId>')     → one report's state
//   __auditStoreLive()             → subscribe to live changes
if (typeof window !== 'undefined') {
	let _snapshot: Record<string, AuditStoreState> = {};
	_states.subscribe((s) => {
		_snapshot = s;
	});
	(window as any).__auditStore = (reportId?: string) =>
		reportId ? _snapshot[reportId] : _snapshot;
	(window as any).__auditStoreLive = () =>
		_states.subscribe((s) => console.log('[audit store]', s));
}

export function getAuditState(reportId: string): Readable<AuditStoreState> {
	return derived(_states, ($s) => $s[reportId] ?? { ...DEFAULT_STATE });
}

function _update(reportId: string, fn: (s: AuditStoreState) => AuditStoreState) {
	_states.update((all) => {
		const current = all[reportId] ?? { ...DEFAULT_STATE };
		return { ...all, [reportId]: fn(current) };
	});
}

export const auditActions = {
	setLoading: (reportId: string) =>
		// Note: phase2Complete + guidelineLookupFailed are intentionally NOT reset
		// here. Re-audit re-runs Phase 1 only — /enhance (which owns Phase 2) does
		// not re-fire. Clearing those on every re-audit would leave the spinner
		// stuck because mergePhase2 is never called again in that window. A fresh
		// /enhance call via the Retry flow resets them through mergePhase2.
		_update(reportId, (s) => ({ ...s, status: 'loading', error: null })),

	setResult: (reportId: string, result: AuditResult, auditId: string | null) =>
		_update(reportId, (s) => {
			// If Phase 2 resolved before Phase 1 (e.g. /enhance faster than /audit,
			// or /enhance was cached backend-side), the Phase 2 criteria are sitting
			// in _phase2Cache waiting for a result to merge into. Fold them in now.
			const cache = s._phase2Cache;
			if (!cache || cache.length === 0) {
				return { ...s, status: 'complete', result, auditId, error: null };
			}
			const PHASE2_NAMES = new Set([
				'diagnostic_fidelity',
				'recommendations',
				'clinical_flagging',
				'characterisation_gap',
			]);
			const phase1Only = result.criteria.filter((c) => !PHASE2_NAMES.has(c.criterion));
			const merged = [...phase1Only, ...cache];
			const worstStatus: 'pass' | 'flag' | 'warning' = merged.some((c) => c.status === 'flag')
				? 'flag'
				: merged.some((c) => c.status === 'warning')
					? 'warning'
					: 'pass';
			return {
				...s,
				status: 'complete',
				result: { ...result, criteria: merged, overall_status: worstStatus },
				auditId,
				error: null,
			};
		}),

	mergePhase2: (
		reportId: string,
		phase2Criteria: AuditCriterionItem[],
		opts?: { guidelineLookupFailed?: boolean; guidelineCardsCount?: number },
	) => {
		const guidelineLookupFailed = opts?.guidelineLookupFailed ?? false;
		const guidelineCardsCount = opts?.guidelineCardsCount ?? 0;
		console.debug('[audit] mergePhase2', {
			reportId,
			count: phase2Criteria.length,
			guidelineLookupFailed,
			guidelineCardsCount,
		});
		_update(reportId, (s) => {
			// phase2Complete=true regardless of criteria length — an empty Phase 2
			// (normal study, no applicable guidelines) must still clear the spinner.
			const newState = {
				...s,
				_phase2Cache: phase2Criteria,
				phase2Complete: true,
				guidelineLookupFailed,
				guidelineCardsCount,
			};
			if (!s.result) return newState;
			const PHASE2_NAMES = new Set(['diagnostic_fidelity', 'recommendations', 'clinical_flagging', 'characterisation_gap']);
			const phase1Only = s.result.criteria.filter((c) => !PHASE2_NAMES.has(c.criterion));
			const merged = [...phase1Only, ...phase2Criteria];
			const worstStatus = merged.some((c) => c.status === 'flag')
				? 'flag'
				: merged.some((c) => c.status === 'warning')
					? 'warning'
					: 'pass';
			return {
				...newState,
				result: {
					...s.result,
					criteria: merged,
					overall_status: worstStatus,
				},
			};
		});
	},

	clearPhase2Cache: (reportId: string) =>
		_update(reportId, (s) => ({ ...s, _phase2Cache: null })),

	setStale: (reportId: string) =>
		_update(reportId, (s) => (s.status === 'complete' ? { ...s, status: 'stale' } : s)),

	setError: (reportId: string, error: string) =>
		_update(reportId, (s) => ({ ...s, status: 'error', error })),

	setActiveCriterion: (reportId: string, criterion: string | null) =>
		_update(reportId, (s) => ({ ...s, activeCriterion: criterion })),

	acknowledgeLocal: (reportId: string, criterion: string, method?: string) =>
		_update(reportId, (s) => {
			if (!s.result) return s;
			const criteria = s.result.criteria.map((c) =>
				c.criterion === criterion
					? { ...c, acknowledged: true, resolution_method: method }
					: c,
			);
			return { ...s, result: { ...s.result, criteria } };
		}),

	unacknowledgeLocal: (reportId: string, criterion: string) =>
		_update(reportId, (s) => {
			if (!s.result) return s;
			const criteria = s.result.criteria.map((c) =>
				c.criterion === criterion
					? { ...c, acknowledged: false, resolution_method: undefined }
					: c,
			);
			return { ...s, result: { ...s.result, criteria } };
		}),

	reset: (reportId: string) =>
		_update(reportId, () => ({ ...DEFAULT_STATE })),
};
