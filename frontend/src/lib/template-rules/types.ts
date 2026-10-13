// Wire types of the Rules step (backend: template_decisions, template_rules_cards, main /skill-sheet/decide,
// /apply-decisions). The sheet itself is never shown: cards speak in report behaviour.

export type LedgerKind = 'value' | 'concept' | 'fixed' | 'normal' | 'habit';
export type CardKind = 'value' | 'concept' | 'disagree' | 'fixed' | 'normal' | 'uncovered' | 'duplicate' | 'group' | 'habit';
export type ChangeSource = 'creation' | 'first_use_review' | 'chat' | 'default';
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
	/** a habit card's wording (with `condition`): the question and the sentence each answer writes */
	question?: string;
	yes?: string;
	no?: string;
	/** a habit edit keeps the mode chosen on the card: asked every time, or always stated */
	mode?: 'ask' | 'state';
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
	/** kind "habit" (findings-triggered rows): the condition, the question and the sentence each answer writes */
	habit?: { condition: string; question: string; yes: string; no: string };
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

export interface NormalSentence {
	key: string;
	text: string;
	kind: 'normal' | 'negative';
	paragraph: string;
}

/** /skill-sheet/sheet-checks: the Style step's checks. A part that failed is empty and named in `errors`. */
export interface SheetChecksResponse {
	success: boolean;
	fixed_cards: DecisionCard[];
	duplicate_cards: DecisionCard[];
	normal_report: { section: string; header: string; sentences: NormalSentence[] }[];
	uncovered_cards: DecisionCard[];
	unmatched_cards: DecisionCard[];
	stale_quotes: string[];
	errors: string[];
}
