// The per-card view state the session store (A6) owns and the card components render. Keyed by cardRef.
import type { OpenResult } from '../types';

import type { Calculation } from '../types';

/** A Calculate on the card (Slice B2): cleared by any later edit. */
export type CalcView = { loading: boolean; error: string | null; result: Calculation | null };
/** One sibling column: its own preview, answers and Calculate (B2 follow-up). */
export type ColumnView = {
	loading: boolean;
	error: string | null;
	result: OpenResult | null;
	edits?: Record<string, string>;
	calc?: CalcView;
	/** A re-preview after an edit failed: the edit was reverted and the last preview kept. */
	editError?: string | null;
	/** Ticks (spec 2026-10-14 §6.2): input → the exact value the radiologist affirmed; never sent. */
	ticks?: Record<string, string>;
	/** The outcome picked from those still possible (spec §4.4). */
	pick?: string | null;
	applying?: boolean;
	applyError?: string | null;
	/** A collapsed guideline (may not apply) shows its full body: set by the toggle or by the confirm gate. */
	expanded?: boolean;
};
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
	editError?: string | null;
	/** Ticks (spec 2026-10-14 §6.2): input → the exact value the radiologist affirmed; never sent. */
	ticks?: Record<string, string>;
	/** The outcome picked from those still possible (spec §4.4). */
	pick?: string | null;
	applying?: boolean;
	applyError?: string | null;
	expanded?: boolean;
};
export const closedView: CardView = { open: false, loading: false, error: null, result: null };

/** The card's failure to show: the request's own, else the one /open returned in its body. */
export const errorOf = (v: { error: string | null; result: OpenResult | null }) => v.error ?? v.result?.error ?? null;
