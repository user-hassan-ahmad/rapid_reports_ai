// Wire types for /api/canvas/stack/* (backend hybrid_stack). Spec 2026-10-10-hybrid-dictation-stack-design.
export interface Region { name: string; includes: string }
export interface StackPart { text: string; group: string; abnormal?: boolean }
export interface StackUnit {
	id: number;
	text: string;
	group: string | null;
	structure: string | null;
	attach_to: number | null;
	parts: StackPart[] | null;
	covers: string[];
	abnormal?: boolean;
	pinned: boolean;
	heading: boolean;
}
export interface StackSchema {
	regions: Region[];
	groups: string[];
	pills: string[];
	source: string;
	family: string | null;
	key: string;
	provisional: boolean;
	quiet?: string[];
	protocol?: { id: string; display_name: string; scan_type_line: string; phases: string[]; laterality: string | null } | null;
	/** The session's signed resolution (D26): /slim-sheet and Generate read it, never re-resolve. */
	structure_key?: string | null;
}
export interface GroupResult {
	units: StackUnit[];
	new_ids: number[];
	pills: string[];
	gate: Record<string, unknown>[];
	problems: string[];
	timings_ms: Record<string, number>;
	model: string | null;
	error: string | null;
}
export type StackOrder = 'anatomy' | 'dictated';
export interface ViewRow { unitId: number; text: string; structure: string | null; partOf: number | null; pinned: boolean; children: ViewRow[] }
export interface ViewGroup { name: string; rows: ViewRow[]; members: string[] } // members: the regions a joined heading spans
export interface StackView { groups: ViewGroup[]; unplaced: ViewRow[] }

/** Scratchpad v2 (spec 2026-10-11). */
export interface RegionStates {
	abnormal: string[]; // in schema order: shown in the scratchpad
	dictatedNormal: { region: string; words: string[] }[]; // solid pills
	assumedNormal: string[]; // dashed pills
	remainder: string[]; // abnormal regions with nothing dictated normal: "Remainder of X: assumed normal"
}
/** Checklist rows (spec 2026-10-11-scratchpad-checklist §2–§4): asked, never assumed. */
export interface StackItem {
	id: string;
	kind: 'finding' | 'referral' | 'template';
	region: string;
	source_text?: string; // the dictated phrase that set a finding check off
	question: string;
	why: string;
	sentences: string[]; // still to be answered (at most 2)
	answered: boolean; // the dictation answered every sentence: the row folds
	/** kind 'template' (a findings-triggered habit of the template): the sentence a Yes writes, and a No */
	yes?: string;
	no?: string;
}
export interface ItemsResult {
	items: StackItem[];
	capped: StackItem[];
	contradicted: string[];
	cached: boolean;
	ms: number;
	error: string | null;
	/** met template required statements, region -> sentences (offered in the assumed tray) */
	required?: Record<string, string[]>;
	/** the template trigger call failed: no template rows this review (what is on screen stays) */
	trigger_error?: string | null;
}
export interface SlimSheet { id: string | null; region_normals: Record<string, string[]>; not_assessable: string; status: string; ready: boolean; level_groups?: Record<string, string[]>; required_values?: string[]; region_structures?: Record<string, Record<string, string[]>>;
	/** Free text: the session token re-minted with the slim sheet's id (Generate reads the sheet from it, D26). */
	structure_key?: string | null }
/** The value cluster (requirements spec 2026-10-12 part 1): a template's required value and how it was resolved.
 *  check: needs a look (stated with no number, or two or more numbers); filling: a fill is running.
 *  picked: a number the radiologist tapped from the dictation (resolved, backstop-checked, never stated as an answer);
 *  entered: a value they typed (stated in FINDINGS). */
export type ValueState = 'filled' | 'picked' | 'entered' | 'na' | 'open' | 'check' | 'filling';
/** A number-bearing clause of the dictation offered on an open chip: one number (value) or several to choose from. */
export interface ClausePick { clause: string; value: string | null; numbers: string[] }
export interface ValueChip {
	item: string;
	state: ValueState;
	value: string | null;
	quote: string | null;
	kept?: boolean;
	/** Open: the dictation's number clauses to pick from. Check with a value: the numbers mapped to it, best first. */
	picks?: ClausePick[];
	/** Picked: the clause the number was tapped from (for a future alias store). */
	picked_clause?: string;
}
/** The server's fill: filled (one number mapped, or stated with no number: value null), check (two or more numbers
 *  mapped: the most confident, the others in picks) or open. */
export interface ValueFill { item: string; state: 'filled' | 'check' | 'open'; value: string | null; quote: string | null; score?: number | null; picks?: ClausePick[] }
export interface ValuesResult { values: ValueFill[]; ms: number; error: string | null }
/** Region -> normals the assumed-normal check dropped, with why. */
export type Dropped = Record<string, { sentence: string; reason: string }[]>;
/** A right/left pair of normals the dictation reports a finding for without giving its side. */
export interface SideAsk { region: string; sentences: string[]; label: string; choice?: SideChoice; score: number }
/** Jev's side for a pair's finding (bilateral fix 2026-10-14). What code did (action): no_side at the bar asks (both
 *  drop), below it flags both; both drops both when the finding touches the pair, else flags both; right / left: none
 *  (the contradiction fates stand). */
