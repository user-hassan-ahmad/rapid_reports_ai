// Dictation checks in the scratchpad (2026-10-12): the integrity check's flags (/api/dictation/check) shown where their
// sentence is, in the checklist's own row language. Tier 1 (code: an unfinished sentence, a dimension missing) is an
// open item at Confirm; tier 2 (gpt-oss: sides, measurements, contradictions, units) is advisory and can be skipped.
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
}

/** A flag placed on the scratchpad: the sentence it belongs to (null: not placed yet, shown up top). */
export interface CheckFlag {
	key: string;
	kind: string;
	blocking: boolean;
	message: string;
	quote: string;
	other: string | null;
	unitId: number | null;
}

export type CheckAnswer = 'as_dictated' | 'skip';

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
		const blocking = f.severity === 'high';
		const quote = blocking ? f.excerpt.trim() : text.slice(f.start, f.end).trim() || f.excerpt.trim();
		const other = f.related_start != null && f.related_end != null ? text.slice(f.related_start, f.related_end).trim() || null : null;
		return { key: `${f.kind}|${norm(quote)}`, kind: f.kind, blocking, message: f.message, quote, other, unitId: unitFor(quote, units) };
	});
}

/** What the row asks, answer-shaped. */
export function checkLabel(kind: string): string {
	switch (kind) {
		case 'truncation': return 'Unfinished sentence?';
		case 'dangling_measurement': return 'A dimension missing?';
		case 'laterality_conflict': return 'Sides as intended?';
		case 'measurement_mismatch': return 'Measurement as intended?';
		case 'unit_anomaly': return 'Unit as intended?';
		case 'garbled_phrase': return 'Words as intended?';
		default: return 'As intended?';
	}
}

/** Checks still asking: not answered, and (advisory ones) not skipped. */
export const openChecks = (checks: CheckFlag[], answers: Record<string, CheckAnswer>) => checks.filter((c) => !answers[c.key]);
