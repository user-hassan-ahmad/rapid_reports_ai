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

export type RouterCard = DecisionCard | ProposalCard;

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
	notice?: string;
	error?: string;
}

export const isProposal = (c: RouterCard): c is ProposalCard => c.kind === 'proposal';
