// The per-card view state the session store (A6) owns and the card components render. Keyed by cardRef.
import type { OpenResult } from '../types';

import type { Calculation } from '../types';

export type ColumnView = { loading: boolean; error: string | null; result: OpenResult | null };
/** A Calculate on the card (Slice B2): cleared by any later edit. */
export type CalcView = { loading: boolean; error: string | null; result: Calculation | null };
export type CardView = {
	open: boolean;
	loading: boolean;
	error: string | null;
	result: OpenResult | null;
	/** SiblingColumns: one entry per pack key (primary + siblings). */
	columns?: Record<string, ColumnView>;
	/** Came from "Other guidelines" (POST /match/other). */
	fromOther?: boolean;
	/** The radiologist's answers on this card, by input id (display form; "Not stated" clears): sent as `answered`. */
	edits?: Record<string, string>;
	calc?: CalcView;
};
export const closedView: CardView = { open: false, loading: false, error: null, result: null };

/** The card's failure to show: the request's own, else the one /open returned in its body. */
export const errorOf = (v: { error: string | null; result: OpenResult | null }) => v.error ?? v.result?.error ?? null;
