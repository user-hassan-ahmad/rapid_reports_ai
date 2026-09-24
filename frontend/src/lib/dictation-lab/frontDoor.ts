import type { Boundary } from './types';

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

export const BACKSTOP_SHORT_MS = 1500;
export const BACKSTOP_LONG_MS = 4000;
export const BACKSTOP_CONFIDENT = 0.9;

/**
 * How long to wait for the next chunk after a `continues` before sending anyway.
 * A confident `continues` earns a longer wait: the words are already on screen
 * (faded render), so the only cost of waiting is a later polish, while sending
 * early splits the sentence. Low confidence or no decision keeps the short wait.
 */
export function backstopDelay(confidence: number | null | undefined): number {
	return confidence != null && confidence >= BACKSTOP_CONFIDENT ? BACKSTOP_LONG_MS : BACKSTOP_SHORT_MS;
}
