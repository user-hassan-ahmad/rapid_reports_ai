import { Decoration, EditorView, type DecorationSet } from '@codemirror/view';
import { StateEffect, StateField, type EditorState, type TransactionSpec } from '@codemirror/state';

/**
 * Phase 2b.3 optimistic render: raw is_final text is shown faded (a "pending" mark) until
 * a polish or fast-append replaces it. markPending adds a faded range; clearPending removes
 * faded marks intersecting [from,to) (null = all). Marks map through document changes.
 *
 * Effect ranges are read AFTER the transaction's changes are applied, so a clear that
 * rides on a replacement must use post-change positions: use replaceAndClear.
 */
export const markPending = StateEffect.define<{ from: number; to: number }>();
export const clearPending = StateEffect.define<{ from: number; to: number } | null>();

export const pendingField = StateField.define<DecorationSet>({
	create: () => Decoration.none,
	update(deco, tr) {
		deco = deco.map(tr.changes);
		for (const e of tr.effects) {
			if (e.is(markPending)) {
				deco = deco.update({
					add: [Decoration.mark({ class: 'cm-dictation-pending' }).range(e.value.from, e.value.to)]
				});
			} else if (e.is(clearPending)) {
				const range = e.value;
				deco = range ? deco.update({ filter: (from, to) => to <= range.from || from >= range.to }) : Decoration.none;
			}
		}
		return deco;
	},
	provide: (f) => EditorView.decorations.from(f)
});

export function pendingRanges(state: EditorState): { from: number; to: number }[] {
	const out: { from: number; to: number }[] = [];
	state.field(pendingField, false)?.between(0, state.doc.length, (from, to) => {
		out.push({ from, to });
	});
	return out;
}

/**
 * Replace `main` (old positions) and clear the faded mark over the text that replaced it,
 * in NEW positions. `edits` are other changes in the same transaction that lie before
 * `main` (a polish's corrections to earlier lines). Clearing with the old range after a
 * shorter rewrite reached into the next final's faded text and cleared it too; that final
 * then looked lost and fell back to a full polish (lab, 2026-09-27: a spoken "New paragraph"
 * was dropped this way).
 */
export function replaceAndClear(
	main: { from: number; to: number; insert: string },
	edits: { from: number; to: number; insert: string }[] = []
): TransactionSpec {
	const shift = edits
		.filter((e) => e.to <= main.from)
		.reduce((n, e) => n + e.insert.length - (e.to - e.from), 0);
	const from = main.from + shift;
	return {
		changes: [...edits, main],
		effects: clearPending.of({ from, to: from + main.insert.length })
	};
}
