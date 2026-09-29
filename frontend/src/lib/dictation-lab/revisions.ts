/**
 * Two-pass ASR revisions (lab): the backend hears each live final again (Deepgram batch +
 * gpt-4o-transcribe) and Jev settles disagreements. A switch (Jev ≥ 0.90) is a quiet swap in
 * the words on screen; a suggestion (0.60–0.90) is an underline with the other reading on
 * hover; if the user already edited the sentence, a switch is only underlined.
 * Plan: docs/superpowers/plans/2026-09-29-two-pass-asr.md
 */

export interface Switch {
	from: string;
	to: string;
	confidence: number;
}

/** A negation, side or number the live stream dropped mid-sentence and both second passes
 *  heard between these neighbouring words. */
export interface Insert {
	left: string;
	right: string;
	text: string;
}

export interface Revision {
	final_seq: number;
	switches: Switch[];
	suggestions: Switch[];
	recovered: string | null;
	inserts?: Insert[];
	spans: number;
	errors: string[];
	ms: number;
}

/** Recovered words go in front of the final's text. Mid-sentence (no terminal mark), the
 *  final's first word loses its capital unless it is an abbreviation or a level (RV, L5/S1). */
export function joinRecovered(recovered: string, following: string): { insert: string; lowerFirst: boolean } {
	const r = recovered.trim();
	const midSentence = !/[.?!:]$/.test(r);
	const first = following.match(/^\S+/)?.[0] ?? '';
	return { insert: `${r} `, lowerFirst: midSentence && /^[A-Z][a-z]+[,.;:]?$/.test(first) };
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The last place the heard words appear as whole words (tokens may be joined by space or hyphen). */
export function findReading(text: string, reading: string): { from: number; to: number } | null {
	const tokens = reading.trim().split(/\s+/).filter(Boolean).map(escapeRe);
	if (!tokens.length) return null;
	const re = new RegExp(`(?<![\\w-])${tokens.join('[\\s-]+')}(?![\\w-])`, 'gi');
	let last: RegExpExecArray | null = null;
	for (let m = re.exec(text); m; m = re.exec(text)) last = m;
	return last ? { from: last.index, to: last.index + last[0].length } : null;
}

function keepCapital(original: string, replacement: string): string {
	return /^[A-Z]/.test(original) ? replacement.charAt(0).toUpperCase() + replacement.slice(1) : replacement;
}

const hover = (s: Switch) => `Also heard as “${s.to}” (${s.confidence.toFixed(2)})`;

/** What to do inside one decision's text: edits (quiet swaps) and underlines, in its coordinates. */
export function planRevision(
	text: string,
	rev: Revision,
	intact: boolean
): {
	edits: { from: number; to: number; insert: string; message?: string }[];
	underlines: { from: number; to: number; message: string }[];
	unmatched: number;
} {
	const edits: { from: number; to: number; insert: string; message?: string }[] = [];
	const underlines: { from: number; to: number; message: string }[] = [];
	let unmatched = 0;
	for (const s of rev.switches) {
		const r = findReading(text, s.from);
		if (!r) unmatched++;
		else if (intact) edits.push({ ...r, insert: keepCapital(text.slice(r.from, r.to), s.to) });
		else underlines.push({ ...r, message: hover(s) });
	}
	for (const s of rev.suggestions) {
		const r = findReading(text, s.from);
		if (!r) unmatched++;
		else underlines.push({ ...r, message: hover(s) });
	}
	for (const ins of rev.inserts ?? []) {
		const r = findReading(text, `${ins.left} ${ins.right}`);
		if (!r) {
			unmatched++;
			continue;
		}
		const at = r.to - (text.slice(r.from, r.to).match(/\S+$/)?.[0].length ?? 0); // start of the right word
		if (intact) edits.push({ from: at, to: at, insert: `${ins.text} `, message: `Inserted “${ins.text}”: both second passes heard it here` });
		else underlines.push({ ...r, message: `Both second passes also heard “${ins.text}” here` });
	}
	edits.sort((a, b) => a.from - b.from);
	return { edits, underlines, unmatched };
}
