import type { Boundary, Placement } from './types';

/**
 * Fold a resolved boundary into the chunk buffer. Pure.
 * - continues: hold the chunk, send nothing.
 * - complete:  send buffer + chunk as one statement.
 * - command:   the command is its own utterance; anything buffered goes out first as a
 *              statement so a formatting/delete command is never glued onto a finding.
 */
export function applyBoundary(
	buffer: string[],
	chunk: string,
	resolved: Boundary
): { sends: string[]; buffer: string[] } {
	if (resolved === 'continues') return { sends: [], buffer: [...buffer, chunk] };
	if (resolved === 'command') {
		const sends = buffer.length ? [buffer.join(' '), chunk] : [chunk];
		return { sends, buffer: [] };
	}
	return { sends: [[...buffer, chunk].join(' ')], buffer: [] };
}

export function flushBuffer(buffer: string[]): { sends: string[]; buffer: string[] } {
	return { sends: buffer.length ? [buffer.join(' ')] : [], buffer: [] };
}

export function lastNonEmptyLine(text: string): string {
	const lines = text
		.split('\n')
		.map((l) => l.trim())
		.filter(Boolean);
	return lines.length ? lines[lines.length - 1] : '';
}

/**
 * Silence schedule after a `continues`. Instead of a blind timer, the classifier is
 * asked again at each milestone with `silence_s` as evidence; only at the hard limit
 * is the buffer sent without asking. The words are already visible faded, so the
 * cost of waiting is only a later polish.
 */
export const SILENCE_MILESTONES_S = [2, 5];
export const SILENCE_HARD_LIMIT_S = 9;

/** Step n (0-based) of the schedule: how long to wait from the previous step, and the
 *  silence value to report; `silenceS: null` means the hard limit — send without asking. */
export function nextSilenceStep(step: number): { delayMs: number; silenceS: number | null } {
	const prev = step === 0 ? 0 : (SILENCE_MILESTONES_S[step - 1] ?? SILENCE_HARD_LIMIT_S);
	if (step < SILENCE_MILESTONES_S.length) {
		return { delayMs: (SILENCE_MILESTONES_S[step] - prev) * 1000, silenceS: SILENCE_MILESTONES_S[step] };
	}
	return { delayMs: (SILENCE_HARD_LIMIT_S - prev) * 1000, silenceS: null };
}

/**
 * What the polish actually did with a statement, from the scratchpad before/after.
 * Line-count based, like the backend's derived action; used to shadow-compare
 * Jev's placement decision. null when nothing changed.
 */
export function derivePlacement(before: string, after: string): Placement | null {
	const b = before.split('\n');
	const a = after.split('\n');
	const bl = b.filter((l) => l.trim());
	const al = a.filter((l) => l.trim());
	if (al.length === bl.length) {
		return bl.length && al[al.length - 1] !== bl[bl.length - 1] && al[al.length - 1].length > bl[bl.length - 1].length
			? 'extend_previous_line'
			: null;
	}
	if (al.length > bl.length) {
		// First line into an empty scratchpad matches the criteria's 'last line is empty' case.
		if (!bl.length) return 'new_paragraph';
		// A blank line inserted before the new text means a paragraph break.
		const tail = a.slice(a.lastIndexOf(al[al.length - 1]) - 1, a.lastIndexOf(al[al.length - 1]));
		return tail.length && tail[0].trim() === '' && bl.length ? 'new_paragraph' : 'new_line';
	}
	return null;
}
