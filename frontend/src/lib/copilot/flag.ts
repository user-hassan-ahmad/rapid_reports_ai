// The Copilot UI (D24): on for everyone whenever the server allows it (stack_copilot; kill switch RR_STACK_COPILOT=0)
// and the stack is latched. No per-browser opt-in. Off means no Copilot request is ever sent.

export function copilotOn(serverAllows: boolean, stackOn: boolean): boolean {
	return serverAllows && stackOn;
}
