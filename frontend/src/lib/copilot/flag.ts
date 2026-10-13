// The Copilot UI is opt-in: the server must allow it (stack_copilot; kill switch RR_STACK_COPILOT=0), the hybrid
// stack must be on, and this browser must have set localStorage rr_stack_copilot = "1". Anything else is off,
// and off means no Copilot request is ever sent.
export const COPILOT_KEY = 'rr_stack_copilot';

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

/** On only when the server allows it, the stack is on, and this browser opted in ("1"); default off. */
export function copilotOn(store = storage(), serverAllows = false, stackOn = false): boolean {
	if (!serverAllows || !stackOn) return false;
	try {
		return store?.getItem(COPILOT_KEY) === '1';
	} catch {
		return false; // blocked storage: never opted in
	}
}
