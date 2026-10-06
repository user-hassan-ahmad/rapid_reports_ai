// Locate a review item in the current document (spec §10, plan Task B2).
// Order: the stored span if it still holds the anchor text → a unique text search → for a zero-width
// (removed) anchor, the widget position the editor field supplies → null, and the caller marks it stale.
import type { ReviewItem } from './types';

export interface Located {
	from: number;
	to: number;
}

export interface LocateOptions {
	/** Where the editor field (Task C1) currently holds this item's widget, mapped through edits. */
	widgetPos?: number | null;
}

/** A zero-width anchor stands for removed text: a negatives removal, or live mode's pre-applied removal. */
function isRemoval(item: ReviewItem): boolean {
	const ev = item.evidence;
	if (typeof ev?.removed_text === 'string' && ev.removed_text) return true;
	return item.edit?.mode === 'remove' && (item.status === 'pre_applied' || !!ev?.undo);
}

export function locate(doc: string, item: ReviewItem, opts: LocateOptions = {}): Located | null {
	const anchor = item.anchor;
	if (!anchor) return null;
	const text = anchor.text ?? '';

	if (text) {
		const { start, end } = anchor;
		if (start >= 0 && end <= doc.length && doc.slice(start, end) === text) return { from: start, to: end };
		const k = doc.indexOf(text);
		if (k >= 0 && doc.indexOf(text, k + 1) < 0) return { from: k, to: k + text.length };
		return null;
	}

	const pos = opts.widgetPos;
	if (isRemoval(item) && typeof pos === 'number' && Number.isInteger(pos) && pos >= 0 && pos <= doc.length) {
		return { from: pos, to: pos };
	}
	return null;
}

/** Where a live pre-applied edit sits now (evidence.undo from live.rebase_items), or null. Positions are never
 * guessed: the stored `final_span` is trusted only when `textHash` (the hash of `doc`) equals the anchor's
 * `text_hash` (the written text) and the span still holds `final_text`; otherwise the span is re-found by its
 * unique context (`left` + `final_text` + `right`; `left` + `right` for a zero-width removal point). */
export function locateUndo(doc: string, item: ReviewItem, textHash?: string | null): Located | null {
	const u = item.evidence?.undo;
	if (!u || !Array.isArray(u.final_span)) return null;
	const hash = item.anchor?.text_hash;
	if (textHash && hash && textHash === hash) {
		const [j1, j2] = u.final_span;
		if (!(Number.isInteger(j1) && Number.isInteger(j2) && j1 >= 0 && j1 <= j2 && j2 <= doc.length)) return null;
		if (typeof u.final_text === 'string' && doc.slice(j1, j2) !== u.final_text) return null;
		return { from: j1, to: j2 };
	}
	if (typeof u.final_text !== 'string' || typeof u.left !== 'string' || typeof u.right !== 'string') return null;
	const needle = u.left + u.final_text + u.right;
	if (!needle) return null;
	const k = doc.indexOf(needle);
	if (k < 0 || doc.indexOf(needle, k + 1) >= 0) return null;
	const from = k + u.left.length;
	return { from, to: from + u.final_text.length };
}
