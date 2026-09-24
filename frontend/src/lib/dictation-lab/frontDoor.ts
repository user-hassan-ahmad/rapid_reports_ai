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
