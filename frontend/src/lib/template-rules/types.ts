// Wire types of the Rules step (backend: template_decisions, template_rules_cards, main /skill-sheet/decide,
// /apply-decisions). The sheet itself is never shown: cards speak in report behaviour.

export type LedgerKind = 'value' | 'concept' | 'fixed' | 'normal';
export type CardKind = 'value' | 'concept' | 'disagree' | 'fixed' | 'normal' | 'uncovered' | 'duplicate' | 'group';
export type ChangeSource = 'creation' | 'first_use_review' | 'default';
export type Choice = Record<string, unknown>;

/** One line of evidence: report numbers (1-based) with a quote, or "not stated" when the quote is null. The study
 * setup (name, scan type, protocol) is evidence too: `source: "setup"`, `reports: []`. */
export interface Evidence {
	reports: number[];
	quote: string | null;
	source?: 'setup';
}

export interface CardChoice {
	id: string;
	label: string;
	choice: Choice | null; // null: the radiologist writes the wording
}

export interface CardWording {
	default?: string;
	when_met?: string;
	condition?: string;
	text?: string;
}

export interface DecisionCard {
	id: string;
	kind: CardKind;
	step: string;
	title: string;
	evidence: Evidence[];
	ledger_kind: LedgerKind | '';
	key: string;
	choices: CardChoice[];
	selected: string | null;
	rank: number;
	wording?: CardWording;
	/** a concept with no clear usual state (contrast): the wording of each state, e.g. {given, not_given} */
	usual?: Record<string, string>;
	note?: string;
	/** kind "group": a collapsed group of cards under "More", each choosable when expanded */
	cards?: DecisionCard[];
	collapsed?: boolean;
}

export interface LedgerEntry {
	kind: LedgerKind;
	key: string;
	choice: Choice;
	by: string;
	at: string;
	source: string;
}

export interface DecisionChange {
	kind: LedgerKind;
	key: string;
	choice: Choice;
	source?: ChangeSource;
}

export interface DecideResponse {
	success: boolean;
	ran: boolean;
	cards: DecisionCard[];
	more: DecisionCard[];
	kept: DecisionCard[];
	defaults: DecisionChange[];
	notice: string;
	run: Record<string, unknown>;
	error?: string;
}

export interface ApplyResponse {
	success: boolean;
	skill_sheet: string;
	decisions: LedgerEntry[];
	applied: { kind: string; key: string; action: string }[];
	unmatched: LedgerEntry[];
	stale_quotes: string[];
	error?: string;
}
