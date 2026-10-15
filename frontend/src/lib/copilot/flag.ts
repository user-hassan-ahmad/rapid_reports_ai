// The Copilot UI (D24): on for everyone whenever the server allows it (stack_copilot; kill switch RR_STACK_COPILOT=0)
// and the stack is latched. No per-browser opt-in. Off means no Copilot request is ever sent.

export function copilotOn(serverAllows: boolean, stackOn: boolean): boolean {
	return serverAllows && stackOn;
}

/** Apply (spec 2026-10-14 §7.6): off unless this browser opted in (localStorage rr_copilot_apply = '1'). Hassan turns
 *  it on in his own browser; any storage error reads as off. */
export const APPLY_KEY = 'rr_copilot_apply';
export function applyOn(storage?: Pick<Storage, 'getItem'> | null): boolean {
	try {
		const s = storage === undefined ? (typeof localStorage === 'undefined' ? null : localStorage) : storage;
		return s?.getItem(APPLY_KEY) === '1';
	} catch {
		return false;
	}
}
