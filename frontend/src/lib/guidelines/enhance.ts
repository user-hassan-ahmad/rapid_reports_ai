// The one client of POST /api/reports/{id}/enhance (guidelines + Phase 2 audit criteria). Used by the Copilot
// sidebar and the review rail's Guidelines tab. Results are cached per report and concurrent calls share one
// request, so both surfaces can ask without a second (30-60 s) enhance run. Every resolution also settles Phase 2 in
// the shared audit store, as the sidebar always did.
import { get } from 'svelte/store';
import { API_URL } from '$lib/config';
import { token } from '$lib/stores/auth';
import { logger } from '$lib/utils/logger';
import type { ApplicableGuideline, Finding, GuidelineEntry } from './types';

export interface EnhancementData {
	findings: Finding[];
	guidelines: GuidelineEntry[];
	urgencySignals: string[];
	applicableGuidelines: ApplicableGuideline[];
	/** /enhance could not fetch guideline evidence (distinct from "no guidelines apply"). */
	lookupFailed: boolean;
}

/** A failed enhance; `message` is fit to show the user. */
export class EnhanceError extends Error {}

const cache = new Map<string, EnhancementData>();
const inflight = new Map<string, Promise<EnhancementData>>();

/** The cached result for a report, if any (no request). */
export function peekEnhancement(reportId: string): EnhancementData | undefined {
	return cache.get(reportId);
}

export function forgetEnhancement(reportId: string): void {
	cache.delete(reportId);
}

/** The report's enhancement: cached unless `force`, one request in flight per report. Throws EnhanceError. */
export function loadEnhancement(
	reportId: string,
	{ force = false }: { force?: boolean } = {}
): Promise<EnhancementData> {
	if (!force) {
		const hit = cache.get(reportId);
		if (hit) return Promise.resolve(hit);
	} else {
		cache.delete(reportId);
	}
	const running = inflight.get(reportId);
	if (running) return running;
	const job = fetchEnhancement(reportId).finally(() => {
		if (inflight.get(reportId) === job) inflight.delete(reportId);
	});
	inflight.set(reportId, job);
	return job;
}

async function fetchEnhancement(reportId: string): Promise<EnhancementData> {
	try {
		const data = await post(reportId);
		cache.set(reportId, data);
		return data;
	} catch (e) {
		// any failure settles Phase 2 too: clears the evaluating spinner and shows the degraded-state banner
		await mergeAudit(reportId, null);
		throw e instanceof EnhanceError ? e : new EnhanceError('Failed to connect. Please try again.');
	}
}

async function post(reportId: string): Promise<EnhancementData> {
	const t = get(token);
	const headers = { 'Content-Type': 'application/json', ...(t ? { Authorization: `Bearer ${t}` } : {}) };
	// enhancement can take 30-60 seconds
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), 120000);
	let response: Response;
	try {
		response = await fetch(`${API_URL}/api/reports/${reportId}/enhance`, {
			method: 'POST',
			headers,
			signal: controller.signal
		});
	} catch (err) {
		const name = (err as { name?: string } | null)?.name;
		if (name === 'AbortError') {
			throw new EnhanceError(
				'Request timed out. The enhancement process may be taking longer than expected.'
			);
		}
		logger.error('loadEnhancement: network error:', err);
		throw new EnhanceError('Something went wrong. Please try again.');
	} finally {
		clearTimeout(timeoutId);
	}
	if (!response.ok) {
		logger.error('loadEnhancement: HTTP error:', response.status, await response.text().catch(() => ''));
		throw new EnhanceError('Something went wrong. Please try again.');
	}
	let data: any;
	try {
		data = await response.json();
	} catch {
		throw new EnhanceError('Failed to parse response, but request succeeded');
	}
	if (!data) throw new EnhanceError('No data received from server');
	if (!data.success) {
		logger.error('loadEnhancement: API returned error:', data.error);
		throw new EnhanceError('Failed to load enhancements. Please try again.');
	}
	const out: EnhancementData = {
		findings: [...(data.findings || [])],
		guidelines: [...(data.guidelines || [])],
		urgencySignals: data.urgency_signals || [],
		applicableGuidelines: data.applicable_guidelines || [],
		lookupFailed: data.guideline_lookup_failed === true
	};
	await mergeAudit(reportId, data);
	return out;
}

const PHASE2_NAMES = new Set([
	'diagnostic_fidelity',
	'recommendations',
	'clinical_flagging',
	'characterisation_gap'
]);

/** Merge Phase 2 audit criteria into the shared audit store; `data` null → the failure path. */
async function mergeAudit(reportId: string, data: any | null): Promise<void> {
	try {
		const { auditActions } = await import('$lib/stores/audit');
		if (!data) {
			auditActions.mergePhase2(reportId, [], { guidelineLookupFailed: true });
			return;
		}
		// Always merge on a successful enhance — even with an empty array — so the store flips phase2Complete and
		// the "N additional criteria evaluating…" spinner clears for studies where Phase 2 produces nothing.
		const guidelineLookupFailed = data.guideline_lookup_failed === true;
		const guidelineCardsCount = Array.isArray(data.guidelines) ? data.guidelines.length : 0;
		// Dual-candidate path: a full audit per candidate seeds each candidate's slot.
		const candidateAudits: any[] = Array.isArray(data.candidate_audits) ? data.candidate_audits : [];
		for (const entry of candidateAudits) {
			if (!entry?.candidate_model || !entry?.criteria) continue;
			const criteria = entry.criteria ?? [];
			auditActions.setResult(
				reportId,
				{ overall_status: entry.overall_status ?? 'pass', criteria, summary: entry.summary ?? '' },
				entry.audit_id ?? null,
				entry.candidate_model
			);
			// Feed the Phase 2 subset back so the store's merge keeps all criteria and flips phase2Complete.
			auditActions.mergePhase2(
				reportId,
				criteria.filter((c: any) => PHASE2_NAMES.has(c?.criterion)),
				{ guidelineLookupFailed, guidelineCardsCount, candidateModel: entry.candidate_model }
			);
		}
		// Always also the default (reportId-only) slot for single-candidate consumers.
		auditActions.mergePhase2(reportId, data.phase2_audit?.criteria ?? [], {
			guidelineLookupFailed,
			guidelineCardsCount
		});
	} catch (e) {
		console.warn('[enhance] Phase 2 audit merge failed:', e);
	}
}
