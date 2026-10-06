// A promise gate for an in-app confirmation (never window.confirm): `ask()` opens it and resolves with the answer
// the dialog gives through `answer()`. History "Open" uses it before replacing a tab that holds unsaved work.
import { writable, type Readable } from 'svelte/store';

export interface ConfirmGate {
	/** True while a question waits for an answer (the dialog's `open`). */
	pending: Readable<boolean>;
	/** Open the gate; resolves true (go ahead) or false (cancel). A second ask cancels the first. */
	ask: () => Promise<boolean>;
	answer: (ok: boolean) => void;
}

export function createConfirmGate(): ConfirmGate {
	const pending = writable(false);
	let resolve: ((ok: boolean) => void) | null = null;
	function answer(ok: boolean): void {
		const r = resolve;
		resolve = null;
		pending.set(false);
		r?.(ok);
	}
	function ask(): Promise<boolean> {
		if (resolve) answer(false);
		pending.set(true);
		return new Promise<boolean>((r) => (resolve = r));
	}
	return { pending: { subscribe: pending.subscribe }, ask, answer };
}

/** A report tab's unsaved work: a dictation in progress (recording, or scratchpad findings no report was generated
 * from) or unsaved editor changes. */
export function hasUnsavedWork(s: {
	recording: boolean;
	findings: string;
	findingsAtReport: string;
	editorDirty: boolean;
}): boolean {
	return s.recording || (!!s.findings && s.findings !== s.findingsAtReport) || s.editorDirty;
}

/** True to go ahead: at once when the target holds no unsaved work, else the answer to `ask`. */
export async function confirmIfUnsaved(
	target: { hasUnsavedWork?: () => boolean } | null | undefined,
	ask: () => Promise<boolean>
): Promise<boolean> {
	if (!target?.hasUnsavedWork?.()) return true;
	return ask();
}
