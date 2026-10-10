// The AI highlights mode (Legend's three-way control), as the emphasis keys the editor theme reads
// (theme.ts `setEmphasis` -> data-rv-emph) and its persistence (localStorage `rv_ai_mode`, as railActive.ts guards
// its storage: every access in try/catch, a blocked store just means the default).
//   key (default): amber negatives, violet synthesis and the teal recommendation underline
//   all:           key plus green normals
//   off:           no AI tints at all (rail cards, action marks and recommendation checkboxes still show)

export type AiMode = 'key' | 'all' | 'off';

// Left to right as a scale: Off · Key · All.
export const AI_MODES: readonly AiMode[] = ['off', 'key', 'all'];
export const DEFAULT_AI_MODE: AiMode = 'key';
export const AI_MODE_STORAGE_KEY = 'rv_ai_mode';

export const AI_MODE_KEYS: Record<AiMode, readonly string[]> = {
	key: ['ai'],
	all: ['ai', 'normals'],
	off: []
};

export function isAiMode(v: unknown): v is AiMode {
	return v === 'key' || v === 'all' || v === 'off';
}

/** The remembered mode, else Key (also when storage is blocked or holds something else). */
export function readAiMode(): AiMode {
	try {
		const v = localStorage.getItem(AI_MODE_STORAGE_KEY);
		return isAiMode(v) ? v : DEFAULT_AI_MODE;
	} catch {
		return DEFAULT_AI_MODE;
	}
}

export function writeAiMode(mode: AiMode): void {
	try {
		localStorage.setItem(AI_MODE_STORAGE_KEY, mode);
	} catch {
		// storage blocked: the choice still holds for this page
	}
}
