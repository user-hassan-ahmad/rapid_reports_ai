/**
 * Decision-first dictation in the lab (work-order step 5). Pure helpers only; the
 * scratchpad wires them. Records and the outcome log are data, never text: lengths,
 * 8-hex hashes, probabilities, qset, route, latency.
 */

export type FastRoute = 'fast_append' | 'command' | 'polish' | 'skip' | 'delete';
export const FAST_ROUTES: FastRoute[] = ['fast_append', 'command', 'polish', 'skip', 'delete'];
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
	asr_fixes?: { heard: string; replacement: string; confidence: number }[];
	asr_flags?: { word: string; score: number }[];
	repair_ms?: number | null;
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
	wait_ms?: number | null; // final arrival → this decision started (queued behind earlier ones)
	final_to_solid_ms?: number | null; // final arrival → its text solid on the page (faded → written)
	// two-pass ASR (lab): the final heard again; numbers only
	two_pass_ms?: number | null;
	two_pass_switched?: number; // quiet swaps applied (Jev ≥ 0.90)
	two_pass_suggested?: number; // underlined, "also heard as …"
	two_pass_recovered_words?: number; // speech the stream dropped, inserted
	two_pass_inserted?: number; // a dropped negation / side / number both second passes heard
	two_pass_unmatched?: number; // readings no longer in the text
	polish_kind?: 'full' | 'lean' | null; // which polish produced the text (racing: lean)
	asr_fix_count?: number; // word-sense fixes applied to this line
	asr_flag_count?: number; // words underlined as not making clinical sense
	repair_ms?: number | null; // the chained word-fix call, when one ran
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

/** What Jev is shown as the scratchpad for one final: everything on screen before it,
 *  including earlier finals still faded while they wait for a polish (otherwise a polish
 *  queue leaves Jev deciding on a stale page). Falls back to the solid text when this
 *  final's tracked range has been overwritten or no longer holds it. */
export function jevContext(
	doc: string,
	own: { from: number; to: number } | null,
	chunk: string,
	solidEnd: number
): string {
	if (own && own.to > own.from && doc.slice(own.from, own.to).trim() === chunk.trim()) {
		return doc.slice(0, own.from).replace(/[ \t]+$/, '');
	}
	return doc.slice(0, solidEnd);
}

/** A correction whose corrected statement is not finished yet: a cue (correction, sorry,
 *  actually, I mean) with no sentence end after it. Deepgram splits "Correction. The nodule
 *  is in the | right lower lobe."; polishing the first half alone left "The nodule is in
 *  the" behind, which the second half then completed into a duplicate. Such a final waits
 *  for the next one and both are polished together. */
export function isUnfinishedCorrection(text: string): boolean {
	const re = /\b(correction|sorry|actually|i mean)\b/gi;
	let last = -1;
	for (let m = re.exec(text); m; m = re.exec(text)) last = m.index + m[0].length;
	if (last < 0) return false;
	const after = text.slice(last).replace(/^[\s,.:;]+/, '');
	return !/[.?!]|\n/.test(after);
}

function escapeRe(s: string): string {
	return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Word-sense fixes from /bundle, applied to text about to be written (fast-append, or the
 *  lean polish's output): whole words only, capital kept; a no-op when the polish already
 *  changed the heard words. */
export function applyAsrFixes(text: string, fixes: { heard: string; replacement: string }[]): string {
	let out = text;
	for (const f of fixes) {
		const re = new RegExp(`\\b${escapeRe(f.heard)}\\b`, 'gi');
		out = out.replace(re, (m) => (m[0] === m[0].toUpperCase() ? f.replacement[0].toUpperCase() + f.replacement.slice(1) : f.replacement));
	}
	return out;
}

/** Where to underline each flagged word in `text`: its last whole-word occurrence. */
export function flagRanges(text: string, flags: { word: string }[]): { from: number; to: number }[] {
	const out: { from: number; to: number }[] = [];
	for (const f of flags) {
		const re = new RegExp(`\\b${escapeRe(f.word)}\\b`, 'gi');
		let last: RegExpExecArray | null = null;
		for (let m = re.exec(text); m; m = re.exec(text)) last = m;
		if (last) out.push({ from: last.index, to: last.index + last[0].length });
	}
	return out;
}

/** Racing: the part of the scratchpad the lean polish may rewrite. The last `n` sentences
 *  of the current line (never across a line break), plus up to `maxContext` characters of
 *  frozen text before it. Chosen by code because the polish is fired before Jev answers. */
export function splitSpan(
	solid: string,
	n = 2,
	maxContext = 600
): { context: string; span: string; spanFrom: number } {
	const lineStart = solid.lastIndexOf('\n') + 1;
	const line = solid.slice(lineStart);
	const starts = [0];
	const re = /[.?!:](?!\d)["')\]]*\s+/g;
	for (let m = re.exec(line); m; m = re.exec(line)) {
		const next = m.index + m[0].length;
		if (next < line.length) starts.push(next);
	}
	const spanFrom = lineStart + starts[Math.max(0, starts.length - n)];
	return {
		context: solid.slice(Math.max(0, spanFrom - maxContext), spanFrom).trim(),
		span: solid.slice(spanFrom),
		spanFrom
	};
}

/** A lean polish's corrections to frozen text, as editor changes: only where the original
 *  occurs exactly once before `before` (the span start); anything else is skipped. */
export function committedEditChanges(
	doc: string,
	before: number,
	edits: { original: string; corrected: string }[]
): { from: number; to: number; insert: string }[] {
	const region = doc.slice(0, before);
	const out: { from: number; to: number; insert: string }[] = [];
	for (const e of edits) {
		if (!e.original) continue;
		const i = region.indexOf(e.original);
		if (i < 0 || region.indexOf(e.original, i + 1) >= 0) continue;
		const c = { from: i, to: i + e.original.length, insert: e.corrected };
		// the editor rejects overlapping changes: the first edit given wins
		if (out.some((o) => c.from < o.to && o.from < c.to)) continue;
		out.push(c);
	}
	return out.sort((a, b) => a.from - b.from);
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

/** Per-case Deepgram keyterms go on the websocket URL as repeated `kt` parameters (the
 *  backend filters them again and uses them only with DEEPGRAM_CASE_KEYTERMS=1). */
export function keytermQuery(terms: string[] | null | undefined): string {
	return (terms ?? [])
		.slice(0, 50)
		.map((t) => `&kt=${encodeURIComponent(t)}`)
		.join('');
}

/** Keyterms are fetched once per case: this key changes when the case does. */
export function keytermCaseKey(scanType: string, history: string, sections: string[]): string {
	return JSON.stringify([scanType.trim(), history.trim(), sections]);
}

/** "Scratch that" on its own (route `delete`, decided by code): undo what the previous
 *  utterance wrote, restoring what it replaced, while nothing else has touched it. The
 *  command's own faded text is the caller's main change; these are the other edits.
 *  Otherwise the reason it cannot, and the utterance goes to polish as before. */
export function deletePrevious(
	last: { from: number; to: number; before: string; intact: boolean; route: FastRoute } | null,
	pend: { from: number; to: number },
	polishBusy: boolean
): { edits: { from: number; to: number; insert: string }[]; reason: null } | { edits: null; reason: string } {
	if (polishBusy) return { edits: null, reason: 'delete_polish_in_flight' };
	if (!last || !last.intact || last.to > pend.from) return { edits: null, reason: 'delete_nothing_intact' };
	if (last.route === 'command') return { edits: null, reason: 'delete_after_command' };
	return { edits: [{ from: last.from, to: last.to, insert: last.before }], reason: null };
}
