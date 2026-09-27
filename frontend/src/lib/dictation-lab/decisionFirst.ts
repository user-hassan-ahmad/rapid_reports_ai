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
	clean_text?: string;
	closes_line: boolean;
	close_on_silence: boolean;
	starts_paragraph?: boolean;
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
	polish_kind?: 'full' | 'lean' | null; // which polish produced the text (racing: lean)
	polish_tokens_in?: number | null;
	polish_tokens_out?: number | null;
	// Deepgram's confidences for this final (mic only; null from the feeder). Recorded for
	// step 7, which tests whether they separate misheard fragments; not used to route.
	asr_conf?: number | null;
	asr_min_conf?: number | null;
	asr_word_confs?: number[] | null;
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

export interface AsrFields {
	asr_conf: number | null;
	asr_min_conf: number | null;
	asr_word_confs: number[] | null;
}

/** The confidence fields the lab websocket adds to a final (numbers only). */
export function asrFields(msg: Record<string, unknown>): AsrFields {
	const num = (v: unknown) => (typeof v === 'number' ? v : null);
	const list = Array.isArray(msg.asr_word_confs) && msg.asr_word_confs.every((x) => typeof x === 'number')
		? (msg.asr_word_confs as number[])
		: null;
	return { asr_conf: num(msg.asr_conf), asr_min_conf: num(msg.asr_min_conf), asr_word_confs: list };
}

/** The unfinished statement at the end of the scratchpad: everything after the last
 *  sentence end (. ? ! not inside a number), colon or line break. Empty when the text
 *  ends a statement. Read from the text itself, so a polish or a timer cannot lose it. */
export function openStatement(solid: string): string {
	if (/\n[ \t]*$/.test(solid)) return ''; // a line or paragraph break closed it
	const text = solid.replace(/\s+$/, '');
	if (!text || /[.?!:]["')\]]*$/.test(text)) return '';
	const re = /[.?!:](?!\d)["')\]]*\s+|\n/g;
	let start = 0;
	for (let m = re.exec(text); m; m = re.exec(text)) start = m.index + m[0].length;
	return text.slice(start).trim();
}

/** What goes between the solid scratchpad and a fast-appended utterance. Dictation
 *  continues the text: a finished sentence is not a new line (the open-line close only
 *  tells Jev a statement ended). New lines come from commands, as the radiologist says them. */
export function joinSeparator(solid: string): string {
	if (!solid || /\s$/.test(solid)) return '';
	return ' ';
}

/** Separator for a fast-appended text: a disc level or heading opens a paragraph (the
 *  backend says which); leading punctuation (': …' after 'L5/S1') attaches directly;
 *  anything else continues the text. */
export function separatorFor(solid: string, text: string, startsParagraph: boolean): string {
	if (!solid) return '';
	if (startsParagraph) return solid.endsWith('\n\n') ? '' : solid.endsWith('\n') ? '\n' : '\n\n';
	if (/^[:;,.?!)\n]/.test(text)) return '';
	return joinSeparator(solid);
}

/** Swap the raw final for its cleaned text in the session transcript, so a polish call
 *  sees 'L3/4: mild', not 'L3/4, colon, mild'. Last occurrence; unchanged if absent. */
export function substituteLast(transcript: string, raw: string, clean: string): string {
	const i = transcript.lastIndexOf(raw);
	return i < 0 ? transcript : transcript.slice(0, i) + clean + transcript.slice(i + raw.length);
}

/** What a command writes after the solid scratchpad: nothing into an empty one, and a
 *  terminal mark only where the text does not already end with one. */
export function commandInsert(solid: string, insert: string): string {
	if (!solid) return '';
	if (/^[.?!]$/.test(insert) && /[.?!]["')\]]*\s*$/.test(solid)) return '';
	return insert;
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

/** Every word of an earlier line of at least this many words reappearing counts too. */
export const REDICTATE_CONTAIN_MIN_WORDS = 3;

/** A later utterance that says the affected line again: word overlap (Jaccard) ≥ 0.7, or
 *  the whole earlier line repeated inside a longer one ("no free fluid" → "no free fluid
 *  in the pelvis"). The other side ("left" → "right") fails both: a word is missing. */
export function isRedictation(prev: Set<string>, next: Set<string>): boolean {
	if (Math.min(prev.size, next.size) < 2) return false;
	let inter = 0;
	for (const t of prev) if (next.has(t)) inter++;
	if (inter === prev.size && prev.size >= REDICTATE_CONTAIN_MIN_WORDS) return true;
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
