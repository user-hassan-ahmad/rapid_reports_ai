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
