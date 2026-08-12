/**
 * Phase 2b.2 incremental dictation: splice the frozen COMMITTED prefix back
 * onto the model's freshly-polished ACTIVE tail.
 *
 * The backend never sees or rewrites the committed zone — it only returns the
 * updated `active_scratchpad` plus any directed `committed_edits`. Joining the
 * two zones is the client's job, and the join must reintroduce the boundary
 * separator the full-regeneration model used to emit itself.
 *
 * Clean-mode Output rule (canvas_routes.py `CANVAS_CLEAN_SYSTEM_PROMPT`): "One
 * distinct statement per line, in the order dictated." A frozen finding and a
 * new active statement are, by construction, distinct statements (the commit
 * happened at a speech pause), so they are separated by a single newline — the
 * same shape the flag-off path produces. Concatenating with no separator was
 * the `lobe.The spleen` defect.
 */

export interface CommittedEdit {
	original: string;
	corrected?: string;
}

export interface MergeResult {
	/** The full document: edited committed prefix + separator + active tail. */
	content: string;
	/**
	 * Offset where the mutable active tail begins. `content.slice(boundary)`
	 * is exactly `activeSanitized`; the separator (if any) belongs to the
	 * committed side so the tail stays pure across mid-burst passes.
	 */
	boundary: number;
}

/**
 * @param committed        Frozen prefix, already clean from prior passes.
 * @param activeSanitized  Model's updated active tail, already sanitized.
 * @param edits            Directed corrections to the committed prefix; each
 *                         `original` must be a verbatim substring or it is
 *                         dropped (drop-if-not-found safety).
 */
export function mergeIncremental(
	committed: string,
	activeSanitized: string,
	edits: CommittedEdit[] | null | undefined
): MergeResult {
	let editedCommitted = committed;
	for (const e of edits ?? []) {
		if (!e || !e.original) continue;
		const idx = editedCommitted.lastIndexOf(e.original);
		if (idx !== -1) {
			editedCommitted =
				editedCommitted.slice(0, idx) +
				(e.corrected ?? '') +
				editedCommitted.slice(idx + e.original.length);
		}
	}

	// Reintroduce the one-statement-per-line boundary the model can no longer
	// emit, unless either side already carries the break (avoids doubling).
	const needsSeparator =
		editedCommitted.length > 0 &&
		activeSanitized.length > 0 &&
		!editedCommitted.endsWith('\n') &&
		!activeSanitized.startsWith('\n');
	const separator = needsSeparator ? '\n' : '';

	return {
		content: editedCommitted + separator + activeSanitized,
		boundary: editedCommitted.length + separator.length
	};
}
