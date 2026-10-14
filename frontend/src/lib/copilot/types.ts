// Wire types for /api/canvas/stack/guidelines/* (backend hybrid_stack/copilot/types.py, routes.py).
// The ONLY place the UI names backend fields; contract.json lists them for the backend's contract test.
import type { StackUnit } from '$lib/hybrid-stack/types';
export type CardState = 'applies' | 'check_first' | 'does_not_apply' | 'which_lesion'; // which_lesion: Task 8
export interface Publication { title: string; body: string; year: string }
export interface Card {
	key: string;
	name: string;
	version: string;
	finding_id: string; // "u<unit>" | "u<unit>.<part>" | "exam" (exam-level card)
	why: string;
	branch: string;
	skeleton: string[];
	publication: Publication;
	known: boolean;
	status: 'draft' | 'verified' | 'new';
	siblings: string[]; // other bodies' pack keys on the same topic: columns on this card (§7.1)
	reference: boolean; // tier 2: read-only
	finding: string; // the unit text (exam card: the dictation) as /match returned it
	needs_modality: string; // e.g. "US": read-only, never opened (M4)
	sibling_names?: string[]; // display names for siblings, same order (contract R: new backend field)
}
/** library/describe.py citation(): a locator with its source's public fields; {} for none. */
export interface Citation { source?: string; title?: string; issuer?: string; edition?: string; url?: string; page?: string | number; section?: string; table?: string }
export interface Proposal {
	classification: string;
	line: string;
	recommendation: string;
	caveats: string[];
	citations: Citation[];
	normal?: boolean; // R3: the outcome is the guideline's normal one (backend default false); quiet prefers it
	// Library packs' display fields ("" when a pack does not set them: the UI then derives fallbacks, verdictOf).
	headline?: string; // a short verdict, <= ~8 words
	action?: string; // a short action, <= ~6 words, e.g. "No further imaging"
	category?: ActionCategory | '';
}
/** types.py OutcomeBrief: an outcome in short (most_likely). */
export interface OutcomeBrief { headline: string; action?: string; category?: ActionCategory | '' }
/** types.py DecidingAnswer: one answer to the deciding question and where it leads. */
export interface DecidingBranch { answer: string; headline: string; category?: ActionCategory | '' }
/** types.py Assumption: a value the draft assumes (never stated): an eligibility input in scope, or a visible sign
 *  absent. `decisive`: flipping it alone changes the outcome (null: not weighed: no tag). */
