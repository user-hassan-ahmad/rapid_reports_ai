import type { Dropped } from './types';

/** The gate's evidence of the assumed-normal check (template pipeline spec, block 4): what the sheet offered and
 *  what the check dropped, with its reason. A failed check is recorded as such (jev_dropped null), never as "no drops". */
export function offeredAndDropped(offered: Record<string, string[]>, dropped: Dropped | undefined, failed = false) {
	const base = { offered: { ...offered } };
	return failed ? { ...base, jev_dropped: null, assumed_check_failed: true } : { ...base, jev_dropped: { ...(dropped ?? {}) } };
}
