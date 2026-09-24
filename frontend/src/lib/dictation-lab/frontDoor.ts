import type { Boundary } from './types';

/** Fold a resolved boundary into the chunk buffer. Pure. */
export function applyBoundary(
	buffer: string[],
	chunk: string,
	resolved: Boundary
): { send: string | null; buffer: string[] } {
	const next = [...buffer, chunk];
	if (resolved === 'continues') return { send: null, buffer: next };
	return { send: next.join(' '), buffer: [] };
}

export function flushBuffer(buffer: string[]): { send: string | null; buffer: string[] } {
	return { send: buffer.length ? buffer.join(' ') : null, buffer: [] };
}

export function lastNonEmptyLine(text: string): string {
	const lines = text
		.split('\n')
		.map((l) => l.trim())
		.filter(Boolean);
	return lines.length ? lines[lines.length - 1] : '';
}
