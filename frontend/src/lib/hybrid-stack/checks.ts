// Dictation checks in the scratchpad (2026-10-12): the integrity check's flags (/api/dictation/check) underlined on the
// words they are about, with a hover card (Grammarly-style). Blocking checks hold Confirm and are walked through at
// Confirm: tier 1 (code: an unfinished sentence, a dimension missing), every conflict (sides, measurements,
// contradictions, units) and a garble that could change the report. A garble whose reading is certain is advisory and
// carries the words to replace it.
import type { StackUnit } from './types';

/** One flag as /api/dictation/check returns it: offsets into the text exactly as sent. */
export interface IntegrityFlag {
	kind: string;
	severity: 'high' | 'medium';
	excerpt: string;
	message: string;
	start: number;
	end: number;
	related_start?: number | null;
	related_end?: number | null;
	/** garbled_phrase: the words to replace the quote with, only when one reading is certain. */
	suggestion?: string;
	/** Holds Confirm (the backend decides; tier 1 always). */
	blocking?: boolean;
}

/** A flag placed on the scratchpad: the sentence it belongs to (null: not placed yet, shown up top). */
export interface CheckFlag {
	key: string;
	kind: string;
	blocking: boolean;
	/** 1: code (an unfinished sentence); 2: the model. */
	tier: 1 | 2;
	message: string;
	quote: string;
	other: string | null;
	suggestion: string;
	unitId: number | null;
}

/** Keep as dictated, skip an advisory one, or the suggestion replaced the words. */
export type CheckAnswer = 'as_dictated' | 'skip' | 'replaced';

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/** The unit holding this text: the longest word-suffix of it found inside one unit (a truncation's excerpt runs to
 *  the end of the line, a conflict's quote is one statement). */
export function unitFor(text: string, units: StackUnit[]): number | null {
	const words = norm(text).split(' ').filter(Boolean);
	const placed = units.filter((u) => !u.heading);
	for (let n = words.length; n >= Math.min(3, words.length) && n > 0; n--) {
		const tail = words.slice(words.length - n).join(' ');
		const hit = [...placed].reverse().find((u) => norm(u.text).includes(tail));
		if (hit) return hit.id;
	}
	return null;
}

export function toChecks(text: string, flags: IntegrityFlag[], units: StackUnit[]): CheckFlag[] {
	return flags.map((f) => {
		const tier = f.severity === 'high' ? 1 : 2;
		const quote = tier === 1 ? f.excerpt.trim() : text.slice(f.start, f.end).trim() || f.excerpt.trim();
		const other = f.related_start != null && f.related_end != null ? text.slice(f.related_start, f.related_end).trim() || null : null;
		return { key: `${f.kind}|${norm(quote)}`, kind: f.kind, blocking: f.blocking ?? tier === 1, tier, message: f.message,
			quote, other, suggestion: (f.suggestion ?? '').trim(), unitId: unitFor(quote, units) };
	});
}

/** The hover card's title. */
export function checkLabel(kind: string): string {
	switch (kind) {
		case 'truncation': return 'Unfinished sentence';
		case 'dangling_measurement': return 'A dimension missing?';
		case 'laterality_conflict': return 'Sides as intended?';
		case 'measurement_mismatch': return 'Measurement as intended?';
		case 'internal_contradiction': return 'Statements conflict';
		case 'unit_anomaly': return 'Unit as intended?';
		case 'garbled_phrase': return 'Possible dictation error';
		default: return 'As intended?';
	}
}

/** A line's text cut into plain runs and runs a check underlines (its quote, or the other half of a conflict). The
 *  first check to claim words keeps them; a check whose words are not on this line is not shown here. */
export function segments(text: string, checks: CheckFlag[]): { text: string; check: CheckFlag | null }[] {
	const marks: { start: number; end: number; check: CheckFlag }[] = [];
	for (const c of checks) {
		for (const q of [c.quote, c.other]) {
			if (!q) continue;
			const start = text.indexOf(q);
			if (start < 0 || marks.some((m) => start < m.end && start + q.length > m.start)) continue;
			marks.push({ start, end: start + q.length, check: c });
		}
	}
	marks.sort((a, b) => a.start - b.start);
	const out: { text: string; check: CheckFlag | null }[] = [];
	let at = 0;
	for (const m of marks) {
		if (m.start > at) out.push({ text: text.slice(at, m.start), check: null });
		out.push({ text: text.slice(m.start, m.end), check: m.check });
		at = m.end;
	}
	if (at < text.length || !out.length) out.push({ text: text.slice(at), check: null });
	return out;
}

/** The line with the check's words replaced by its suggestion. */
export const replaced = (text: string, c: CheckFlag) => (c.suggestion && text.includes(c.quote) ? text.replace(c.quote, c.suggestion) : text);

/** Checks still asking: not answered, and (advisory ones) not skipped. */
export const openChecks = (checks: CheckFlag[], answers: Record<string, CheckAnswer>) => checks.filter((c) => !answers[c.key]);
