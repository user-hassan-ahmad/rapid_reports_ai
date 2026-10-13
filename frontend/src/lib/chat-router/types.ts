// Wire types of the chat-edit router (backend: chat_router.response, /skill-sheet/refine, /refine/undo,
// /refine/card). The sheet is never shown: replies and cards speak in report behaviour.
import type { DecisionCard, LedgerEntry } from '$lib/template-rules/types';

/** A change with no ledger card (layout, a new or reworded line): Apply sends `apply` back unchanged. */
export interface ProposalCard {
	id: string;
	kind: 'proposal';
	title: string;
	apply: Record<string, unknown>;
}

/** A finding-triggered habit the router parked (nothing written; set up later, item 5): shown, never applied. */
export interface HabitCard {
	id: string;
	kind: 'habit';
	title: string;
	instruction: string;
}

export type RouterCard = DecisionCard | ProposalCard | HabitCard;

/** One applied change of a router turn; opaque here, /refine/undo reverses it. */
export type RouterRecord = Record<string, unknown>;

export type CardAnswer =
	| { kind: string; key: string; choice: Record<string, unknown> }
	| { proposal: Record<string, unknown> };

export interface RouterTurnResponse {
	success: boolean;
	skill_sheet: string;
	response: string;
	behavioral_claim: string;
	applied: boolean;
	route?: 'router';
	changes?: RouterRecord[];
	cards?: RouterCard[];
	decisions?: LedgerEntry[];
	unmatched?: Record<string, unknown>[];
	/** the server's signature of `changes` (undo accepts only records it signed) */
	changes_sig?: string;
	/** the stored turn (a saved template): undo uses its own records */
	turn_id?: string;
	notice?: string;
	error?: string;
}

export const isProposal = (c: RouterCard): c is ProposalCard => c.kind === 'proposal';
export const isHabit = (c: RouterCard): c is HabitCard => c.kind === 'habit';
