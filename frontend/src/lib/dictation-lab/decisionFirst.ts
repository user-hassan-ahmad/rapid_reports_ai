/**
 * Decision-first dictation in the lab (work-order step 5). Pure helpers only; the
 * scratchpad wires them. Records and the outcome log are data, never text: lengths,
 * 8-hex hashes, probabilities, qset, route, latency.
 */

export type FastRoute = 'fast_append' | 'command' | 'polish' | 'skip';
export const FAST_ROUTES: FastRoute[] = ['fast_append', 'command', 'polish', 'skip'];
export type LineClosedBy = 'punctuation' | 'newline' | 'standalone' | 'hard_limit' | 'polish' | 'stop';
export type OutcomeKind = 'undo' | 'edit' | 'redictate';

/** Outcome windows: what counts as a consequence of a decision. */
export const EDIT_WINDOW_MS = 10_000;
export const REDICTATE_WINDOW_MS = 15_000;
export const REDICTATE_MIN_OVERLAP = 0.7; // "no left…" vs "no right pleural effusion" is 0.6: a new finding, not a re-dictation

/** Mirrors backend canvas_routes.BundleRouteResponse. */
export interface BundleRouteResponse {
	decision_id: string;
	route: FastRoute;
	reason: string;
	text: string;
	insert: string;
	closes_line: boolean;
	close_on_silence: boolean;
	line_close: { silence_s: number; hard_limit_s: number };
	action: string | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	is_correction: number | null;
	needs_committed_edit: number | null;
	standalone: number | null;
	coverage: Record<string, number> | null;
	latency_ms: number | null;
	error: string | null;
	qset: string;
}

/** One routed utterance. No text. */
export interface DecisionRecord {
	id: string;
	seq: number;
	at: number;
	route: FastRoute;
	reason: string;
	qset: string | null;
	action: string | null;
	confidence: number | null;
	probabilities: Record<string, number> | null;
	is_correction: number | null;
	standalone: number | null;
	latency_ms: number | null; // Jev bundle, server-measured
	roundtrip_ms: number | null; // browser → route decision
	polish_called: boolean;
	polish_ms?: number | null; // the polish call this decision caused, when one ran
	utterance_len: number;
	utterance_hash: string;
	applied_len: number; // characters written by the automatic action
	closes_line: boolean;
	line_closed_by: LineClosedBy | null;
	error: string | null;
}

export interface OutcomeEvent {
	decision_id: string;
	kind: OutcomeKind;
	route: FastRoute;
	ms_since: number;
	at: number;
}

/** What goes between the solid scratchpad and a fast-appended utterance. Dictation
 *  continues the text: a finished sentence is not a new line (the open-line close only
 *  tells Jev a statement ended). New lines come from commands, as the radiologist says them. */
export function joinSeparator(solid: string): string {
	if (!solid || /\s$/.test(solid)) return '';
	return ' ';
}

/** The span of `after` that differs from `before` (common prefix/suffix trimmed),
 *  and the text of `before` it replaced. Used to attribute edits and undo a polish. */
export function changedRange(before: string, after: string): { from: number; to: number; before: string } {
	let p = 0;
	const max = Math.min(before.length, after.length);
	while (p < max && before[p] === after[p]) p++;
	let s = 0;
	while (s < max - p && before[before.length - 1 - s] === after[after.length - 1 - s]) s++;
	return { from: p, to: after.length - s, before: before.slice(p, before.length - s) };
}

export function tokenSet(text: string): Set<string> {
	return new Set((text.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter(Boolean));
}

/** A later utterance that says the affected line again (Jaccard over word tokens). */
export function isRedictation(prev: Set<string>, next: Set<string>): boolean {
	if (Math.min(prev.size, next.size) < 2) return false;
	let inter = 0;
	for (const t of prev) if (next.has(t)) inter++;
	const union = prev.size + next.size - inter;
	return union > 0 && inter / union >= REDICTATE_MIN_OVERLAP;
}

/** FNV-1a, 8 hex chars. Enough to join a record to a log line; not a secret. */
export function hash8(s: string): string {
	let h = 0x811c9dc5;
	for (let i = 0; i < s.length; i++) {
		h ^= s.charCodeAt(i);
		h = Math.imul(h, 0x01000193);
	}
	return (h >>> 0).toString(16).padStart(8, '0');
}

function quantile(xs: number[], q: number): number | null {
	if (!xs.length) return null;
	const s = [...xs].sort((a, b) => a - b);
	const pos = (s.length - 1) * q;
	const lo = Math.floor(pos);
	const hi = Math.ceil(pos);
	return Math.round(s[lo] + (s[hi] - s[lo]) * (pos - lo));
}

export interface RouteCounts {
	n: number;
	undo: number;
	edit: number;
	redictate: number;
}

export interface DecisionSummary {
	utterances: number;
	polishCalls: number;
	avoided: number; // vs polish-everything: one polish per utterance
	byRoute: Record<FastRoute, RouteCounts>;
	bundleN: number;
	bundleP50: number | null;
	bundleP95: number | null;
}

export function summariseDecisions(decisions: DecisionRecord[], outcomes: OutcomeEvent[]): DecisionSummary {
	const byRoute = Object.fromEntries(
		FAST_ROUTES.map((r) => [r, { n: 0, undo: 0, edit: 0, redictate: 0 }])
	) as Record<FastRoute, RouteCounts>;
	const routeOf = new Map(decisions.map((d) => [d.id, d.route]));
	for (const d of decisions) byRoute[d.route].n += 1;
	const seen = new Set<string>();
	for (const o of outcomes) {
		const key = `${o.decision_id}:${o.kind}`;
		const route = routeOf.get(o.decision_id);
		if (!route || seen.has(key)) continue;
		seen.add(key);
		byRoute[route][o.kind] += 1;
	}
	const polishCalls = decisions.filter((d) => d.polish_called).length;
	const lat = decisions.map((d) => d.latency_ms).filter((x): x is number => x != null);
	return {
		utterances: decisions.length,
		polishCalls,
		avoided: decisions.length - polishCalls,
		byRoute,
		bundleN: lat.length,
		bundleP50: quantile(lat, 0.5),
		bundleP95: quantile(lat, 0.95)
	};
}

export interface SessionExport {
	schema: 'rr-lab-session/1';
	started_at: number;
	exported_at: number;
	scan_type: string;
	qsets: string[];
	decisions: DecisionRecord[];
	outcomes: OutcomeEvent[];
}

/** Input to scripts/lab_session_summary.py. Data only. */
export function buildSessionExport(
	decisions: DecisionRecord[],
	outcomes: OutcomeEvent[],
	meta: { scanType: string; startedAt: number; exportedAt: number }
): SessionExport {
	return {
		schema: 'rr-lab-session/1',
		started_at: meta.startedAt,
		exported_at: meta.exportedAt,
		scan_type: meta.scanType,
		qsets: [...new Set(decisions.map((d) => d.qset).filter((q): q is string => !!q))],
		decisions: decisions.map((d) => ({ ...d })),
		outcomes: outcomes.map((o) => ({ ...o }))
	};
}
