/**
 * The transcript delta since the previous /process call. The backend only ever
 * sees the whole session transcript, so the utterance boundary is computed here,
 * where the previous value is known. When the transcript no longer starts with the
 * last-sent value (the sliding window dropped the prefix, or a reset), send no
 * delta this call and resync.
 */
export function computeDelta(
	sessionTranscript: string,
	lastSent: string
): { delta: string | null; next: string } {
	if (!sessionTranscript.startsWith(lastSent)) {
		return { delta: null, next: sessionTranscript };
	}
	const tail = sessionTranscript.slice(lastSent.length).trim();
	return { delta: tail.length ? tail : null, next: sessionTranscript };
}
