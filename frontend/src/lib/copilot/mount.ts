// How a scratchpad starts a Copilot session: context first, then the units as placed now (none after a clear, so a
// fresh session never re-matches what was just cleared).
import type { StackUnit } from '$lib/hybrid-stack/types';
import { createCopilotSession, type CopilotApi, type CopilotContext, type CopilotSession } from './session';

export function mountCopilot(
	ctx: CopilotContext,
	units: StackUnit[],
	recording: boolean,
	groups: string[],
	api?: CopilotApi
): CopilotSession {
	const s = createCopilotSession(api);
	s.setContext(ctx);
	if (units.length) s.round(units, recording, groups);
	return s;
}