export interface Assumption { input: string; label: string; value: string; decisive: boolean | null; kind: 'eligibility' | 'sign' }
/** `outcome`: the input's exclusion_outcome (spec §7.12): the exclusion then carries that outcome's own wording. */
export interface ExclusionReason { input: string; label: string; value: string; outcome?: string | null }
export interface DecidingInput { input: string; label: string }
export type ActionCategory = 'none' | 'surveillance' | 'workup' | 'refer' | 'info' | 'not_applicable'; // info: no management stated
export interface Settled { input: string; value: string; quote: string; fact: string; by: '' | 'exam' }
/** pack_preview._asks: one per missing input (A5 reads input + label; the rest is for Slice B). */
export interface Ask { input: string; label: string; role?: string; [k: string]: unknown } // role: 'eligibility' | 'clinical' | …
export type ValueState = 'read' | 'prefilled' | 'assumed' | 'asked' | 'answered' | 'edited' | 'not_applicable'; // Task 3
export interface DraftValue {
	// Task 3
	input: string;
	label: string;
	role: string;
	scope: string;
	fact: string;
	state: ValueState;
	value: string;
	quote: string;
	why: string[];
	needed: boolean;
	waiting: boolean;
	options: string[];
	by?: '' | 'exam'; // contract request R1
	decisive?: boolean | null; // assumed: flipping it alone changes the outcome; null when not weighed (no tag: never guessed)
	basis?: string; // where a derived value came from, e.g. "from the CT of 12 Mar 2025" (spec §7.12 item 4)
}
export interface Checker {
	// Task 7
	category: string;
	quote: string;
	verdict: 'agrees' | 'disagrees' | 'unchecked';
	outcomes: string[];
	computed: string[];
}
export interface Highlight { linked: boolean; ids: string[]; rows: Record<string, number[]> } // Task 5
export interface Preview {
	settled: Settled[];
	missing: string[];
	proposal: Proposal | null;
	state: CardState;
	exclusion: Proposal | null;
	possible: string[];
	bounded: boolean;
	asks: Ask[];
	trace: Record<string, unknown> | null;
	degraded: boolean;
	waiting?: string[]; // Task 1
	assumptions?: Assumption[]; // every assumed draft value, in pack order (eligibility in scope, visible signs absent)
	assumed_eligible?: boolean; // the draft rests on assumptions (state stays check_first)
	most_likely?: OutcomeBrief | null; // the draft's outcome under its assumptions, in short; null while several remain
	exclusion_reason?: ExclusionReason | null; // does_not_apply: the one read or answered value behind it
	deciding_input?: DecidingInput | null; // several outcomes remain: the input whose answer splits them most
	deciding?: DecidingBranch[]; // its answers -> outcomes (at most 3)
	/** Input ids of pre-filled values that would make the guideline not apply: never an exclusion until confirmed
	 *  (Hassan's rule: nothing excludes silently); the card shows them prominently. */
	scope_doubt?: string[];
	draft?: DraftValue[]; // Task 3
	draft_outcome?: Proposal | null; // Task 3
	checker?: Checker | null; // Task 7
	lesions?: string[]; // Task 8
	lesion?: string; // Task 8
	highlight?: Highlight | null; // Task 5
}
/** library/describe.reference_view: RefText / RefTable with `citation` in place of the locator. */
export interface RefText { id: string; text: string; citation: Citation }
export interface RefTable { id: string; title: string; columns: string[]; rows: string[][]; citation: Citation }
export type RefItem = RefText | RefTable;
export interface ReferenceView { summary: RefText[]; definitions: RefText[]; tables: RefTable[]; pitfalls: RefText[] }
/** types.py Branch / Input: a TNM card shows its branch criteria as text. */
export interface BranchInput { id: string; question: string; options: string[] }
export interface Branch { name: string; inputs: BranchInput[]; rule: string }
export interface Entry {
	key: string;
	name: string;
	version: string;
	status: 'draft' | 'verified';
	publication: Publication;
	content: { applies_to: string; summary: string; branches: Branch[] };
	sources: { url: string; title: string; tier: number }[];
}
export interface OpenResult {
	entry: Entry | null;
	preview: Preview | null;
	branch: string;
	ms: number;
	error: 'unavailable' | 'loading' | 'unknown guideline' | string | null;
	reference: ReferenceView | null;
	needs_modality: string;
}
export interface MatchResult { cards: Card[]; ms: number }
export interface Calculation {
	// Task 3 (+5, 7, 8)
	outcome: string | null;
	result: Proposal | null;
	exclusion: Proposal | null;
	possible: string[];
	needed: string[];
	values: DraftValue[];
	assumptions: Assumption[]; // values sent back at the draft's assumption: still assumptions (confirmed at Apply)
	exclusion_reason?: ExclusionReason | null;
	most_likely?: OutcomeBrief | null;
	deciding_input?: DecidingInput | null;
	deciding?: DecidingBranch[];
	trace: Record<string, unknown> | null;
	pack: string;
	bundle: string;
	checker?: Checker | null;
	highlight?: Highlight | null;
	lesion?: string;
}
export interface CalculateResult { calculation: Calculation | null; ms: number; error: string | null }

// P2c: the round's units and groups replace the dictation/findings text; the server builds that text with the one
// builder (findings_text, P2b). An exam card's `finding` still carries the findings text (its own field).
export interface MatchBody {
	scan_type: string;
	clinical_history: string;
	findings: { id: string; text: string }[];
	units: StackUnit[];
	groups: string[];
	patient: Record<string, string>;
}
export interface OpenBody {
	card: Card;
	finding: string;
	units: StackUnit[];
	groups: string[];
	clinical_history: string;
	answered: Record<string, string>;
	patient: Record<string, string>;
	lesion?: string; // Task 8
}
export interface CalculateBody extends OpenBody { values: Record<string, string> } // Task 3

/** POST conclusion_check (spec §7.12 item 5): what the conclusion recommends for each card's finding. `key` is an
 *  opaque id the response echoes. */
export type ConclusionCategory = 'none' | 'surveillance' | 'workup' | 'refer';
export interface ConclusionCheckBody { conclusion: string; cards: { key: string; finding: string }[] }
export interface ConclusionCheckResult { results: Record<string, ConclusionCategory | null> }