export type SideChoice = 'right' | 'left' | 'both' | 'no_side';
export interface SidePick extends SideAsk { action: 'ask' | 'drop' | 'flag' | 'none' }
export interface AssumedResult {
	assumed: Record<string, string[]>;
	/** Region -> assumed normals the dictation may conflict with (also in `assumed`): shown highlighted (review R1). */
	flagged?: Record<string, string[]>;
	/** Region -> normals not assumed, with why: covered | contradicted | removed | rule | side (no side dictated) |
	 *  both (a bilateral finding). */
	dropped?: Dropped;
	/** Quick sessions: pairs dictated without a side (both sides dropped); each asks "Which side?" (side brief). */
	side_asks?: SideAsk[];
	/** Every pair Jev placed a finding for, with its side (none left out). */
	side_choices?: SidePick[];
	side_failed?: boolean;
	/** The side call failed twice: regions held for Confirm ("side check unavailable"), re-review N1. */
	side_hold?: string[];
	/** The session's template context-rule decision (condition -> P(met)); kept and sent back (review R5). */
	rules?: Record<string, number> | null;
	/** The sheet has context rules: Confirm re-asks every one with the dictation. */
	confirm_recheck?: boolean;
	ms: number;
	error: string | null;
}
export interface GateItem { id: string; kind: StackItem['kind']; region: string; question: string; sentences: string[]; answered_by: 'dictation' | 'tap' | 'skip' | 'not_assessed' }
export interface DraftResult { text: string; ms: number; error: string | null }
/** One value behind an applied recommendation (spec 2026-10-14 §7.2): `state` is the card's, or 'confirmed' when ticked. */
export interface AppliedValue { input: string; value: string; state: string; quote?: string }
/** A recommendation the radiologist applied from a guideline card (spec 2026-10-14 §7.2). */
export interface AppliedRec {
	key: string; // the gate key: card ref, or `<card ref>#<pack key>` for a column
	finding_id: string;
	pack: string; // pack key
	version: string; // Calculation.pack, else the card's version
	bundle: string;
	source: string; // the guideline's display name, as written in the line
	outcome: string;
	verdict: string; // verdictKey(preview) at Apply
	chosen_from?: number;
	sentence: string; // as written at Apply
	text: string; // as it stands (edited by hand or not)
	values: AppliedValue[];
	stale?: 'values' | 'finding';
}

export interface GateRecord {
	confirmed_at: string;
	conclusion_text: string;
	conclusion_source: 'dictated' | 'draft' | 'draft_edited' | 'typed';
	assumed_normal: string[];
	remainder_normal: string[];
	dictated_normal: { region: string; words: string[] }[];
	items: GateItem[]; // rows answered by dictation or by a tap (tapped sentences are stated)
	assumed: Record<string, string[]>; // region normals confirmed (not dictated)
	removed: string[]; // sentences the radiologist removed: never stated
	// Every row behind the "N more checks" line at Confirm (over the writer's caps), whatever became of it: a tapped
	// one also appears in `items` (answered_by 'tap') and in capped_tapped; a skipped one also in `items`.
	capped: { region: string; question: string }[];
	capped_opened?: boolean; // the "N more checks" line was opened (E1b)
	capped_tapped?: { region: string; question: string }[]; // rows over the cap answered with a tap
	review_failed?: boolean; // the end-of-dictation review failed: no finding checks were offered
	offered?: Record<string, string[]>; // region normals the sheet offered, before the assumed-normal check
	jev_dropped?: Dropped | null; // what the check dropped, with why (null: the check failed)
	flagged?: Record<string, string[]>; // assumed normals confirmed with the "may conflict" marker (R1)
	assumed_check_failed?: boolean; // the assumed-normal check failed: nothing was dropped by it
	// "Which side?" asks seen this session and how each ended (side brief 2026-10-14; quick sessions only)
	// every pair asked this session, its last score and how it ended (sides.ts SideEnding: kept_without_side | open |
	// sided | gone)
	side_asks?: { region: string; pair: string; score: number; answered_by: 'kept_without_side' | 'kept_unchecked' | 'open' | 'sided' | 'gone' | 'unchecked' }[];
	side_failed?: boolean; // the Confirm answer's side call failed: the last open asks were carried forward (review F2)
	// The Confirm answer's side per pair Jev placed a finding for (bilateral fix): its choice and whether it dropped both
	side_choices?: { region: string; pair: string; choice: SideChoice; action: SidePick['action'] }[];
	side_hold?: string[]; // regions the failed side check held, kept as dictated at Confirm
	// Dictation checks seen this session and how each ended: answered, skipped, edited away, or still open (advisory).
	checks?: { kind: string; quote: string; other: string | null; answered_by: 'as_dictated' | 'skip' | 'replaced' | 'edited' | 'open' }[];
	recommendations?: AppliedRec[]; // guideline recommendations applied from a card (spec 2026-10-14 §7.2)
	values?: ValueChip[]; // the value cluster at Confirm (absent: the template has no required values)
	units_hash: string;
	/** findingsHash of the units sent at Confirm (incl. the live tail): the server refuses a stale gate. */
	findings_hash?: string;
}
export interface StackCommand { action: 'dictate' | 'delete' | 'answer'; region: string | null; item: string | null; command: string | null; confidence: number | null }
