export type Dropped = Record<string, { sentence: string; reason: string }[]>;

/** The gate's evidence of the assumed-normal check (template pipeline spec, block 4): what the sheet offered and
 *  what the check dropped, with its reason. */
export function offeredAndDropped(offered: Record<string, string[]>, dropped: Dropped | undefined) {
	return { offered: { ...offered }, jev_dropped: { ...(dropped ?? {}) } };
}
