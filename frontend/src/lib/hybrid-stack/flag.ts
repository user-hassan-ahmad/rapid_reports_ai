// The hybrid stack is on when the server allows it (RR_HYBRID_STACK, with the dictation package) and
// the user has not opted out (localStorage rr_hybrid_stack = "0"), as rr_dictation_v2 does.
export const HYBRID_STACK_KEY = 'rr_hybrid_stack';

function storage(): Storage | undefined {
	try {
		return typeof localStorage !== 'undefined' ? localStorage : undefined;
	} catch {
		return undefined;
	}
}

export function hybridStackOn(store = storage(), serverAllows = false): boolean {
	if (!serverAllows) return false;
	try {
		return store?.getItem(HYBRID_STACK_KEY) !== '0';
	} catch {
		return true;
	}
}
